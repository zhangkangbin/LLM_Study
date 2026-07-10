import argparse
import hashlib
import json
import math
import pathlib
import re


DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DOCS_PATH = pathlib.Path(__file__).with_name("sample_documents.json")


SYNONYM_PHRASES = {
    "崩溃": "crash",
    "异常": "crash",
    "闪退": "crash",
    "空指针": "nullpointer",
    "空对象": "nullpointer",
    "无响应": "anr",
    "卡死": "anr",
    "主线程": "mainthread",
    "生命周期": "lifecycle",
    "语音": "voice",
    "知识库": "knowledgebase",
    "向量": "vector",
    "检索": "retrieval",
    "日志": "log",
}


ENGLISH_SYNONYMS = {
    "crash": "crash",
    "exception": "crash",
    "fatal": "crash",
    "nullpointerexception": "nullpointer",
    "npe": "nullpointer",
    "anr": "anr",
    "main": "mainthread",
    "mainthread": "mainthread",
    "activity": "activity",
    "lifecycle": "lifecycle",
    "logcat": "log",
    "stacktrace": "stacktrace",
    "embedding": "embedding",
    "vector": "vector",
    "retrieval": "retrieval",
    "rag": "rag",
}


def build_embeddings_payload(model, inputs, dimensions=None, encoding_format="float"):
    payload = {
        "model": model,
        "input": inputs,
        "encoding_format": encoding_format,
    }
    if dimensions is not None:
        payload["dimensions"] = dimensions
    return payload


def chunk_text(text, max_chars=500, overlap=80):
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    chunks = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(
            {
                "chunk_index": index,
                "start": start,
                "end": end,
                "text": text[start:end],
            }
        )
        if end == len(text):
            break
        start = end - overlap
        index += 1
    return chunks


def tokenize(text):
    lowered = text.lower()
    tokens = []

    for phrase, canonical in SYNONYM_PHRASES.items():
        if phrase in lowered:
            tokens.append(canonical)

    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", lowered):
        tokens.append(ENGLISH_SYNONYMS.get(token, token))

    for number in re.findall(r"\d+", lowered):
        tokens.append(number)

    return tokens


def toy_embed(text, dimensions=128):
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        vector[bucket] += 1.0
    return vector


def cosine_similarity(left, right):
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def build_vector_index(documents, dimensions=128, max_chars=500, overlap=80):
    index = []
    for document in documents:
        chunks = chunk_text(document["text"], max_chars=max_chars, overlap=overlap)
        for chunk in chunks:
            index.append(
                {
                    "document_id": document["id"],
                    "title": document.get("title", document["id"]),
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "start": chunk["start"],
                    "end": chunk["end"],
                    "embedding": toy_embed(
                        f"{document.get('title', '')}\n{chunk['text']}",
                        dimensions=dimensions,
                    ),
                }
            )
    return index


def search_index(index, query, top_k=3, dimensions=128):
    query_embedding = toy_embed(query, dimensions=dimensions)
    scored = []
    for item in index:
        score = cosine_similarity(query_embedding, item["embedding"])
        scored.append(
            {
                "score": round(score, 6),
                "document_id": item["document_id"],
                "title": item["title"],
                "chunk_index": item["chunk_index"],
                "text": item["text"],
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def load_documents(path=DEFAULT_DOCS_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)["documents"]


def build_parser():
    parser = argparse.ArgumentParser(description="Local toy embedding and vector search demo")
    parser.add_argument("--docs", default=str(DEFAULT_DOCS_PATH), help="示例文档 JSON 路径")
    parser.add_argument("--dimensions", type=int, default=128)
    subparsers = parser.add_subparsers(dest="command", required=True)

    payload = subparsers.add_parser("payload", help="打印 Embeddings API 请求体示例")
    payload.add_argument("--model", default=DEFAULT_MODEL)
    payload.add_argument("--input", required=True)
    payload.add_argument("--dimensions", type=int)

    search = subparsers.add_parser("search", help="在本地示例文档上执行玩具向量检索")
    search.add_argument("--query", required=True)
    search.add_argument("--top-k", type=int, default=3)
    search.add_argument("--max-chars", type=int, default=220)
    search.add_argument("--overlap", type=int, default=40)

    chunks = subparsers.add_parser("chunks", help="展示文档切分结果")
    chunks.add_argument("--max-chars", type=int, default=220)
    chunks.add_argument("--overlap", type=int, default=40)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "payload":
        result = build_embeddings_payload(
            model=args.model,
            inputs=[args.input],
            dimensions=args.dimensions,
        )
    else:
        documents = load_documents(args.docs)
        if args.command == "chunks":
            result = [
                {
                    "document_id": document["id"],
                    "title": document.get("title", document["id"]),
                    "chunks": chunk_text(
                        document["text"],
                        max_chars=args.max_chars,
                        overlap=args.overlap,
                    ),
                }
                for document in documents
            ]
        else:
            index = build_vector_index(
                documents,
                dimensions=args.dimensions,
                max_chars=args.max_chars,
                overlap=args.overlap,
            )
            result = {
                "query": args.query,
                "results": search_index(
                    index,
                    query=args.query,
                    top_k=args.top_k,
                    dimensions=args.dimensions,
                ),
            }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
