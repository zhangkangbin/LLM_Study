import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


SAMPLE_KNOWLEDGE = [
    {
        "id": "android-crash-guide",
        "title": "Android 崩溃排查知识",
        "text": "NullPointerException 需要结合 FATAL EXCEPTION、Caused by、业务堆栈和最近发布版本分析。页面切换后崩溃要检查 Activity 生命周期和异步回调。",
        "tags": ["android", "crash", "logcat"],
    },
    {
        "id": "backend-api-errors",
        "title": "后端 API 错误排查",
        "text": "接口 500、409、429 等错误应记录 HTTP 状态码、业务错误码、trace_id、请求参数摘要和下游依赖，后端通过 trace_id 定位网关、鉴权、业务服务和数据库日志。",
        "tags": ["backend", "api", "trace"],
    },
    {
        "id": "product-refund-faq",
        "title": "产品退款 FAQ",
        "text": "用户申请退款时，需要确认订单状态、支付渠道、购买时间和是否已经消耗权益。",
        "tags": ["product", "refund", "faq"],
    },
]

WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
SYNONYMS = {
    "空指针": ["nullpointerexception", "崩溃"],
    "崩溃": ["crash", "exception", "fatal"],
    "接口": ["api", "http"],
    "错误": ["error", "状态码"],
    "工单": ["ticket", "跟进"],
    "跟进": ["工单", "ticket"],
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class ScriptedPlanner:
    def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        goal = state["goal"]
        if not has_tool_call(state, "search_knowledge_base"):
            return {
                "type": "tool_call",
                "name": "search_knowledge_base",
                "arguments": {"query": goal, "max_results": 2},
            }
        if wants_followup_ticket(goal) and not has_tool_call(state, "create_followup_ticket"):
            summary = summarize_first_match(state)
            return {
                "type": "tool_call",
                "name": "create_followup_ticket",
                "arguments": {
                    "title": f"跟进：{goal[:24]}",
                    "summary": summary,
                    "priority": "normal",
                },
            }
        return {"type": "final", "answer": compose_final_answer(goal, state)}


class LoopPlanner:
    def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "tool_call",
            "name": "search_knowledge_base",
            "arguments": {"query": state["goal"], "max_results": 1},
        }


def build_tool_schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def build_default_tools() -> dict[str, Tool]:
    search_schema = build_tool_schema(
        name="search_knowledge_base",
        description="Search internal troubleshooting and product knowledge.",
        properties={
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Maximum results"},
        },
        required=["query"],
    )
    ticket_schema = build_tool_schema(
        name="create_followup_ticket",
        description="Create a follow-up ticket for human tracking.",
        properties={
            "title": {"type": "string", "description": "Ticket title"},
            "summary": {"type": "string", "description": "Ticket summary"},
            "priority": {"type": "string", "description": "Ticket priority"},
        },
        required=["title", "summary"],
    )
    return {
        "search_knowledge_base": Tool(
            name="search_knowledge_base",
            description="Search internal troubleshooting and product knowledge.",
            schema=search_schema,
            handler=search_knowledge_base,
        ),
        "create_followup_ticket": Tool(
            name="create_followup_ticket",
            description="Create a follow-up ticket for human tracking.",
            schema=ticket_schema,
            handler=create_followup_ticket,
        ),
    }


def execute_tool_call(
    tool_call: dict[str, Any],
    tools: dict[str, Tool],
) -> dict[str, Any]:
    name = str(tool_call.get("name", ""))
    arguments = dict(tool_call.get("arguments") or {})
    tool = tools.get(name)
    if tool is None:
        return {"ok": False, "error": "unknown_tool", "tool_name": name}
    try:
        return tool.handler(**arguments)
    except TypeError as error:
        return {"ok": False, "error": "invalid_arguments", "message": str(error)}


def run_agent(
    goal: str,
    tools: dict[str, Tool] | None = None,
    planner: Any | None = None,
    max_steps: int = 5,
) -> dict[str, Any]:
    active_tools = tools or build_default_tools()
    active_planner = planner or ScriptedPlanner()
    state: dict[str, Any] = {"goal": goal, "trace": []}

    for step_number in range(1, max_steps + 1):
        action = active_planner.plan(state)
        if action["type"] == "final":
            return {
                "status": "completed",
                "goal": goal,
                "final_answer": action["answer"],
                "trace": state["trace"],
            }
        if action["type"] != "tool_call":
            return {
                "status": "planner_error",
                "goal": goal,
                "final_answer": f"Planner returned unsupported action: {action['type']}",
                "trace": state["trace"],
            }
        result = execute_tool_call(action, active_tools)
        state["trace"].append(
            {
                "step": step_number,
                "type": "tool_call",
                "tool_name": action["name"],
                "arguments": action.get("arguments", {}),
                "result": result,
            }
        )

    return {
        "status": "max_steps_exceeded",
        "goal": goal,
        "final_answer": f"任务达到最大步数 {max_steps}，已停止以避免循环执行。",
        "trace": state["trace"],
    }


def search_knowledge_base(query: str, max_results: int = 2) -> dict[str, Any]:
    query_tokens = set(tokenize(query))
    matches: list[dict[str, Any]] = []
    for item in SAMPLE_KNOWLEDGE:
        searchable = " ".join([item["title"], item["text"], " ".join(item["tags"])])
        item_tokens = set(tokenize(searchable))
        overlap = query_tokens & item_tokens
        if not overlap:
            continue
        matches.append(
            {
                "id": item["id"],
                "title": item["title"],
                "text": item["text"],
                "score": round(len(overlap) / max(len(query_tokens), 1), 4),
                "matched_terms": sorted(overlap),
            }
        )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return {"ok": True, "matches": matches[:max_results]}


def create_followup_ticket(title: str, summary: str, priority: str = "normal") -> dict[str, Any]:
    digest = hashlib.sha1(f"{title}|{summary}|{priority}".encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "ticket_id": f"TICKET-{digest[:8].upper()}",
        "title": title,
        "summary": summary,
        "priority": priority,
    }


def tokenize(text: str) -> list[str]:
    normalized = text.lower()
    tokens = WORD_PATTERN.findall(normalized)
    expanded = list(tokens)
    for keyword, synonyms in SYNONYMS.items():
        if keyword in normalized:
            expanded.append(keyword)
            expanded.extend(synonyms)
    return expanded


def has_tool_call(state: dict[str, Any], tool_name: str) -> bool:
    return any(step["tool_name"] == tool_name for step in state["trace"])


def wants_followup_ticket(goal: str) -> bool:
    return any(keyword in goal.lower() for keyword in ["工单", "ticket", "跟进"])


def summarize_first_match(state: dict[str, Any]) -> str:
    for step in state["trace"]:
        if step["tool_name"] != "search_knowledge_base":
            continue
        matches = step["result"].get("matches", [])
        if matches:
            first = matches[0]
            return f"{first['title']}：{first['text']}"
    return "未检索到明确资料，需要人工跟进。"


def compose_final_answer(goal: str, state: dict[str, Any]) -> str:
    lines = [f"目标：{goal}"]
    search_matches: list[dict[str, Any]] = []
    ticket_result: dict[str, Any] | None = None
    for step in state["trace"]:
        if step["tool_name"] == "search_knowledge_base":
            search_matches = step["result"].get("matches", [])
        if step["tool_name"] == "create_followup_ticket":
            ticket_result = step["result"]

    if search_matches:
        first = search_matches[0]
        lines.append(f"检索结论：{first['text']} [{first['id']}]")
    else:
        lines.append("检索结论：知识库没有足够信息，需要补充资料或转人工确认。")

    if ticket_result and ticket_result.get("ok"):
        lines.append(f"已创建跟进工单：{ticket_result['ticket_id']}")
    return "\n".join(lines)


def build_responses_agent_payload(
    goal: str,
    tools: list[dict[str, Any]],
    model: str = "gpt-5.5",
) -> dict[str, Any]:
    return {
        "model": model,
        "input": goal,
        "tools": tools,
        "tool_choice": "auto",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local multi-step agent demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the scripted agent loop.")
    run_parser.add_argument("--goal", required=True)
    run_parser.add_argument("--max-steps", type=int, default=5)

    subparsers.add_parser("schema", help="Print default tool schemas.")

    payload_parser = subparsers.add_parser("payload", help="Print a Responses API tool payload.")
    payload_parser.add_argument("--goal", required=True)
    payload_parser.add_argument("--model", default="gpt-5.5")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    tools = build_default_tools()

    if args.command == "run":
        result = run_agent(args.goal, tools=tools, max_steps=args.max_steps)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "schema":
        schemas = [tool.schema for tool in tools.values()]
        print(json.dumps(schemas, ensure_ascii=False, indent=2))
        return

    if args.command == "payload":
        payload = build_responses_agent_payload(
            goal=args.goal,
            tools=[tool.schema for tool in tools.values()],
            model=args.model,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
