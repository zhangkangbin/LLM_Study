from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


VALID_SPLITS = frozenset({"train", "validation", "test"})
INTENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
DEFAULT_DATA_PATH = Path(__file__).with_name("sample_intents.jsonl")


@dataclass(frozen=True)
class IntentClassifier:
    class_counts: Mapping[str, int]
    feature_counts: Mapping[str, Mapping[str, int]]
    total_features: Mapping[str, int]
    vocabulary: tuple[str, ...]

    def __post_init__(self) -> None:
        intents = sorted(self.class_counts)
        class_counts = MappingProxyType(
            {intent: self.class_counts[intent] for intent in intents}
        )
        feature_counts = MappingProxyType(
            {
                intent: MappingProxyType(
                    {
                        feature: self.feature_counts[intent][feature]
                        for feature in sorted(self.feature_counts[intent])
                    }
                )
                for intent in sorted(self.feature_counts)
            }
        )
        total_features = MappingProxyType(
            {
                intent: self.total_features[intent]
                for intent in sorted(self.total_features)
            }
        )
        vocabulary = tuple(sorted(set(self.vocabulary)))

        object.__setattr__(self, "class_counts", class_counts)
        object.__setattr__(self, "feature_counts", feature_counts)
        object.__setattr__(self, "total_features", total_features)
        object.__setattr__(self, "vocabulary", vocabulary)


@dataclass(frozen=True)
class Thresholds:
    confidence: float
    margin: float
    minimum_accepted_accuracy: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "confidence",
            _validate_threshold("confidence", self.confidence),
        )
        object.__setattr__(
            self,
            "margin",
            _validate_threshold("margin", self.margin),
        )
        object.__setattr__(
            self,
            "minimum_accepted_accuracy",
            _validate_threshold(
                "minimum_accepted_accuracy",
                self.minimum_accepted_accuracy,
            ),
        )


def load_examples(path: Path | str) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"line {line_number}: invalid JSON: {error.msg}"
                ) from error
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}: expected object")
            examples.append(value)
    return examples


def validate_examples(
    examples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    indexed_rows: dict[int, tuple[str, str, str]] = {}
    exact_text_indexes: dict[str, list[int]] = {}
    normalized_text_indexes: dict[str, list[int]] = {}
    split_indexes = {split: [] for split in VALID_SPLITS}
    ordinary_intent_indexes = {split: {} for split in VALID_SPLITS}

    for index, example in enumerate(examples):
        if not isinstance(example, Mapping):
            issues.append(_issue("invalid_field", "样本必须是对象", [index]))
            continue

        text = example.get("text")
        intent = example.get("intent")
        split = example.get("split")
        fields_valid = True

        for field_name, value in (("text", text), ("intent", intent), ("split", split)):
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    _issue("invalid_field", f"{field_name} 必须是非空字符串", [index])
                )
                fields_valid = False

        if (
            isinstance(intent, str)
            and intent.strip()
            and not INTENT_PATTERN.fullmatch(intent)
        ):
            issues.append(
                _issue("invalid_intent", "intent 必须使用小写蛇形命名", [index])
            )

        if isinstance(split, str) and split.strip() and split not in VALID_SPLITS:
            issues.append(
                _issue(
                    "invalid_split",
                    "split 只能是 train、validation 或 test",
                    [index],
                )
            )

        if split == "train" and intent == "unknown":
            issues.append(
                _issue(
                    "unknown_in_train",
                    "unknown 是系统拒识标签，不能作为训练标签",
                    [index],
                )
            )

        if not fields_valid:
            continue

        assert isinstance(text, str)
        assert isinstance(intent, str)
        assert isinstance(split, str)
        normalized = normalize_text(text)
        normalized_valid = bool(normalized)
        intent_valid = bool(INTENT_PATTERN.fullmatch(intent))
        split_valid = split in VALID_SPLITS

        if not normalized_valid:
            issues.append(
                _issue(
                    "empty_normalized_text",
                    "text 规范化后不能为空",
                    [index],
                )
            )

        if not (normalized_valid and intent_valid and split_valid):
            continue

        indexed_rows[index] = (text, intent, split)
        exact_text_indexes.setdefault(text, []).append(index)
        normalized_text_indexes.setdefault(normalized, []).append(index)
        split_indexes[split].append(index)
        if intent != "unknown":
            ordinary_intent_indexes[split].setdefault(intent, []).append(index)

    for normalized, indexes in normalized_text_indexes.items():
        if len(indexes) < 2:
            continue

        sorted_indexes = sorted(indexes)
        rows = [indexed_rows[index] for index in sorted_indexes]
        labels = {intent for _, intent, _ in rows}
        splits = {split for _, _, split in rows}
        if len(labels) > 1:
            issues.append(
                _issue(
                    "conflicting_label",
                    "同一规范化文本存在冲突标签",
                    sorted_indexes,
                )
            )
        if len(splits) > 1:
            issues.append(
                _issue(
                    "cross_split_leakage",
                    "同一规范化文本不能跨数据分段出现",
                    sorted_indexes,
                )
            )

        duplicate_partitions: dict[tuple[str, str], list[int]] = {}
        for index in sorted_indexes:
            _, intent, split = indexed_rows[index]
            duplicate_partitions.setdefault((split, intent), []).append(index)

        for same_partition_indexes in duplicate_partitions.values():
            if len(same_partition_indexes) < 2:
                continue
            partition_index_set = set(same_partition_indexes)
            has_exact_duplicate = any(
                len(
                    partition_index_set.intersection(
                        exact_text_indexes[indexed_rows[index][0]]
                    )
                )
                > 1
                for index in same_partition_indexes
            )
            message = (
                "同一文本重复出现"
                if has_exact_duplicate
                else "规范化后的同一文本重复出现"
            )
            issues.append(_issue("duplicate_text", message, same_partition_indexes))

    for split in sorted(VALID_SPLITS):
        if not split_indexes[split]:
            issues.append(_issue("empty_split", f"{split} 数据分段不能为空", []))

    train_intents = set(ordinary_intent_indexes["train"])
    evaluation_intents = set(ordinary_intent_indexes["validation"]) | set(
        ordinary_intent_indexes["test"]
    )
    for intent in sorted(evaluation_intents - train_intents):
        indexes = sorted(
            ordinary_intent_indexes["validation"].get(intent, [])
            + ordinary_intent_indexes["test"].get(intent, [])
        )
        issues.append(
            _issue(
                "missing_train_intent",
                f"验证/测试意图 {intent} 没有训练样本",
                indexes,
            )
        )

    return sorted(issues, key=lambda issue: (issue["code"], issue["indexes"]))


def normalize_text(text: str) -> str:
    return "".join(character for character in text.lower() if character.isalnum())


def extract_features(text: str) -> list[str]:
    normalized = normalize_text(text)
    unigrams = list(normalized)
    bigrams = [normalized[index : index + 2] for index in range(len(normalized) - 1)]
    return unigrams + bigrams


def train_classifier(examples: Sequence[dict[str, str]]) -> IntentClassifier:
    class_counts: Counter[str] = Counter()
    feature_counters: dict[str, Counter[str]] = {}
    vocabulary: set[str] = set()

    for example in examples:
        if example.get("split") != "train" or example.get("intent") == "unknown":
            continue
        intent = example["intent"]
        features = extract_features(example["text"])
        class_counts[intent] += 1
        feature_counters.setdefault(intent, Counter()).update(features)
        vocabulary.update(features)

    if not class_counts:
        raise ValueError("训练集不能为空")

    return IntentClassifier(
        class_counts=dict(class_counts),
        feature_counts={
            intent: dict(counts) for intent, counts in feature_counters.items()
        },
        total_features={
            intent: sum(counts.values()) for intent, counts in feature_counters.items()
        },
        vocabulary=tuple(vocabulary),
    )


def predict_intent(
    model: IntentClassifier,
    text: str,
    *,
    confidence_threshold: float = 0.45,
    margin_threshold: float = 0.10,
) -> dict[str, object]:
    confidence_threshold = _validate_threshold(
        "confidence_threshold", confidence_threshold
    )
    margin_threshold = _validate_threshold("margin_threshold", margin_threshold)
    features = [
        feature for feature in extract_features(text) if feature in model.vocabulary
    ]
    if not features:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "margin": 0.0,
            "candidates": [],
            "reason": "no_features",
        }

    feature_frequency = Counter(features)
    total_examples = sum(model.class_counts.values())
    vocabulary_size = max(1, len(model.vocabulary))
    log_scores: dict[str, float] = {}

    for intent, class_count in model.class_counts.items():
        score = math.log(class_count / total_examples)
        denominator = model.total_features[intent] + vocabulary_size
        counts = model.feature_counts[intent]
        for feature, frequency in feature_frequency.items():
            score += frequency * math.log((counts.get(feature, 0) + 1) / denominator)
        log_scores[intent] = score

    max_score = max(log_scores.values())
    weights = {
        intent: math.exp(score - max_score) for intent, score in log_scores.items()
    }
    weight_sum = sum(weights.values())
    candidates = sorted(
        (
            {"intent": intent, "probability": weight / weight_sum}
            for intent, weight in weights.items()
        ),
        key=lambda candidate: (-candidate["probability"], candidate["intent"]),
    )
    confidence = candidates[0]["probability"]
    runner_up = candidates[1]["probability"] if len(candidates) > 1 else 0.0
    predicted_intent = candidates[0]["intent"]
    reason = "accepted"
    if confidence < confidence_threshold:
        predicted_intent = "unknown"
        reason = "low_confidence"
    elif confidence - runner_up < margin_threshold:
        predicted_intent = "unknown"
        reason = "low_margin"

    result: dict[str, object] = {
        "intent": predicted_intent,
        "confidence": confidence,
        "margin": confidence - runner_up,
        "candidates": candidates,
        "reason": reason,
    }
    return result


def classification_metrics(
    actual: Sequence[str], predicted: Sequence[str]
) -> dict[str, object]:
    if len(actual) != len(predicted):
        raise ValueError("actual 和 predicted 长度必须一致")

    labels = sorted(set(actual) | set(predicted))
    confusion_matrix = {
        actual_label: {predicted_label: 0 for predicted_label in labels}
        for actual_label in labels
    }
    for actual_label, predicted_label in zip(actual, predicted):
        confusion_matrix[actual_label][predicted_label] += 1

    per_intent: dict[str, dict[str, float | int]] = {}
    for label in labels:
        true_positive = confusion_matrix[label][label]
        false_positive = sum(
            confusion_matrix[other][label] for other in labels if other != label
        )
        false_negative = sum(
            confusion_matrix[label][other] for other in labels if other != label
        )
        support = sum(confusion_matrix[label].values())
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        per_intent[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    label_count = len(labels)
    macro = {
        metric: _safe_divide(
            sum(float(values[metric]) for values in per_intent.values()), label_count
        )
        for metric in ("precision", "recall", "f1")
    }
    correct = sum(
        1 for actual_label, predicted_label in zip(actual, predicted) if actual_label == predicted_label
    )
    return {
        "count": len(actual),
        "accuracy": _safe_divide(correct, len(actual)),
        "labels": labels,
        "confusion_matrix": confusion_matrix,
        "per_intent": per_intent,
        "macro": macro,
    }


def evaluate_classifier(
    model: IntentClassifier,
    examples: Sequence[dict[str, str]],
    *,
    split: str,
    thresholds: Thresholds,
) -> dict[str, object]:
    if split not in {"validation", "test"}:
        raise ValueError("split must be 'validation' or 'test'")

    evaluation_examples = [
        example for example in examples if example.get("split") == split
    ]
    actual: list[str] = []
    predicted: list[str] = []
    predictions: list[dict[str, object]] = []
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    for example in evaluation_examples:
        prediction = predict_intent(
            model,
            example["text"],
            confidence_threshold=thresholds.confidence,
            margin_threshold=thresholds.margin,
        )
        expected_intent = example["intent"]
        actual.append(expected_intent)
        predicted_intent = str(prediction["intent"])
        predicted.append(predicted_intent)
        is_accepted = prediction["reason"] == "accepted"
        is_correct = predicted_intent == expected_intent
        record = {
            "text": example["text"],
            "expected": expected_intent,
            "accepted": is_accepted,
            "correct": is_correct,
            **prediction,
        }
        predictions.append(record)
        if is_accepted:
            accepted.append(record)
        else:
            rejected.append(record)
        if is_accepted and not is_correct:
            errors.append(record)

    metrics = classification_metrics(actual, predicted)
    correctly_accepted = sum(1 for record in accepted if record["correct"])
    return {
        **metrics,
        "rejection_rate": _safe_divide(len(rejected), len(predictions)),
        "coverage": _safe_divide(len(accepted), len(predictions)),
        "accepted_accuracy": _safe_divide(correctly_accepted, len(accepted)),
        "predictions": predictions,
        "accepted": accepted,
        "rejected": rejected,
        "errors": errors,
    }


def calibrate_thresholds(
    model: IntentClassifier,
    examples: Sequence[dict[str, str]],
    *,
    confidence_values: Sequence[object] = (0.35, 0.45, 0.55, 0.65),
    margin_values: Sequence[object] = (0.05, 0.10, 0.20, 0.30),
    minimum_accepted_accuracy: object = 0.75,
) -> Thresholds:
    if not any(example.get("split") == "validation" for example in examples):
        raise ValueError("validation split must not be empty")

    confidence_grid = _validate_threshold_grid(
        "confidence_values",
        confidence_values,
    )
    margin_grid = _validate_threshold_grid("margin_values", margin_values)
    minimum_accuracy = _validate_threshold(
        "minimum_accepted_accuracy",
        minimum_accepted_accuracy,
    )

    candidates: list[tuple[float, float, Thresholds]] = []
    for confidence in confidence_grid:
        for margin in margin_grid:
            thresholds = Thresholds(confidence, margin, minimum_accuracy)
            report = evaluate_classifier(
                model,
                examples,
                split="validation",
                thresholds=thresholds,
            )
            accepted_accuracy = float(report["accepted_accuracy"])
            if accepted_accuracy < minimum_accuracy:
                continue
            macro = report["macro"]
            assert isinstance(macro, dict)
            candidates.append(
                (
                    float(macro["f1"]),
                    float(report["coverage"]),
                    thresholds,
                )
            )

    if not candidates:
        raise ValueError("no threshold pair satisfies minimum accepted accuracy")

    return max(
        candidates,
        key=lambda candidate: (
            candidate[0],
            candidate[1],
            -candidate[2].confidence,
            -candidate[2].margin,
        ),
    )[2]


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _validate_threshold_grid(name: str, values: object) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    try:
        grid = tuple(values)
    except TypeError as error:
        raise ValueError(f"{name} must be a sequence") from error
    if not grid:
        raise ValueError(f"{name} must not be empty")
    return tuple(_validate_threshold(name, value) for value in grid)


def _validate_threshold(name: str, value: object) -> float:
    try:
        valid = (
            not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 1
        )
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线意图识别与分类训练 Demo")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="校验 JSONL 数据集")

    evaluate_parser = subparsers.add_parser("evaluate", help="训练并评估分类器")
    _add_threshold_arguments(evaluate_parser)

    predict_parser = subparsers.add_parser("predict", help="训练并预测一条文本")
    predict_parser.add_argument("--text", required=True, type=_non_blank_text)
    _add_threshold_arguments(predict_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        examples = load_examples(args.data)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        _print_json({"error": "data_load_failed", "message": str(error)}, sys.stderr)
        return 2

    issues = validate_examples(examples)
    if args.command == "validate":
        _print_json({"valid": not issues, "count": len(examples), "issues": issues})
        return 0 if not issues else 1

    if issues:
        _print_json({"error": "invalid_dataset", "issues": issues}, sys.stderr)
        return 2

    try:
        model = train_classifier(examples)
    except ValueError as error:
        _print_json({"error": "training_failed", "message": str(error)}, sys.stderr)
        return 2

    if args.command == "evaluate":
        _print_json(
            evaluate_classifier(
                model,
                examples,
                split="test",
                thresholds=Thresholds(
                    args.confidence_threshold,
                    args.margin_threshold,
                    0.75,
                ),
            )
        )
        return 0

    _print_json(
        predict_intent(
            model,
            args.text,
            confidence_threshold=args.confidence_threshold,
            margin_threshold=args.margin_threshold,
        )
    )
    return 0


def _add_threshold_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confidence-threshold", type=_threshold_argument, default=0.45
    )
    parser.add_argument("--margin-threshold", type=_threshold_argument, default=0.10)


def _threshold_argument(value: str) -> float:
    try:
        return _validate_threshold("threshold", float(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _non_blank_text(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("--text 不能为空")
    return value


def _print_json(value: object, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream)


def _issue(code: str, message: str, indexes: list[int]) -> dict[str, object]:
    return {"code": code, "message": message, "indexes": sorted(indexes)}


if __name__ == "__main__":
    raise SystemExit(main())
