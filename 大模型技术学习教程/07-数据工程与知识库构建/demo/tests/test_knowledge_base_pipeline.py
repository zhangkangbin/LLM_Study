import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge_base_pipeline import (  # noqa: E402
    Document,
    build_current_manifest,
    chunk_document,
    diff_manifests,
    normalize_text,
    parse_front_matter,
    run_pipeline,
)


class KnowledgeBasePipelineTests(unittest.TestCase):
    def test_normalize_text_collapses_whitespace_and_control_chars(self):
        raw = "  Android\u200b  崩溃\r\n\r\n日志\t\t分析  "

        self.assertEqual(normalize_text(raw), "Android 崩溃 日志 分析")

    def test_parse_front_matter_extracts_metadata_and_body(self):
        content = """---
id: android-crash
title: Android 崩溃排查
source_uri: app://docs/crash
tags: android, crash, logcat
version: v1
---

# 标题

正文内容
"""

        metadata, body = parse_front_matter(content)

        self.assertEqual(metadata["id"], "android-crash")
        self.assertEqual(metadata["title"], "Android 崩溃排查")
        self.assertEqual(metadata["tags"], ["android", "crash", "logcat"])
        self.assertEqual(metadata["version"], "v1")
        self.assertIn("正文内容", body)

    def test_chunk_document_keeps_metadata_and_stable_chunk_ids(self):
        document = Document(
            doc_id="android-anr",
            title="Android ANR 排查",
            source_uri="app://docs/anr",
            body="主线程 IO 会导致 ANR。" * 20,
            metadata={"tags": ["android", "anr"], "version": "v2"},
        )

        chunks = chunk_document(document, max_chars=80, overlap=16)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["doc_id"], "android-anr")
        self.assertEqual(chunks[0]["title"], "Android ANR 排查")
        self.assertEqual(chunks[0]["source_uri"], "app://docs/anr")
        self.assertEqual(chunks[0]["tags"], ["android", "anr"])
        self.assertEqual(chunks[0]["version"], "v2")
        self.assertTrue(chunks[0]["chunk_id"].startswith("android-anr:"))
        self.assertNotEqual(chunks[0]["chunk_id"], chunks[1]["chunk_id"])

    def test_build_current_manifest_summarizes_documents(self):
        documents = [
            Document(
                doc_id="faq",
                title="产品 FAQ",
                source_uri="app://docs/faq",
                body="退款政策与账号注销说明",
                metadata={"version": "v1"},
            )
        ]

        manifest = build_current_manifest(documents, max_chars=20, overlap=5)

        self.assertEqual(manifest["documents"]["faq"]["title"], "产品 FAQ")
        self.assertEqual(manifest["documents"]["faq"]["source_uri"], "app://docs/faq")
        self.assertGreaterEqual(manifest["documents"]["faq"]["chunk_count"], 1)
        self.assertRegex(manifest["documents"]["faq"]["checksum"], r"^[a-f0-9]{64}$")

    def test_diff_manifests_detects_created_updated_deleted_and_unchanged(self):
        previous = {
            "documents": {
                "old": {"checksum": "aaa"},
                "update": {"checksum": "bbb"},
                "same": {"checksum": "ccc"},
            }
        }
        current = {
            "documents": {
                "new": {"checksum": "ddd"},
                "update": {"checksum": "changed"},
                "same": {"checksum": "ccc"},
            }
        }

        plan = diff_manifests(previous, current)

        self.assertEqual(plan["created"], ["new"])
        self.assertEqual(plan["updated"], ["update"])
        self.assertEqual(plan["deleted"], ["old"])
        self.assertEqual(plan["unchanged"], ["same"])

    def test_run_pipeline_writes_chunks_manifest_and_sync_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "source_docs"
            output_dir = root / "build"
            previous_manifest = root / "previous_manifest.json"
            input_dir.mkdir()
            previous_manifest.write_text(
                json.dumps({"documents": {"removed": {"checksum": "gone"}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (input_dir / "android_crash.md").write_text(
                """---
id: android-crash
title: Android 崩溃排查
source_uri: app://docs/crash
tags: android, crash
version: v1
---

NullPointerException 需要结合 FATAL EXCEPTION、Caused by 和业务堆栈分析。
""",
                encoding="utf-8",
            )

            result = run_pipeline(
                input_dir=input_dir,
                output_dir=output_dir,
                previous_manifest_path=previous_manifest,
                max_chars=60,
                overlap=10,
            )

            self.assertEqual(result["document_count"], 1)
            self.assertEqual(result["chunk_count"], 1)
            self.assertTrue((output_dir / "chunks.jsonl").exists())
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "sync_plan.json").exists())
            chunks = [
                json.loads(line)
                for line in (output_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(chunks[0]["doc_id"], "android-crash")
            plan = json.loads((output_dir / "sync_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["created"], ["android-crash"])
            self.assertEqual(plan["deleted"], ["removed"])


if __name__ == "__main__":
    unittest.main()
