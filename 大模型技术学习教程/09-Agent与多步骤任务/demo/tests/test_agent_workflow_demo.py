import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_workflow_demo import (  # noqa: E402
    LoopPlanner,
    build_default_tools,
    build_responses_agent_payload,
    build_tool_schema,
    execute_tool_call,
    run_agent,
)


class AgentWorkflowDemoTests(unittest.TestCase):
    def test_build_tool_schema_matches_responses_function_tool_shape(self):
        schema = build_tool_schema(
            name="search_knowledge_base",
            description="Search internal knowledge base.",
            properties={"query": {"type": "string", "description": "Search query"}},
            required=["query"],
        )

        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["name"], "search_knowledge_base")
        self.assertTrue(schema["strict"])
        self.assertEqual(schema["parameters"]["type"], "object")
        self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(schema["parameters"]["required"], ["query"])

    def test_execute_tool_call_returns_error_for_unknown_tool(self):
        result = execute_tool_call(
            {"name": "missing_tool", "arguments": {}},
            build_default_tools(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_tool")

    def test_run_agent_searches_then_answers_with_trace(self):
        result = run_agent("空指针崩溃怎么排查", max_steps=4)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["trace"][0]["tool_name"], "search_knowledge_base")
        self.assertIn("NullPointerException", result["final_answer"])
        self.assertIn("[android-crash-guide]", result["final_answer"])

    def test_run_agent_creates_followup_ticket_when_goal_requests_tracking(self):
        result = run_agent("帮我创建工单跟进接口 500 trace_id 问题", max_steps=5)

        tool_names = [step["tool_name"] for step in result["trace"] if step["type"] == "tool_call"]
        self.assertIn("search_knowledge_base", tool_names)
        self.assertIn("create_followup_ticket", tool_names)
        self.assertEqual(result["status"], "completed")
        self.assertIn("TICKET-", result["final_answer"])

    def test_run_agent_stops_at_max_steps_for_looping_planner(self):
        result = run_agent(
            "循环测试",
            planner=LoopPlanner(),
            max_steps=2,
        )

        self.assertEqual(result["status"], "max_steps_exceeded")
        self.assertEqual(len(result["trace"]), 2)
        self.assertIn("最大步数", result["final_answer"])

    def test_build_responses_agent_payload_includes_tools_and_input(self):
        payload = build_responses_agent_payload(
            goal="排查 Android 崩溃",
            tools=[build_default_tools()["search_knowledge_base"].schema],
            model="gpt-5.5",
        )

        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["input"], "排查 Android 崩溃")
        self.assertEqual(payload["tools"][0]["name"], "search_knowledge_base")
        self.assertEqual(payload["tool_choice"], "auto")


if __name__ == "__main__":
    unittest.main()
