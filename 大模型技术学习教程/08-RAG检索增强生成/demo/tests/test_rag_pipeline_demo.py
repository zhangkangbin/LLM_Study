import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_pipeline_demo import (  # noqa: E402
    answer_question,
    build_file_search_payload,
    build_rag_prompt,
    load_chunks,
    retrieve_context,
)


def sample_chunks():
    return [
        {
            "chunk_id": "android-crash-guide:0:aaa",
            "doc_id": "android-crash-guide",
            "title": "Android 崩溃排查知识",
            "source_uri": "app://knowledge/android/crash",
            "chunk_index": 0,
            "text": "NullPointerException 需要结合 FATAL EXCEPTION、Caused by、业务堆栈和最近发布版本分析。页面切换后崩溃要检查 Activity 生命周期和异步回调。",
            "tags": ["android", "crash", "logcat"],
            "version": "v1",
        },
        {
            "chunk_id": "backend-api-errors:0:bbb",
            "doc_id": "backend-api-errors",
            "title": "后端 API 错误排查",
            "source_uri": "app://knowledge/backend/api-errors",
            "chunk_index": 0,
            "text": "接口错误知识库应记录 HTTP 状态码、业务错误码、trace_id、请求参数摘要和下游依赖。",
            "tags": ["backend", "api"],
            "version": "v1",
        },
        {
            "chunk_id": "product-refund-faq:0:ccc",
            "doc_id": "product-refund-faq",
            "title": "产品退款 FAQ",
            "source_uri": "app://knowledge/product/refund",
            "chunk_index": 0,
            "text": "用户申请退款时，需要确认订单状态、支付渠道、购买时间和是否已经消耗权益。",
            "tags": ["product", "faq"],
            "version": "v1",
        },
    ]


class RagPipelineDemoTests(unittest.TestCase):
    def test_load_chunks_reads_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chunks.jsonl"
            path.write_text(
                "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in sample_chunks()),
                encoding="utf-8",
            )

            chunks = load_chunks(path)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["doc_id"], "android-crash-guide")

    def test_retrieve_context_ranks_relevant_android_crash_chunk(self):
        results = retrieve_context(
            "空指针 NullPointerException 页面切换后崩溃怎么排查",
            sample_chunks(),
            top_k=2,
            min_score=0.1,
        )

        self.assertEqual(results[0]["doc_id"], "android-crash-guide")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_retrieve_context_supports_metadata_filtering(self):
        results = retrieve_context(
            "接口 500 错误 trace_id 怎么定位",
            sample_chunks(),
            top_k=3,
            required_tags=["backend"],
        )

        self.assertEqual([item["doc_id"] for item in results], ["backend-api-errors"])

    def test_build_rag_prompt_contains_rules_context_and_citations(self):
        contexts = retrieve_context("退款需要看什么", sample_chunks(), top_k=1)

        prompt = build_rag_prompt("退款需要看什么", contexts)

        self.assertIn("只能基于【检索上下文】回答", prompt)
        self.assertIn("[product-refund-faq#0]", prompt)
        self.assertIn("退款需要看什么", prompt)

    def test_answer_question_returns_grounded_answer_with_citations(self):
        result = answer_question(
            "空指针崩溃怎么排查",
            sample_chunks(),
            top_k=2,
            min_score=0.1,
        )

        self.assertEqual(result["status"], "answered")
        self.assertIn("FATAL EXCEPTION", result["answer"])
        self.assertEqual(result["citations"][0]["doc_id"], "android-crash-guide")

    def test_answer_question_falls_back_when_no_context_matches(self):
        result = answer_question(
            "今天上海天气怎么样",
            sample_chunks(),
            top_k=2,
            min_score=0.2,
        )

        self.assertEqual(result["status"], "no_answer")
        self.assertIn("知识库中没有足够信息", result["answer"])
        self.assertEqual(result["citations"], [])

    def test_build_file_search_payload_matches_responses_api_shape(self):
        payload = build_file_search_payload(
            question="怎么排查退款问题",
            vector_store_ids=["vs_123"],
            model="gpt-5.5",
            max_num_results=2,
            include_results=True,
        )

        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["input"], "怎么排查退款问题")
        self.assertEqual(payload["tools"][0]["type"], "file_search")
        self.assertEqual(payload["tools"][0]["vector_store_ids"], ["vs_123"])
        self.assertEqual(payload["tools"][0]["max_num_results"], 2)
        self.assertEqual(payload["include"], ["file_search_call.results"])


if __name__ == "__main__":
    unittest.main()
