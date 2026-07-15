import copy
import hashlib
import io
import json
import math
import sys
import tempfile
import unittest
from collections.abc import Iterator, Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

import intent_classifier_demo as demo
from intent_classifier_demo import (
    REQUIRED_ARTIFACT_KEYS,
    SCHEMA_VERSION,
    Thresholds,
    build_artifact,
    calibrate_thresholds,
    classification_metrics,
    evaluate_classifier,
    extract_features,
    load_artifact,
    load_examples,
    main,
    model_from_artifact,
    normalize_text,
    predict_intent,
    predict_with_artifact,
    save_artifact,
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

    def test_duplicate_wording_uses_only_reported_subgroup(self):
        rows = self.valid + [
            {"text": "查询，订单", "intent": "query_order", "split": "train"},
            {"text": "查询，订单", "intent": "query_order", "split": "test"},
        ]

        duplicate_issue = next(
            issue
            for issue in validate_examples(rows)
            if issue["code"] == "duplicate_text" and issue["indexes"] == [0, 5]
        )

        self.assertEqual(duplicate_issue["message"], "规范化后的同一文本重复出现")

    def test_conflicting_labels_are_reported(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "cancel_order", "split": "train"}
        ]

        codes = {issue["code"] for issue in validate_examples(rows)}

        self.assertIn("conflicting_label", codes)

    def test_duplicate_partition_is_independent_of_conflicting_labels(self):
        rows = self.valid + [
            {"text": "查询，订单", "intent": "query_order", "split": "train"},
            {"text": "查询订单！", "intent": "cancel_order", "split": "train"},
        ]

        diagnostics = {
            (issue["code"], tuple(issue["indexes"]))
            for issue in validate_examples(rows)
        }

        self.assertIn(("duplicate_text", (0, 5)), diagnostics)
        self.assertIn(("conflicting_label", (0, 5, 6)), diagnostics)

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

    def test_load_examples_reports_physical_line_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "examples.jsonl"
            path.write_text('\n{"text": "A"}\n{"text":\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"line 3: invalid JSON:"):
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

    def test_training_statistics_use_only_train_split(self):
        examples = [
            {"text": "取消", "intent": "cancel_order", "split": "train"},
            {"text": "验证专用词", "intent": "validation_only", "split": "validation"},
            {"text": "测试专用词", "intent": "test_only", "split": "test"},
        ]

        model = train_classifier(examples)

        self.assertEqual(model.class_counts, {"cancel_order": 1})
        self.assertEqual(
            model.feature_counts["cancel_order"],
            {"取": 1, "消": 1, "取消": 1},
        )
        self.assertEqual(set(model.vocabulary), {"取", "消", "取消"})

    def test_model_data_is_deterministically_ordered(self):
        model = train_classifier(
            [
                {"text": "乙甲", "intent": "zeta", "split": "train"},
                {"text": "丙甲", "intent": "alpha", "split": "train"},
            ]
        )

        self.assertEqual(list(model.class_counts), ["alpha", "zeta"])
        self.assertEqual(list(model.feature_counts), ["alpha", "zeta"])
        self.assertEqual(list(model.total_features), ["alpha", "zeta"])
        for counts in model.feature_counts.values():
            self.assertEqual(list(counts), sorted(counts))
        self.assertEqual(model.vocabulary, tuple(sorted(model.vocabulary)))

    def test_model_data_is_deeply_immutable(self):
        model = train_classifier(
            [
                {"text": "乙甲", "intent": "zeta", "split": "train"},
                {"text": "丙甲", "intent": "alpha", "split": "train"},
            ]
        )

        with self.assertRaises(TypeError):
            model.class_counts["alpha"] = 99
        with self.assertRaises(TypeError):
            model.feature_counts["alpha"]["甲"] = 99
        with self.assertRaises(TypeError):
            model.total_features["alpha"] = 99
        with self.assertRaises(TypeError):
            model.vocabulary[0] = "changed"

    def test_direct_model_construction_defensively_freezes_caller_data(self):
        class_counts = {"zeta": 1, "alpha": 2}
        feature_counts = {
            "zeta": {"z": 1},
            "alpha": {"b": 1, "a": 2},
        }
        total_features = {"zeta": 1, "alpha": 3}
        vocabulary = ["z", "b", "a"]

        model = demo.IntentClassifier(
            class_counts=class_counts,
            feature_counts=feature_counts,
            total_features=total_features,
            vocabulary=vocabulary,
        )
        class_counts["alpha"] = 99
        class_counts["new"] = 1
        feature_counts["alpha"]["a"] = 99
        feature_counts["new"] = {"new": 1}
        total_features["alpha"] = 99
        vocabulary.append("changed")

        self.assertEqual(list(model.class_counts), ["alpha", "zeta"])
        self.assertEqual(dict(model.class_counts), {"alpha": 2, "zeta": 1})
        self.assertEqual(list(model.feature_counts), ["alpha", "zeta"])
        self.assertEqual(list(model.feature_counts["alpha"]), ["a", "b"])
        self.assertEqual(dict(model.feature_counts["alpha"]), {"a": 2, "b": 1})
        self.assertEqual(dict(model.total_features), {"alpha": 3, "zeta": 1})
        self.assertEqual(model.vocabulary, ("a", "b", "z"))

        with self.assertRaises(TypeError):
            model.class_counts["alpha"] = 99
        with self.assertRaises(TypeError):
            model.feature_counts["alpha"]["a"] = 99
        with self.assertRaises(TypeError):
            model.total_features["alpha"] = 99

    def test_training_rejects_empty_train_split(self):
        examples = [
            {"text": "只用于验证", "intent": "example", "split": "validation"},
            {"text": "只用于测试", "intent": "example", "split": "test"},
        ]

        with self.assertRaises(ValueError):
            train_classifier(examples)

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

    def test_repeated_features_contribute_their_full_frequency(self):
        model = train_classifier(
            [
                {"text": "x", "intent": "a", "split": "train"},
                {"text": "y", "intent": "b", "split": "train"},
            ]
        )

        result = predict_intent(
            model,
            "xxx",
            confidence_threshold=0.0,
            margin_threshold=0.0,
        )

        self.assertEqual(result["intent"], "a")
        self.assertAlmostEqual(result["candidates"][0]["probability"], 8 / 9)

    def test_softmax_probabilities_remain_finite_for_long_repeated_input(self):
        model = train_classifier(
            [
                {"text": "x", "intent": "a", "split": "train"},
                {"text": "y", "intent": "b", "split": "train"},
            ]
        )

        result = predict_intent(
            model,
            "x" * 20_000,
            confidence_threshold=0.0,
            margin_threshold=0.0,
        )
        probabilities = [
            candidate["probability"] for candidate in result["candidates"]
        ]

        self.assertTrue(all(math.isfinite(value) for value in probabilities))
        self.assertAlmostEqual(sum(probabilities), 1.0)

    def test_tied_candidates_are_ordered_by_intent_and_accepted(self):
        model = train_classifier(
            [
                {"text": "甲乙", "intent": "zeta", "split": "train"},
                {"text": "甲乙", "intent": "alpha", "split": "train"},
            ]
        )

        result = predict_intent(
            model,
            "甲乙",
            confidence_threshold=0.0,
            margin_threshold=0.0,
        )

        self.assertEqual(
            [candidate["intent"] for candidate in result["candidates"]],
            ["alpha", "zeta"],
        )
        self.assertEqual(
            [candidate["probability"] for candidate in result["candidates"]],
            [0.5, 0.5],
        )
        self.assertEqual(result["intent"], "alpha")
        self.assertEqual(result["reason"], "accepted")

    def test_confidence_equal_to_threshold_is_accepted(self):
        model = train_classifier(
            [
                {"text": "甲乙", "intent": "zeta", "split": "train"},
                {"text": "甲乙", "intent": "alpha", "split": "train"},
            ]
        )

        result = predict_intent(
            model,
            "甲乙",
            confidence_threshold=0.5,
            margin_threshold=0.0,
        )

        self.assertEqual(result["confidence"], 0.5)
        self.assertEqual(result["intent"], "alpha")
        self.assertEqual(result["reason"], "accepted")

    def test_margin_equal_to_threshold_is_accepted(self):
        model = train_classifier(
            [{"text": "甲", "intent": "single", "split": "train"}]
        )

        result = predict_intent(
            model,
            "甲",
            confidence_threshold=0.0,
            margin_threshold=1.0,
        )

        self.assertEqual(result["margin"], 1.0)
        self.assertEqual(result["intent"], "single")
        self.assertEqual(result["reason"], "accepted")

    def test_out_of_vocabulary_features_are_rejected(self):
        examples = [
            {"text": "甲", "intent": "short", "split": "train"},
            {"text": "乙丙丁戊己庚辛壬癸", "intent": "long", "split": "train"},
        ]
        model = train_classifier(examples)

        result = predict_intent(model, "zzzzzzzzzz")

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["reason"], "no_features")


class IntentClassifierArtifactTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"text": "取消订单", "intent": "cancel_order", "split": "train"},
            {"text": "查询物流", "intent": "query_order", "split": "train"},
            {"text": "撤销购买", "intent": "cancel_order", "split": "validation"},
            {"text": "查看包裹", "intent": "query_order", "split": "validation"},
            {"text": "今天天气", "intent": "unknown", "split": "validation"},
            {"text": "不要订单", "intent": "cancel_order", "split": "test"},
            {"text": "订单到哪", "intent": "query_order", "split": "test"},
            {"text": "播放音乐", "intent": "unknown", "split": "test"},
        ]
        self.model = train_classifier(self.rows)
        self.thresholds = Thresholds(0.45, 0.10, 0.75)
        self.frozen_time = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)
        with patch.object(demo, "_utc_now", return_value=self.frozen_time):
            self.artifact = build_artifact(
                self.model,
                self.thresholds,
                self.rows,
                model_version="demo-v1",
            )

    def _copy_artifact(self):
        return copy.deepcopy(self.artifact)

    def test_artifact_has_fixed_schema_and_json_serializable_snapshot(self):
        self.assertEqual(SCHEMA_VERSION, 1)
        self.assertEqual(set(self.artifact), REQUIRED_ARTIFACT_KEYS)
        self.assertEqual(self.artifact["schema_version"], 1)
        self.assertEqual(self.artifact["algorithm"], "multinomial_naive_bayes")
        self.assertEqual(
            self.artifact["normalization"],
            {
                "version": 1,
                "strategy": "whole_string_lower_then_alphanumeric_filter",
                "ngram_range": [1, 2],
            },
        )
        self.assertEqual(self.artifact["labels"], sorted(self.model.class_counts))

        snapshot = self.model.mutable_snapshot()
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        snapshot["class_counts"]["cancel_order"] = 999
        self.assertNotEqual(self.model.class_counts["cancel_order"], 999)

    def test_dataset_fingerprint_is_exact_and_order_invariant(self):
        canonical_rows = sorted(
            self.rows,
            key=lambda row: (
                row["split"],
                row["intent"],
                normalize_text(row["text"]),
                row["text"],
            ),
        )
        canonical_json = json.dumps(
            canonical_rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        expected = hashlib.sha256(canonical_json).hexdigest()

        with patch.object(demo, "_utc_now", return_value=self.frozen_time):
            reordered = build_artifact(
                self.model,
                self.thresholds,
                list(reversed(self.rows)),
                model_version="demo-v1",
            )

        self.assertEqual(
            self.artifact["training_metadata"]["dataset_sha256"],
            expected,
        )
        self.assertEqual(
            reordered["training_metadata"]["dataset_sha256"],
            expected,
        )

    def test_build_rejects_blank_version_and_invalid_rows(self):
        for version in ("", "   "):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "model_version"):
                    build_artifact(
                        self.model,
                        self.thresholds,
                        self.rows,
                        model_version=version,
                    )

        invalid_rows = [*self.rows, {"text": "", "intent": "bad", "split": "train"}]
        with self.assertRaisesRegex(ValueError, "rows"):
            build_artifact(
                self.model,
                self.thresholds,
                invalid_rows,
                model_version="demo-v1",
            )

    def test_artifact_round_trip_preserves_model_prediction_exactly(self):
        expected = predict_intent(
            self.model,
            "帮我取消订单",
            confidence_threshold=self.thresholds.confidence,
            margin_threshold=self.thresholds.margin,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intent-model.json"
            save_artifact(self.artifact, path)
            loaded = load_artifact(path)

        self.assertEqual(predict_with_artifact(self.artifact, "帮我取消订单"), expected)
        self.assertEqual(predict_with_artifact(loaded, "帮我取消订单"), expected)
        self.assertEqual(
            model_from_artifact(loaded).mutable_snapshot(),
            self.model.mutable_snapshot(),
        )

    def test_stable_serialization_with_frozen_time(self):
        with patch.object(demo, "_utc_now", return_value=self.frozen_time):
            reordered = build_artifact(
                train_classifier(list(reversed(self.rows))),
                self.thresholds,
                list(reversed(self.rows)),
                model_version="demo-v1",
            )

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            save_artifact(self.artifact, first)
            save_artifact(reordered, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertTrue(first.read_bytes().endswith(b"\n"))

    def test_existing_artifact_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intent-model.json"
            save_artifact(self.artifact, path)
            original = path.read_bytes()

            with self.assertRaises(FileExistsError):
                save_artifact(self.artifact, path, force=False)
            self.assertEqual(path.read_bytes(), original)

            save_artifact(self.artifact, path, force=True)
            self.assertEqual(path.read_bytes(), original)

    def test_save_requires_existing_parent_and_cleans_temp_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                save_artifact(self.artifact, root / "missing" / "model.json")
            self.assertEqual(list(root.iterdir()), [])

            path = root / "intent-model.json"
            with patch.object(
                demo.os,
                "replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    save_artifact(self.artifact, path)
            self.assertFalse(path.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_rejects_unknown_schema_and_missing_or_unexpected_top_level_keys(self):
        invalid_artifacts = []
        unknown_schema = self._copy_artifact()
        unknown_schema["schema_version"] = 2
        invalid_artifacts.append(unknown_schema)
        missing_key = self._copy_artifact()
        del missing_key["algorithm"]
        invalid_artifacts.append(missing_key)
        unexpected_key = self._copy_artifact()
        unexpected_key["extra"] = True
        invalid_artifacts.append(unexpected_key)

        for artifact in invalid_artifacts:
            with self.subTest(
                keys=set(artifact),
                schema=artifact.get("schema_version"),
            ):
                with self.assertRaises(ValueError):
                    model_from_artifact(artifact)

    def test_rejects_unknown_algorithm_and_wrong_normalization_types(self):
        invalid_artifacts = []
        unknown_algorithm = self._copy_artifact()
        unknown_algorithm["algorithm"] = "other"
        invalid_artifacts.append(unknown_algorithm)
        float_version = self._copy_artifact()
        float_version["normalization"]["version"] = 1.0
        invalid_artifacts.append(float_version)
        float_ngram = self._copy_artifact()
        float_ngram["normalization"]["ngram_range"] = [1.0, 2.0]
        invalid_artifacts.append(float_ngram)

        for artifact in invalid_artifacts:
            with self.subTest(artifact=artifact):
                with self.assertRaises(ValueError):
                    model_from_artifact(artifact)

    def test_rejects_nan_infinity_wrong_threshold_types_and_corrupt_json(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, "0.5"):
            invalid = self._copy_artifact()
            invalid["thresholds"]["confidence"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    model_from_artifact(invalid)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            for payload in ('{"thresholds": NaN}', '{"value": Infinity}', "{broken"):
                with self.subTest(payload=payload):
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_artifact(path)

    def test_rejects_negative_bool_and_inconsistent_counts(self):
        invalid_values = (-1, True, 1.5)
        for value in invalid_values:
            invalid = self._copy_artifact()
            invalid["statistics"]["class_counts"]["cancel_order"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    model_from_artifact(invalid)

        invalid_total = self._copy_artifact()
        invalid_total["statistics"]["total_features"]["cancel_order"] += 1
        with self.assertRaises(ValueError):
            model_from_artifact(invalid_total)

        invalid_train_count = self._copy_artifact()
        invalid_train_count["training_metadata"]["split_counts"]["train"] += 1
        with self.assertRaises(ValueError):
            model_from_artifact(invalid_train_count)

    def test_rejects_label_and_vocabulary_mismatches(self):
        invalid_artifacts = []
        for labels in (
            list(reversed(self.artifact["labels"])),
            [*self.artifact["labels"], self.artifact["labels"][0]],
            ["", *self.artifact["labels"]],
        ):
            invalid = self._copy_artifact()
            invalid["labels"] = labels
            invalid_artifacts.append(invalid)

        missing_label = self._copy_artifact()
        del missing_label["statistics"]["feature_counts"]["cancel_order"]
        invalid_artifacts.append(missing_label)
        extra_label = self._copy_artifact()
        extra_label["statistics"]["total_features"]["extra"] = 0
        invalid_artifacts.append(extra_label)
        vocabulary_mismatch = self._copy_artifact()
        vocabulary_mismatch["statistics"]["vocabulary"].append("zzz")
        invalid_artifacts.append(vocabulary_mismatch)
        unsorted_vocabulary = self._copy_artifact()
        unsorted_vocabulary["statistics"]["vocabulary"].reverse()
        invalid_artifacts.append(unsorted_vocabulary)

        for artifact in invalid_artifacts:
            with self.subTest(labels=artifact["labels"]):
                with self.assertRaises(ValueError):
                    model_from_artifact(artifact)

    def test_rejects_invalid_metadata_and_evaluation_summaries(self):
        invalid_artifacts = []
        for timestamp in ("", "2026-07-15", "2026-07-15T08:30:00+08:00"):
            invalid = self._copy_artifact()
            invalid["training_metadata"]["trained_at"] = timestamp
            invalid_artifacts.append(invalid)
        for fingerprint in ("", "g" * 64, "a" * 63, "A" * 64):
            invalid = self._copy_artifact()
            invalid["training_metadata"]["dataset_sha256"] = fingerprint
            invalid_artifacts.append(invalid)
        invalid_split_count = self._copy_artifact()
        invalid_split_count["training_metadata"]["split_counts"]["test"] = True
        invalid_artifacts.append(invalid_split_count)
        extra_metadata = self._copy_artifact()
        extra_metadata["training_metadata"]["extra"] = "unexpected"
        invalid_artifacts.append(extra_metadata)
        invalid_summary = self._copy_artifact()
        invalid_summary["evaluation_summary"]["test"]["accuracy"] = float("nan")
        invalid_artifacts.append(invalid_summary)
        inconsistent_summary = self._copy_artifact()
        inconsistent_summary["evaluation_summary"]["test"]["count"] += 1
        invalid_artifacts.append(inconsistent_summary)

        for artifact in invalid_artifacts:
            with self.subTest(metadata=artifact["training_metadata"]):
                with self.assertRaises(ValueError):
                    model_from_artifact(artifact)


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

    def test_prediction_rejects_non_finite_or_out_of_range_thresholds(self):
        model = train_classifier(self.training_examples)

        for threshold_name in ("confidence_threshold", "margin_threshold"):
            invalid_values = (
                -0.01,
                1.01,
                float("nan"),
                float("inf"),
                float("-inf"),
                10**1000,
            )
            for invalid_value in invalid_values:
                with self.subTest(
                    threshold_name=threshold_name, invalid_value=invalid_value
                ):
                    thresholds = {
                        "confidence_threshold": 0.0,
                        "margin_threshold": 0.0,
                        threshold_name: invalid_value,
                    }
                    with self.assertRaisesRegex(ValueError, threshold_name):
                        predict_intent(model, "订单", **thresholds)

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

    def test_evaluation_distinguishes_rejections_from_accepted_errors(self):
        model = train_classifier(
            [
                {"text": "x", "intent": "a", "split": "train"},
                {"text": "y", "intent": "b", "split": "train"},
            ]
        )
        examples = [
            {"text": "x", "intent": "a", "split": "validation"},
            {"text": "x", "intent": "b", "split": "validation"},
            {"text": "z", "intent": "b", "split": "validation"},
            {"text": "y", "intent": "b", "split": "test"},
        ]

        result = evaluate_classifier(
            model,
            examples,
            split="validation",
            thresholds=Thresholds(0.0, 0.0, 0.75),
        )

        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["coverage"], 2 / 3)
        self.assertAlmostEqual(result["rejection_rate"], 1 / 3)
        self.assertEqual(result["rejection_rate"], 1.0 - result["coverage"])
        self.assertEqual(result["accepted_accuracy"], 0.5)
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(len(result["accepted_errors"]), 1)
        self.assertEqual(result["rejected"][0]["reason"], "no_features")
        self.assertEqual(
            [row["reason"] for row in result["errors"]],
            ["accepted", "no_features"],
        )
        self.assertEqual(result["accepted_errors"][0]["reason"], "accepted")
        self.assertEqual(
            [row["expected"] for row in result["predictions"]],
            ["a", "b", "b"],
        )
        self.assertEqual(
            set(result),
            {
                "count",
                "accuracy",
                "labels",
                "confusion_matrix",
                "per_intent",
                "macro",
                "rejection_rate",
                "coverage",
                "accepted_accuracy",
                "predictions",
                "accepted",
                "rejected",
                "errors",
                "accepted_errors",
            },
        )
        self.assertTrue(
            all(
                set(row)
                == {
                    "text",
                    "expected",
                    "accepted",
                    "correct",
                    "intent",
                    "confidence",
                    "margin",
                    "candidates",
                    "reason",
                }
                for row in result["predictions"]
            )
        )

    def test_evaluation_with_zero_accepted_predictions_reports_zero_accepted_accuracy(
        self,
    ):
        model = train_classifier(
            [
                {"text": "x", "intent": "a", "split": "train"},
                {"text": "y", "intent": "b", "split": "train"},
            ]
        )
        examples = [{"text": "x", "intent": "a", "split": "test"}]

        result = evaluate_classifier(
            model,
            examples,
            split="test",
            thresholds=Thresholds(1.0, 0.0, 0.75),
        )

        self.assertEqual(result["coverage"], 0.0)
        self.assertEqual(result["rejection_rate"], 1.0)
        self.assertEqual(result["accepted_accuracy"], 0.0)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["accepted_errors"], [])
        self.assertEqual(result["errors"], result["rejected"])

    def test_evaluation_rejects_non_evaluation_splits(self):
        model = train_classifier(self.training_examples)

        with self.assertRaisesRegex(ValueError, "validation.*test"):
            evaluate_classifier(
                model,
                self.training_examples,
                split="train",
                thresholds=Thresholds(0.0, 0.0, 0.75),
            )

    def test_evaluation_rejects_empty_requested_split(self):
        model = train_classifier(self.training_examples)

        for split in ("validation", "test"):
            with (
                self.subTest(split=split),
                self.assertRaisesRegex(
                    ValueError,
                    rf"^{split} split must not be empty$",
                ),
            ):
                evaluate_classifier(
                    model,
                    self.training_examples,
                    split=split,
                    thresholds=Thresholds(0.0, 0.0, 0.75),
                )


class IntentClassifierCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "x", "intent": "a", "split": "validation"},
            {"text": "y", "intent": "b", "split": "validation"},
            {"text": "x", "intent": "a", "split": "test"},
        ]

    def test_thresholds_are_immutable(self):
        thresholds = Thresholds(0.45, 0.10, 0.75)

        with self.assertRaises(FrozenInstanceError):
            thresholds.confidence = 0.55

    def test_thresholds_reject_decimal_signaling_nan_with_field_name(self):
        for field_name in (
            "confidence",
            "margin",
            "minimum_accepted_accuracy",
        ):
            with self.subTest(field_name=field_name):
                values = {
                    "confidence": 0.45,
                    "margin": 0.10,
                    "minimum_accepted_accuracy": 0.75,
                    field_name: Decimal("sNaN"),
                }
                with self.assertRaisesRegex(
                    ValueError,
                    rf"^{field_name} must be a finite number in \[0, 1\]$",
                ):
                    Thresholds(**values)

    def test_thresholds_reject_out_of_range_values(self):
        for field_name, invalid_value in (
            ("confidence", -0.01),
            ("margin", 1.01),
            ("minimum_accepted_accuracy", float("inf")),
        ):
            with self.subTest(field_name=field_name):
                values = {
                    "confidence": 0.45,
                    "margin": 0.10,
                    "minimum_accepted_accuracy": 0.75,
                    field_name: invalid_value,
                }
                with self.assertRaisesRegex(ValueError, field_name):
                    Thresholds(**values)

    def test_thresholds_canonicalize_negative_zero(self):
        thresholds = Thresholds(-0.0, -0.0, -0.0)

        for value in asdict(thresholds).values():
            self.assertEqual(math.copysign(1.0, value), 1.0)
        self.assertNotIn("-0.0", json.dumps(asdict(thresholds), sort_keys=True))

    def test_calibration_reads_only_validation_rows(self):
        changed_test = [
            (
                dict(row, text="completely different test text", intent="changed")
                if row["split"] == "test"
                else row
            )
            for row in self.rows
        ]

        first = calibrate_thresholds(train_classifier(self.rows), self.rows)
        second = calibrate_thresholds(
            train_classifier(changed_test),
            changed_test,
        )

        self.assertEqual(first, second)

    def test_calibration_never_reads_test_text_or_intent(self):
        class PoisonTestRow(Mapping[str, str]):
            def __init__(self):
                self.split_reads = 0
                self.text_reads = 0
                self.intent_reads = 0

            def __getitem__(self, key: str) -> str:
                if key == "split":
                    self.split_reads += 1
                    return "test"
                if key == "text":
                    self.text_reads += 1
                    raise AssertionError("calibration read a test text")
                if key == "intent":
                    self.intent_reads += 1
                    raise AssertionError("calibration read a test intent")
                raise KeyError(key)

            def __iter__(self) -> Iterator[str]:
                return iter(("text", "intent", "split"))

            def __len__(self) -> int:
                return 3

        poison = PoisonTestRow()
        calibration_rows = [*self.rows[:-1], poison]

        calibrate_thresholds(
            train_classifier(self.rows),
            calibration_rows,
            confidence_values=(0.0,),
            margin_values=(0.0,),
            minimum_accepted_accuracy=0.0,
        )

        self.assertGreater(poison.split_reads, 0)
        self.assertEqual(poison.text_reads, 0)
        self.assertEqual(poison.intent_reads, 0)

    def test_calibration_threshold_grids_must_be_sequences(self):
        model = train_classifier(self.rows)

        with self.assertRaisesRegex(
            ValueError,
            "^confidence_values must be a sequence$",
        ):
            calibrate_thresholds(
                model,
                self.rows,
                confidence_values=(value for value in (0.0, 0.5)),
            )

    def test_calibration_prefers_higher_macro_f1_over_higher_coverage(self):
        rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "x", "intent": "a", "split": "validation"},
            {"text": "y", "intent": "b", "split": "validation"},
            {"text": "xy", "intent": "unknown", "split": "validation"},
        ]
        model = train_classifier(rows)
        high_coverage = evaluate_classifier(
            model,
            rows,
            split="validation",
            thresholds=Thresholds(0.0, 0.0, 0.0),
        )
        high_macro_f1 = evaluate_classifier(
            model,
            rows,
            split="validation",
            thresholds=Thresholds(0.6, 0.0, 0.0),
        )

        self.assertGreater(high_coverage["coverage"], high_macro_f1["coverage"])
        self.assertGreater(high_macro_f1["macro"]["f1"], high_coverage["macro"]["f1"])

        thresholds = calibrate_thresholds(
            model,
            rows,
            confidence_values=(0.0, 0.6),
            margin_values=(0.0,),
            minimum_accepted_accuracy=0.0,
        )

        self.assertEqual(thresholds, Thresholds(0.6, 0.0, 0.0))

    def test_calibration_prefers_higher_coverage_when_macro_f1_is_equal(self):
        rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "x", "intent": "b", "split": "validation"},
        ]
        model = train_classifier(rows)
        high_coverage = evaluate_classifier(
            model,
            rows,
            split="validation",
            thresholds=Thresholds(0.0, 0.0, 0.0),
        )
        low_coverage = evaluate_classifier(
            model,
            rows,
            split="validation",
            thresholds=Thresholds(0.8, 0.0, 0.0),
        )

        self.assertEqual(high_coverage["macro"]["f1"], low_coverage["macro"]["f1"])
        self.assertGreater(high_coverage["coverage"], low_coverage["coverage"])

        thresholds = calibrate_thresholds(
            model,
            rows,
            confidence_values=(0.8, 0.0),
            margin_values=(0.0,),
            minimum_accepted_accuracy=0.0,
        )

        self.assertEqual(thresholds, Thresholds(0.0, 0.0, 0.0))

    def test_calibration_keeps_candidate_equal_to_accuracy_floor(self):
        rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "x", "intent": "a", "split": "validation"},
            {"text": "y", "intent": "a", "split": "validation"},
        ]

        thresholds = calibrate_thresholds(
            train_classifier(rows),
            rows,
            confidence_values=(0.0,),
            margin_values=(0.0,),
            minimum_accepted_accuracy=0.5,
        )

        self.assertEqual(thresholds, Thresholds(0.0, 0.0, 0.5))

    def test_calibration_breaks_ties_by_lowest_thresholds(self):
        rows = [
            {"text": "x", "intent": "only", "split": "train"},
            {"text": "x", "intent": "only", "split": "validation"},
        ]

        descending = calibrate_thresholds(
            train_classifier(rows),
            rows,
            confidence_values=(0.8, 0.2),
            margin_values=(0.9, 0.1),
            minimum_accepted_accuracy=0.5,
        )
        ascending = calibrate_thresholds(
            train_classifier(rows),
            rows,
            confidence_values=(0.2, 0.8),
            margin_values=(0.1, 0.9),
            minimum_accepted_accuracy=0.5,
        )

        self.assertEqual(descending, Thresholds(0.2, 0.1, 0.5))
        self.assertEqual(ascending, descending)

    def test_calibration_canonicalizes_zero_independent_of_grid_order(self):
        rows = [
            {"text": "x", "intent": "only", "split": "train"},
            {"text": "x", "intent": "only", "split": "validation"},
        ]
        model = train_classifier(rows)

        negative_first = calibrate_thresholds(
            model,
            rows,
            confidence_values=(-0.0, 0.0),
            margin_values=(-0.0, 0.0),
            minimum_accepted_accuracy=-0.0,
        )
        positive_first = calibrate_thresholds(
            model,
            rows,
            confidence_values=(0.0, -0.0),
            margin_values=(0.0, -0.0),
            minimum_accepted_accuracy=0.0,
        )

        negative_payload = json.dumps(asdict(negative_first), sort_keys=True)
        positive_payload = json.dumps(asdict(positive_first), sort_keys=True)
        self.assertEqual(negative_payload, positive_payload)
        self.assertNotIn("-0.0", negative_payload)

    def test_calibration_fails_when_accuracy_floor_is_unreachable(self):
        rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "x", "intent": "b", "split": "validation"},
        ]

        with self.assertRaisesRegex(
            ValueError,
            "^no threshold pair satisfies minimum accepted accuracy$",
        ):
            calibrate_thresholds(
                train_classifier(rows),
                rows,
                confidence_values=(0.0,),
                margin_values=(0.0,),
                minimum_accepted_accuracy=1.0,
            )

    def test_calibration_rejects_empty_validation_input(self):
        rows = [{"text": "x", "intent": "a", "split": "train"}]

        with self.assertRaisesRegex(ValueError, "validation split must not be empty"):
            calibrate_thresholds(train_classifier(rows), rows)

    def test_calibration_rejects_empty_or_invalid_candidate_grids(self):
        model = train_classifier(self.rows)
        invalid_arguments = (
            ({"confidence_values": ()}, "confidence_values must not be empty"),
            ({"margin_values": ()}, "margin_values must not be empty"),
            (
                {"confidence_values": None},
                "confidence_values must be a sequence",
            ),
            (
                {"confidence_values": (1.01,)},
                r"confidence_values must be a finite number in \[0, 1\]",
            ),
            (
                {"margin_values": (float("nan"),)},
                r"margin_values must be a finite number in \[0, 1\]",
            ),
            (
                {"minimum_accepted_accuracy": -0.01},
                r"minimum_accepted_accuracy must be a finite number in \[0, 1\]",
            ),
        )

        for arguments, message in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, rf"^{message}$"):
                    calibrate_thresholds(model, self.rows, **arguments)


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

    def test_cli_rejects_invalid_thresholds(self):
        for flag in ("--confidence-threshold", "--margin-threshold"):
            invalid_values = ("-0.01", "1.01", "nan", "inf", "-inf", "1e1000")
            for invalid_value in invalid_values:
                with self.subTest(flag=flag, invalid_value=invalid_value):
                    with (
                        redirect_stderr(io.StringIO()),
                        self.assertRaises(SystemExit) as error,
                    ):
                        main(
                            [
                                "--data",
                                str(self.data_path),
                                "predict",
                                "--text",
                                "订单",
                                flag,
                                invalid_value,
                            ]
                        )

                    self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
