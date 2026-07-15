import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from intent_classifier_demo import (
    classification_metrics,
    evaluate_classifier,
    extract_features,
    predict_intent,
    train_classifier,
    validate_examples,
)


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


class IntentClassifierTrainingTest(unittest.TestCase):
    def setUp(self):
        self.training_examples = [
            {"text": "取消订单", "intent": "cancel_order", "split": "train"},
            {"text": "不要这个订单", "intent": "cancel_order", "split": "train"},
            {"text": "撤销购买", "intent": "cancel_order", "split": "train"},
            {"text": "查询物流", "intent": "query_order", "split": "train"},
            {"text": "订单到哪里了", "intent": "query_order", "split": "train"},
            {"text": "查看包裹进度", "intent": "query_order", "split": "train"},
        ]

    def test_extract_features_uses_normalized_unigrams_and_bigrams(self):
        self.assertEqual(extract_features("取消！"), ["取", "消", "取消"])

    def test_training_records_classes_and_vocabulary(self):
        model = train_classifier(self.training_examples)

        self.assertEqual(model.class_counts["cancel_order"], 3)
        self.assertEqual(model.class_counts["query_order"], 3)
        self.assertIn("取消", model.vocabulary)

    def test_trained_classifier_predicts_representative_intent(self):
        model = train_classifier(self.training_examples)

        result = predict_intent(
            model,
            "请帮我取消这个订单",
            confidence_threshold=0.0,
            margin_threshold=0.0,
        )

        self.assertEqual(result["intent"], "cancel_order")
        self.assertEqual(result["candidates"][0]["intent"], "cancel_order")
        self.assertAlmostEqual(
            sum(candidate["probability"] for candidate in result["candidates"]),
            1.0,
        )


class IntentClassifierEvaluationTest(unittest.TestCase):
    def setUp(self):
        self.training_examples = [
            {"text": "取消订单", "intent": "cancel_order", "split": "train"},
            {"text": "撤销购买", "intent": "cancel_order", "split": "train"},
            {"text": "查询物流", "intent": "query_order", "split": "train"},
            {"text": "包裹进度", "intent": "query_order", "split": "train"},
        ]

    def test_empty_features_are_rejected_as_unknown(self):
        model = train_classifier(self.training_examples)

        result = predict_intent(model, "!!!")

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["reason"], "no_features")

    def test_low_confidence_is_rejected_and_preserves_candidates(self):
        model = train_classifier(self.training_examples)

        result = predict_intent(
            model,
            "订单",
            confidence_threshold=1.0,
            margin_threshold=0.0,
        )

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["reason"], "low_confidence")
        self.assertGreater(len(result["candidates"]), 0)

    def test_low_margin_is_rejected(self):
        model = train_classifier(self.training_examples)

        result = predict_intent(
            model,
            "订单",
            confidence_threshold=0.0,
            margin_threshold=1.0,
        )

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["reason"], "low_margin")

    def test_confusion_matrix_rows_are_actual_labels(self):
        metrics = classification_metrics(
            actual=["cancel_order", "query_order"],
            predicted=["query_order", "query_order"],
        )

        self.assertEqual(
            metrics["confusion_matrix"]["cancel_order"]["query_order"], 1
        )
        self.assertEqual(
            metrics["confusion_matrix"]["query_order"]["query_order"], 1
        )

    def test_classification_metrics_handle_zero_denominators(self):
        metrics = classification_metrics(
            actual=["cancel_order", "query_order", "query_order"],
            predicted=["query_order", "query_order", "unknown"],
        )

        self.assertEqual(metrics["per_intent"]["cancel_order"]["precision"], 0.0)
        self.assertEqual(metrics["per_intent"]["unknown"]["recall"], 0.0)
        self.assertAlmostEqual(metrics["per_intent"]["query_order"]["f1"], 0.5)
        self.assertAlmostEqual(metrics["macro"]["f1"], 1 / 6)

    def test_evaluation_contains_errors_and_metrics(self):
        model = train_classifier(self.training_examples)
        test_examples = [
            {"text": "请取消", "intent": "cancel_order", "split": "test"},
            {"text": "查一下物流", "intent": "query_order", "split": "test"},
        ]

        result = evaluate_classifier(
            model,
            test_examples,
            confidence_threshold=1.0,
            margin_threshold=0.0,
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("macro", result)


if __name__ == "__main__":
    unittest.main()
