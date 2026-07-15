import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import intent_classifier_demo as demo
from intent_classifier_demo import (
    classification_metrics,
    evaluate_classifier,
    extract_features,
    load_examples,
    main,
    normalize_text,
    predict_intent,
    train_classifier,
    validate_examples,
)


SAMPLE_DATA = DEMO_DIR / "sample_intents.jsonl"


class IntentDataValidationTest(unittest.TestCase):
    def setUp(self):
        self.valid = [
            {"text": "查询订单", "intent": "query_order", "split": "train"},
            {"text": "订单在哪里", "intent": "query_order", "split": "validation"},
            {"text": "查看物流", "intent": "query_order", "split": "test"},
            {"text": "今天天气", "intent": "unknown", "split": "validation"},
            {"text": "播放音乐", "intent": "unknown", "split": "test"},
        ]

    def test_valid_three_way_split_has_no_issues(self):
        self.assertEqual(validate_examples(self.valid), [])

    def test_missing_and_invalid_fields_are_reported(self):
        rows = self.valid + [
            {},
            {"text": 123, "intent": "query_order", "split": "train"},
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("invalid_field", codes)

    def test_blank_normalized_text_is_reported(self):
        rows = self.valid + [
            {"text": " ！！ ", "intent": "query_order", "split": "train"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("empty_normalized_text", codes)

    def test_invalid_lower_snake_case_intent_is_reported(self):
        for intent in ("Bad Intent", "_query", "query_", "query__order"):
            with self.subTest(intent=intent):
                rows = self.valid + [
                    {"text": f"测试{intent}", "intent": intent, "split": "train"}
                ]
                codes = {issue["code"] for issue in validate_examples(rows)}
                self.assertIn("invalid_intent", codes)

    def test_invalid_split_is_reported(self):
        rows = self.valid + [
            {"text": "测试文本", "intent": "query_order", "split": "other"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("invalid_split", codes)

    def test_same_split_normalized_duplicate_is_reported(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "query_order", "split": "train"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("duplicate_text", codes)

    def test_cross_split_normalized_duplicate_is_rejected(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "query_order", "split": "test"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("cross_split_leakage", codes)

    def test_cross_split_group_still_reports_same_split_duplicates(self):
        rows = self.valid + [
            {"text": "查询，订单", "intent": "query_order", "split": "train"},
            {"text": "查询订单！", "intent": "query_order", "split": "test"},
        ]

        issues = validate_examples(rows)

        self.assertIn(
            ("duplicate_text", (0, 5)),
            {(issue["code"], tuple(issue["indexes"])) for issue in issues},
        )

    def test_conflicting_labels_are_reported(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "cancel_order", "split": "train"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("conflicting_label", codes)

    def test_empty_train_validation_or_test_split_is_reported(self):
        for split in demo.VALID_SPLITS:
            with self.subTest(split=split):
                rows = [row for row in self.valid if row["split"] != split]
                issues = validate_examples(rows)
                empty_split_issues = [
                    issue for issue in issues if issue["code"] == "empty_split"
                ]
                self.assertTrue(empty_split_issues)
                self.assertTrue(
                    any(split in issue["message"] for issue in empty_split_issues)
                )

    def test_validation_and_test_labels_must_exist_in_train(self):
        rows = self.valid + [
            {"text": "我要投诉", "intent": "complaint", "split": "validation"},
            {"text": "帮我开发票", "intent": "invoice", "split": "test"},
        ]

        issues = validate_examples(rows)
        missing_train_issues = [
            issue for issue in issues if issue["code"] == "missing_train_intent"
        ]

        self.assertEqual(len(missing_train_issues), 2)
        self.assertEqual(
            {tuple(issue["indexes"]) for issue in missing_train_issues}, {(5,), (6,)}
        )

    def test_unknown_is_rejected_in_training_split(self):
        rows = self.valid + [
            {"text": "无法识别的训练样本", "intent": "unknown", "split": "train"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("unknown_in_train", codes)

    def test_unknown_in_train_is_reported_even_when_text_is_invalid(self):
        cases = (("!!!", "empty_normalized_text"), (123, "invalid_field"))
        for text, text_issue in cases:
            with self.subTest(text=text):
                rows = self.valid + [
                    {"text": text, "intent": "unknown", "split": "train"}
                ]

                codes = {issue["code"] for issue in validate_examples(rows)}

                self.assertIn(text_issue, codes)
                self.assertIn("unknown_in_train", codes)

    def test_validation_constants_define_the_contract(self):
        self.assertEqual(
            demo.VALID_SPLITS, frozenset({"train", "validation", "test"})
        )
        for intent in ("a", "query_order", "intent2", "a_2"):
            with self.subTest(intent=intent):
                self.assertIsNotNone(demo.INTENT_PATTERN.fullmatch(intent))
        for intent in ("2intent", "_intent", "intent_", "intent__name", "Upper"):
            with self.subTest(intent=intent):
                self.assertIsNone(demo.INTENT_PATTERN.fullmatch(intent))

    def test_normalize_text_keeps_only_lowercase_unicode_alphanumerics(self):
        self.assertEqual(normalize_text(" Hello，订单-42！ "), "hello订单42")
        self.assertEqual(normalize_text("İ！"), "i")
        self.assertEqual(normalize_text("ΟΣ"), "ος")

    def test_load_examples_reads_nonblank_jsonl_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "examples.jsonl"
            path.write_text(
                '\n{"text": "A", "intent": "a", "split": "train"}\n\n'
                '{"text": "B", "intent": "a", "split": "test"}\n',
                encoding="utf-8",
            )

            rows = load_examples(path)

        self.assertEqual([row["text"] for row in rows], ["A", "B"])

    def test_load_examples_reports_physical_line_for_non_object_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "examples.jsonl"
            path.write_text(
                '\n{"text": "A"}\n["not", "an", "object"]\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, r"line 3: expected object"):
                load_examples(path)

    def test_issues_have_deterministic_shape_and_order(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "query_order", "split": "test"},
            {"text": " ！ ", "intent": "Bad Intent", "split": "other"},
        ]

        issues = validate_examples(rows)

        self.assertTrue(issues)
        self.assertTrue(
            all(set(issue) == {"code", "message", "indexes"} for issue in issues)
        )
        self.assertTrue(
            all(issue["indexes"] == sorted(issue["indexes"]) for issue in issues)
        )
        self.assertEqual(
            issues,
            sorted(issues, key=lambda issue: (issue["code"], issue["indexes"])),
        )


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

    def test_out_of_vocabulary_features_are_rejected(self):
        examples = [
            {"text": "甲", "intent": "short", "split": "train"},
            {"text": "乙丙丁戊己庚辛壬癸", "intent": "long", "split": "train"},
        ]
        model = train_classifier(examples)

        result = predict_intent(model, "zzzzzzzzzz")

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["reason"], "no_features")


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


class IntentClassifierCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_path = Path(cls.temporary_directory.name) / "sample_intents.jsonl"
        moved_intents = set()
        rows = []
        for source_row in load_examples(SAMPLE_DATA):
            row = dict(source_row)
            if row["split"] == "train" and row["intent"] not in moved_intents:
                row["split"] = "validation"
                moved_intents.add(row["intent"])
            rows.append(row)
        cls.data_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def test_validate_command_returns_json_success(self):
        with redirect_stdout(io.StringIO()) as output:
            exit_code = main(["--data", str(self.data_path), "validate"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["count"], 39)

    def test_evaluate_command_returns_metrics(self):
        with redirect_stdout(io.StringIO()) as output:
            exit_code = main(["--data", str(self.data_path), "evaluate"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["count"], 15)
        self.assertIn("confusion_matrix", payload)
        self.assertIn("macro", payload)

    def test_predict_command_returns_candidates(self):
        with redirect_stdout(io.StringIO()) as output:
            exit_code = main(
                [
                    "--data",
                    str(self.data_path),
                    "predict",
                    "--text",
                    "帮我取消订单",
                    "--confidence-threshold",
                    "0",
                    "--margin-threshold",
                    "0",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["intent"], "cancel_order")
        self.assertIn("candidates", payload)

    def test_predict_command_rejects_blank_text(self):
        for text in ("", "   "):
            with (
                self.subTest(text=text),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                main(["--data", str(SAMPLE_DATA), "predict", "--text", text])


if __name__ == "__main__":
    unittest.main()
