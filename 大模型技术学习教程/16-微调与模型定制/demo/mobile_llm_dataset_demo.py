"""Chat JSONL loading, validation, and summary helpers for the mobile LLM tutorial."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NoReturn, Sequence, TextIO


VALID_SPLITS = frozenset({"train", "validation", "test"})
VALID_ROLES = frozenset({"system", "user", "assistant"})

_SPLIT_ORDER = ("train", "validation", "test")
_ROW_FIELDS = frozenset({"id", "split", "messages"})
_MESSAGE_FIELDS = frozenset({"role", "content"})
_DEFAULT_DATA_PATH = Path(__file__).with_name("sample_mobile_llm_chat.jsonl")
_DEFAULT_MAX_CHARACTERS = 4096
_SOURCE_LINE_PATTERN = re.compile(r"\bsource line (\d+):")


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json_number(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _parse_finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        _reject_nonfinite_json_number(value)
    return number


def _reject_isolated_unicode_surrogates(value: object) -> None:
    """Reject surrogate code points anywhere in a decoded JSON tree."""

    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            for character in current:
                code_point = ord(character)
                if 0xD800 <= code_point <= 0xDFFF:
                    raise ValueError(
                        f"isolated Unicode surrogate U+{code_point:04X} is not allowed"
                    )
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def load_conversations(path: str | Path) -> list[dict[str, Any]]:
    """Load nonblank UTF-8 JSONL objects and report their physical source line."""

    rows: list[dict[str, Any]] = []
    with Path(path).open("rb") as source:
        for line_number, raw_line in enumerate(source, start=1):
            try:
                line = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ValueError(
                    f"source line {line_number}: invalid UTF-8: {error.reason}"
                ) from error

            if not line.strip():
                continue

            try:
                row = json.loads(
                    line,
                    object_pairs_hook=_json_object_without_duplicate_keys,
                    parse_constant=_reject_nonfinite_json_number,
                    parse_float=_parse_finite_json_float,
                )
                _reject_isolated_unicode_surrogates(row)
            except ValueError as error:
                raise ValueError(f"source line {line_number}: {error}") from error

            if not isinstance(row, dict):
                raise ValueError(
                    f"source line {line_number}: each nonblank JSONL value must be an object"
                )
            rows.append(row)
    return rows


def _issue(code: str, message: str, indexes: Iterable[int]) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "indexes": sorted(set(indexes)),
    }


def _materialize_rows(rows: Iterable[object]) -> list[object]:
    try:
        return list(rows)
    except TypeError as error:
        raise ValueError("rows must be an iterable of conversation objects") from error


def _describe_fields(fields: set[object]) -> str:
    return ", ".join(sorted(repr(field) for field in fields))


def _normalized_content(content: str) -> str:
    """Normalize one message without erasing role or turn boundaries.

    NFKC is applied first, then Python's whole-string ``lower()``. Unicode
    whitespace and characters in a punctuation category are removed. Symbols
    and all other characters remain significant.
    """

    lowered = unicodedata.normalize("NFKC", content).lower()
    return "".join(
        character
        for character in lowered
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _validate_messages(
    messages: list[object],
    *,
    row_index: int,
    max_characters: int,
) -> tuple[list[dict[str, object]], tuple[tuple[str, str], ...] | None]:
    issues: list[dict[str, object]] = []
    invalid_message_positions: list[int] = []
    unexpected_field_positions: list[int] = []
    invalid_role_positions: list[int] = []
    invalid_content_positions: list[int] = []
    empty_content_positions: list[int] = []
    empty_normalized_content_positions: list[int] = []
    roles: list[str] = []
    exact_messages: list[tuple[str, str]] = []
    total_characters = 0

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            invalid_message_positions.append(message_index)
            continue

        extra_fields = set(message) - _MESSAGE_FIELDS
        if extra_fields:
            unexpected_field_positions.append(message_index)

        role = message.get("role")
        role_is_valid = isinstance(role, str) and role in VALID_ROLES
        if not role_is_valid:
            invalid_role_positions.append(message_index)
        else:
            roles.append(role)

        content = message.get("content")
        content_is_valid = isinstance(content, str)
        if not content_is_valid:
            invalid_content_positions.append(message_index)
        else:
            total_characters += len(content)
            if not content.strip():
                empty_content_positions.append(message_index)
            elif not _normalized_content(content):
                empty_normalized_content_positions.append(message_index)

        if (
            role_is_valid
            and content_is_valid
            and content.strip()
            and not extra_fields
            and set(message) == _MESSAGE_FIELDS
        ):
            exact_messages.append((role, content))

    if invalid_message_positions:
        issues.append(
            _issue(
                "invalid_message",
                f"row {row_index} messages at positions {invalid_message_positions} must be objects",
                [row_index],
            )
        )
    if unexpected_field_positions:
        issues.append(
            _issue(
                "unexpected_message_fields",
                f"row {row_index} messages at positions {unexpected_field_positions} must use exact keys role/content",
                [row_index],
            )
        )
    if invalid_role_positions:
        issues.append(
            _issue(
                "invalid_role",
                f"row {row_index} messages at positions {invalid_role_positions} require a valid role",
                [row_index],
            )
        )
    if invalid_content_positions:
        issues.append(
            _issue(
                "invalid_content",
                f"row {row_index} messages at positions {invalid_content_positions} require string content",
                [row_index],
            )
        )
    if empty_content_positions:
        issues.append(
            _issue(
                "empty_content",
                f"row {row_index} messages at positions {empty_content_positions} require nonblank content",
                [row_index],
            )
        )
    if empty_normalized_content_positions:
        issues.append(
            _issue(
                "empty_normalized_content",
                f"row {row_index} messages at positions {empty_normalized_content_positions} require content that remains after normalization",
                [row_index],
            )
        )
    if total_characters > max_characters:
        issues.append(
            _issue(
                "excessive_length",
                f"row {row_index} has {total_characters} characters; maximum is {max_characters}",
                [row_index],
            )
        )

    all_messages_have_valid_roles = (
        not invalid_message_positions
        and not invalid_role_positions
        and len(roles) == len(messages)
    )
    role_order_is_valid = False
    if all_messages_have_valid_roles:
        dialogue_start = 1 if roles[0] == "system" else 0
        dialogue_roles = roles[dialogue_start:]
        role_order_is_valid = bool(dialogue_roles) and all(
            role == ("user" if offset % 2 == 0 else "assistant")
            for offset, role in enumerate(dialogue_roles)
        )
        if not role_order_is_valid:
            issues.append(
                _issue(
                    "invalid_role_order",
                    f"row {row_index} permits one leading system message followed by alternating user/assistant messages",
                    [row_index],
                )
            )
        if roles[-1] != "assistant":
            issues.append(
                _issue(
                    "missing_final_assistant",
                    f"row {row_index} must end with an assistant message",
                    [row_index],
                )
            )

    message_schema_is_valid = (
        len(exact_messages) == len(messages)
        and not unexpected_field_positions
        and not invalid_message_positions
        and not invalid_content_positions
        and not empty_content_positions
        and not empty_normalized_content_positions
    )
    conversation_key = (
        tuple(exact_messages)
        if message_schema_is_valid
        and role_order_is_valid
        and roles[-1] == "assistant"
        else None
    )
    return issues, conversation_key


def validate_conversations(
    rows: Iterable[object],
    *,
    max_characters: int = 4096,
) -> list[dict[str, object]]:
    """Return deterministic issues for Chat JSONL rows without mutating them."""

    if (
        not isinstance(max_characters, int)
        or isinstance(max_characters, bool)
        or max_characters <= 0
    ):
        raise ValueError("max_characters must be a positive integer")

    materialized_rows = _materialize_rows(rows)
    issues: list[dict[str, object]] = []
    id_indexes: dict[str, list[int]] = {}
    split_counts = {split: 0 for split in _SPLIT_ORDER}
    duplicate_candidates: list[
        tuple[int, str, tuple[tuple[str, str], ...]]
    ] = []

    for row_index, row in enumerate(materialized_rows):
        if not isinstance(row, dict):
            issues.append(
                _issue(
                    "invalid_row",
                    f"row {row_index} must be an object",
                    [row_index],
                )
            )
            continue

        extra_fields = set(row) - _ROW_FIELDS
        if extra_fields:
            issues.append(
                _issue(
                    "unexpected_fields",
                    f"row {row_index} has unexpected fields: {_describe_fields(extra_fields)}",
                    [row_index],
                )
            )

        row_id = row.get("id")
        id_is_valid = isinstance(row_id, str) and bool(row_id.strip())
        if "id" not in row:
            issues.append(
                _issue("missing_id", f"row {row_index} requires id", [row_index])
            )
        elif not id_is_valid:
            issues.append(
                _issue(
                    "invalid_id",
                    f"row {row_index} id must be a nonblank string",
                    [row_index],
                )
            )
        else:
            id_indexes.setdefault(row_id, []).append(row_index)

        split = row.get("split")
        split_is_valid = isinstance(split, str) and split in VALID_SPLITS
        if not split_is_valid:
            issues.append(
                _issue(
                    "invalid_split",
                    f"row {row_index} split must be one of train/validation/test",
                    [row_index],
                )
            )
        else:
            split_counts[split] += 1

        messages = row.get("messages")
        conversation_key: tuple[tuple[str, str], ...] | None = None
        if not isinstance(messages, list) or not messages:
            issues.append(
                _issue(
                    "invalid_messages",
                    f"row {row_index} messages must be a nonempty array",
                    [row_index],
                )
            )
        else:
            message_issues, conversation_key = _validate_messages(
                messages,
                row_index=row_index,
                max_characters=max_characters,
            )
            issues.extend(message_issues)

        row_uses_exact_fields = set(row) == _ROW_FIELDS
        if (
            row_uses_exact_fields
            and id_is_valid
            and split_is_valid
            and conversation_key is not None
        ):
            duplicate_candidates.append((row_index, split, conversation_key))

    for row_id, indexes in id_indexes.items():
        if len(indexes) > 1:
            issues.append(
                _issue(
                    "duplicate_id",
                    f"id {row_id!r} is repeated at indexes {indexes}",
                    indexes,
                )
            )

    for split in _SPLIT_ORDER:
        if split_counts[split] == 0:
            issues.append(
                _issue(
                    "empty_split",
                    f"split {split!r} must contain at least one conversation",
                    [],
                )
            )

    exact_groups: dict[tuple[tuple[str, str], ...], list[int]] = {}
    normalized_groups: dict[
        tuple[tuple[str, str], ...], list[tuple[int, str]]
    ] = {}
    for row_index, split, conversation_key in duplicate_candidates:
        exact_groups.setdefault(conversation_key, []).append(row_index)
        normalized_key = tuple(
            (role, _normalized_content(content))
            for role, content in conversation_key
        )
        normalized_groups.setdefault(normalized_key, []).append((row_index, split))

    for indexes in exact_groups.values():
        if len(indexes) > 1:
            issues.append(
                _issue(
                    "exact_duplicate",
                    f"messages are exactly duplicated at indexes {indexes}",
                    indexes,
                )
            )

    for entries in normalized_groups.values():
        if len({split for _, split in entries}) > 1:
            indexes = [row_index for row_index, _ in entries]
            issues.append(
                _issue(
                    "normalized_cross_split_duplicate",
                    f"normalized messages cross splits at indexes {indexes}",
                    indexes,
                )
            )

    issues.sort(key=lambda issue: (issue["code"], tuple(issue["indexes"])))
    return issues


def summarize_conversations(rows: Iterable[object]) -> dict[str, object]:
    """Summarize structurally valid rows without requiring full validation.

    This function checks the exact row/message shape and field types itself. It
    intentionally does not enforce split coverage, uniqueness, role order, or
    nonempty message arrays, because those rules do not prevent a useful
    summary. Structural errors raise ``ValueError`` with a row index.
    """

    materialized_rows = _materialize_rows(rows)
    split_counts = {split: 0 for split in _SPLIT_ORDER}
    character_lengths: list[int] = []

    for row_index, row in enumerate(materialized_rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {row_index}: conversation must be an object")
        if set(row) != _ROW_FIELDS:
            raise ValueError(
                f"row {row_index}: conversation must use exact keys id/split/messages"
            )
        if not isinstance(row["id"], str) or not row["id"].strip():
            raise ValueError(f"row {row_index}: id must be a nonblank string")

        split = row["split"]
        if not isinstance(split, str) or split not in VALID_SPLITS:
            raise ValueError(
                f"row {row_index}: split must be one of train/validation/test"
            )
        split_counts[split] += 1

        messages = row["messages"]
        if not isinstance(messages, list):
            raise ValueError(f"row {row_index}: messages must be an array")
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ValueError(
                    f"row {row_index} message {message_index}: message must be an object"
                )
            if set(message) != _MESSAGE_FIELDS:
                raise ValueError(
                    f"row {row_index} message {message_index}: message must use exact keys role/content"
                )
            role = message["role"]
            if not isinstance(role, str) or role not in VALID_ROLES:
                raise ValueError(
                    f"row {row_index} message {message_index}: role is invalid"
                )
            content = message["content"]
            if not isinstance(content, str):
                raise ValueError(
                    f"row {row_index} message {message_index}: content must be a string"
                )
            character_lengths.append(len(content))

    if character_lengths:
        character_summary: dict[str, int | float] = {
            "min": min(character_lengths),
            "max": max(character_lengths),
            "mean": sum(character_lengths) / len(character_lengths),
        }
    else:
        character_summary = {"min": 0, "max": 0, "mean": 0}

    return {
        "split_counts": split_counts,
        "total_conversations": len(materialized_rows),
        "total_messages": len(character_lengths),
        "characters": character_summary,
    }


class _CliArgumentError(ValueError):
    """An argparse usage error that can be rendered as JSON."""


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _CliArgumentError(message)


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        description="Validate or summarize the mobile LLM Chat JSONL dataset."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate Chat JSONL data",
    )
    validate_parser.add_argument(
        "--data",
        type=Path,
        default=_DEFAULT_DATA_PATH,
        help="JSONL path (default: the sample beside this script)",
    )
    validate_parser.add_argument(
        "--max-characters",
        type=_positive_integer,
        default=_DEFAULT_MAX_CHARACTERS,
        help="positive per-conversation character limit (default: 4096)",
    )

    summarize_parser = subparsers.add_parser(
        "summarize",
        help="validate and summarize Chat JSONL data",
    )
    summarize_parser.add_argument(
        "--data",
        type=Path,
        default=_DEFAULT_DATA_PATH,
        help="JSONL path (default: the sample beside this script)",
    )
    return parser


def _write_json(payload: dict[str, object], stream: TextIO) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is not None:
        binary_stream.write(serialized.encode("utf-8"))
        binary_stream.flush()
    else:
        stream.write(serialized)
        stream.flush()


def _write_user_error(code: str, error: Exception) -> None:
    message = str(error) or error.__class__.__name__
    payload: dict[str, object] = {"error": code, "message": message}
    line_match = _SOURCE_LINE_PATTERN.search(message)
    if line_match is not None:
        payload["line"] = int(line_match.group(1))
    _write_json(payload, sys.stderr)


def _write_internal_error(_error: Exception) -> None:
    _write_user_error(
        "internal_error",
        RuntimeError("unexpected internal error"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standard-library CLI and return its process exit code."""

    try:
        arguments = _build_argument_parser().parse_args(argv)
    except _CliArgumentError as error:
        _write_user_error("argument_error", error)
        return 2

    try:
        rows = load_conversations(arguments.data)
    except ValueError as error:
        _write_user_error("invalid_data", error)
        return 2
    except OSError as error:
        _write_user_error("file_error", error)
        return 2
    except Exception as error:
        _write_internal_error(error)
        return 1

    try:
        max_characters = (
            arguments.max_characters
            if arguments.command == "validate"
            else _DEFAULT_MAX_CHARACTERS
        )
        issues = validate_conversations(rows, max_characters=max_characters)
        validation = {
            "valid": not issues,
            "count": len(rows),
            "issues": issues,
        }
        if issues:
            _write_json(validation, sys.stderr)
            return 2

        if arguments.command == "validate":
            _write_json(validation, sys.stdout)
        else:
            _write_json(summarize_conversations(rows), sys.stdout)
        return 0
    except Exception as error:
        _write_internal_error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
