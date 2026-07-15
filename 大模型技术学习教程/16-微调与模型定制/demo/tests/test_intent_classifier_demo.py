import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
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
PARITY_CASES = DEMO_DIR / "intent_parity_cases.jsonl"
ANDROID_DEMO_DIR = (
    DEMO_DIR.parents[1] / "17-本地模型与私有化部署" / "demo" / "android"
)


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

    def _artifact_with_q_feature_count(self, count):
        artifact = self._copy_artifact()
        statistics = artifact["statistics"]
        statistics["feature_counts"]["cancel_order"]["q"] = count
        statistics["total_features"]["cancel_order"] += count
        statistics["vocabulary"].append("q")
        statistics["vocabulary"].sort()
        return artifact

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

    def test_build_rejects_validation_accuracy_below_calibration_floor(self):
        rows = [
            {"text": "x", "intent": "a", "split": "train"},
            {"text": "y", "intent": "b", "split": "train"},
            {"text": "xx", "intent": "b", "split": "validation"},
            {"text": "yy", "intent": "b", "split": "validation"},
            {"text": "xxx", "intent": "a", "split": "test"},
            {"text": "yyy", "intent": "b", "split": "test"},
        ]

        with self.assertRaisesRegex(ValueError, "minimum_accepted_accuracy"):
            build_artifact(
                train_classifier(rows),
                Thresholds(0.0, 0.0, 0.75),
                rows,
                model_version="below-floor",
            )

    def test_build_rejects_zero_count_feature_with_field_path(self):
        invalid = self._artifact_with_q_feature_count(0)
        statistics = invalid["statistics"]
        model = demo.IntentClassifier(
            class_counts=statistics["class_counts"],
            feature_counts=statistics["feature_counts"],
            total_features=statistics["total_features"],
            vocabulary=statistics["vocabulary"],
        )

        with self.assertRaisesRegex(
            ValueError,
            r"statistics\.feature_counts\.cancel_order\.q",
        ):
            build_artifact(
                model,
                self.thresholds,
                self.rows,
                model_version="zero-feature",
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
                    save_artifact(self.artifact, path, force=True)
            self.assertFalse(path.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_force_false_does_not_overwrite_target_created_during_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "intent-model.json"
            racer_payload = "created by another writer\n"
            real_link = demo.os.link

            def create_racer_then_publish(source, destination):
                path.write_text(racer_payload, encoding="utf-8")
                return real_link(source, destination)

            with patch.object(
                demo.os,
                "link",
                side_effect=create_racer_then_publish,
            ):
                with self.assertRaises(FileExistsError):
                    save_artifact(self.artifact, path, force=False)

            self.assertEqual(path.read_text(encoding="utf-8"), racer_payload)
            self.assertEqual(list(root.iterdir()), [path])

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

    def test_rejects_whitespace_only_feature_names(self):
        invalid = self._copy_artifact()
        statistics = invalid["statistics"]
        counts = statistics["feature_counts"]["cancel_order"]
        other_features = set(statistics["feature_counts"]["query_order"])
        feature = next(value for value in counts if value not in other_features)
        count = counts.pop(feature)
        counts["   "] = count
        vocabulary = statistics["vocabulary"]
        vocabulary[vocabulary.index(feature)] = "   "
        vocabulary.sort()

        with self.assertRaisesRegex(
            ValueError,
            "^feature names must be non-blank strings$",
        ):
            model_from_artifact(invalid)

    def test_rejects_whitespace_only_vocabulary_entries(self):
        invalid = self._copy_artifact()
        vocabulary = invalid["statistics"]["vocabulary"]
        vocabulary[0] = "\t  "
        vocabulary.sort()

        with self.assertRaisesRegex(
            ValueError,
            r"^statistics\.vocabulary must be a list of non-blank strings$",
        ):
            model_from_artifact(invalid)

    def test_rejects_features_outside_the_training_contract(self):
        for replacement in ("abc", "A", "a!"):
            invalid = self._copy_artifact()
            statistics = invalid["statistics"]
            counts = statistics["feature_counts"]["cancel_order"]
            other_features = set(statistics["feature_counts"]["query_order"])
            feature = next(value for value in counts if value not in other_features)
            count = counts.pop(feature)
            counts[replacement] = count
            vocabulary = statistics["vocabulary"]
            vocabulary[vocabulary.index(feature)] = replacement
            vocabulary.sort()

            with self.subTest(replacement=replacement):
                with self.assertRaises(ValueError):
                    model_from_artifact(invalid)

    def test_accepts_reachable_unicode_one_and_two_code_point_features(self):
        for replacement in ("é", "汉字"):
            valid = self._copy_artifact()
            statistics = valid["statistics"]
            counts = statistics["feature_counts"]["cancel_order"]
            other_features = set(statistics["feature_counts"]["query_order"])
            feature = next(value for value in counts if value not in other_features)
            count = counts.pop(feature)
            counts[replacement] = count
            vocabulary = statistics["vocabulary"]
            vocabulary[vocabulary.index(feature)] = replacement
            vocabulary.sort()

            with self.subTest(replacement=replacement):
                model_from_artifact(valid)

    def test_rejects_total_features_below_class_count(self):
        invalid = self._copy_artifact()
        statistics = invalid["statistics"]
        statistics["class_counts"]["cancel_order"] = 2
        statistics["feature_counts"]["cancel_order"] = {"取": 1}
        statistics["total_features"]["cancel_order"] = 1
        feature_union = {
            feature
            for counts in statistics["feature_counts"].values()
            for feature in counts
        }
        statistics["vocabulary"] = sorted(feature_union)
        invalid["training_metadata"]["split_counts"]["train"] = 3

        with self.assertRaises(ValueError):
            model_from_artifact(invalid)

    def test_rejects_zero_count_feature_with_field_path(self):
        invalid = self._artifact_with_q_feature_count(0)

        with self.assertRaisesRegex(
            ValueError,
            r"statistics\.feature_counts\.cancel_order\.q",
        ):
            model_from_artifact(invalid)

    def test_load_rejects_zero_count_feature_with_field_path(self):
        invalid = self._artifact_with_q_feature_count(0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zero-feature.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                r"statistics\.feature_counts\.cancel_order\.q",
            ):
                load_artifact(path)

    def test_normal_and_positive_count_features_remain_valid(self):
        model_from_artifact(self.artifact)
        positive = self._artifact_with_q_feature_count(1)
        model_from_artifact(positive)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "positive-feature.json"
            save_artifact(positive, path)
            load_artifact(path)

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

    def test_rejects_evaluation_ratios_impossible_for_integer_counts(self):
        mutations = (
            {"accuracy": 0.1},
            {"coverage": 0.5, "rejection_rate": 0.5},
            {"accepted_accuracy": 0.123},
            {
                "coverage": 0.0,
                "rejection_rate": 1.0,
                "accepted_accuracy": 0.1,
            },
        )
        for mutation in mutations:
            invalid = self._copy_artifact()
            invalid["evaluation_summary"]["test"].update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    model_from_artifact(invalid)

    def test_accepts_evaluation_ratios_possible_for_integer_counts(self):
        valid = self._copy_artifact()
        valid["evaluation_summary"]["test"].update(
            {
                "accuracy": 1 / 3,
                "coverage": 2 / 3,
                "rejection_rate": 1 / 3,
                "accepted_accuracy": 0.5,
            }
        )
        model_from_artifact(valid)

        zero_accepted = self._copy_artifact()
        zero_accepted["evaluation_summary"]["test"].update(
            {
                "coverage": 0.0,
                "rejection_rate": 1.0,
                "accepted_accuracy": 0.0,
            }
        )
        model_from_artifact(zero_accepted)

    def test_rejects_jointly_impossible_evaluation_counts(self):
        mutations = (
            {
                "accuracy": 0.0,
                "coverage": 1.0,
                "rejection_rate": 0.0,
                "accepted_accuracy": 1.0,
            },
            {
                "accuracy": 1.0,
                "coverage": 1.0,
                "rejection_rate": 0.0,
                "accepted_accuracy": 0.0,
            },
        )
        for mutation in mutations:
            invalid = self._copy_artifact()
            invalid["evaluation_summary"]["test"].update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    model_from_artifact(invalid)

    def test_accepts_joint_count_boundaries_with_rejected_predictions(self):
        boundaries = (
            {
                "accuracy": 1 / 3,
                "coverage": 2 / 3,
                "rejection_rate": 1 / 3,
                "accepted_accuracy": 0.5,
            },
            {
                "accuracy": 2 / 3,
                "coverage": 2 / 3,
                "rejection_rate": 1 / 3,
                "accepted_accuracy": 0.5,
            },
        )
        for boundary in boundaries:
            valid = self._copy_artifact()
            valid["evaluation_summary"]["test"].update(boundary)
            with self.subTest(boundary=boundary):
                model_from_artifact(valid)

    def test_rejects_validation_accuracy_below_calibration_floor(self):
        invalid = self._copy_artifact()
        invalid["evaluation_summary"]["validation"]["accepted_accuracy"] = 0.0

        with self.assertRaisesRegex(ValueError, "minimum_accepted_accuracy"):
            model_from_artifact(invalid)

    def test_load_rejects_validation_accuracy_below_calibration_floor(self):
        invalid = self._copy_artifact()
        invalid["evaluation_summary"]["validation"]["accepted_accuracy"] = 0.0

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "below-floor.json"
            path.write_text(
                json.dumps(invalid, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "minimum_accepted_accuracy"):
                load_artifact(path)

    def test_calibration_floor_accepts_equal_validation_and_ignores_test(self):
        valid = self._copy_artifact()
        valid["thresholds"]["minimum_accepted_accuracy"] = 1.0
        valid["evaluation_summary"]["test"].update(
            {
                "accuracy": 1 / 3,
                "accepted_accuracy": 0.0,
            }
        )

        model_from_artifact(valid)

    def test_calibration_floor_uses_strict_less_than_comparison(self):
        invalid = self._copy_artifact()
        invalid["thresholds"]["minimum_accepted_accuracy"] = 0.7500000000005
        invalid["training_metadata"]["split_counts"]["validation"] = 4
        invalid["evaluation_summary"]["validation"].update(
            {
                "count": 4,
                "accuracy": 0.75,
                "coverage": 1.0,
                "rejection_rate": 0.0,
                "accepted_accuracy": 0.75,
            }
        )

        with self.assertRaisesRegex(ValueError, "minimum_accepted_accuracy"):
            model_from_artifact(invalid)

    def test_calibration_floor_accepts_exact_equality(self):
        valid = self._copy_artifact()
        valid["thresholds"]["minimum_accepted_accuracy"] = 0.75
        valid["training_metadata"]["split_counts"]["validation"] = 4
        valid["evaluation_summary"]["validation"].update(
            {
                "count": 4,
                "accuracy": 0.75,
                "coverage": 1.0,
                "rejection_rate": 0.0,
                "accepted_accuracy": 0.75,
            }
        )

        model_from_artifact(valid)

    def test_load_wraps_huge_evaluation_count_overflow_as_field_value_error(self):
        invalid = self._copy_artifact()
        huge_count = 10**400
        invalid["training_metadata"]["split_counts"]["test"] = huge_count
        invalid["evaluation_summary"]["test"]["count"] = huge_count

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huge-count.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                r"evaluation_summary\.test\.accuracy",
            ):
                load_artifact(path)


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


class IntentSampleDataTest(unittest.TestCase):
    def test_sample_data_is_balanced_and_passes_the_data_contract(self):
        rows = load_examples(SAMPLE_DATA)

        self.assertEqual(validate_examples(rows), [])
        counts = Counter((row["intent"], row["split"]) for row in rows)
        ordinary_intents = {
            "query_order",
            "cancel_order",
            "request_refund",
            "human_service",
        }
        self.assertEqual(
            {row["intent"] for row in rows if row["intent"] != "unknown"},
            ordinary_intents,
        )
        for intent in ordinary_intents:
            with self.subTest(intent=intent):
                self.assertGreaterEqual(counts[intent, "train"], 6)
                self.assertGreaterEqual(counts[intent, "validation"], 2)
                self.assertGreaterEqual(counts[intent, "test"], 2)
        self.assertGreaterEqual(counts["unknown", "validation"], 4)
        self.assertGreaterEqual(counts["unknown", "test"], 4)

    def test_training_vocabulary_contains_ascii_letter_and_digit_features(self):
        model = train_classifier(load_examples(SAMPLE_DATA))
        vocabulary = set(model.vocabulary)

        latin_overlap = set(extract_features("ID")) & vocabulary
        digit_overlap = set(extract_features("2026")) & vocabulary
        self.assertTrue(
            any(feature.isascii() and feature.isalpha() for feature in latin_overlap)
        )
        self.assertTrue(any(len(feature) == 1 for feature in latin_overlap))
        self.assertTrue(any(len(feature) == 2 for feature in latin_overlap))
        self.assertTrue(
            any(
                feature.isascii() and any(character.isdigit() for character in feature)
                for feature in digit_overlap
            )
        )
        self.assertTrue(any(len(feature) == 1 for feature in digit_overlap))
        self.assertTrue(any(len(feature) == 2 for feature in digit_overlap))

    def test_parity_cases_cover_decisions_and_portable_input_shapes(self):
        cases = load_examples(PARITY_CASES)

        self.assertTrue(cases)
        self.assertTrue(
            all(
                set(case)
                == {"text", "expected_intent", "expected_reason"}
                for case in cases
            )
        )
        accepted_intents = {
            case["expected_intent"]
            for case in cases
            if case["expected_reason"] == "accepted"
        }
        self.assertTrue(
            {
                "query_order",
                "cancel_order",
                "request_refund",
                "human_service",
            }.issubset(accepted_intents)
        )
        reasons = {case["expected_reason"] for case in cases}
        self.assertTrue(
            {"accepted", "low_confidence", "low_margin", "no_features"}.issubset(
                reasons
            )
        )
        texts = [case["text"] for case in cases]
        self.assertTrue(any(text.isascii() and text.isalpha() for text in texts))
        self.assertTrue(any(any(char.isdigit() for char in text) for text in texts))
        self.assertTrue(
            any(
                any(char.isascii() and char.isalpha() for char in text)
                and any("\u4e00" <= char <= "\u9fff" for char in text)
                for text in texts
            )
        )


class JavaIntentClassifierParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.javac = shutil.which("javac")
        cls.java = shutil.which("java")
        if cls.javac is None:
            raise unittest.SkipTest("javac is not installed or not on PATH")
        if cls.java is None:
            raise unittest.SkipTest("java is not installed or not on PATH")

        cls.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(cls.temporary_directory.name)
        cls.classes_directory = temporary_root / "classes"
        cls.classes_directory.mkdir()
        unicode_directory = temporary_root / "Java 意图 parity"
        unicode_directory.mkdir()
        cls.model_path = unicode_directory / "模型 制品.json"

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "train",
                    "--data",
                    str(SAMPLE_DATA),
                    "--model",
                    str(cls.model_path),
                    "--model-version",
                    "java-parity-v1",
                ]
            )
        if exit_code != 0 or stderr.getvalue():
            raise AssertionError(
                "temporary parity artifact training failed:\n"
                f"exit={exit_code}\nstdout={stdout.getvalue()}\n"
                f"stderr={stderr.getvalue()}"
            )
        cls.artifact = load_artifact(cls.model_path)
        cls._create_unicode_artifact(temporary_root)
        cls._create_unicode_boundary_truth(temporary_root)

        java_sources = [
            ANDROID_DEMO_DIR / "MiniJson.java",
            ANDROID_DEMO_DIR / "IntentModelLoader.java",
            ANDROID_DEMO_DIR / "MobileIntentClassifier.java",
            ANDROID_DEMO_DIR / "MobileIntentClassifierTest.java",
        ]
        compile_process = subprocess.run(
            [
                cls.javac,
                "--release",
                "17",
                "-Xlint:all",
                "-encoding",
                "UTF-8",
                "-d",
                str(cls.classes_directory),
                *(str(path) for path in java_sources),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if compile_process.returncode != 0:
            raise AssertionError(
                "Java intent classifier compilation failed:\n"
                f"stdout={compile_process.stdout}\n"
                f"stderr={compile_process.stderr}"
            )

    @classmethod
    def _create_unicode_artifact(cls, temporary_root):
        dotted_i = "\u0130"
        squared = "\u00b2"
        deseret_upper = "\U00010400"
        extension_i = "\U0002EBF0"
        final_sigma = "\u039f\u03a3"
        non_final_sigma = "\u039f\u03a3\u0391"
        ignored_sigma_context = "A\u03a3'A"
        mixed = dotted_i + squared + deseret_upper + extension_i + final_sigma
        rows = [
            *(
                {"text": text, "intent": "unicode_intent", "split": "train"}
                for text in (
                    dotted_i + squared,
                    deseret_upper + extension_i,
                    final_sigma,
                    non_final_sigma,
                    ignored_sigma_context,
                    mixed,
                )
            ),
            *(
                {"text": text, "intent": "ascii_intent", "split": "train"}
                for text in (
                    "zzzero",
                    "yyone",
                    "qqtwo",
                    "wwthree",
                    "vvfour",
                    "uufive",
                )
            ),
            {
                "text": dotted_i + squared + "v",
                "intent": "unicode_intent",
                "split": "validation",
            },
            {"text": "zzv", "intent": "ascii_intent", "split": "validation"},
            {
                "text": final_sigma + "t",
                "intent": "unicode_intent",
                "split": "test",
            },
            {"text": "zzt", "intent": "ascii_intent", "split": "test"},
        ]
        issues = validate_examples(rows)
        if issues:
            raise AssertionError(f"invalid Unicode parity rows: {issues}")
        model = train_classifier(rows)
        artifact = build_artifact(
            model,
            Thresholds(0.0, 0.0, 0.0),
            rows,
            "java-unicode-file-parity-v1",
        )
        cls.unicode_model_path = temporary_root / "Unicode 模型.json"
        save_artifact(artifact, cls.unicode_model_path)
        cls.unicode_artifact = artifact
        cls.unicode_parity_texts = (
            dotted_i,
            squared,
            deseret_upper,
            extension_i,
            final_sigma,
            non_final_sigma,
            "A'\u03a3",
            ignored_sigma_context,
            mixed,
        )

    @classmethod
    def _create_unicode_boundary_truth(cls, temporary_root):
        source = (ANDROID_DEMO_DIR / "MobileIntentClassifier.java").read_text(
            encoding="utf-8"
        )

        def java_int_array(name):
            match = re.search(
                rf"private static final int\[\] {name} = \{{(.*?)\n        \}};",
                source,
                re.DOTALL,
            )
            if match is None:
                raise AssertionError(f"missing Java Unicode table: {name}")
            return [
                int(token, 0)
                for token in re.findall(r"-?0x[0-9A-F]+|-?\d+", match.group(1))
            ]

        lower_mappings = java_int_array("LOWER_MAPPINGS")
        cased_ranges = java_int_array("CASED_RANGES")
        ignorable_ranges = java_int_array("CASE_IGNORABLE_RANGES")
        if len(lower_mappings) // 4 != 177:
            raise AssertionError("expected 177 compressed lower mapping groups")
        if len(cased_ranges) // 2 != 174:
            raise AssertionError("expected 174 Cased ranges")
        if len(ignorable_ranges) // 2 != 491:
            raise AssertionError("expected 491 Case_Ignorable ranges")

        normalization_probes = {
            code_point
            for code_point in range(0x110000)
            if chr(code_point).lower() != chr(code_point)
        }
        if len(normalization_probes) != 1433:
            raise AssertionError("expected 1433 Unicode 15.1 lower-changing codepoints")
        for offset in range(0, len(lower_mappings), 4):
            start, end = lower_mappings[offset : offset + 2]
            for boundary in (start, end):
                normalization_probes.update(
                    code_point
                    for code_point in (boundary - 1, boundary, boundary + 1)
                    if 0 <= code_point <= 0x10FFFF
                )

        cls.normalization_boundary_truth = (
            temporary_root / "normalization-boundaries.bin"
        )
        payload = bytearray(struct.pack(">I", len(normalization_probes)))
        for code_point in sorted(normalization_probes):
            normalized = "".join(
                character
                for character in chr(code_point).lower()
                if character.isalnum()
            )
            if len(normalized) > 1:
                raise AssertionError("single-codepoint normalization expanded unexpectedly")
            payload.extend(
                struct.pack(">Ii", code_point, ord(normalized) if normalized else -1)
            )
        cls.normalization_boundary_truth.write_bytes(payload)

        sigma_probes = set()
        for ranges in (cased_ranges, ignorable_ranges):
            for offset in range(0, len(ranges), 2):
                for boundary in ranges[offset : offset + 2]:
                    sigma_probes.update(
                        code_point
                        for code_point in (boundary - 1, boundary, boundary + 1)
                        if 0 <= code_point <= 0x10FFFF
                    )
        cls.final_sigma_boundary_truth = temporary_root / "final-sigma-boundaries.bin"
        payload = bytearray(struct.pack(">I", len(sigma_probes)))
        for code_point in sorted(sigma_probes):
            character = chr(code_point)
            payload.extend(struct.pack(">I", code_point))
            payload.extend(
                (
                    (character + "\u03a3").lower().endswith("\u03c2"),
                    ("A" + character + "\u03a3").lower().endswith("\u03c2"),
                    ("A\u03a3" + character).lower()[1] == "\u03c2",
                    ("A\u03a3" + character + "A").lower()[1] == "\u03c2",
                )
            )
        cls.final_sigma_boundary_truth.write_bytes(payload)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temporary_directory"):
            cls.temporary_directory.cleanup()
        super().tearDownClass()

    def invoke_java(self, *arguments):
        return subprocess.run(
            [
                self.java,
                "-cp",
                str(self.classes_directory),
                "MobileIntentClassifier",
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )

    def assert_single_json_document(self, output):
        decoder = json.JSONDecoder()
        payload, end = decoder.raw_decode(output)
        self.assertEqual(output[end:].strip(), "")
        return payload

    def test_java_test_main_runs_against_python_artifact(self):
        process = subprocess.run(
            [
                self.java,
                f"-Dintent.normalization.boundary.truth={self.normalization_boundary_truth}",
                f"-Dintent.final_sigma.boundary.truth={self.final_sigma_boundary_truth}",
                "-cp",
                str(self.classes_directory),
                "MobileIntentClassifierTest",
                str(self.model_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(process.stdout.strip(), "MobileIntentClassifierTest OK")

    def test_java_truth_probe_rejects_corrupted_compact_truth(self):
        corrupted = Path(self.temporary_directory.name) / "corrupted-truth.bin"
        corrupted.write_bytes(b"bad")
        process = subprocess.run(
            [
                self.java,
                f"-Dintent.normalization.boundary.truth={corrupted}",
                "-cp",
                str(self.classes_directory),
                "MobileIntentClassifierTest",
                str(self.model_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

        self.assertNotEqual(process.returncode, 0)
        self.assertIn("normalization boundary truth length", process.stderr)

    def test_java_cli_matches_python_for_every_parity_case(self):
        for case in load_examples(PARITY_CASES):
            with self.subTest(text=case["text"]):
                expected = predict_with_artifact(self.artifact, case["text"])
                process = self.invoke_java(
                    "--model",
                    str(self.model_path),
                    "--text",
                    case["text"],
                )

                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                actual = self.assert_single_json_document(process.stdout)
                self.assertEqual(actual["intent"], case["expected_intent"])
                self.assertEqual(actual["reason"], case["expected_reason"])
                self.assertEqual(actual["intent"], expected["intent"])
                self.assertEqual(actual["reason"], expected["reason"])
                self.assertEqual(
                    [candidate["intent"] for candidate in actual["candidates"]],
                    [candidate["intent"] for candidate in expected["candidates"]],
                )
                self.assertEqual(
                    len(actual["candidates"]),
                    len(expected["candidates"]),
                )
                for java_candidate, python_candidate in zip(
                    actual["candidates"], expected["candidates"]
                ):
                    self.assertLessEqual(
                        abs(
                            java_candidate["probability"]
                            - python_candidate["probability"]
                        ),
                        1e-9,
                    )
                self.assertLessEqual(
                    abs(actual["confidence"] - expected["confidence"]),
                    1e-9,
                )
                self.assertLessEqual(
                    abs(actual["margin"] - expected["margin"]),
                    1e-9,
                )

    def test_java_cli_uses_utf8_unicode_paths_and_structured_exit_two(self):
        unicode_process = self.invoke_java(
            "--model",
            str(self.model_path),
            "--text",
            "取消订单",
        )
        self.assertEqual(unicode_process.returncode, 0, unicode_process.stderr)
        self.assertEqual(unicode_process.stderr, "")
        unicode_payload = self.assert_single_json_document(unicode_process.stdout)
        unicode_expected = predict_with_artifact(self.artifact, "取消订单")
        self.assertEqual(unicode_payload["intent"], unicode_expected["intent"])
        self.assertEqual(unicode_payload["reason"], unicode_expected["reason"])

        missing_model = self.model_path.with_name("不存在 模型.json")
        invalid_invocations = (
            ((), "invalid_arguments"),
            (("--model", str(self.model_path)), "invalid_arguments"),
            (
                ("--model", str(missing_model), "--text", "订单"),
                "model_load_failed",
            ),
            (
                (
                    "--model",
                    str(self.model_path),
                    "--text",
                    "订单",
                    "--extra",
                    "value",
                ),
                "invalid_arguments",
            ),
        )
        for arguments, expected_error in invalid_invocations:
            with self.subTest(arguments=arguments):
                process = self.invoke_java(*arguments)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                payload = self.assert_single_json_document(process.stderr)
                self.assertEqual(payload["error"], expected_error)
                if expected_error == "model_load_failed":
                    self.assertIn("不存在 模型.json", payload["message"])

    def test_java_text_file_preserves_unicode_and_matches_python(self):
        corrupted_argv_prediction = predict_with_artifact(
            self.unicode_artifact, "?"
        )
        self.assertEqual(corrupted_argv_prediction["reason"], "no_features")

        for index, text in enumerate(self.unicode_parity_texts):
            with self.subTest(text=ascii(text)):
                text_path = Path(self.temporary_directory.name) / f"input-{index}.txt"
                text_path.write_text(text, encoding="utf-8")
                expected = predict_with_artifact(self.unicode_artifact, text)
                self.assertNotEqual(expected, corrupted_argv_prediction)
                self.assertEqual(expected["intent"], "unicode_intent")
                self.assertEqual(expected["reason"], "accepted")
                process = self.invoke_java(
                    "--model",
                    str(self.unicode_model_path),
                    "--text-file",
                    str(text_path),
                )

                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                actual = self.assert_single_json_document(process.stdout)
                self.assertEqual(actual["intent"], expected["intent"])
                self.assertEqual(actual["reason"], expected["reason"])
                self.assertEqual(
                    [candidate["intent"] for candidate in actual["candidates"]],
                    [candidate["intent"] for candidate in expected["candidates"]],
                )
                for java_candidate, python_candidate in zip(
                    actual["candidates"], expected["candidates"]
                ):
                    self.assertLessEqual(
                        abs(
                            java_candidate["probability"]
                            - python_candidate["probability"]
                        ),
                        1e-9,
                    )
                self.assertLessEqual(
                    abs(actual["confidence"] - expected["confidence"]),
                    1e-9,
                )
                self.assertLessEqual(
                    abs(actual["margin"] - expected["margin"]),
                    1e-9,
                )

    def test_java_cli_rejects_ambiguous_options_and_invalid_text_files(self):
        root = Path(self.temporary_directory.name)
        empty = root / "empty.txt"
        empty.write_bytes(b"")
        blank = root / "blank.txt"
        blank.write_text("  \r\n", encoding="utf-8")
        malformed = root / "malformed.txt"
        malformed.write_bytes(b"\xc3\x28")
        oversized = root / "oversized.txt"
        oversized.write_bytes(b"x" * (1024 * 1024 + 1))
        missing = root / "missing.txt"
        model = str(self.model_path)
        invalid_arguments = (
            ("--model", model, "--text", "--model"),
            ("--model", "--text", "--text", "x"),
            ("--model", model, "--model", model, "--text", "x"),
            ("--model", model, "--text", "x", "--text", "y"),
            ("--model", model, "--text-file", str(empty), "--text-file", str(blank)),
            ("--model", model, "--text", "x", "--text-file", str(empty)),
            ("--model",),
            ("--model", model),
            ("--text", "x"),
            ("--model", model, "--text-file"),
            ("--model", model, "--unknown", "x"),
            ("--unknown-one", "x", "--model", model, "--text", "x"),
            ("--unknown-two", "--model", "--model", model, "--text", "x"),
            ("--model", model, "--text", "--unknown"),
            ("--model", model, "--text", ""),
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                process = self.invoke_java(*arguments)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                payload = self.assert_single_json_document(process.stderr)
                self.assertEqual(payload["error"], "invalid_arguments")

        invalid_files = (missing, root, empty, blank, malformed, oversized)
        for text_path in invalid_files:
            with self.subTest(text_path=text_path):
                process = self.invoke_java(
                    "--model",
                    model,
                    "--text-file",
                    str(text_path),
                )
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                payload = self.assert_single_json_document(process.stderr)
                self.assertEqual(payload["error"], "text_load_failed")


class IntentClassifierCliTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.model_path = Path(self.temporary_directory.name) / "intent-model.json"

    def invoke(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(arguments)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def assert_single_json_document(self, output):
        decoder = json.JSONDecoder()
        payload, end = decoder.raw_decode(output)
        self.assertEqual(output[end:].strip(), "")
        return payload

    def train_model(self, *, model_version="test-v1"):
        exit_code, stdout, stderr = self.invoke(
            [
                "train",
                "--data",
                str(SAMPLE_DATA),
                "--model",
                str(self.model_path),
                "--model-version",
                model_version,
            ]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(exit_code, 0)
        return self.assert_single_json_document(stdout)

    def test_validate_command_returns_one_json_document(self):
        exit_code, stdout, stderr = self.invoke(
            ["validate", "--data", str(SAMPLE_DATA)]
        )

        payload = self.assert_single_json_document(stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["count"], len(load_examples(SAMPLE_DATA)))

    def test_train_writes_a_versioned_artifact_and_json_summary(self):
        payload = self.train_model(model_version="tutorial-test-v1")
        artifact = load_artifact(self.model_path)

        self.assertEqual(payload["model"], str(self.model_path))
        self.assertEqual(payload["model_version"], "tutorial-test-v1")
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(artifact["model_version"], "tutorial-test-v1")
        self.assertIn("validation", payload["evaluation_summary"])
        self.assertIn("test", payload["evaluation_summary"])

    def test_train_refuses_overwrite_without_force_and_force_replaces_it(self):
        self.train_model(model_version="first")
        original = self.model_path.read_bytes()

        exit_code, stdout, stderr = self.invoke(
            [
                "train",
                "--data",
                str(SAMPLE_DATA),
                "--model",
                str(self.model_path),
                "--model-version",
                "second",
            ]
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(self.assert_single_json_document(stderr)["error"], "model_exists")
        self.assertEqual(self.model_path.read_bytes(), original)

        exit_code, stdout, stderr = self.invoke(
            [
                "train",
                "--data",
                str(SAMPLE_DATA),
                "--model",
                str(self.model_path),
                "--model-version",
                "second",
                "--force",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.assert_single_json_document(stdout)["model_version"], "second"
        )
        self.assertEqual(load_artifact(self.model_path)["model_version"], "second")

    def test_existing_model_is_rejected_before_training_or_calibration(self):
        self.model_path.write_text("existing model", encoding="utf-8")

        with (
            patch.object(
                demo,
                "train_classifier",
                wraps=demo.train_classifier,
            ) as train_spy,
            patch.object(
                demo,
                "calibrate_thresholds",
                wraps=demo.calibrate_thresholds,
            ) as calibration_spy,
        ):
            exit_code, stdout, stderr = self.invoke(
                [
                    "train",
                    "--data",
                    str(SAMPLE_DATA),
                    "--model",
                    str(self.model_path),
                    "--model-version",
                    "must-not-train",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            self.assert_single_json_document(stderr)["error"],
            "model_exists",
        )
        train_spy.assert_not_called()
        calibration_spy.assert_not_called()

    def test_evaluate_loads_artifact_uses_requested_split_and_never_mutates_model(self):
        self.train_model()
        original = self.model_path.read_bytes()
        original_hash = hashlib.sha256(original).hexdigest()
        original_mtime = self.model_path.stat().st_mtime_ns

        with patch.object(
            demo,
            "train_classifier",
            side_effect=AssertionError("evaluate must not train"),
        ):
            exit_code, stdout, stderr = self.invoke(
                [
                    "evaluate",
                    "--data",
                    str(SAMPLE_DATA),
                    "--model",
                    str(self.model_path),
                    "--split",
                    "validation",
                ]
            )

        payload = self.assert_single_json_document(stdout)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["split"], "validation")
        self.assertEqual(
            payload["metrics"]["count"],
            sum(
                row["split"] == "validation" for row in load_examples(SAMPLE_DATA)
            ),
        )
        current = self.model_path.read_bytes()
        self.assertEqual(current, original)
        self.assertEqual(hashlib.sha256(current).hexdigest(), original_hash)
        self.assertEqual(self.model_path.stat().st_mtime_ns, original_mtime)

    def test_predict_loads_artifact_and_returns_stable_smoke_prediction(self):
        self.train_model()

        with patch.object(
            demo,
            "train_classifier",
            side_effect=AssertionError("predict must not train"),
        ):
            exit_code, stdout, stderr = self.invoke(
                [
                    "predict",
                    "--model",
                    str(self.model_path),
                    "--text",
                    "帮我取消订单",
                ]
            )

        payload = self.assert_single_json_document(stdout)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["intent"], "cancel_order")
        self.assertEqual(payload["reason"], "accepted")
        self.assertIn("candidates", payload)

    def test_inspect_returns_compact_metadata_without_feature_payloads(self):
        self.train_model()

        exit_code, stdout, stderr = self.invoke(
            ["inspect", "--model", str(self.model_path)]
        )

        payload = self.assert_single_json_document(stdout)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertIn("training_metadata", payload)
        self.assertIn("evaluation_summary", payload)
        self.assertEqual(
            set(payload["statistics"]),
            {"class_counts", "total_features", "vocabulary_size"},
        )
        self.assertNotIn("feature_counts", stdout)
        self.assertNotIn('"vocabulary"', stdout)

    def test_expected_user_errors_are_json_and_exit_two(self):
        missing = Path(self.temporary_directory.name) / "missing.jsonl"
        cases = (
            (["validate", "--data", str(missing)], "data_load_failed"),
            (
                [
                    "predict",
                    "--model",
                    str(self.model_path),
                    "--text",
                    "订单",
                ],
                "model_load_failed",
            ),
        )

        for arguments, expected_error in cases:
            with self.subTest(arguments=arguments):
                exit_code, stdout, stderr = self.invoke(arguments)
                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    self.assert_single_json_document(stderr)["error"],
                    expected_error,
                )

    def test_invalid_dataset_is_a_user_error_with_exit_two(self):
        invalid_data = Path(self.temporary_directory.name) / "invalid.jsonl"
        invalid_data.write_text(
            json.dumps(
                {"text": "未知训练标签", "intent": "unknown", "split": "train"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        exit_code, stdout, stderr = self.invoke(
            ["validate", "--data", str(invalid_data)]
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        payload = self.assert_single_json_document(stderr)
        self.assertEqual(payload["error"], "invalid_dataset")
        self.assertTrue(payload["issues"])

    def test_unexpected_failure_is_json_and_exit_one(self):
        with patch.object(demo, "load_artifact", side_effect=RuntimeError("boom")):
            exit_code, stdout, stderr = self.invoke(
                [
                    "predict",
                    "--model",
                    str(self.model_path),
                    "--text",
                    "订单",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        payload = self.assert_single_json_document(stderr)
        self.assertEqual(payload["error"], "unexpected_failure")
        self.assertEqual(payload["message"], "boom")

    def test_argument_errors_are_structured_and_exit_two(self):
        for arguments in (
            ["predict", "--model", str(self.model_path), "--text", "   "],
            [
                "evaluate",
                "--data",
                str(SAMPLE_DATA),
                "--model",
                str(self.model_path),
                "--split",
                "train",
            ],
        ):
            with self.subTest(arguments=arguments):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    main(arguments)
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(
                    self.assert_single_json_document(stderr.getvalue())["error"],
                    "invalid_arguments",
                )

    def test_parity_expectations_match_artifact_trained_by_cli(self):
        self.train_model(model_version="parity-test-v1")
        artifact = load_artifact(self.model_path)

        for case in load_examples(PARITY_CASES):
            with self.subTest(text=case["text"]):
                prediction = predict_with_artifact(artifact, case["text"])
                self.assertEqual(prediction["intent"], case["expected_intent"])
                self.assertEqual(prediction["reason"], case["expected_reason"])

    def test_ascii_digit_parity_detects_normalization_mutant(self):
        self.train_model(model_version="normalization-mutant-v1")
        artifact = load_artifact(self.model_path)
        statistics = artifact["statistics"]
        vocabulary = set(statistics["vocabulary"])
        parity_cases = {
            case["text"]: case for case in load_examples(PARITY_CASES)
        }
        probe_texts = ("ID", "2026", "订单ID2026")
        self.assertTrue(set(probe_texts).issubset(parity_cases))

        latin_overlap = set(extract_features("ID")) & vocabulary
        digit_overlap = set(extract_features("2026")) & vocabulary
        mixed_overlap = set(extract_features("订单ID2026")) & vocabulary
        self.assertTrue(
            any(feature.isascii() and feature.isalpha() for feature in latin_overlap)
        )
        self.assertTrue(any(len(feature) == 1 for feature in latin_overlap))
        self.assertTrue(any(len(feature) == 2 for feature in latin_overlap))
        self.assertTrue(
            any(any(character.isdigit() for character in feature) for feature in digit_overlap)
        )
        self.assertTrue(any(len(feature) == 1 for feature in digit_overlap))
        self.assertTrue(any(len(feature) == 2 for feature in digit_overlap))
        self.assertTrue(
            any(feature.isascii() and feature.isalpha() for feature in mixed_overlap)
        )
        self.assertTrue(
            any(any(character.isdigit() for character in feature) for feature in mixed_overlap)
        )

        baseline = {
            text: predict_with_artifact(artifact, text) for text in probe_texts
        }

        def drop_ascii_letters_and_digits(text):
            return "".join(
                character
                for character in text
                if not (character.isascii() and character.isalnum())
            )

        mutant = {
            text: predict_with_artifact(
                artifact,
                drop_ascii_letters_and_digits(text),
            )
            for text in probe_texts
        }

        self.assertTrue(
            any(baseline[text] != mutant[text] for text in probe_texts)
        )
        mutant_mismatches = [
            text
            for text in probe_texts
            if (
                mutant[text]["intent"],
                mutant[text]["reason"],
            )
            != (
                parity_cases[text]["expected_intent"],
                parity_cases[text]["expected_reason"],
            )
        ]
        self.assertTrue(mutant_mismatches)

    def test_real_subprocess_handles_unicode_space_paths_and_utf8_json(self):
        unicode_directory = (
            Path(self.temporary_directory.name) / "意图 模型 subprocess"
        )
        unicode_directory.mkdir()
        data_path = unicode_directory / "训练 数据.jsonl"
        model_path = unicode_directory / "模型 制品.json"
        data_path.write_bytes(SAMPLE_DATA.read_bytes())
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}

        train_process = subprocess.run(
            [
                sys.executable,
                str(Path(demo.__file__).resolve()),
                "train",
                "--data",
                str(data_path),
                "--model",
                str(model_path),
                "--model-version",
                "subprocess-v1",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=10,
            check=False,
        )
        self.assertEqual(train_process.returncode, 0, train_process.stderr)
        self.assertEqual(train_process.stderr, "")
        train_payload = self.assert_single_json_document(train_process.stdout)
        self.assertEqual(train_payload["model_version"], "subprocess-v1")

        predict_process = subprocess.run(
            [
                sys.executable,
                str(Path(demo.__file__).resolve()),
                "predict",
                "--model",
                str(model_path),
                "--text",
                "ID",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=10,
            check=False,
        )
        self.assertEqual(predict_process.returncode, 0, predict_process.stderr)
        self.assertEqual(predict_process.stderr, "")
        prediction = self.assert_single_json_document(predict_process.stdout)
        self.assertEqual(prediction["intent"], "query_order")
        self.assertEqual(prediction["reason"], "accepted")


if __name__ == "__main__":
    unittest.main()
