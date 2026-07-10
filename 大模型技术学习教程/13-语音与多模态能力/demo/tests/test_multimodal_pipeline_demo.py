import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from multimodal_pipeline_demo import (  # noqa: E402
    build_android_permission_plan,
    build_multimodal_responses_payload,
    build_realtime_session_config,
    build_speech_to_text_request,
    build_text_to_speech_request,
    chunk_audio_bytes,
    merge_transcript_events,
    route_multimodal_task,
)


class MultimodalPipelineDemoTest(unittest.TestCase):
    def test_audio_bytes_are_split_into_stable_chunks(self):
        chunks = chunk_audio_bytes(b"abcdef", chunk_size=2)

        self.assertEqual([b"ab", b"cd", b"ef"], chunks)

    def test_transcript_events_prefer_final_text(self):
        transcript = merge_transcript_events(
            [
                {"type": "partial", "text": "你好"},
                {"type": "final", "text": "你好，"},
                {"type": "partial", "text": "世界"},
                {"type": "final", "text": "世界"},
            ]
        )

        self.assertEqual("你好，世界", transcript)

    def test_router_detects_image_understanding(self):
        decision = route_multimodal_task("帮我看一下这张截图有什么问题", has_image=True)

        self.assertEqual("image_understanding", decision.mode)
        self.assertEqual("responses", decision.recommended_api)

    def test_router_detects_realtime_voice(self):
        decision = route_multimodal_task("我要做实时语音问答", needs_low_latency=True)

        self.assertEqual("realtime_voice", decision.mode)
        self.assertEqual("realtime", decision.recommended_api)

    def test_responses_payload_contains_text_and_image_parts(self):
        payload = build_multimodal_responses_payload(
            text="这张图有什么问题？",
            image_url="app://image/screenshot.png",
            model="demo-multimodal-model",
        )

        content = payload["input"][0]["content"]
        self.assertEqual("demo-multimodal-model", payload["model"])
        self.assertEqual("input_text", content[0]["type"])
        self.assertEqual("input_image", content[1]["type"])
        self.assertEqual("app://image/screenshot.png", content[1]["image_url"])

    def test_realtime_session_config_enables_audio_and_text(self):
        config = build_realtime_session_config(model="demo-realtime-model", voice="marin")

        self.assertEqual("demo-realtime-model", config["model"])
        self.assertEqual("marin", config["voice"])
        self.assertIn("audio", config["modalities"])
        self.assertIn("text", config["modalities"])
        self.assertEqual("server_vad", config["turn_detection"]["type"])

    def test_android_permission_plan_matches_features(self):
        plan = build_android_permission_plan(["voice_recording", "image_capture"])

        self.assertIn("RECORD_AUDIO", plan["required_permissions"])
        self.assertIn("CAMERA", plan["required_permissions"])
        self.assertIn("server_gateway", plan["recommended_upload_boundary"])

    def test_speech_to_text_request_carries_file_and_model(self):
        request = build_speech_to_text_request("meeting.wav", model="demo-transcribe-model")

        self.assertEqual("meeting.wav", request["file"])
        self.assertEqual("demo-transcribe-model", request["model"])
        self.assertEqual("zh", request["language"])

    def test_text_to_speech_request_carries_voice_and_input(self):
        request = build_text_to_speech_request(
            "请用自然语气朗读这段文字",
            model="demo-tts-model",
            voice="alloy",
        )

        self.assertEqual("demo-tts-model", request["model"])
        self.assertEqual("alloy", request["voice"])
        self.assertEqual("请用自然语气朗读这段文字", request["input"])


if __name__ == "__main__":
    unittest.main()
