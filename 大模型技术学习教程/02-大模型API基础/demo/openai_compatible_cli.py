import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.5"


def build_responses_payload(
    prompt,
    model,
    instructions=None,
    stream=False,
    max_output_tokens=None,
):
    payload = {
        "model": model,
        "input": prompt,
        "stream": stream,
    }
    if instructions:
        payload["instructions"] = instructions
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return payload


def normalize_responses_url(base_url):
    base = base_url.rstrip("/")
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def extract_output_text(response_json):
    if isinstance(response_json.get("output_text"), str):
        return response_json["output_text"]

    chunks = []
    for item in response_json.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def parse_sse_events(lines):
    event_type = None
    data_lines = []

    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8")
        else:
            line = raw_line

        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    payload = {"raw": data}
                if event_type and "type" not in payload:
                    payload["type"] = event_type
                yield payload
            event_type = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())

    if data_lines:
        data = "\n".join(data_lines)
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            payload = {"raw": data}
        if event_type and "type" not in payload:
            payload["type"] = event_type
        yield payload


def extract_stream_delta(event):
    if event.get("type") == "response.output_text.delta":
        return event.get("delta", "")
    return ""


def call_responses_api(api_key, base_url, payload):
    request = urllib.request.Request(
        normalize_responses_url(base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=60)


def run_once(args):
    model = args.model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    payload = build_responses_payload(
        prompt=args.prompt,
        model=model,
        instructions=args.instructions,
        stream=args.stream,
        max_output_tokens=args.max_output_tokens,
    )

    if args.dry_run:
        print(json.dumps({"url": normalize_responses_url(base_url), "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    if not api_key:
        print("缺少 OPENAI_API_KEY。可以先加 --dry-run 查看请求体。", file=sys.stderr)
        return 2

    try:
        with call_responses_api(api_key, base_url, payload) as response:
            if args.stream:
                for event in parse_sse_events(response):
                    delta = extract_stream_delta(event)
                    if delta:
                        print(delta, end="", flush=True)
                print()
            else:
                data = json.loads(response.read().decode("utf-8"))
                print(extract_output_text(data))
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"请求失败: {exc}", file=sys.stderr)
        return 1


def build_parser():
    parser = argparse.ArgumentParser(description="OpenAI-compatible Responses API CLI demo")
    parser.add_argument("--prompt", required=True, help="用户输入内容")
    parser.add_argument("--instructions", help="系统级指令，对应 Responses API 的 instructions")
    parser.add_argument("--model", help=f"模型名称，默认读取 OPENAI_MODEL 或使用 {DEFAULT_MODEL}")
    parser.add_argument("--base-url", help=f"API Base URL，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--api-key", help="API Key，默认读取 OPENAI_API_KEY")
    parser.add_argument("--max-output-tokens", type=int, help="限制最大输出 Token")
    parser.add_argument("--stream", action="store_true", help="启用 SSE 流式输出")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求 URL 和 JSON 请求体")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
