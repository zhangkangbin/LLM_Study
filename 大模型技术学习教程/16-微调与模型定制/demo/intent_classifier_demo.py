from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


INTENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class IntentClassifier:
    class_counts: dict[str, int]
    feature_counts: dict[str, dict[str, int]]
    total_features: dict[str, int]
    vocabulary: frozenset[str]


def load_examples(path: Path | str) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
            examples.append(value)
    return examples


def validate_examples(
    examples: Sequence[dict[str, str]],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    seen: dict[str, tuple[int, str]] = {}
    train_intents: set[str] = set()
    test_intents: set[str] = set()

    for index, example in enumerate(examples):
        if not isinstance(example, dict):
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

        if isinstance(intent, str) and intent.strip() and not INTENT_PATTERN.fullmatch(intent):
            issues.append(
                _issue("invalid_intent", "intent 必须使用小写蛇形命名", [index])
            )

        if isinstance(split, str) and split not in {"train", "test"}:
            issues.append(
                _issue("invalid_split", "split 只能是 train 或 test", [index])
            )

        if not fields_valid:
            continue

        normalized = _normalize_for_identity(text)
        if normalized in seen:
            previous_index, previous_intent = seen[normalized]
            code = "duplicate_text" if previous_intent == intent else "conflicting_label"
            message = "同一文本重复出现" if code == "duplicate_text" else "同一文本存在冲突标签"
            issues.append(_issue(code, message, [previous_index, index]))
        else:
            seen[normalized] = (index, intent)

        if split == "train" and INTENT_PATTERN.fullmatch(intent) and intent != "unknown":
            train_intents.add(intent)
        if split == "test" and INTENT_PATTERN.fullmatch(intent) and intent != "unknown":
            test_intents.add(intent)

    for intent in sorted(train_intents - test_intents):
        issues.append(
            _issue("missing_test_intent", f"训练意图 {intent} 没有测试样本")
        )
    for intent in sorted(test_intents - train_intents):
        issues.append(
            _issue("missing_train_intent", f"测试意图 {intent} 没有训练样本")
        )

    return issues


def normalize_text(text: str) -> str:
    return _normalize_for_identity(text)


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
        vocabulary=frozenset(vocabulary),
    )


def predict_intent(
    model: IntentClassifier,
    text: str,
    *,
    confidence_threshold: float = 0.45,
    margin_threshold: float = 0.10,
) -> dict[str, object]:
    del confidence_threshold, margin_threshold
    features = extract_features(text)
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
    return {
        "intent": candidates[0]["intent"],
        "confidence": confidence,
        "margin": confidence - runner_up,
        "candidates": candidates,
    }


def _normalize_for_identity(text: str) -> str:
    return "".join(character.lower() for character in text if character.isalnum())


def _issue(
    code: str, message: str, indexes: list[int] | None = None
) -> dict[str, object]:
    issue: dict[str, object] = {"code": code, "message": message}
    if indexes is not None:
        issue["indexes"] = indexes
    return issue
