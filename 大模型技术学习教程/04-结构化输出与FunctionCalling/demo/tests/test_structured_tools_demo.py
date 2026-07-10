import json
import pathlib
import sys
import unittest


DEMO_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import structured_tools_demo as demo


class StructuredOutputPayloadTest(unittest.TestCase):
    def test_android_crash_schema_requires_stable_fields(self):
        schema = demo.build_android_crash_analysis_schema()

        self.assertEqual(schema["type"], "object")
        self.assertIn("issue_type", schema["required"])
        self.assertIn("severity", schema["required"])
        self.assertIn("evidence", schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["severity"]["enum"],
            ["low", "medium", "high", "unknown"],
        )

    def test_builds_responses_payload_with_text_format_json_schema(self):
        payload = demo.build_structured_output_payload(
            model="demo-model",
            crash_log="java.lang.NullPointerException",
            app_version="1.2.0",
        )

        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(payload["text"]["format"]["name"], "android_crash_analysis")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(
            payload["text"]["format"]["schema"],
            demo.build_android_crash_analysis_schema(),
        )

    def test_validates_structured_analysis(self):
        result = {
            "issue_type": "NullPointerException",
            "severity": "high",
            "summary": "MainActivity.onCreate 出现空指针。",
            "evidence": ["java.lang.NullPointerException"],
            "likely_causes": ["对象未初始化"],
            "fix_suggestions": ["增加空值检查"],
            "needs_more_info": [],
        }

        errors = demo.validate_android_crash_analysis(result)

        self.assertEqual(errors, [])


class FunctionCallingTest(unittest.TestCase):
    def test_builds_strict_function_tool_definition(self):
        tool = demo.build_known_issue_search_tool()

        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["name"], "search_known_android_issues")
        self.assertTrue(tool["strict"])
        self.assertFalse(tool["parameters"]["additionalProperties"])
        self.assertIn("keyword", tool["parameters"]["required"])

    def test_extracts_function_calls_from_responses_output(self):
        response = {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "search_known_android_issues",
                    "arguments": json.dumps({"keyword": "NullPointerException"}),
                }
            ]
        }

        calls = demo.extract_function_calls(response)

        self.assertEqual(
            calls,
            [
                {
                    "call_id": "call_123",
                    "name": "search_known_android_issues",
                    "arguments": {"keyword": "NullPointerException"},
                }
            ],
        )

    def test_executes_tool_call_and_builds_function_call_output_item(self):
        call = {
            "call_id": "call_123",
            "name": "search_known_android_issues",
            "arguments": {"keyword": "NullPointerException"},
        }

        item = demo.execute_tool_call(call)
        output = json.loads(item["output"])

        self.assertEqual(item["type"], "function_call_output")
        self.assertEqual(item["call_id"], "call_123")
        self.assertGreaterEqual(len(output["matches"]), 1)
        self.assertEqual(output["matches"][0]["category"], "crash")


if __name__ == "__main__":
    unittest.main()
