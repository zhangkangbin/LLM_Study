import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from ai_protocols_demo import (  # noqa: E402
    build_mcp_tool_descriptor,
    build_openapi_function_schema,
    choose_integration_surface,
    validate_protocol_manifest,
)


class AiProtocolsDemoTest(unittest.TestCase):
    def test_mcp_descriptor_contains_name_description_and_schema(self):
        descriptor = build_mcp_tool_descriptor("search_docs", "检索文档", {"query": "string"})

        self.assertEqual("search_docs", descriptor["name"])
        self.assertIn("inputSchema", descriptor)

    def test_openapi_function_schema_marks_required_fields(self):
        schema = build_openapi_function_schema("create_ticket", ["title", "priority"])

        self.assertEqual(["title", "priority"], schema["parameters"]["required"])

    def test_choose_mcp_for_many_ai_clients(self):
        decision = choose_integration_surface(
            needs_ai_client_interop=True,
            needs_public_http_api=False,
            needs_embedded_ui=False,
        )

        self.assertEqual("mcp", decision["surface"])

    def test_manifest_validation_requires_version_and_tools(self):
        result = validate_protocol_manifest({"name": "demo"})

        self.assertFalse(result["valid"])
        self.assertIn("version", result["missing"])
        self.assertIn("tools", result["missing"])


if __name__ == "__main__":
    unittest.main()
