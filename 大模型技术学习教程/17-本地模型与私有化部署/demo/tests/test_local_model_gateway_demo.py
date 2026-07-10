import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from local_model_gateway_demo import (  # noqa: E402
    build_ollama_generate_request,
    estimate_memory_gb,
    route_inference,
    summarize_deployment_plan,
)


class LocalModelGatewayDemoTest(unittest.TestCase):
    def test_estimate_memory_uses_model_size_and_quantization(self):
        memory = estimate_memory_gb(parameter_billion=7, quantization_bits=4)

        self.assertEqual(3.5, memory)

    def test_route_inference_prefers_local_for_privacy_and_available_capacity(self):
        route = route_inference(
            requires_private_data=True,
            local_available=True,
            estimated_memory_gb=4,
            available_memory_gb=8,
        )

        self.assertEqual("local", route["target"])

    def test_route_inference_falls_back_to_cloud_when_local_capacity_is_low(self):
        route = route_inference(
            requires_private_data=False,
            local_available=True,
            estimated_memory_gb=12,
            available_memory_gb=8,
        )

        self.assertEqual("cloud", route["target"])

    def test_ollama_request_uses_model_prompt_and_stream_flag(self):
        request = build_ollama_generate_request("llama-demo", "你好", stream=False)

        self.assertEqual("llama-demo", request["model"])
        self.assertEqual("你好", request["prompt"])
        self.assertFalse(request["stream"])

    def test_deployment_plan_mentions_gateway_and_observability(self):
        plan = summarize_deployment_plan("local", "internal_knowledge_base")

        self.assertIn("gateway", plan["components"])
        self.assertIn("observability", plan["components"])


if __name__ == "__main__":
    unittest.main()
