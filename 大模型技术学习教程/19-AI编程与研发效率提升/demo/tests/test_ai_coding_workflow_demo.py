import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from ai_coding_workflow_demo import (  # noqa: E402
    build_code_review_checklist,
    classify_coding_task,
    plan_ai_pairing_workflow,
    summarize_diff_risk,
)


class AiCodingWorkflowDemoTest(unittest.TestCase):
    def test_classify_bugfix_requires_reproduction_first(self):
        task = classify_coding_task("修复登录闪退 bug")

        self.assertEqual("bugfix", task["type"])
        self.assertIn("reproduce", task["first_step"])

    def test_review_checklist_includes_tests_security_and_rollback(self):
        checklist = build_code_review_checklist(["api", "auth"])

        self.assertIn("tests", checklist)
        self.assertIn("security", checklist)
        self.assertIn("rollback", checklist)

    def test_diff_risk_counts_files_and_sensitive_keywords(self):
        risk = summarize_diff_risk(
            [
                {"path": "app/AuthService.kt", "added": 20, "removed": 5},
                {"path": "docs/readme.md", "added": 3, "removed": 0},
            ]
        )

        self.assertEqual(2, risk["files_changed"])
        self.assertIn("auth", risk["risk_signals"])

    def test_ai_pairing_workflow_has_verify_step(self):
        workflow = plan_ai_pairing_workflow("实现 RAG 引用展示")

        self.assertEqual("understand", workflow[0]["phase"])
        self.assertEqual("verify", workflow[-1]["phase"])


if __name__ == "__main__":
    unittest.main()
