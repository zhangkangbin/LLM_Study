import pathlib
import sys
import unittest


DEMO_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import openai_compatible_cli as demo


class ResponsesPayloadTest(unittest.TestCase):
    def test_builds_basic_responses_payload(self):
        payload = demo.build_responses_payload(
            prompt="用一句话解释 Android ANR",
            model="demo-model",
            stream=False,
            max_output_tokens=128,
        )

        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["input"], "用一句话解释 Android ANR")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_output_tokens"], 128)

    def test_adds_instructions_when_system_prompt_is_present(self):
        payload = demo.build_responses_payload(
            prompt="分析日志",
            model="demo-model",
            instructions="你是 Android 稳定性专家。",
            stream=True,
            max_output_tokens=None,
        )

        self.assertEqual(payload["instructions"], "你是 Android 稳定性专家。")
        self.assertTrue(payload["stream"])
        self.assertNotIn("max_output_tokens", payload)


class ResponsesParsingTest(unittest.TestCase):
    def test_extracts_output_text_from_responses_json(self):
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "ANR 表示主线程长时间无响应。"}
                    ],
                }
            ]
        }

        self.assertEqual(
            demo.extract_output_text(response),
            "ANR 表示主线程长时间无响应。",
        )

    def test_extracts_delta_text_from_typed_sse_events(self):
        raw = (
            "event: response.output_text.delta\n"
            'data: {"type":"response.output_text.delta","delta":"你可以"}\n'
            "\n"
            "event: response.output_text.delta\n"
            'data: {"type":"response.output_text.delta","delta":"先看主线程堆栈"}\n'
            "\n"
            "event: response.completed\n"
            'data: {"type":"response.completed"}\n'
            "\n"
        )

        events = list(demo.parse_sse_events(raw.splitlines()))
        text = "".join(demo.extract_stream_delta(event) for event in events)

        self.assertEqual(text, "你可以先看主线程堆栈")


if __name__ == "__main__":
    unittest.main()
