import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from llmops_monitor_demo import (  # noqa: E402
    aggregate_metrics,
    build_release_gate,
    check_alerts,
    record_call,
)


class LlmOpsMonitorDemoTest(unittest.TestCase):
    def test_aggregate_metrics_calculates_cost_latency_and_error_rate(self):
        calls = [
            record_call("chat", 100, 0.01, 800, True),
            record_call("chat", 200, 0.02, 1200, False),
        ]

        metrics = aggregate_metrics(calls)

        self.assertEqual(300, metrics["tokens"])
        self.assertEqual(0.03, metrics["cost_usd"])
        self.assertEqual(1000, metrics["avg_latency_ms"])
        self.assertEqual(0.5, metrics["error_rate"])

    def test_alerts_fire_for_budget_latency_and_error_rate(self):
        alerts = check_alerts(
            {"cost_usd": 12, "avg_latency_ms": 2500, "error_rate": 0.2},
            {"max_cost_usd": 10, "max_latency_ms": 2000, "max_error_rate": 0.1},
        )

        self.assertEqual({"budget", "latency", "error_rate"}, set(alerts))

    def test_release_gate_blocks_when_quality_or_ops_is_bad(self):
        gate = build_release_gate(
            eval_summary={"pass_rate": 0.85},
            ops_metrics={"error_rate": 0.03, "avg_latency_ms": 1500},
            policy={"min_pass_rate": 0.9, "max_error_rate": 0.05, "max_latency_ms": 2000},
        )

        self.assertFalse(gate["can_release"])
        self.assertIn("eval_pass_rate", gate["failed_checks"])


if __name__ == "__main__":
    unittest.main()
