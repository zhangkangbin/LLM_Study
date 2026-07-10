import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


DEFAULT_CHUNKS_PATH = Path(__file__).resolve().parent / "sample_chunks.jsonl"
WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")

SYNONYMS = {
    "空指针": ["nullpointerexception", "崩溃", "exception"],
    "npe": ["nullpointerexception", "空指针", "崩溃"],
    "崩溃": ["crash", "exception", "fatal", "排查"],
    "排查": ["定位", "分析", "检查"],
    "页面": ["activity", "fragment", "ui"],
    "切换": ["生命周期", "activity", "回调"],
    "卡死": ["anr", "无响应", "主线程"],
    "无响应": ["anr", "卡死", "主线程"],
    "接口": ["api", "http", "错误码"],
    "错误": ["error", "状态码", "trace_id"],
    "退款": ["refund", "订单", "支付"],
    "注销": ["账号", "删除", "account"],
}


def load_chunks(path: Path | str = DEFAULT_CHUNKS_PATH) -> list[dict[str, Any]]:
    chunks_path = Path(path)
    chunks: list[dict[str, Any]] = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    tokens = WORD_PATTERN.findall(normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(SYNONYMS.get(token, []))
    for keyword, synonyms in SYNONYMS.items():
        if keyword in normalized and keyword not in expanded:
            expanded.append(keyword)
            expanded.extend(synonyms)
    return expanded


def token_vector(text: str) -> dict[str, float]:
    vector: dict[str, float] = {}
    for token in tokenize(text):
        vector[token] = vector.get(token, 0.0) + 1.0
    return vector


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def retrieve_context(
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int = 3,
    min_score: float = 0.0,
    required_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_vector = token_vector(question)
    required = set(required_tags or [])
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        tags = set(chunk.get("tags") or [])
        if required and not required.issubset(tags):
            continue
        searchable_text = " ".join(
            [
                str(chunk.get("title", "")),
                str(chunk.get("text", "")),
                " ".join(chunk.get("tags") or []),
            ]
        )
        score = cosine_similarity(query_vector, token_vector(searchable_text))
        if score < min_score:
            continue
        enriched = dict(chunk)
        enriched["score"] = round(score, 6)
        results.append(enriched)

    return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]


def citation_label(context: dict[str, Any]) -> str:
    return f"[{context['doc_id']}#{context.get('chunk_index', 0)}]"


def build_rag_prompt(
    question: str,
    contexts: list[dict[str, Any]],
    answer_language: str = "中文",
    max_context_chars: int = 1800,
) -> str:
    context_lines: list[str] = []
    used_chars = 0
    for context in contexts:
        text = context.get("text", "")
        if used_chars >= max_context_chars:
            break
        remaining = max_context_chars - used_chars
        clipped = text[:remaining]
        used_chars += len(clipped)
        context_lines.append(
            "\n".join(
                [
                    f"{citation_label(context)}",
                    f"标题：{context.get('title', '')}",
                    f"来源：{context.get('source_uri', '')}",
                    f"相似度：{context.get('score', 0)}",
                    f"内容：{clipped}",
                ]
            )
        )

    joined_context = "\n\n".join(context_lines) if context_lines else "无可用上下文"
    return "\n".join(
        [
            "你是一个面向开发者的知识库问答助手。",
            f"请使用{answer_language}回答。",
            "只能基于【检索上下文】回答；如果上下文不足，必须说明知识库中没有足够信息。",
            "回答中需要保留引用标记，例如 [android-crash-guide#0]。",
            "",
            "【用户问题】",
            question,
            "",
            "【检索上下文】",
            joined_context,
            "",
            "【回答要求】",
            "1. 先给出直接结论。",
            "2. 再列出关键排查步骤或注意事项。",
            "3. 不要编造上下文没有出现的事实。",
        ]
    )


def answer_question(
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int = 3,
    min_score: float = 0.2,
    required_tags: list[str] | None = None,
) -> dict[str, Any]:
    contexts = retrieve_context(
        question,
        chunks,
        top_k=top_k,
        min_score=min_score,
        required_tags=required_tags,
    )
    if not contexts:
        return {
            "status": "no_answer",
            "question": question,
            "answer": "知识库中没有足够信息回答这个问题。建议补充相关文档后再检索，或转人工确认。",
            "citations": [],
            "retrieved": [],
            "prompt": build_rag_prompt(question, []),
        }

    citations = [
        {
            "label": citation_label(context),
            "doc_id": context["doc_id"],
            "title": context.get("title", ""),
            "source_uri": context.get("source_uri", ""),
            "score": context.get("score", 0),
        }
        for context in contexts
    ]
    answer = synthesize_answer(question, contexts)
    return {
        "status": "answered",
        "question": question,
        "answer": answer,
        "citations": citations,
        "retrieved": contexts,
        "prompt": build_rag_prompt(question, contexts),
    }


def synthesize_answer(question: str, contexts: list[dict[str, Any]]) -> str:
    lead = f"基于知识库，问题“{question}”可以先从最相关的资料排查。"
    bullet_lines: list[str] = []
    for context in contexts:
        sentences = split_sentences(context.get("text", ""))
        selected = sentences[:2] if sentences else [context.get("text", "")]
        for sentence in selected:
            if sentence:
                bullet_lines.append(f"- {sentence} {citation_label(context)}")
        if len(bullet_lines) >= 4:
            break
    return "\n".join([lead, *bullet_lines])


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s*", text.strip())
    return [part.strip() for part in parts if part.strip()]


def build_file_search_payload(
    question: str,
    vector_store_ids: list[str],
    model: str = "gpt-5.5",
    max_num_results: int = 3,
    include_results: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": question,
        "tools": [
            {
                "type": "file_search",
                "vector_store_ids": vector_store_ids,
                "max_num_results": max_num_results,
            }
        ],
    }
    if include_results:
        payload["include"] = ["file_search_call.results"]
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a small local RAG demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    answer_parser = subparsers.add_parser("answer", help="Retrieve context and synthesize an answer.")
    answer_parser.add_argument("--question", required=True)
    answer_parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    answer_parser.add_argument("--top-k", type=int, default=3)
    answer_parser.add_argument("--min-score", type=float, default=0.2)
    answer_parser.add_argument("--tag", action="append", default=[])

    prompt_parser = subparsers.add_parser("prompt", help="Print the prompt built from retrieved context.")
    prompt_parser.add_argument("--question", required=True)
    prompt_parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    prompt_parser.add_argument("--top-k", type=int, default=3)
    prompt_parser.add_argument("--min-score", type=float, default=0.2)

    payload_parser = subparsers.add_parser("payload", help="Print a Responses API file_search payload.")
    payload_parser.add_argument("--question", required=True)
    payload_parser.add_argument("--vector-store-id", action="append", required=True)
    payload_parser.add_argument("--model", default="gpt-5.5")
    payload_parser.add_argument("--max-num-results", type=int, default=3)
    payload_parser.add_argument("--no-include-results", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "answer":
        result = answer_question(
            question=args.question,
            chunks=load_chunks(args.chunks),
            top_k=args.top_k,
            min_score=args.min_score,
            required_tags=args.tag,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "prompt":
        chunks = load_chunks(args.chunks)
        contexts = retrieve_context(
            args.question,
            chunks,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        print(build_rag_prompt(args.question, contexts))
        return

    if args.command == "payload":
        payload = build_file_search_payload(
            question=args.question,
            vector_store_ids=args.vector_store_id,
            model=args.model,
            max_num_results=args.max_num_results,
            include_results=not args.no_include_results,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
