import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_backend_gateway import (  # noqa: E402
    FakeModelClient,
    InMemoryRateLimiter,
    LlmRequest,
    estimate_tokens,
    handle_chat_request,
    mask_sensitive_text,
    pick_model,
    retry_with_backoff,
    sse_events_from_text,
)


class LlmBackendGatewayTests(unittest.TestCase):
    def test_estimate_tokens_uses_character_based_floor(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("hello"), 2)
        self.assertEqual(estimate_tokens("a" * 400), 100)

    def test_pick_model_routes_by_task_and_token_budget(self):
        small = pick_model(task_type="chat", estimated_input_tokens=100)
        rag = pick_model(task_type="rag", estimated_input_tokens=100)
        long_context = pick_model(task_type="chat", estimated_input_tokens=9000)

        self.assertEqual(small.name, "fast-chat")
        self.assertEqual(rag.name, "balanced-rag")
        self.assertEqual(long_context.name, "long-context")

    def test_rate_limiter_allows_until_limit_then_blocks(self):
        limiter = InMemoryRateLimiter(max_requests=2)

        self.assertTrue(limiter.allow("user-1"))
        self.assertTrue(limiter.allow("user-1"))
        self.assertFalse(limiter.allow("user-1"))
        self.assertTrue(limiter.allow("user-2"))

    def test_retry_with_backoff_retries_transient_errors(self):
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise TimeoutError("temporary")
            return "ok"

        result = retry_with_backoff(flaky, max_retries=3, base_delay_ms=0)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_mask_sensitive_text_redacts_tokens_and_email(self):
        text = "contact me@example.com with sk-1234567890abcdef"

        masked = mask_sensitive_text(text)

        self.assertNotIn("me@example.com", masked)
        self.assertNotIn("sk-1234567890abcdef", masked)
        self.assertIn("[email]", masked)
        self.assertIn("[api_key]", masked)

    def test_sse_events_from_text_splits_delta_events_and_done(self):
        events = list(sse_events_from_text("hello world", chunk_size=5))

        self.assertEqual(events[0], "event: response.output_text.delta\ndata: hello\n")
        self.assertEqual(events[1], "event: response.output_text.delta\ndata:  worl\n")
        self.assertEqual(events[-1], "event: response.completed\ndata: [DONE]\n")

    def test_handle_chat_request_enforces_budget_and_logs_safely(self):
        request = LlmRequest(
            user_id="u1",
            task_type="chat",
            prompt="请分析这个 token sk-1234567890abcdef，联系 me@example.com",
            max_output_tokens=200,
        )
        client = FakeModelClient(response_text="后端网关应该隐藏密钥并记录 trace。")

        response = handle_chat_request(
            request,
            client=client,
            rate_limiter=InMemoryRateLimiter(max_requests=3),
            token_budget=1000,
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["model"], "fast-chat")
        self.assertIn("trace_id", response)
        self.assertNotIn("sk-1234567890abcdef", response["log"]["prompt"])
        self.assertNotIn("me@example.com", response["log"]["prompt"])

    def test_handle_chat_request_rejects_when_token_budget_exceeded(self):
        request = LlmRequest(
            user_id="u1",
            task_type="chat",
            prompt="a" * 4000,
            max_output_tokens=200,
        )

        response = handle_chat_request(
            request,
            client=FakeModelClient(),
            rate_limiter=InMemoryRateLimiter(max_requests=3),
            token_budget=500,
        )

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["error"], "token_budget_exceeded")

    def test_handle_chat_request_rejects_when_rate_limited(self):
        limiter = InMemoryRateLimiter(max_requests=0)
        request = LlmRequest(user_id="u1", task_type="chat", prompt="hello")

        response = handle_chat_request(
            request,
            client=FakeModelClient(),
            rate_limiter=limiter,
            token_budget=1000,
        )

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["error"], "rate_limited")


if __name__ == "__main__":
    unittest.main()
