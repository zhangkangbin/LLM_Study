"""Chat JSONL loading, validation, and summary helpers for the mobile LLM tutorial."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any


VALID_SPLITS = frozenset({"train", "validation", "test"})
VALID_ROLES = frozenset({"system", "user", "assistant"})

_SPLIT_ORDER = ("train", "validation", "test")
_ROW_FIELDS = frozenset({"id", "split", "messages"})
_MESSAGE_FIELDS = frozenset({"role", "content"})


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


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
                )
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
