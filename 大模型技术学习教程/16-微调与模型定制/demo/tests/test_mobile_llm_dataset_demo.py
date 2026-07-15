import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from mobile_llm_dataset_demo import (  # noqa: E402
    VALID_ROLES,
    VALID_SPLITS,
    load_conversations,
    summarize_conversations,
    validate_conversations,
)


def make_messages(tag):
    return [
        {"role": "system", "content": f"你是{tag}离线助手"},
        {"role": "user", "content": f"如何查询{tag}订单"},
        {"role": "assistant", "content": f"请打开{tag}订单页面。"},
    ]


def make_row(row_id, split, tag):
    return {"id": row_id, "split": split, "messages": make_messages(tag)}


def valid_rows():
    return [
        make_row("train-001", "train", "训练"),
        make_row("validation-001", "validation", "验证"),
        make_row("test-001", "test", "测试"),
    ]


def diagnostics(issues):
    return [(issue["code"], tuple(issue["indexes"])) for issue in issues]


class MobileLlmDatasetLoadTest(unittest.TestCase):
    def test_load_reads_nonblank_utf8_jsonl_objects_into_a_list(self):
        expected = [
            make_row("train-001", "train", "甲"),
            make_row("test-001", "test", "乙"),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "对话.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(expected[0], ensure_ascii=False),
                        "  \t  ",
                        json.dumps(expected[1], ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )
            actual = load_conversations(path)

        self.assertIsInstance(actual, list)
        self.assertEqual(expected, actual)

    def test_load_reports_the_physical_source_line_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.jsonl"
            path.write_text("{}\n  \nnot-json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"source line 3"):
                load_conversations(path)

    def test_load_reports_source_line_for_non_object_duplicate_key_and_nonfinite_number(self):
        cases = {
            "non_object": "[]",
            "duplicate_key": '{"id":"first","id":"second"}',
            "nan": '{"value":NaN}',
            "positive_infinity": '{"value":Infinity}',
            "negative_infinity": '{"value":-Infinity}',
        }
        for name, invalid_line in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                path = Path(temporary_directory) / "invalid.jsonl"
                path.write_text(f"\n{invalid_line}\n", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, r"source line 2"):
                    load_conversations(path)

    def test_load_rejects_duplicate_keys_inside_nested_objects(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.jsonl"
            path.write_text(
                '{"messages":[{"role":"user","role":"assistant"}]}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, r"source line 1"):
                load_conversations(path)

    def test_load_reports_source_line_for_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid-utf8.jsonl"
            path.write_bytes(b"{}\n\xff\n")

            with self.assertRaisesRegex(ValueError, r"source line 2"):
                load_conversations(path)

    def test_load_preserves_file_io_errors(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing.jsonl"

            with self.assertRaises(FileNotFoundError):
                load_conversations(missing)


class MobileLlmDatasetValidationTest(unittest.TestCase):
    def test_validation_constants_define_the_public_contract(self):
        self.assertEqual(frozenset({"train", "validation", "test"}), VALID_SPLITS)
        self.assertEqual(frozenset({"system", "user", "assistant"}), VALID_ROLES)

    def test_valid_rows_with_multiple_turns_have_no_issues(self):
        rows = valid_rows()
        rows[0]["messages"].extend(
            [
                {"role": "user", "content": "还可以取消吗？"},
                {"role": "assistant", "content": "未发货时可以申请取消。"},
            ]
        )

        self.assertEqual([], validate_conversations(rows))

    def test_missing_blank_and_wrong_type_ids_are_reported_separately(self):
        cases = [
            ("missing", None, "missing_id"),
            ("blank", "  ", "invalid_id"),
            ("wrong_type", 7, "invalid_id"),
        ]
        for name, value, expected_code in cases:
            with self.subTest(name=name):
                rows = valid_rows()
                if value is None:
                    del rows[0]["id"]
                else:
                    rows[0]["id"] = value

                self.assertIn((expected_code, (0,)), diagnostics(validate_conversations(rows)))

    def test_duplicate_ids_report_all_indexes_in_ascending_order(self):
        rows = valid_rows()
        rows[2]["id"] = rows[0]["id"]
        rows.append(make_row(rows[0]["id"], "train", "补充"))

        self.assertIn(
            ("duplicate_id", (0, 2, 3)),
            diagnostics(validate_conversations(rows)),
        )

    def test_invalid_and_empty_splits_are_reported(self):
        for split in ("", "dev", None, 3):
            with self.subTest(split=split):
                rows = valid_rows()
                rows[1]["split"] = split

                self.assertIn(
                    ("invalid_split", (1,)),
                    diagnostics(validate_conversations(rows)),
                )

    def test_each_empty_split_has_one_deterministic_issue(self):
        issues = validate_conversations([])

        self.assertEqual(
            [
                ("empty_split", "split 'train' must contain at least one conversation", []),
                (
                    "empty_split",
                    "split 'validation' must contain at least one conversation",
                    [],
                ),
                ("empty_split", "split 'test' must contain at least one conversation", []),
            ],
            [
                (issue["code"], issue["message"], issue["indexes"])
                for issue in issues
            ],
        )

    def test_row_and_message_objects_use_exact_keys(self):
        rows = valid_rows()
        rows[0]["note"] = "not part of the contract"
        rows[1]["messages"][0]["name"] = "not part of the contract"

        self.assertIn(("unexpected_fields", (0,)), diagnostics(validate_conversations(rows)))
        self.assertIn(
            ("unexpected_message_fields", (1,)),
            diagnostics(validate_conversations(rows)),
        )

    def test_malformed_rows_are_collected_without_key_or_type_errors(self):
        rows = valid_rows()
        rows.extend(
            [
                None,
                {"id": "train-002", "split": "train"},
                {
                    "id": "train-003",
                    "split": "train",
                    "messages": ["not an object"],
                },
                {
                    "id": "train-004",
                    "split": "train",
                    "messages": [{"role": "user"}],
                },
            ]
        )

        issues = validate_conversations(rows)

        self.assertIn(("invalid_row", (3,)), diagnostics(issues))
        self.assertIn(("invalid_messages", (4,)), diagnostics(issues))
        self.assertIn(("invalid_message", (5,)), diagnostics(issues))
        self.assertIn(("invalid_content", (6,)), diagnostics(issues))

    def test_invalid_role_is_distinct_from_role_order(self):
        rows = valid_rows()
        rows[0]["messages"][1]["role"] = "tool"

        row_zero_codes = {
            issue["code"] for issue in validate_conversations(rows) if issue["indexes"] == [0]
        }

        self.assertIn("invalid_role", row_zero_codes)
        self.assertNotIn("invalid_role_order", row_zero_codes)
        self.assertNotIn("missing_final_assistant", row_zero_codes)

    def test_invalid_starting_role_is_reported_as_role_order(self):
        rows = valid_rows()
        rows[0]["messages"] = [{"role": "assistant", "content": "直接回答"}]

        self.assertIn(
            ("invalid_role_order", (0,)),
            diagnostics(validate_conversations(rows)),
        )

    def test_system_role_is_only_allowed_once_at_the_start(self):
        rows = valid_rows()
        rows[0]["messages"].insert(2, {"role": "system", "content": "新的系统指令"})

        self.assertIn(
            ("invalid_role_order", (0,)),
            diagnostics(validate_conversations(rows)),
        )

    def test_empty_content_has_a_stable_code(self):
        rows = valid_rows()
        rows[0]["messages"][1]["content"] = " \t\n "

        self.assertIn(("empty_content", (0,)), diagnostics(validate_conversations(rows)))

    def test_missing_final_assistant_does_not_create_a_role_order_cascade(self):
        rows = valid_rows()
        rows[0]["messages"] = [{"role": "user", "content": "请回答"}]

        row_zero_codes = {
            issue["code"] for issue in validate_conversations(rows) if issue["indexes"] == [0]
        }

        self.assertEqual({"missing_final_assistant"}, row_zero_codes)

    def test_consecutive_roles_report_one_role_order_issue(self):
        rows = valid_rows()
        rows[0]["messages"] = [
            {"role": "user", "content": "问题一"},
            {"role": "user", "content": "问题二"},
            {"role": "assistant", "content": "回答"},
        ]

        matching = [
            issue
            for issue in validate_conversations(rows)
            if issue["code"] == "invalid_role_order" and issue["indexes"] == [0]
        ]
        self.assertEqual(1, len(matching))

    def test_total_python_character_length_is_bounded_inclusively(self):
        rows = valid_rows()
        total = sum(len(message["content"]) for message in rows[0]["messages"])

        self.assertNotIn(
            ("excessive_length", (0,)),
            diagnostics(validate_conversations(rows, max_characters=total)),
        )
        self.assertIn(
            ("excessive_length", (0,)),
            diagnostics(validate_conversations(rows, max_characters=total - 1)),
        )

    def test_max_characters_requires_a_positive_non_boolean_integer(self):
        for value in (0, -1, True, 1.5, "4096", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    validate_conversations(valid_rows(), max_characters=value)

    def test_exact_duplicate_ignores_id_and_split(self):
        rows = valid_rows()
        rows.append(
            {
                "id": "train-002",
                "split": "train",
                "messages": copy.deepcopy(rows[0]["messages"]),
            }
        )

        self.assertIn(
            ("exact_duplicate", (0, 3)),
            diagnostics(validate_conversations(rows)),
        )

    def test_normalized_duplicate_detects_case_fullwidth_punctuation_and_whitespace(self):
        rows = valid_rows()
        rows[0]["messages"] = [
            {"role": "user", "content": "Track  ORDER！"},
            {"role": "assistant", "content": "Open，Orders Page。"},
        ]
        rows[1]["messages"] = [
            {"role": "user", "content": "track\torder"},
            {"role": "assistant", "content": "open orders-page"},
        ]

        self.assertIn(
            ("normalized_cross_split_duplicate", (0, 1)),
            diagnostics(validate_conversations(rows)),
        )

    def test_normalized_duplicate_preserves_message_turn_boundaries(self):
        rows = valid_rows()
        rows[0]["messages"] = [
            {"role": "user", "content": "ab"},
            {"role": "assistant", "content": "c"},
        ]
        rows[1]["messages"] = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "bc"},
        ]

        self.assertNotIn(
            "normalized_cross_split_duplicate",
            [issue["code"] for issue in validate_conversations(rows)],
        )

    def test_exact_cross_split_duplicate_reports_both_codes_deterministically(self):
        rows = valid_rows()
        rows[1]["messages"] = copy.deepcopy(rows[0]["messages"])

        duplicate_diagnostics = [
            diagnostic
            for diagnostic in diagnostics(validate_conversations(rows))
            if diagnostic[0] in {"exact_duplicate", "normalized_cross_split_duplicate"}
        ]

        self.assertEqual(
            [
                ("exact_duplicate", (0, 1)),
                ("normalized_cross_split_duplicate", (0, 1)),
            ],
            duplicate_diagnostics,
        )

    def test_issues_have_exact_keys_sorted_order_and_detached_indexes(self):
        rows = valid_rows()
        rows[0]["id"] = "same"
        rows[1]["id"] = "same"
        rows[1]["messages"] = copy.deepcopy(rows[0]["messages"])

        issues = validate_conversations(rows)
        before_mutation = copy.deepcopy(issues)
        rows.clear()

        self.assertEqual(before_mutation, issues)
        self.assertTrue(all(set(issue) == {"code", "message", "indexes"} for issue in issues))
        self.assertTrue(all(issue["indexes"] == sorted(issue["indexes"]) for issue in issues))
        self.assertEqual(
            sorted(issues, key=lambda issue: (issue["code"], tuple(issue["indexes"]))),
            issues,
        )

    def test_validation_does_not_mutate_caller_rows(self):
        rows = valid_rows()
        snapshot = copy.deepcopy(rows)

        validate_conversations(rows)

        self.assertEqual(snapshot, rows)


class MobileLlmDatasetSummaryTest(unittest.TestCase):
    def test_empty_summary_has_all_fixed_keys_and_zero_character_values(self):
        self.assertEqual(
            {
                "split_counts": {"train": 0, "validation": 0, "test": 0},
                "total_conversations": 0,
                "total_messages": 0,
                "characters": {"min": 0, "max": 0, "mean": 0},
            },
            summarize_conversations([]),
        )

    def test_summary_counts_splits_messages_and_raw_python_characters(self):
        rows = [
            {
                "id": "train-001",
                "split": "train",
                "messages": [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "ok"},
                ],
            },
            {
                "id": "test-001",
                "split": "test",
                "messages": [{"role": "assistant", "content": "四个字符"}],
            },
        ]

        self.assertEqual(
            {
                "split_counts": {"train": 1, "validation": 0, "test": 1},
                "total_conversations": 2,
                "total_messages": 3,
                "characters": {"min": 2, "max": 4, "mean": 8 / 3},
            },
            summarize_conversations(rows),
        )

    def test_summary_accepts_structurally_valid_empty_message_arrays(self):
        rows = [{"id": "train-001", "split": "train", "messages": []}]

        self.assertEqual(
            {"min": 0, "max": 0, "mean": 0},
            summarize_conversations(rows)["characters"],
        )

    def test_summary_rejects_malformed_structure_with_a_clear_value_error(self):
        malformed_rows = [
            [None],
            [{"id": "x", "split": "dev", "messages": []}],
            [{"id": "x", "split": "train", "messages": "not a list"}],
            [{"id": "x", "split": "train", "messages": [None]}],
            [
                {
                    "id": "x",
                    "split": "train",
                    "messages": [{"role": "user", "content": 3}],
                }
            ],
        ]
        for rows in malformed_rows:
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(ValueError, r"row 0"):
                    summarize_conversations(rows)

    def test_summary_does_not_mutate_caller_rows(self):
        rows = valid_rows()
        snapshot = copy.deepcopy(rows)

        summarize_conversations(rows)

        self.assertEqual(snapshot, rows)


if __name__ == "__main__":
    unittest.main()
