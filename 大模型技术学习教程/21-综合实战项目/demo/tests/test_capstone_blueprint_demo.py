import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from capstone_blueprint_demo import (  # noqa: E402
    build_acceptance_checklist,
    build_capstone_blueprint,
    build_milestone_plan,
    map_feature_to_stage,
)


class CapstoneBlueprintDemoTest(unittest.TestCase):
    def test_blueprint_contains_android_backend_rag_and_eval_components(self):
        blueprint = build_capstone_blueprint("Android 知识库助手")

        self.assertIn("android_app", blueprint["components"])
        self.assertIn("backend_gateway", blueprint["components"])
        self.assertIn("rag_pipeline", blueprint["components"])
        self.assertIn("eval_harness", blueprint["components"])

    def test_milestone_plan_has_four_incremental_milestones(self):
        milestones = build_milestone_plan()

        self.assertEqual(4, len(milestones))
        self.assertEqual("MVP", milestones[0]["name"])
        self.assertEqual("上线准备", milestones[-1]["name"])

    def test_acceptance_checklist_covers_quality_ops_and_security(self):
        checklist = build_acceptance_checklist()

        self.assertIn("质量评估通过", checklist)
        self.assertIn("监控告警可用", checklist)
        self.assertIn("安全红队用例通过", checklist)

    def test_feature_mapping_points_to_relevant_stage(self):
        mapping = map_feature_to_stage("模型评估与回归测试")

        self.assertEqual(14, mapping["stage"])


if __name__ == "__main__":
    unittest.main()
