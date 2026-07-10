import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = Path(__file__).resolve().parent / "source_docs"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "build"

LIST_FIELDS = {"tags", "aliases", "audiences"}
CONTROL_CHARS_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    source_uri: str
    body: str
    metadata: dict[str, Any]


def normalize_text(text: str) -> str:
    without_control_chars = CONTROL_CHARS_PATTERN.sub("", text)
    return WHITESPACE_PATTERN.sub(" ", without_control_chars).strip()


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    normalized_newlines = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_newlines.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, normalized_newlines

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        return {}, normalized_newlines

    metadata: dict[str, Any] = {}
    for line in lines[1:closing_index]:
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in LIST_FIELDS:
            metadata[key] = [item.strip() for item in value.split(",") if item.strip()]
        else:
            metadata[key] = value

    body = "\n".join(lines[closing_index + 1 :]).strip()
    return metadata, body


def load_documents(input_dir: Path | str = DEFAULT_INPUT_DIR) -> list[Document]:
    root = Path(input_dir)
    documents: list[Document] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".md":
            documents.append(load_markdown_document(path))
        elif path.suffix.lower() == ".txt":
            documents.append(load_text_document(path))
        elif path.suffix.lower() == ".json":
            documents.extend(load_json_documents(path))
    return documents


def load_markdown_document(path: Path) -> Document:
    content = path.read_text(encoding="utf-8")
    metadata, body = parse_front_matter(content)
    doc_id = str(metadata.get("id") or path.stem)
    title = str(metadata.get("title") or extract_title(body) or path.stem)
    source_uri = str(metadata.get("source_uri") or path.as_posix())
    clean_metadata = {
        key: value
        for key, value in metadata.items()
        if key not in {"id", "title", "source_uri"}
    }
    return Document(
        doc_id=doc_id,
        title=title,
        source_uri=source_uri,
        body=normalize_text(strip_markdown_heading(body)),
        metadata=clean_metadata,
    )


def load_text_document(path: Path) -> Document:
    return Document(
        doc_id=path.stem,
        title=path.stem.replace("_", " "),
        source_uri=path.as_posix(),
        body=normalize_text(path.read_text(encoding="utf-8")),
        metadata={"format": "txt"},
    )


def load_json_documents(path: Path) -> list[Document]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("documents", raw) if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise ValueError(f"{path} must contain a JSON array or a documents array")

    documents: list[Document] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"{path} record {index} must be an object")
        doc_id = str(record.get("id") or f"{path.stem}-{index}")
        title = str(record.get("title") or doc_id)
        source_uri = str(record.get("source_uri") or f"{path.as_posix()}#{index}")
        body = str(record.get("body") or record.get("content") or record.get("text") or "")
        metadata = dict(record.get("metadata") or {})
        for key, value in record.items():
            if key not in {"id", "title", "source_uri", "body", "content", "text", "metadata"}:
                metadata.setdefault(key, value)
        documents.append(
            Document(
                doc_id=doc_id,
                title=title,
                source_uri=source_uri,
                body=normalize_text(body),
                metadata=metadata,
            )
        )
    return documents


def extract_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def strip_markdown_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].strip().startswith("# "):
        return "\n".join(lines[1:]).strip()
    return markdown


def document_checksum(document: Document) -> str:
    canonical = {
        "doc_id": document.doc_id,
        "title": document.title,
        "source_uri": document.source_uri,
        "body": document.body,
        "metadata": document.metadata,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_document(document: Document, max_chars: int = 700, overlap: int = 120) -> list[dict[str, Any]]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    text = normalize_text(document.body)
    if not text:
        return []

    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_index = 0
    step = max_chars - overlap
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk_text = text[start:end].strip()
        checksum = text_checksum(chunk_text)
        chunks.append(
            {
                "chunk_id": f"{document.doc_id}:{chunk_index}:{checksum[:12]}",
                "doc_id": document.doc_id,
                "title": document.title,
                "source_uri": document.source_uri,
                "chunk_index": chunk_index,
                "text": chunk_text,
                "text_checksum": checksum,
                "char_count": len(chunk_text),
                "tags": document.metadata.get("tags", []),
                "version": document.metadata.get("version", "unknown"),
                "metadata": document.metadata,
            }
        )
        if end == len(text):
            break
        start += step
        chunk_index += 1
    return chunks


def build_current_manifest(
    documents: list[Document], max_chars: int = 700, overlap: int = 120
) -> dict[str, Any]:
    manifest = {
        "schema_version": "1.0",
        "chunking": {"max_chars": max_chars, "overlap": overlap},
        "documents": {},
    }
    for document in sorted(documents, key=lambda item: item.doc_id):
        chunks = chunk_document(document, max_chars=max_chars, overlap=overlap)
        manifest["documents"][document.doc_id] = {
            "title": document.title,
            "source_uri": document.source_uri,
            "checksum": document_checksum(document),
            "chunk_count": len(chunks),
            "version": document.metadata.get("version", "unknown"),
            "tags": document.metadata.get("tags", []),
        }
    return manifest


def diff_manifests(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    previous_docs = previous.get("documents", {})
    current_docs = current.get("documents", {})
    previous_ids = set(previous_docs)
    current_ids = set(current_docs)
    common_ids = previous_ids & current_ids

    return {
        "created": sorted(current_ids - previous_ids),
        "updated": sorted(
            doc_id
            for doc_id in common_ids
            if previous_docs[doc_id].get("checksum") != current_docs[doc_id].get("checksum")
        ),
        "deleted": sorted(previous_ids - current_ids),
        "unchanged": sorted(
            doc_id
            for doc_id in common_ids
            if previous_docs[doc_id].get("checksum") == current_docs[doc_id].get("checksum")
        ),
    }


def run_pipeline(
    input_dir: Path | str = DEFAULT_INPUT_DIR,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    previous_manifest_path: Path | str | None = None,
    max_chars: int = 700,
    overlap: int = 120,
) -> dict[str, Any]:
    source_dir = Path(input_dir)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    documents = load_documents(source_dir)
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_chars=max_chars, overlap=overlap)
    ]
    manifest = build_current_manifest(documents, max_chars=max_chars, overlap=overlap)
    previous_manifest = load_manifest(previous_manifest_path)
    sync_plan = diff_manifests(previous_manifest, manifest)

    write_jsonl(target_dir / "chunks.jsonl", chunks)
    write_json(target_dir / "manifest.json", manifest)
    write_json(target_dir / "sync_plan.json", sync_plan)

    return {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "output_dir": target_dir.as_posix(),
        "chunks_path": (target_dir / "chunks.jsonl").as_posix(),
        "manifest_path": (target_dir / "manifest.json").as_posix(),
        "sync_plan_path": (target_dir / "sync_plan.json").as_posix(),
        "sync_plan": sync_plan,
    }


def load_manifest(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {"documents": {}}
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {"documents": {}}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a small local knowledge-base index.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="List normalized source documents.")
    inspect_parser.add_argument("--input", default=str(DEFAULT_INPUT_DIR))

    build_parser = subparsers.add_parser("build", help="Build chunks, manifest, and sync plan.")
    build_parser.add_argument("--input", default=str(DEFAULT_INPUT_DIR))
    build_parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR))
    build_parser.add_argument("--previous-manifest")
    build_parser.add_argument("--max-chars", type=int, default=180)
    build_parser.add_argument("--overlap", type=int, default=40)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect":
        documents = load_documents(args.input)
        payload = [
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "source_uri": document.source_uri,
                "char_count": len(document.body),
                "metadata": document.metadata,
            }
            for document in documents
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "build":
        result = run_pipeline(
            input_dir=args.input,
            output_dir=args.output,
            previous_manifest_path=args.previous_manifest,
            max_chars=args.max_chars,
            overlap=args.overlap,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
