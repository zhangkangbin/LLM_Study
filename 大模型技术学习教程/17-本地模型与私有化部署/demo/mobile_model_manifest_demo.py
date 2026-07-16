"""Validate the deployment contract for an Android GGUF model."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_MISSING = object()
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_ZERO_SHA256 = "0" * 64
_REMOTE_BASE = "/data/local/tmp"
_SHELL_METACHAR_PATTERN = re.compile(r"[;&|`$><*?!()\[\]{}'\"~]")


@dataclass(frozen=True)
class DeviceFacts:
    """Resource facts reported by one Android device."""

    abi: str
    android_api: int
    memory_mb: int
    free_storage_mb: int


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


def validate_manifest(
    manifest: object, *, allow_example: bool = False
) -> list[dict[str, object]]:
    """Return deterministic schema issues without modifying *manifest*."""

    issues: list[dict[str, object]] = []
    if not isinstance(manifest, dict):
        _issue(issues, "invalid_type", "manifest must be an object", "$")
        return issues

    example_only = False
    if "example_only" in manifest:
        example_value = manifest["example_only"]
        if type(example_value) is not bool:
            _issue(
                issues,
                "invalid_type",
                "example_only must be a boolean",
                "$.example_only",
            )
        else:
            example_only = example_value
            if example_only and not allow_example:
                _issue(
                    issues,
                    "example_not_allowed",
                    "example manifests require explicit permission",
                    "$.example_only",
                )

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
        size_bytes = _validate_integer(file_section, "size_bytes", "$.file.size_bytes", issues)
        if size_bytes is not None:
            if example_only:
                if size_bytes != 0:
                    _issue(
                        issues,
                        "example_placeholder_required",
                        "example size_bytes must be zero",
                        "$.file.size_bytes",
                    )
            elif size_bytes <= 0:
                _issue(
                    issues,
                    "invalid_value",
                    "size_bytes must be positive",
                    "$.file.size_bytes",
                )
        _validate_digest(file_section, "sha256", _SHA256_PATTERN, "invalid_sha256", "$.file.sha256", issues)
        sha256_value = file_section.get("sha256", _MISSING)
        if isinstance(sha256_value, str) and _SHA256_PATTERN.fullmatch(sha256_value):
            if example_only and sha256_value != _ZERO_SHA256:
                _issue(
                    issues,
                    "example_placeholder_required",
                    "example sha256 must be the zero placeholder",
                    "$.file.sha256",
                )
            elif not example_only and sha256_value == _ZERO_SHA256:
                _issue(
                    issues,
                    "placeholder_not_allowed",
                    "zero sha256 is only allowed for an example manifest",
                    "$.file.sha256",
                )

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
        if example_only:
            for key in ("desktop_smoke_tested", "device_smoke_tested"):
                if verification.get(key) is True:
                    _issue(
                        issues,
                        "example_must_be_unverified",
                        f"example {key} must be false",
                        f"$.verification.{key}",
                    )

    return sorted(issues, key=lambda issue: (str(issue["path"]), str(issue["code"])))


def verify_model_file(
    manifest: object, path: Path | str
) -> list[dict[str, object]]:
    """Stream and verify a real model file against a non-example manifest."""

    issues = validate_manifest(manifest, allow_example=True)
    if issues:
        return issues
    assert isinstance(manifest, dict)
    if manifest.get("example_only") is True:
        return [
            {
                "code": "example_not_verifiable",
                "message": "example manifests cannot verify model files",
                "path": "$.example_only",
            }
        ]

    model_path = Path(path)
    try:
        if not model_path.exists():
            return [_model_path_issue("model_not_found", "model file does not exist")]
        if not model_path.is_file():
            return [_model_path_issue("model_not_file", "model path must be a regular file")]
    except OSError:
        return [_model_path_issue("model_read_error", "model file cannot be inspected")]

    digest = hashlib.sha256()
    size = 0
    try:
        with model_path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        return [_model_path_issue("model_read_error", "model file cannot be read")]

    file_section = manifest["file"]
    assert isinstance(file_section, dict)
    if size != file_section["size_bytes"]:
        _issue(
            issues,
            "size_mismatch",
            "model size does not match the manifest",
            "$.file.size_bytes",
        )
    if digest.hexdigest() != file_section["sha256"]:
        _issue(
            issues,
            "sha256_mismatch",
            "model SHA-256 does not match the manifest",
            "$.file.sha256",
        )
    return _sorted_issues(issues)


def check_device(
    manifest: object, facts: DeviceFacts
) -> list[dict[str, object]]:
    """Return deterministic compatibility issues for *facts*."""

    issues = validate_manifest(manifest, allow_example=True)
    if issues:
        return issues
    if not isinstance(facts, DeviceFacts):
        return [
            {
                "code": "invalid_type",
                "message": "facts must be DeviceFacts",
                "path": "$.device",
            }
        ]

    abi_valid = isinstance(facts.abi, str)
    if not abi_valid:
        _issue(issues, "invalid_type", "abi must be a string", "$.device.abi")
    elif not facts.abi.strip() or _contains_control(facts.abi):
        abi_valid = False
        _issue(issues, "invalid_value", "abi must be nonempty", "$.device.abi")

    api_valid = _validate_fact_integer(
        issues, facts.android_api, "android_api", "$.device.android_api", positive=True
    )
    memory_valid = _validate_fact_integer(
        issues, facts.memory_mb, "memory_mb", "$.device.memory_mb", positive=False
    )
    storage_valid = _validate_fact_integer(
        issues,
        facts.free_storage_mb,
        "free_storage_mb",
        "$.device.free_storage_mb",
        positive=False,
    )

    assert isinstance(manifest, dict)
    requirements = manifest["device_requirements"]
    assert isinstance(requirements, dict)
    if abi_valid and facts.abi not in requirements["abis"]:
        _issue(issues, "unsupported_abi", "device ABI is not supported", "$.device.abi")
    if api_valid and facts.android_api < requirements["min_android_api"]:
        _issue(
            issues,
            "android_api_too_low",
            "Android API is below the manifest minimum",
            "$.device.android_api",
        )
    if memory_valid and facts.memory_mb < requirements["min_memory_mb"]:
        _issue(
            issues,
            "insufficient_memory",
            "device memory is below the manifest minimum",
            "$.device.memory_mb",
        )
    if storage_valid and facts.free_storage_mb < requirements["min_free_storage_mb"]:
        _issue(
            issues,
            "insufficient_storage",
            "free storage is below the manifest minimum",
            "$.device.free_storage_mb",
        )
    return _sorted_issues(issues)


def build_adb_plan(
    manifest: object,
    *,
    local_model: Path | str,
    remote_directory: str = "/data/local/tmp/llama.cpp",
    context_tokens: int | None = None,
) -> list[list[str]]:
    """Return safe adb argument arrays without executing a process."""

    issues = validate_manifest(manifest)
    if issues:
        issue = issues[0]
        raise ValueError(f"manifest is invalid: {issue['code']} at {issue['path']}")
    assert isinstance(manifest, dict)
    file_section = manifest["file"]
    context = manifest["context"]
    assert isinstance(file_section, dict)
    assert isinstance(context, dict)

    manifest_name = file_section["name"]
    assert isinstance(manifest_name, str)
    _require_safe_filename(manifest_name, "manifest file name")
    local_name = str(local_model)
    _require_safe_filename(local_name, "local model name")
    if local_name != manifest_name:
        raise ValueError("local model name must match the manifest")

    remote = _normalize_remote_directory(remote_directory)
    selected_context = context["max_context_tokens"] if context_tokens is None else context_tokens
    if type(selected_context) is not int or selected_context <= 0:
        raise ValueError("context_tokens must be a positive integer")
    if selected_context > context["max_context_tokens"]:
        raise ValueError("context_tokens must not exceed the manifest maximum")

    remote_model = f"{remote}/{manifest_name}"
    executable = f"{remote}/bin/llama-cli"
    library_path = f"LD_LIBRARY_PATH={remote}/lib"
    return [
        ["adb", "shell", "mkdir", "-p", remote],
        ["adb", "push", local_name, remote_model],
        [
            "adb",
            "shell",
            "env",
            library_path,
            executable,
            "-m",
            remote_model,
            "-c",
            str(selected_context),
            "-n",
            str(context["max_output_tokens"]),
            "-p",
            "请用一句话说明如何查询订单",
        ],
    ]


class _CliArgumentError(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def print_help(self, file: object | None = None) -> None:
        del file

    def exit(self, status: int = 0, message: str | None = None) -> None:
        del status, message
        raise _CliArgumentError("invalid command arguments")

    def error(self, message: str) -> None:
        del message
        raise _CliArgumentError("invalid command arguments")


def _build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="mobile_model_manifest_demo.py")
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_JsonArgumentParser
    )

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--manifest", required=True)
    validate_parser.add_argument("--allow-example", action="store_true")

    verify_parser = subparsers.add_parser("verify-file")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--model", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--manifest", required=True)
    preflight_parser.add_argument("--abi", required=True)
    preflight_parser.add_argument("--android-api", required=True, type=int)
    preflight_parser.add_argument("--memory-mb", required=True, type=int)
    preflight_parser.add_argument("--free-storage-mb", required=True, type=int)
    preflight_parser.add_argument("--allow-example", action="store_true")

    plan_parser = subparsers.add_parser("plan-adb")
    plan_parser.add_argument("--manifest", required=True)
    plan_parser.add_argument("--model", required=True)
    plan_parser.add_argument("--remote-directory", required=True)
    plan_parser.add_argument("--context-tokens", type=int)
    return parser


def run_cli(argv: list[str] | None = None) -> int:
    """Run the JSON-only CLI and return a process exit code."""

    try:
        args = _build_parser().parse_args(argv)
        manifest = load_manifest(args.manifest)
        if args.command == "validate":
            issues = validate_manifest(manifest, allow_example=args.allow_example)
            return _emit_issues(issues, extra=_manifest_state(manifest))
        if args.command == "verify-file":
            issues = verify_model_file(manifest, args.model)
            return _emit_issues(issues)
        if args.command == "preflight":
            schema_issues = validate_manifest(manifest, allow_example=args.allow_example)
            if schema_issues:
                return _emit_issues(schema_issues)
            facts = DeviceFacts(
                abi=args.abi,
                android_api=args.android_api,
                memory_mb=args.memory_mb,
                free_storage_mb=args.free_storage_mb,
            )
            return _emit_issues(check_device(manifest, facts), extra=_manifest_state(manifest))
        if args.command == "plan-adb":
            commands = build_adb_plan(
                manifest,
                local_model=args.model,
                remote_directory=args.remote_directory,
                context_tokens=args.context_tokens,
            )
            _write_json(sys.stdout, {"ok": True, "commands": commands})
            return 0
        raise _CliArgumentError("invalid command arguments")
    except _CliArgumentError:
        _write_json(
            sys.stderr,
            {"ok": False, "error": {"code": "argument_error", "message": "invalid command arguments"}},
        )
        return 2
    except (OSError, ValueError):
        _write_json(
            sys.stderr,
            {"ok": False, "error": {"code": "input_error", "message": "input could not be processed"}},
        )
        return 2
    except KeyboardInterrupt:
        _write_json(
            sys.stderr,
            {"ok": False, "error": {"code": "interrupted", "message": "operation interrupted"}},
        )
        return 130
    except Exception:
        _write_json(
            sys.stderr,
            {"ok": False, "error": {"code": "internal_error", "message": "internal error"}},
        )
        return 1


def main() -> None:
    raise SystemExit(run_cli())


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


def _model_path_issue(code: str, message: str) -> dict[str, object]:
    return {"code": code, "message": message, "path": "$model"}


def _sorted_issues(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(issues, key=lambda issue: (str(issue["path"]), str(issue["code"])))


def _contains_control(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


def _validate_fact_integer(
    issues: list[dict[str, object]],
    value: object,
    name: str,
    path: str,
    *,
    positive: bool,
) -> bool:
    if type(value) is not int:
        _issue(issues, "invalid_type", f"{name} must be an integer", path)
        return False
    if (positive and value <= 0) or (not positive and value < 0):
        qualifier = "positive" if positive else "nonnegative"
        _issue(issues, "invalid_value", f"{name} must be {qualifier}", path)
        return False
    return True


def _require_safe_filename(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or value.startswith("-")
    ):
        raise ValueError(f"{label} is invalid")
    if (
        "/" in value
        or "\\" in value
        or ":" in value
        or _contains_control(value)
        or any(character.isspace() for character in value)
        or _SHELL_METACHAR_PATTERN.search(value)
    ):
        raise ValueError(f"{label} is unsafe")


def _normalize_remote_directory(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("remote_directory is invalid")
    if (
        "\\" in value
        or ":" in value
        or _contains_control(value)
        or any(character.isspace() for character in value)
    ):
        raise ValueError("remote_directory is unsafe")
    if _SHELL_METACHAR_PATTERN.search(value):
        raise ValueError("remote_directory contains unsafe characters")
    if not value.startswith("/") or ".." in value.split("/"):
        raise ValueError("remote_directory must be an absolute safe path")

    normalized = posixpath.normpath(value)
    candidate = PurePosixPath(normalized)
    base = PurePosixPath(_REMOTE_BASE)
    if candidate == base or base not in candidate.parents:
        raise ValueError("remote_directory must be a child of /data/local/tmp")
    return normalized


def _manifest_state(manifest: dict[str, object]) -> dict[str, object]:
    verification = manifest.get("verification")
    return {
        "example_only": manifest.get("example_only") is True,
        "verification": verification if isinstance(verification, dict) else None,
    }


def _emit_issues(
    issues: list[dict[str, object]], *, extra: dict[str, object] | None = None
) -> int:
    if issues:
        _write_json(sys.stderr, {"ok": False, "issues": issues})
        return 2
    payload: dict[str, object] = {"ok": True, "issues": []}
    if extra:
        payload.update(extra)
    _write_json(sys.stdout, payload)
    return 0


def _write_json(stream: object, value: object) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
