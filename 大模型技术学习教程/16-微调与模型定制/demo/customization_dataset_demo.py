from __future__ import annotations

import argparse
import json
from typing import Sequence


def validate_training_examples(examples: Sequence[dict[str, str]]) -> dict[str, object]:
    invalid_indexes = [
        index
        for index, example in enumerate(examples)
        if not example.get("input") or not example.get("output")
    ]
    return {
        "valid": not invalid_indexes,
        "count": len(examples),
        "invalid_indexes": invalid_indexes,
    }


def split_examples(
    examples: Sequence[dict[str, str]],
    *,
    validation_ratio: float = 0.2,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not 0 < validation_ratio < 1:
        raise ValueError("validation_ratio must be between 0 and 1")
    validation_count = max(1, round(len(examples) * validation_ratio)) if examples else 0
    split_index = len(examples) - validation_count
    return list(examples[:split_index]), list(examples[split_index:])


def to_jsonl_lines(examples: Sequence[dict[str, str]]) -> list[str]:
    return [json.dumps(example, ensure_ascii=False, separators=(",", ":")) for example in examples]


def choose_customization_strategy(
    *,
    needs_private_knowledge: bool,
    needs_style_consistency: bool,
    has_verified_training_data: bool,
) -> dict[str, object]:
    if needs_private_knowledge:
        return {
            "strategy": "rag",
            "reason": "事实知识、业务文档和经常变化的数据优先放进检索链路。",
        }
    if needs_style_consistency and has_verified_training_data:
        return {
            "strategy": "fine_tuning_or_adapter",
            "reason": "稳定风格和可验证样例更适合模型定制，但要先确认平台可用性。",
        }
    return {
        "strategy": "prompt_engineering",
        "reason": "没有足够高质量样例前，先用提示词、few-shot 和结构化输出优化。",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="微调与模型定制数据集 Demo")
    parser.add_argument("--strategy", choices=["rag", "style", "prompt"], default="rag")
    args = parser.parse_args(argv)

    examples = [
        {"input": "把这句话改成客服口吻：订单发出去了", "output": "您的订单已经发出，请留意物流更新。"},
        {"input": "把这句话改成客服口吻：退款好了", "output": "您的退款已处理完成，请关注到账通知。"},
    ]
    train, validation = split_examples(examples, validation_ratio=0.5)
    decision = choose_customization_strategy(
        needs_private_knowledge=args.strategy == "rag",
        needs_style_consistency=args.strategy == "style",
        has_verified_training_data=args.strategy == "style",
    )
    print(
        json.dumps(
            {
                "validation": validate_training_examples(examples),
                "train": train,
                "validation_set": validation,
                "jsonl": to_jsonl_lines(examples),
                "decision": decision,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
