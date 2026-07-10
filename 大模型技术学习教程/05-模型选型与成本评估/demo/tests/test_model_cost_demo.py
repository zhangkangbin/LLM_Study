import pathlib
import sys
import unittest


DEMO_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import model_cost_demo as demo


class CostEstimatorTest(unittest.TestCase):
    def test_estimates_single_request_cost_with_cached_input(self):
        model = {
            "id": "demo-model",
            "input_price_per_million": 5.0,
            "cached_input_price_per_million": 0.5,
            "output_price_per_million": 30.0,
        }

        cost = demo.estimate_request_cost(
            model=model,
            input_tokens=10_000,
            output_tokens=2_000,
            cached_input_tokens=4_000,
        )

        self.assertAlmostEqual(cost["input_cost"], 0.03)
        self.assertAlmostEqual(cost["cached_input_cost"], 0.002)
        self.assertAlmostEqual(cost["output_cost"], 0.06)
        self.assertAlmostEqual(cost["total_cost"], 0.092)

    def test_estimates_period_cost(self):
        model = {
            "id": "demo-model",
            "input_price_per_million": 1.0,
            "cached_input_price_per_million": 0.1,
            "output_price_per_million": 2.0,
        }

        result = demo.estimate_period_cost(
            model=model,
            requests_per_day=100,
            days=30,
            avg_input_tokens=1_000,
            avg_output_tokens=500,
            avg_cached_input_tokens=200,
        )

        self.assertEqual(result["total_requests"], 3_000)
        self.assertAlmostEqual(result["total_cost"], 5.46)


class ModelRecommendationTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "models": [
                {
                    "id": "frontier",
                    "quality": 5,
                    "speed": 3,
                    "cost_level": 5,
                    "supports_tools": True,
                    "supports_vision": True,
                    "recommended_for": ["complex_reasoning", "coding"],
                },
                {
                    "id": "mini",
                    "quality": 4,
                    "speed": 4,
                    "cost_level": 2,
                    "supports_tools": True,
                    "supports_vision": True,
                    "recommended_for": ["balanced", "rag", "android_crash_analysis"],
                },
                {
                    "id": "nano",
                    "quality": 2,
                    "speed": 5,
                    "cost_level": 1,
                    "supports_tools": False,
                    "supports_vision": False,
                    "recommended_for": ["classification", "high_volume"],
                },
            ]
        }

    def test_recommends_quality_model_for_complex_code_review(self):
        result = demo.recommend_model(
            catalog=self.catalog,
            task="coding",
            priority="quality",
            requires_tools=True,
            requires_vision=False,
        )

        self.assertEqual(result["model"]["id"], "frontier")
        self.assertIn("quality", result["reasons"][0])

    def test_recommends_low_cost_model_for_simple_classification(self):
        result = demo.recommend_model(
            catalog=self.catalog,
            task="classification",
            priority="cost",
            requires_tools=False,
            requires_vision=False,
        )

        self.assertEqual(result["model"]["id"], "nano")

    def test_filters_out_models_without_required_tools(self):
        result = demo.recommend_model(
            catalog=self.catalog,
            task="high_volume",
            priority="latency",
            requires_tools=True,
            requires_vision=False,
        )

        self.assertNotEqual(result["model"]["id"], "nano")

    def test_finds_model_by_id(self):
        model = demo.find_model(self.catalog, "mini")

        self.assertEqual(model["id"], "mini")


if __name__ == "__main__":
    unittest.main()
