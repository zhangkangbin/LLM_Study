import argparse
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider_model: str
    max_context_tokens: int
    cost_tier: str
    supports_streaming: bool


@dataclass(frozen=True)
class LlmRequest:
    user_id: str
    task_type: str
    prompt: str
    max_output_tokens: int = 512
    stream: bool = False


MODEL_PROFILES = [
    ModelProfile(
        name="fast-chat",
        provider_model="gpt-5.5-mini",
        max_context_tokens=8_000,
        cost_tier="low",
        supports_streaming=True,
    ),
    ModelProfile(
        name="balanced-rag",
        provider_model="gpt-5.5",
        max_context_tokens=32_000,
        cost_tier="medium",
        supports_streaming=True,
    ),
    ModelProfile(
        name="long-context",
        provider_model="gpt-5.5",
        max_context_tokens=128_000,
        cost_tier="high",
        supports_streaming=True,
    ),
]


class InMemoryRateLimiter:
    def __init__(self, max_requests: int) -> None:
        self.max_requests = max_requests
        self._counts: dict[str, int] = {}

    def allow(self, key: str) -> bool:
        current = self._counts.get(key, 0)
        if current >= self.max_requests:
            return False
        self._counts[key] = current + 1
        return True


class FakeModelClient:
    def __init__(self, response_text: str = "这是一个模拟模型响应。") -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def create_response(self, model: str, prompt: str, max_output_tokens: int) -> dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "max_output_tokens": max_output_tokens,
            }
        )
        return {
            "id": stable_trace_id(f"{model}|{prompt}|{len(self.calls)}"),
            "output_text": self.response_text,
            "usage": {
                "input_tokens": estimate_tokens(prompt),
                "output_tokens": estimate_tokens(self.response_text),
            },
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def pick_model(task_type: str, estimated_input_tokens: int) -> ModelProfile:
    if estimated_input_tokens > 8_000:
        return profile_by_name("long-context")
    if task_type in {"rag", "agent", "analysis"}:
        return profile_by_name("balanced-rag")
    return profile_by_name("fast-chat")


def profile_by_name(name: str) -> ModelProfile:
    for profile in MODEL_PROFILES:
        if profile.name == name:
            return profile
    raise ValueError(f"unknown model profile: {name}")


def retry_with_backoff(
    operation: Callable[[], Any],
    max_retries: int = 3,
    base_delay_ms: int = 50,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return operation()
        except (TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt == max_retries - 1:
                break
            delay = (base_delay_ms / 1000.0) * (2**attempt)
            if delay > 0:
                time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("operation was not attempted")


def mask_sensitive_text(text: str) -> str:
    masked = EMAIL_PATTERN.sub("[email]", text)
    return API_KEY_PATTERN.sub("[api_key]", masked)


def stable_trace_id(seed: str) -> str:
    return f"trace_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def sse_events_from_text(text: str, chunk_size: int = 12) -> Iterable[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    for start in range(0, len(text), chunk_size):
        yield f"event: response.output_text.delta\ndata: {text[start:start + chunk_size]}\n"
    yield "event: response.completed\ndata: [DONE]\n"


def build_responses_payload(
    request: LlmRequest,
    model_profile: ModelProfile,
    background: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_profile.provider_model,
        "input": request.prompt,
        "max_output_tokens": request.max_output_tokens,
        "stream": request.stream,
    }
    if background:
        payload["background"] = True
    return payload


def handle_chat_request(
    request: LlmRequest,
    client: FakeModelClient,
    rate_limiter: InMemoryRateLimiter,
    token_budget: int,
) -> dict[str, Any]:
    trace_id = stable_trace_id(f"{request.user_id}|{request.task_type}|{request.prompt}")
    estimated_input_tokens = estimate_tokens(request.prompt)
    total_estimated_tokens = estimated_input_tokens + request.max_output_tokens

    if not rate_limiter.allow(request.user_id):
        return {
            "status": "rejected",
            "error": "rate_limited",
            "trace_id": trace_id,
        }
    if total_estimated_tokens > token_budget:
        return {
            "status": "rejected",
            "error": "token_budget_exceeded",
            "trace_id": trace_id,
            "estimated_tokens": total_estimated_tokens,
            "token_budget": token_budget,
        }

    model_profile = pick_model(request.task_type, estimated_input_tokens)
    result = retry_with_backoff(
        lambda: client.create_response(
            model=model_profile.provider_model,
            prompt=request.prompt,
            max_output_tokens=request.max_output_tokens,
        ),
        max_retries=3,
    )
    response: dict[str, Any] = {
        "status": "ok",
        "trace_id": trace_id,
        "model": model_profile.name,
        "provider_model": model_profile.provider_model,
        "output_text": result["output_text"],
        "usage": result["usage"],
        "log": build_safe_log(request, model_profile, trace_id),
    }
    if request.stream:
        response["events"] = list(sse_events_from_text(result["output_text"]))
    return response


def build_safe_log(
    request: LlmRequest,
    model_profile: ModelProfile,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "user_id": request.user_id,
        "task_type": request.task_type,
        "model": model_profile.name,
        "provider_model": model_profile.provider_model,
        "prompt": mask_sensitive_text(request.prompt),
        "estimated_input_tokens": estimate_tokens(request.prompt),
        "max_output_tokens": request.max_output_tokens,
        "stream": request.stream,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local LLM backend gateway demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route_parser = subparsers.add_parser("route", help="Pick a model profile for a request.")
    route_parser.add_argument("--task-type", default="chat")
    route_parser.add_argument("--prompt", required=True)

    chat_parser = subparsers.add_parser("chat", help="Handle a simulated chat request.")
    chat_parser.add_argument("--user-id", default="demo-user")
    chat_parser.add_argument("--task-type", default="chat")
    chat_parser.add_argument("--prompt", required=True)
    chat_parser.add_argument("--max-output-tokens", type=int, default=256)
    chat_parser.add_argument("--token-budget", type=int, default=2000)
    chat_parser.add_argument("--stream", action="store_true")

    payload_parser = subparsers.add_parser("payload", help="Build a Responses API request payload.")
    payload_parser.add_argument("--task-type", default="chat")
    payload_parser.add_argument("--prompt", required=True)
    payload_parser.add_argument("--stream", action="store_true")
    payload_parser.add_argument("--background", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "route":
        profile = pick_model(args.task_type, estimate_tokens(args.prompt))
        print(json.dumps(profile.__dict__, ensure_ascii=False, indent=2))
        return

    if args.command == "chat":
        request = LlmRequest(
            user_id=args.user_id,
            task_type=args.task_type,
            prompt=args.prompt,
            max_output_tokens=args.max_output_tokens,
            stream=args.stream,
        )
        response = handle_chat_request(
            request,
            client=FakeModelClient(response_text="模拟响应：后端已完成鉴权、预算检查、模型路由和安全日志。"),
            rate_limiter=InMemoryRateLimiter(max_requests=3),
            token_budget=args.token_budget,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.command == "payload":
        request = LlmRequest(
            user_id="demo-user",
            task_type=args.task_type,
            prompt=args.prompt,
            stream=args.stream,
        )
        profile = pick_model(request.task_type, estimate_tokens(request.prompt))
        payload = build_responses_payload(request, profile, background=args.background)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
