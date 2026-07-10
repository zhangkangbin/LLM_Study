import argparse
import json
import os


DEFAULT_MODEL = "gpt-5.5"


KNOWN_ISSUES = [
    {
        "id": "android-npe-activity-lifecycle",
        "category": "crash",
        "keyword": "NullPointerException",
        "summary": "Activity 生命周期中访问了尚未初始化或已经释放的对象。",
        "suggestion": "检查 onCreate/onResume/onDestroy 之间的对象初始化和释放时机。",
    },
    {
        "id": "android-anr-main-thread-io",
        "category": "anr",
        "keyword": "ANR",
        "summary": "主线程执行磁盘、网络或锁等待导致无响应。",
        "suggestion": "将耗时操作移动到后台线程，并检查主线程堆栈。",
    },
    {
        "id": "android-index-out-of-bounds-list",
        "category": "crash",
        "keyword": "IndexOutOfBoundsException",
        "summary": "列表数据和 UI 下标不同步。",
        "suggestion": "检查 Adapter 数据更新、DiffUtil 和点击位置是否一致。",
    },
]


def build_android_crash_analysis_schema():
    return {
        "type": "object",
        "properties": {
            "issue_type": {"type": "string"},
            "severity": {
                "type": "string",
                "enum": ["low", "medium", "high", "unknown"],
            },
            "summary": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
            },
            "likely_causes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "fix_suggestions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "needs_more_info": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "issue_type",
            "severity",
            "summary",
            "evidence",
            "likely_causes",
            "fix_suggestions",
            "needs_more_info",
        ],
        "additionalProperties": False,
    }


def build_crash_input(crash_log, app_version="unknown"):
    return [
        {
            "role": "system",
            "content": (
                "你是 Android 稳定性分析助手。只基于输入日志和上下文分析，"
                "不确定时把 severity 设为 unknown，并在 needs_more_info 中说明缺少什么。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"App 版本：{app_version}\n\n"
                "请分析下面的崩溃日志，并按 JSON Schema 输出。\n\n"
                "<crash_log>\n"
                f"{crash_log}\n"
                "</crash_log>"
            ),
        },
    ]


def build_structured_output_payload(model, crash_log, app_version="unknown"):
    return {
        "model": model,
        "input": build_crash_input(crash_log=crash_log, app_version=app_version),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "android_crash_analysis",
                "strict": True,
                "schema": build_android_crash_analysis_schema(),
            }
        },
    }


def validate_android_crash_analysis(data):
    schema = build_android_crash_analysis_schema()
    errors = []

    if not isinstance(data, dict):
        return ["result must be an object"]

    for field in schema["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")

    allowed_fields = set(schema["properties"].keys())
    for field in data:
        if field not in allowed_fields:
            errors.append(f"unexpected field: {field}")

    if data.get("severity") not in schema["properties"]["severity"]["enum"]:
        errors.append("severity must be one of low, medium, high, unknown")

    for field in ("evidence", "likely_causes", "fix_suggestions", "needs_more_info"):
        if field in data and not isinstance(data[field], list):
            errors.append(f"{field} must be an array")
        elif field in data and not all(isinstance(item, str) for item in data[field]):
            errors.append(f"{field} must contain only strings")

    for field in ("issue_type", "summary"):
        if field in data and not isinstance(data[field], str):
            errors.append(f"{field} must be a string")

    return errors


def build_known_issue_search_tool():
    return {
        "type": "function",
        "name": "search_known_android_issues",
        "description": "Search a small local Android crash and ANR knowledge base by keyword.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Exception or symptom keyword, such as NullPointerException or ANR.",
                }
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    }


def build_tool_enabled_payload(model, question):
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "你是 Android 稳定性分析助手。需要历史经验或已知问题时，"
                    "可以调用 search_known_android_issues 工具。"
                ),
            },
            {"role": "user", "content": question},
        ],
        "tools": [build_known_issue_search_tool()],
    }


def extract_function_calls(response_json):
    calls = []
    for item in response_json.get("output", []):
        if item.get("type") != "function_call":
            continue
        try:
            arguments = json.loads(item.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        calls.append(
            {
                "call_id": item.get("call_id"),
                "name": item.get("name"),
                "arguments": arguments,
            }
        )
    return calls


def search_known_android_issues(keyword):
    normalized = keyword.lower()
    matches = [
        issue
        for issue in KNOWN_ISSUES
        if normalized in issue["keyword"].lower()
        or normalized in issue["summary"].lower()
        or normalized in issue["category"].lower()
    ]
    return {"matches": matches}


def execute_tool_call(call):
    name = call["name"]
    arguments = call.get("arguments", {})
    if name != "search_known_android_issues":
        result = {"error": f"unsupported tool: {name}"}
    else:
        result = search_known_android_issues(arguments.get("keyword", ""))
    return {
        "type": "function_call_output",
        "call_id": call["call_id"],
        "output": json.dumps(result, ensure_ascii=False),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Structured Outputs and Function Calling demo")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema = subparsers.add_parser("schema", help="Print Android crash analysis JSON Schema")
    schema.set_defaults(func=lambda args: build_android_crash_analysis_schema())

    structured = subparsers.add_parser("structured-payload", help="Print a Responses API structured output payload")
    structured.add_argument("--crash-log", required=True)
    structured.add_argument("--app-version", default="unknown")
    structured.set_defaults(
        func=lambda args: build_structured_output_payload(
            model=args.model,
            crash_log=args.crash_log,
            app_version=args.app_version,
        )
    )

    tools = subparsers.add_parser("tools-payload", help="Print a Responses API payload with a function tool")
    tools.add_argument("--question", required=True)
    tools.set_defaults(func=lambda args: build_tool_enabled_payload(model=args.model, question=args.question))

    simulate = subparsers.add_parser("simulate-tool", help="Simulate executing a model function_call item")
    simulate.add_argument("--keyword", default="NullPointerException")
    simulate.set_defaults(func=simulate_tool_call)

    return parser


def simulate_tool_call(args):
    response = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_demo_001",
                "name": "search_known_android_issues",
                "arguments": json.dumps({"keyword": args.keyword}, ensure_ascii=False),
            }
        ]
    }
    calls = extract_function_calls(response)
    return {
        "model_function_call": response["output"][0],
        "function_call_output": [execute_tool_call(call) for call in calls],
    }


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
