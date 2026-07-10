import pathlib
import sys
import unittest


DEMO_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import prompt_builder


class AndroidCrashPromptBuilderTest(unittest.TestCase):
    def test_builds_stable_instructions_with_output_contract(self):
        instructions = prompt_builder.build_android_crash_instructions()

        self.assertIn("Android 稳定性分析助手", instructions)
        self.assertIn("只基于输入内容分析", instructions)
        self.assertIn("问题类型", instructions)
        self.assertIn("关键证据", instructions)
        self.assertIn("修复建议", instructions)
        self.assertIn("不确定", instructions)

    def test_wraps_dynamic_user_content_with_clear_delimiters(self):
        crash_log = "java.lang.NullPointerException\nat com.example.MainActivity.onCreate"
        user_input = prompt_builder.build_android_crash_input(
            app_version="1.2.0",
            android_version="14",
            device="Pixel 8",
            recent_changes="登录页读取缓存逻辑调整",
            crash_log=crash_log,
        )

        self.assertIn("<crash_log>", user_input)
        self.assertIn("</crash_log>", user_input)
        self.assertIn(crash_log, user_input)
        self.assertIn("登录页读取缓存逻辑调整", user_input)

    def test_builds_responses_payload_from_prompt_parts(self):
        payload = prompt_builder.build_responses_payload(
            model="demo-model",
            instructions="system prompt",
            user_input="user prompt",
        )

        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["instructions"], "system prompt")
        self.assertEqual(payload["input"], "user prompt")

    def test_compares_naive_and_engineered_prompt(self):
        comparison = prompt_builder.build_prompt_comparison(
            crash_log="FATAL EXCEPTION: main",
            app_version="1.0.0",
            android_version="13",
            device="demo-device",
            recent_changes="无",
            model="demo-model",
        )

        self.assertIn("naive", comparison)
        self.assertIn("engineered", comparison)
        self.assertNotIn("instructions", comparison["naive"])
        self.assertIn("instructions", comparison["engineered"])
        self.assertLess(
            len(comparison["naive"]["input"]),
            len(comparison["engineered"]["input"]),
        )


if __name__ == "__main__":
    unittest.main()
