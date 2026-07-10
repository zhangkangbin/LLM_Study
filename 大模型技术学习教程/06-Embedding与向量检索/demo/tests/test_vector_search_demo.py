import pathlib
import sys
import unittest


DEMO_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import vector_search_demo as demo


class EmbeddingPayloadTest(unittest.TestCase):
    def test_builds_embeddings_payload_for_multiple_inputs(self):
        payload = demo.build_embeddings_payload(
            model="text-embedding-3-small",
            inputs=["Android 崩溃日志", "ANR 主线程无响应"],
            dimensions=256,
        )

        self.assertEqual(payload["model"], "text-embedding-3-small")
        self.assertEqual(payload["input"], ["Android 崩溃日志", "ANR 主线程无响应"])
        self.assertEqual(payload["encoding_format"], "float")
        self.assertEqual(payload["dimensions"], 256)


class ChunkingTest(unittest.TestCase):
    def test_chunks_text_with_overlap(self):
        text = "0123456789" * 5

        chunks = demo.chunk_text(text, max_chars=20, overlap=5)

        self.assertEqual(chunks[0]["text"], "01234567890123456789")
        self.assertEqual(chunks[1]["start"], 15)
        self.assertEqual(chunks[1]["text"], "56789012345678901234")
        self.assertEqual(chunks[-1]["end"], len(text))

    def test_rejects_overlap_greater_than_window(self):
        with self.assertRaises(ValueError):
            demo.chunk_text("abcdef", max_chars=5, overlap=5)


class VectorSearchTest(unittest.TestCase):
    def test_cosine_similarity_identical_vectors_is_one(self):
        similarity = demo.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])

        self.assertAlmostEqual(similarity, 1.0)

    def test_search_returns_most_relevant_android_crash_chunk(self):
        documents = [
            {
                "id": "crash",
                "title": "Android 崩溃排查",
                "text": "NullPointerException 常见于 Activity 生命周期中对象未初始化。崩溃日志应关注 FATAL EXCEPTION 和关键堆栈。",
            },
            {
                "id": "anr",
                "title": "ANR 排查",
                "text": "ANR 表示主线程长时间无响应，常见原因包括主线程 IO、锁等待和 BroadcastReceiver 超时。",
            },
            {
                "id": "ui",
                "title": "UI 设计",
                "text": "聊天界面需要处理 Markdown、代码块和流式输出状态。",
            },
        ]
        index = demo.build_vector_index(documents, dimensions=128, max_chars=80, overlap=10)

        results = demo.search_index(index, "空指针崩溃 NullPointerException 怎么排查", top_k=2)

        self.assertEqual(results[0]["document_id"], "crash")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_search_returns_anr_chunk_for_no_response_query(self):
        documents = [
            {
                "id": "crash",
                "title": "Android 崩溃排查",
                "text": "NullPointerException 常见于 Activity 生命周期中对象未初始化。",
            },
            {
                "id": "anr",
                "title": "ANR 排查",
                "text": "ANR 表示主线程长时间无响应，常见原因包括主线程 IO、锁等待和 BroadcastReceiver 超时。",
            },
        ]
        index = demo.build_vector_index(documents, dimensions=128, max_chars=80, overlap=10)

        results = demo.search_index(index, "App 卡死无响应 主线程", top_k=1)

        self.assertEqual(results[0]["document_id"], "anr")


if __name__ == "__main__":
    unittest.main()
