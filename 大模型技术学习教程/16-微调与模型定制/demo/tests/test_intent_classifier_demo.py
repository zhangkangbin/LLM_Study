import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from intent_classifier_demo import validate_examples


class IntentDataValidationTest(unittest.TestCase):
    def setUp(self):
        self.examples = [
            {"text": "取消订单", "intent": "cancel_order", "split": "train"},
            {"text": "不想要这个订单了", "intent": "cancel_order", "split": "test"},
            {"text": "查询物流", "intent": "query_order", "split": "train"},
            {"text": "我的包裹在哪里", "intent": "query_order", "split": "test"},
            {"text": "今天天气怎么样", "intent": "unknown", "split": "test"},
        ]

    def test_valid_examples_have_no_issues(self):
        self.assertEqual(validate_examples(self.examples), [])

    def test_missing_and_invalid_fields_are_reported(self):
        examples = self.examples + [
            {"text": "", "intent": "cancel_order", "split": "train"},
            {"text": "测试文本", "intent": "Bad Intent", "split": "other"},
        ]

        codes = {issue["code"] for issue in validate_examples(examples)}

        self.assertIn("invalid_field", codes)
        self.assertIn("invalid_intent", codes)
        self.assertIn("invalid_split", codes)

    def test_duplicate_text_is_reported(self):
        examples = self.examples + [
            {"text": " 取消订单！", "intent": "cancel_order", "split": "test"}
        ]

        codes = {issue["code"] for issue in validate_examples(examples)}

        self.assertIn("duplicate_text", codes)

    def test_conflicting_labels_are_reported(self):
        examples = self.examples + [
            {"text": "取消订单", "intent": "query_order", "split": "test"}
        ]

        codes = {issue["code"] for issue in validate_examples(examples)}

        self.assertIn("conflicting_label", codes)

    def test_missing_train_or_test_coverage_is_reported(self):
        examples = self.examples + [
            {"text": "我要投诉", "intent": "complaint", "split": "train"},
            {"text": "帮我开发票", "intent": "invoice", "split": "test"},
        ]

        codes = {issue["code"] for issue in validate_examples(examples)}

        self.assertIn("missing_test_intent", codes)
        self.assertIn("missing_train_intent", codes)


if __name__ == "__main__":
    unittest.main()
