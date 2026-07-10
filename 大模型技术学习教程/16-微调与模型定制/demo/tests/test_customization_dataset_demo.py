import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from customization_dataset_demo import (  # noqa: E402
    choose_customization_strategy,
    split_examples,
    to_jsonl_lines,
    validate_training_examples,
)


class CustomizationDatasetDemoTest(unittest.TestCase):
    def test_validate_training_examples_finds_missing_fields(self):
        report = validate_training_examples(
            [
                {"input": "问候", "output": "你好"},
                {"input": "缺少输出"},
            ]
        )

        self.assertFalse(report["valid"])
        self.assertEqual([1], report["invalid_indexes"])

    def test_split_examples_uses_deterministic_validation_tail(self):
        train, validation = split_examples(
            [{"input": str(index), "output": str(index)} for index in range(10)],
            validation_ratio=0.2,
        )

        self.assertEqual(8, len(train))
        self.assertEqual(["8", "9"], [item["input"] for item in validation])

    def test_jsonl_conversion_keeps_one_example_per_line(self):
        lines = to_jsonl_lines([{"input": "a", "output": "b"}, {"input": "c", "output": "d"}])

        self.assertEqual(2, len(lines))
        self.assertTrue(all(line.startswith("{") and line.endswith("}") for line in lines))

    def test_strategy_prefers_rag_for_factual_knowledge(self):
        decision = choose_customization_strategy(
            needs_private_knowledge=True,
            needs_style_consistency=False,
            has_verified_training_data=False,
        )

        self.assertEqual("rag", decision["strategy"])


if __name__ == "__main__":
    unittest.main()
