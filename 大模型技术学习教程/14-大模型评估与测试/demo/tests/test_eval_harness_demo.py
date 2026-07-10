import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from eval_harness_demo import (  # noqa: E402
    build_eval_case,
    detect_regression,
    keyword_coverage,
    run_eval_suite,
    summarize_results,
)


class EvalHarnessDemoTest(unittest.TestCase):
    def test_keyword_coverage_counts_required_keywords(self):
        score = keyword_coverage("回答包含订单号和处理状态", ["订单号", "状态", "金额"])

        self.assertAlmostEqual(2 / 3, score)

    def test_run_eval_suite_scores_each_case(self):
        cases = [
            build_eval_case("case-1", "订单状态", "订单号 123 已完成", ["订单号", "完成"]),
            build_eval_case("case-2", "退款", "退款处理中", ["退款", "处理中"]),
        ]

        results = run_eval_suite(cases)

        self.assertEqual(2, len(results))
        self.assertTrue(all(result["passed"] for result in results))

    def test_summary_reports_pass_rate_and_average_score(self):
        summary = summarize_results(
            [
                {"score": 1.0, "passed": True},
                {"score": 0.5, "passed": False},
            ]
        )

        self.assertEqual(0.5, summary["pass_rate"])
        self.assertEqual(0.75, summary["average_score"])

    def test_regression_is_detected_against_baseline(self):
        regression = detect_regression(
            baseline={"pass_rate": 0.9, "average_score": 0.88},
            current={"pass_rate": 0.8, "average_score": 0.7},
            tolerance=0.05,
        )

        self.assertTrue(regression["has_regression"])
        self.assertIn("average_score", regression["failed_metrics"])


if __name__ == "__main__":
    unittest.main()
