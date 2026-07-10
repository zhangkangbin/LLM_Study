from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RouteDecision:
    mode: str
    recommended_api: str
    reason: str
    client_boundary: str


def chunk_audio_bytes(audio_bytes: bytes, chunk_size: int) -> list[bytes]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    return [
        audio_bytes[index : index + chunk_size]
        for index in range(0, len(audio_bytes), chunk_size)
    ]


def merge_transcript_events(
    events: Iterable[dict[str, object]],
    *,
    separator: str = "",
) -> str:
    final_segments: list[str] = []
    latest_partial = ""

    for event in events:
        text = str(event.get("text", ""))
        event_type = str(event.get("type", "")).lower()
        is_final = bool(event.get("is_final", False))

        if not text:
            continue

        if event_type == "final" or is_final:
            final_segments.append(text)
        elif event_type == "partial":
            latest_partial = text

    if final_segments:
        return separator.join(final_segments)
    return latest_partial


def route_multimodal_task(
    text: str,
    *,
    has_image: bool = False,
    needs_low_latency: bool = False,
) -> RouteDecision:
    normalized = text.lower()

    if has_image or _contains_any(normalized, ["图片", "截图", "照片", "视觉", "ocr", "拍照"]):
        return RouteDecision(
            mode="image_understanding",
            recommended_api="responses",
            reason="输入包含图片或截图，需要把文本与图像作为同一次用户输入处理。",
            client_boundary="Android 负责选图/拍照/压缩，后端负责签名上传与模型调用。",
        )

    if needs_low_latency or _contains_any(normalized, ["实时", "通话", "打断", "边说边", "realtime"]):
        return RouteDecision(
            mode="realtime_voice",
            recommended_api="realtime",
            reason="用户希望低延迟双向语音交互，需要持续会话、打断和语音输出。",
            client_boundary="Android 持有短时会话凭证，模型密钥只保留在后端。",
        )

    if _contains_any(normalized, ["转写", "听写", "录音识别", "speech to text", "stt"]):
        return RouteDecision(
            mode="speech_to_text",
            recommended_api="audio_transcription",
            reason="任务核心是把录音转成文本，再进入普通文本处理链路。",
            client_boundary="Android 录音并上传音频文件，后端调用转写接口。",
        )

    if _contains_any(normalized, ["朗读", "播报", "配音", "text to speech", "tts"]):
        return RouteDecision(
            mode="text_to_speech",
            recommended_api="audio_speech",
            reason="任务核心是把文本生成语音，适合后端生成音频后返回给客户端播放。",
            client_boundary="Android 只播放业务后端返回的音频 URL 或字节流。",
        )

    if _contains_any(normalized, ["知识库", "检索", "引用", "文档", "rag"]):
        return RouteDecision(
            mode="multimodal_rag",
            recommended_api="responses",
            reason="需要把图片/文本理解结果接入检索、引用和业务知识库。",
            client_boundary="Android 只提交问题和素材，检索、权限、引用由后端完成。",
        )

    return RouteDecision(
        mode="voice_chat",
        recommended_api="responses",
        reason="可以先把语音转写成文本，再按普通聊天/RAG 流程处理。",
        client_boundary="Android 不直连模型供应商，统一经过业务后端网关。",
    )


def build_multimodal_responses_payload(
    *,
    text: str,
    image_url: str,
    model: str = "demo-multimodal-model",
) -> dict[str, object]:
    _require_text(text, "text")
    _require_text(image_url, "image_url")

    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    }


def build_speech_to_text_request(
    file_name: str,
    *,
    model: str = "demo-transcribe-model",
    language: str = "zh",
) -> dict[str, object]:
    _require_text(file_name, "file_name")

    return {
        "model": model,
        "file": file_name,
        "language": language,
        "response_format": "json",
    }


def build_text_to_speech_request(
    text: str,
    *,
    model: str = "demo-tts-model",
    voice: str = "alloy",
    output_format: str = "mp3",
) -> dict[str, object]:
    _require_text(text, "text")

    return {
        "model": model,
        "voice": voice,
        "input": text,
        "format": output_format,
    }


def build_realtime_session_config(
    *,
    model: str = "demo-realtime-model",
    voice: str = "marin",
    instructions: str = "你是移动端语音助手，回答要简短、自然、可被朗读。",
) -> dict[str, object]:
    return {
        "type": "realtime.session",
        "model": model,
        "voice": voice,
        "modalities": ["audio", "text"],
        "instructions": instructions,
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "turn_detection": {
            "type": "server_vad",
            "create_response": True,
            "interrupt_response": True,
        },
    }


def build_android_permission_plan(features: Sequence[str]) -> dict[str, object]:
    permission_by_feature = {
        "voice_recording": "RECORD_AUDIO",
        "realtime_voice": "RECORD_AUDIO",
        "speech_to_text": "RECORD_AUDIO",
        "image_capture": "CAMERA",
        "image_pick": "READ_MEDIA_IMAGES",
    }
    required_permissions: list[str] = []

    for feature in features:
        permission = permission_by_feature.get(feature)
        if permission and permission not in required_permissions:
            required_permissions.append(permission)

    return {
        "required_permissions": required_permissions,
        "recommended_upload_boundary": (
            "server_gateway: Android 上传音频/图片到自己的业务后端，"
            "由后端处理鉴权、审计、压缩、脱敏和模型调用。"
        ),
        "runtime_notes": [
            "在用户触发录音、拍照或选图动作时再申请权限。",
            "取消、页面销毁、进入后台时要停止采集并释放麦克风/相机。",
            "默认不要在本地长期保存原始音频和图片。",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线语音与多模态流水线 Demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route_parser = subparsers.add_parser("route", help="判断任务应该走哪类模型能力")
    route_parser.add_argument("--text", required=True)
    route_parser.add_argument("--has-image", action="store_true")
    route_parser.add_argument("--low-latency", action="store_true")

    payload_parser = subparsers.add_parser("payload", help="生成文本+图片 Responses payload")
    payload_parser.add_argument("--text", required=True)
    payload_parser.add_argument("--image-url", required=True)
    payload_parser.add_argument("--model", default="demo-multimodal-model")

    realtime_parser = subparsers.add_parser("realtime", help="生成 Realtime 会话配置")
    realtime_parser.add_argument("--model", default="demo-realtime-model")
    realtime_parser.add_argument("--voice", default="marin")

    chunks_parser = subparsers.add_parser("audio-chunks", help="模拟音频字节分片")
    chunks_parser.add_argument("--text", required=True)
    chunks_parser.add_argument("--chunk-size", type=int, default=4)

    transcript_parser = subparsers.add_parser("transcript", help="合并模拟转写事件")

    args = parser.parse_args(argv)

    if args.command == "route":
        decision = route_multimodal_task(
            args.text,
            has_image=args.has_image,
            needs_low_latency=args.low_latency,
        )
        _print_json(asdict(decision))
        return 0

    if args.command == "payload":
        _print_json(
            build_multimodal_responses_payload(
                text=args.text,
                image_url=args.image_url,
                model=args.model,
            )
        )
        return 0

    if args.command == "realtime":
        _print_json(build_realtime_session_config(model=args.model, voice=args.voice))
        return 0

    if args.command == "audio-chunks":
        chunks = chunk_audio_bytes(args.text.encode("utf-8"), args.chunk_size)
        _print_json(
            {
                "chunk_size": args.chunk_size,
                "chunks": [chunk.decode("utf-8", errors="replace") for chunk in chunks],
            }
        )
        return 0

    if args.command == "transcript":
        events = [
            {"type": "partial", "text": "你好"},
            {"type": "final", "text": "你好，"},
            {"type": "partial", "text": "世界"},
            {"type": "final", "text": "世界"},
        ]
        _print_json({"transcript": merge_transcript_events(events), "events": events})
        return 0

    return 1


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
