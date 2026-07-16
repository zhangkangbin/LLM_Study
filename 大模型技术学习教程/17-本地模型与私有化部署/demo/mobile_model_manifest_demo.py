"""Validate the deployment contract for an Android GGUF model."""

from __future__ import annotations

import json
import re
from pathlib import Path


_MISSING = object()
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def load_manifest(path: Path | str) -> dict[str, object]:
    """Load a manifest as strict UTF-8 JSON without exposing its contents on errors."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("manifest must be UTF-8 encoded") from None

    try:
        value = json.loads(text, parse_constant=_reject_nonstandard_constant)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("manifest must contain valid JSON") from None

    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    return value


def _reject_nonstandard_constant(value: str) -> object:
    raise ValueError(f"nonstandard JSON constant: {value}")


def validate_manifest(manifest: object) -> list[dict[str, object]]:
    """Return deterministic schema issues without modifying *manifest*."""

    issues: list[dict[str, object]] = []
    if not isinstance(manifest, dict):
        _issue(issues, "invalid_type", "manifest must be an object", "$")
        return issues

    schema_version = _required(manifest, "schema_version", "$.schema_version", issues)
    if schema_version is not _MISSING:
        if type(schema_version) is not int:
            _issue(issues, "invalid_type", "schema_version must be an integer", "$.schema_version")
        elif schema_version != 1:
            _issue(issues, "unsupported_value", "only schema_version 1 is supported", "$.schema_version")

    _validate_nonempty_string(manifest, "model_id", "$.model_id", issues)
    _validate_supported_string(manifest, "runtime", "llama.cpp", "$.runtime", issues)
    _validate_supported_string(manifest, "format", "gguf", "$.format", issues)
    _validate_nonempty_string(manifest, "quantization", "$.quantization", issues)

    file_section = _required_object(manifest, "file", "$.file", issues)
    if file_section is not None:
        _validate_nonempty_string(file_section, "name", "$.file.name", issues)
        _validate_positive_integer(file_section, "size_bytes", "$.file.size_bytes", issues)
        _validate_digest(file_section, "sha256", _SHA256_PATTERN, "invalid_sha256", "$.file.sha256", issues)

    context = _required_object(manifest, "context", "$.context", issues)
    if context is not None:
        max_context = _validate_positive_integer(
            context, "max_context_tokens", "$.context.max_context_tokens", issues
        )
        max_output = _validate_positive_integer(
            context, "max_output_tokens", "$.context.max_output_tokens", issues
        )
        if max_context is not None and max_output is not None and max_output > max_context:
            _issue(
                issues,
                "limit_exceeded",
                "max_output_tokens must not exceed max_context_tokens",
                "$.context.max_output_tokens",
            )

    device = _required_object(manifest, "device_requirements", "$.device_requirements", issues)
    if device is not None:
        _validate_abis(device, issues)
        android_api = _validate_integer(
            device, "min_android_api", "$.device_requirements.min_android_api", issues
        )
        if android_api is not None and android_api < 28:
            _issue(
                issues,
                "invalid_value",
                "min_android_api must be at least 28",
                "$.device_requirements.min_android_api",
            )
        _validate_positive_integer(
            device, "min_memory_mb", "$.device_requirements.min_memory_mb", issues
        )
        _validate_positive_integer(
            device,
            "min_free_storage_mb",
            "$.device_requirements.min_free_storage_mb",
            issues,
        )

    provenance = _required_object(manifest, "provenance", "$.provenance", issues)
    if provenance is not None:
        _validate_nonempty_string(provenance, "base_model", "$.provenance.base_model", issues)
        _validate_digest(
            provenance,
            "base_revision",
            _COMMIT_PATTERN,
            "invalid_commit",
            "$.provenance.base_revision",
            issues,
        )
        _validate_digest(
            provenance,
            "adapter_sha256",
            _SHA256_PATTERN,
            "invalid_sha256",
            "$.provenance.adapter_sha256",
            issues,
        )
        _validate_digest(
            provenance,
            "llama_cpp_commit",
            _COMMIT_PATTERN,
            "invalid_commit",
            "$.provenance.llama_cpp_commit",
            issues,
        )

    licenses = _required_object(manifest, "licenses", "$.licenses", issues)
    if licenses is not None:
        _validate_reviewed_flag(licenses, "model_reviewed", "$.licenses.model_reviewed", issues)
        _validate_reviewed_flag(licenses, "data_reviewed", "$.licenses.data_reviewed", issues)

    verification = _required_object(manifest, "verification", "$.verification", issues)
    if verification is not None:
        _validate_bool(
            verification,
            "desktop_smoke_tested",
            "$.verification.desktop_smoke_tested",
            issues,
        )
        _validate_bool(
            verification,
            "device_smoke_tested",
            "$.verification.device_smoke_tested",
            issues,
        )

    return sorted(issues, key=lambda issue: (str(issue["path"]), str(issue["code"])))


def _issue(issues: list[dict[str, object]], code: str, message: str, path: str) -> None:
    issues.append({"code": code, "message": message, "path": path})


def _required(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> object:
    if key not in parent:
        _issue(issues, "missing_required", f"required field {key} is missing", path)
        return _MISSING
    return parent[key]


def _required_object(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> dict[object, object] | None:
    value = _required(parent, key, path, issues)
    if value is _MISSING:
        return None
    if not isinstance(value, dict):
        _issue(issues, "invalid_type", f"{key} must be an object", path)
        return None
    return value


def _validate_nonempty_string(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> str | None:
    value = _required(parent, key, path, issues)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        _issue(issues, "invalid_type", f"{key} must be a string", path)
        return None
    if not value.strip():
        _issue(issues, "invalid_value", f"{key} must not be empty", path)
        return None
    return value


def _validate_supported_string(
    parent: dict[object, object],
    key: str,
    supported: str,
    path: str,
    issues: list[dict[str, object]],
) -> None:
    value = _required(parent, key, path, issues)
    if value is _MISSING:
        return
    if not isinstance(value, str):
        _issue(issues, "invalid_type", f"{key} must be a string", path)
    elif value != supported:
        _issue(issues, "unsupported_value", f"only {supported} is supported", path)


def _validate_integer(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> int | None:
    value = _required(parent, key, path, issues)
    if value is _MISSING:
        return None
    if type(value) is not int:
        _issue(issues, "invalid_type", f"{key} must be an integer", path)
        return None
    return value


def _validate_positive_integer(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> int | None:
    value = _validate_integer(parent, key, path, issues)
    if value is not None and value <= 0:
        _issue(issues, "invalid_value", f"{key} must be positive", path)
        return None
    return value


def _validate_digest(
    parent: dict[object, object],
    key: str,
    pattern: re.Pattern[str],
    invalid_code: str,
    path: str,
    issues: list[dict[str, object]],
) -> None:
    value = _required(parent, key, path, issues)
    if value is _MISSING:
        return
    if not isinstance(value, str):
        _issue(issues, "invalid_type", f"{key} must be a string", path)
    elif pattern.fullmatch(value) is None:
        length = 64 if pattern is _SHA256_PATTERN else 40
        _issue(
            issues,
            invalid_code,
            f"{key} must be exactly {length} lowercase hexadecimal characters",
            path,
        )


def _validate_abis(device: dict[object, object], issues: list[dict[str, object]]) -> None:
    path = "$.device_requirements.abis"
    value = _required(device, "abis", path, issues)
    if value is _MISSING:
        return
    if not isinstance(value, list):
        _issue(issues, "invalid_type", "abis must be a list", path)
    elif not value:
        _issue(issues, "invalid_value", "abis must contain at least one ABI", path)
    elif any(not isinstance(abi, str) for abi in value):
        _issue(issues, "invalid_type", "every ABI must be a string", path)
    elif any(not abi.strip() for abi in value):
        _issue(issues, "invalid_value", "every ABI must be nonempty", path)


def _validate_reviewed_flag(
    licenses: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> None:
    value = _required(licenses, key, path, issues)
    if value is _MISSING:
        return
    if type(value) is not bool:
        _issue(issues, "invalid_type", f"{key} must be a boolean", path)
    elif not value:
        _issue(issues, "must_be_true", f"{key} must be true before deployment", path)


def _validate_bool(
    parent: dict[object, object], key: str, path: str, issues: list[dict[str, object]]
) -> None:
    value = _required(parent, key, path, issues)
    if value is not _MISSING and type(value) is not bool:
        _issue(issues, "invalid_type", f"{key} must be a boolean", path)
