import copy
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


DEMO_DIR = Path(__file__).resolve().parents[1]
SAMPLE_MANIFEST_PATH = DEMO_DIR / "sample_mobile_model_manifest.json"
sys.path.insert(0, str(DEMO_DIR))

from mobile_model_manifest_demo import (  # noqa: E402
    DeviceFacts,
    build_adb_plan,
    check_device,
    load_manifest,
    run_cli,
    validate_manifest,
    verify_model_file,
)


VALID_MANIFEST = {
    "schema_version": 1,
    "model_id": "order-assistant-0.6b-q4",
    "runtime": "llama.cpp",
    "format": "gguf",
    "quantization": "Q4_K_M",
    "file": {
        "name": "order-assistant-q4_k_m.gguf",
        "size_bytes": 420000000,
        "sha256": "a" * 64,
    },
    "context": {"max_context_tokens": 2048, "max_output_tokens": 256},
    "device_requirements": {
        "abis": ["arm64-v8a"],
        "min_android_api": 28,
        "min_memory_mb": 3072,
        "min_free_storage_mb": 1024,
    },
    "provenance": {
        "base_model": "Qwen/Qwen3-0.6B",
        "base_revision": "d" * 40,
        "adapter_sha256": "b" * 64,
        "llama_cpp_commit": "c" * 40,
    },
    "licenses": {"model_reviewed": True, "data_reviewed": True},
    "verification": {"desktop_smoke_tested": True, "device_smoke_tested": False},
}


def delete_path(value, dotted_path):
    keys = dotted_path.split(".")
    cursor = value
    for key in keys[:-1]:
        cursor = cursor[key]
    del cursor[keys[-1]]


def set_path(value, dotted_path, replacement):
    keys = dotted_path.split(".")
    cursor = value
    for key in keys[:-1]:
        cursor = cursor[key]
    cursor[keys[-1]] = replacement


class MobileModelManifestValidationTest(unittest.TestCase):
    def assert_issue(self, issues, path, code):
        self.assertTrue(
            any(issue["path"] == path and issue["code"] == code for issue in issues),
            f"missing issue {code} at {path}: {issues}",
        )

    def test_complete_manifest_is_valid_and_input_is_unchanged(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        original = copy.deepcopy(manifest)

        issues = validate_manifest(manifest)

        self.assertEqual([], issues)
        self.assertEqual(original, manifest)

    def test_every_required_top_level_object_is_reported_at_its_own_path(self):
        for field in ("file", "context", "device_requirements", "provenance", "licenses", "verification"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(VALID_MANIFEST)
                del manifest[field]

                issues = validate_manifest(manifest)

                self.assertEqual(1, len(issues))
                self.assert_issue(issues, f"$.{field}", "missing_required")

    def test_every_required_scalar_field_is_reported_when_missing(self):
        required_fields = (
            "schema_version",
            "model_id",
            "runtime",
            "format",
            "quantization",
            "file.name",
            "file.size_bytes",
            "file.sha256",
            "context.max_context_tokens",
            "context.max_output_tokens",
            "device_requirements.abis",
            "device_requirements.min_android_api",
            "device_requirements.min_memory_mb",
            "device_requirements.min_free_storage_mb",
            "provenance.base_model",
            "provenance.base_revision",
            "provenance.adapter_sha256",
            "provenance.llama_cpp_commit",
            "licenses.model_reviewed",
            "licenses.data_reviewed",
            "verification.desktop_smoke_tested",
            "verification.device_smoke_tested",
        )
        for field in required_fields:
            with self.subTest(field=field):
                manifest = copy.deepcopy(VALID_MANIFEST)
                delete_path(manifest, field)

                issues = validate_manifest(manifest)

                self.assertEqual(1, len(issues))
                self.assert_issue(issues, f"$.{field}", "missing_required")

    def test_wrong_parent_type_produces_one_issue_without_child_noise(self):
        for field in ("file", "context", "device_requirements", "provenance", "licenses", "verification"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest[field] = []

                issues = validate_manifest(manifest)

                self.assertEqual(1, len(issues))
                self.assert_issue(issues, f"$.{field}", "invalid_type")

    def test_required_strings_must_be_nonempty_strings(self):
        fields = ("model_id", "quantization", "file.name", "provenance.base_model")
        for field in fields:
            for replacement in ("", "  ", 123, False):
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    set_path(manifest, field, replacement)

                    issues = validate_manifest(manifest)

                    code = "invalid_type" if not isinstance(replacement, str) else "invalid_value"
                    self.assert_issue(issues, f"$.{field}", code)

    def test_only_supported_schema_runtime_and_format_are_accepted(self):
        cases = (
            ("schema_version", 2),
            ("runtime", "LiteRT-LM"),
            ("format", "safetensors"),
        )
        for field, replacement in cases:
            with self.subTest(field=field):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest[field] = replacement

                issues = validate_manifest(manifest)

                self.assert_issue(issues, f"$.{field}", "unsupported_value")

    def test_schema_version_requires_an_integer_not_bool(self):
        for replacement in (True, 1.0, "1"):
            with self.subTest(replacement=replacement):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest["schema_version"] = replacement

                issues = validate_manifest(manifest)

                self.assert_issue(issues, "$.schema_version", "invalid_type")

    def test_sha256_fields_require_64_lowercase_hex_characters(self):
        fields = ("file.sha256", "provenance.adapter_sha256")
        invalid_values = ("a" * 63, "a" * 65, "A" * 64, "g" * 64, 123)
        for field in fields:
            for replacement in invalid_values:
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    set_path(manifest, field, replacement)

                    issues = validate_manifest(manifest)

                    code = "invalid_type" if not isinstance(replacement, str) else "invalid_sha256"
                    self.assert_issue(issues, f"$.{field}", code)

    def test_commit_fields_require_40_lowercase_hex_characters(self):
        fields = ("provenance.base_revision", "provenance.llama_cpp_commit")
        invalid_values = ("a" * 39, "a" * 41, "A" * 40, "g" * 40, 123)
        for field in fields:
            for replacement in invalid_values:
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    set_path(manifest, field, replacement)

                    issues = validate_manifest(manifest)

                    code = "invalid_type" if not isinstance(replacement, str) else "invalid_commit"
                    self.assert_issue(issues, f"$.{field}", code)

    def test_sizes_and_limits_require_positive_integers_not_bool(self):
        fields = (
            "file.size_bytes",
            "context.max_context_tokens",
            "context.max_output_tokens",
            "device_requirements.min_memory_mb",
            "device_requirements.min_free_storage_mb",
        )
        for field in fields:
            for replacement in (0, -1, True, 1.5, "1"):
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    set_path(manifest, field, replacement)

                    issues = validate_manifest(manifest)

                    code = "invalid_value" if type(replacement) is int else "invalid_type"
                    self.assert_issue(issues, f"$.{field}", code)

    def test_output_limit_cannot_exceed_context_limit(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["context"]["max_output_tokens"] = 2049

        issues = validate_manifest(manifest)

        self.assert_issue(issues, "$.context.max_output_tokens", "limit_exceeded")

    def test_abis_require_a_nonempty_list_of_nonempty_strings(self):
        for replacement, code in (([], "invalid_value"), ([1], "invalid_type"), ([""], "invalid_value"), ("arm64-v8a", "invalid_type")):
            with self.subTest(replacement=replacement):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest["device_requirements"]["abis"] = replacement

                issues = validate_manifest(manifest)

                self.assert_issue(issues, "$.device_requirements.abis", code)

    def test_android_api_requires_integer_at_least_28(self):
        for replacement, code in ((27, "invalid_value"), (0, "invalid_value"), (-1, "invalid_value"), (True, "invalid_type"), (28.0, "invalid_type")):
            with self.subTest(replacement=replacement):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest["device_requirements"]["min_android_api"] = replacement

                issues = validate_manifest(manifest)

                self.assert_issue(issues, "$.device_requirements.min_android_api", code)

    def test_license_flags_must_be_literal_true(self):
        for field in ("model_reviewed", "data_reviewed"):
            for replacement, code in ((False, "must_be_true"), (1, "invalid_type"), ("true", "invalid_type")):
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    manifest["licenses"][field] = replacement

                    issues = validate_manifest(manifest)

                    self.assert_issue(issues, f"$.licenses.{field}", code)

    def test_verification_flags_must_be_bool_but_may_be_false(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["verification"]["desktop_smoke_tested"] = False
        self.assertEqual([], validate_manifest(manifest))

        for field in ("desktop_smoke_tested", "device_smoke_tested"):
            for replacement in (0, 1, "false", None):
                with self.subTest(field=field, replacement=replacement):
                    manifest = copy.deepcopy(VALID_MANIFEST)
                    manifest["verification"][field] = replacement

                    issues = validate_manifest(manifest)

                    self.assert_issue(issues, f"$.verification.{field}", "invalid_type")

    def test_non_object_manifest_is_reported_without_exception(self):
        issues = validate_manifest([])

        self.assertEqual(1, len(issues))
        self.assert_issue(issues, "$", "invalid_type")

    def test_issues_have_exact_shape_and_deterministic_sort_order(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["runtime"] = "other"
        manifest["file"]["sha256"] = "BAD"
        manifest["context"]["max_output_tokens"] = 0

        first = validate_manifest(manifest)
        second = validate_manifest(manifest)

        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first, key=lambda issue: (issue["path"], issue["code"])))
        self.assertTrue(first)
        for issue in first:
            self.assertEqual({"code", "message", "path"}, set(issue))


class MobileModelManifestLoadingTest(unittest.TestCase):
    def test_load_manifest_reads_strict_utf8_json_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(VALID_MANIFEST, ensure_ascii=False), encoding="utf-8")

            loaded = load_manifest(path)

        self.assertEqual(VALID_MANIFEST, loaded)

    def test_load_manifest_rejects_non_object_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "root must be an object"):
                load_manifest(path)

    def test_load_manifest_rejects_invalid_json_without_echoing_content(self):
        secret = "top-secret-value"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"secret": "' + secret + '"', encoding="utf-8")

            with self.assertRaises(ValueError) as raised:
                load_manifest(path)

        self.assertIn("valid JSON", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))

    def test_load_manifest_rejects_nonstandard_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"size": NaN}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "valid JSON"):
                load_manifest(path)

    def test_load_manifest_rejects_invalid_utf8_without_echoing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(b'{"secret":"\xff"}')

            with self.assertRaises(ValueError) as raised:
                load_manifest(path)

        self.assertIn("UTF-8", str(raised.exception))
        self.assertNotIn("\\xff", str(raised.exception))


class MobileModelManifestExampleTest(unittest.TestCase):
    def setUp(self):
        self.example = copy.deepcopy(VALID_MANIFEST)
        self.example["example_only"] = True
        self.example["file"]["size_bytes"] = 0
        self.example["file"]["sha256"] = "0" * 64
        self.example["verification"] = {
            "desktop_smoke_tested": False,
            "device_smoke_tested": False,
        }

    def assert_issue(self, issues, path, code):
        self.assertTrue(
            any(issue["path"] == path and issue["code"] == code for issue in issues),
            f"missing issue {code} at {path}: {issues}",
        )

    def test_example_requires_explicit_permission(self):
        rejected = validate_manifest(self.example)
        self.assert_issue(rejected, "$.example_only", "example_not_allowed")
        self.assertEqual([], validate_manifest(self.example, allow_example=True))

    def test_committed_sample_is_a_valid_unverified_zero_placeholder(self):
        sample = load_manifest(SAMPLE_MANIFEST_PATH)
        self.assertIs(sample["example_only"], True)
        self.assertEqual(0, sample["file"]["size_bytes"])
        self.assertEqual("0" * 64, sample["file"]["sha256"])
        self.assertEqual(
            {"desktop_smoke_tested": False, "device_smoke_tested": False},
            sample["verification"],
        )
        self.assertEqual([], validate_manifest(sample, allow_example=True))

    def test_example_flag_must_be_a_boolean(self):
        for replacement in (1, "true", None):
            with self.subTest(replacement=replacement):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest["example_only"] = replacement
                self.assert_issue(
                    validate_manifest(manifest, allow_example=True),
                    "$.example_only",
                    "invalid_type",
                )

    def test_only_example_manifest_may_use_placeholders(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["file"]["size_bytes"] = 0
        manifest["file"]["sha256"] = "0" * 64
        issues = validate_manifest(manifest, allow_example=True)
        self.assert_issue(issues, "$.file.size_bytes", "invalid_value")
        self.assert_issue(issues, "$.file.sha256", "placeholder_not_allowed")

    def test_example_requires_placeholder_metadata_and_false_verification(self):
        cases = (
            ("file.size_bytes", 1, "example_placeholder_required"),
            ("file.sha256", "a" * 64, "example_placeholder_required"),
            ("verification.desktop_smoke_tested", True, "example_must_be_unverified"),
            ("verification.device_smoke_tested", True, "example_must_be_unverified"),
        )
        for dotted_path, replacement, code in cases:
            with self.subTest(path=dotted_path):
                manifest = copy.deepcopy(self.example)
                set_path(manifest, dotted_path, replacement)
                self.assert_issue(
                    validate_manifest(manifest, allow_example=True),
                    f"$.{dotted_path}",
                    code,
                )


class ModelFileVerificationTest(unittest.TestCase):
    def manifest_for(self, payload):
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["file"]["size_bytes"] = len(payload)
        manifest["file"]["sha256"] = hashlib.sha256(payload).hexdigest()
        return manifest

    def assert_issue(self, issues, path, code):
        self.assertTrue(
            any(issue["path"] == path and issue["code"] == code for issue in issues),
            f"missing issue {code} at {path}: {issues}",
        )

    def test_matching_file_passes_and_input_is_unchanged(self):
        payload = b"gguf-test-fixture"
        manifest = self.manifest_for(payload)
        original = copy.deepcopy(manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / manifest["file"]["name"]
            path.write_bytes(payload)
            self.assertEqual([], verify_model_file(manifest, path))
        self.assertEqual(original, manifest)

    def test_exact_size_and_lowercase_hash_are_checked(self):
        payload = b"expected"
        manifest = self.manifest_for(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / manifest["file"]["name"]
            path.write_bytes(b"different")
            issues = verify_model_file(manifest, path)
        self.assert_issue(issues, "$.file.size_bytes", "size_mismatch")
        self.assert_issue(issues, "$.file.sha256", "sha256_mismatch")

    def test_hashing_crosses_the_one_mib_chunk_boundary(self):
        payload = (b"a" * (1024 * 1024)) + b"boundary"
        manifest = self.manifest_for(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / manifest["file"]["name"]
            path.write_bytes(payload)
            self.assertEqual([], verify_model_file(manifest, path))

    def test_missing_directory_and_read_failure_are_deterministic_and_redacted(self):
        manifest = self.manifest_for(b"x")
        secret = "secret-model-name.gguf"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / secret
            first = verify_model_file(manifest, missing)
            second = verify_model_file(manifest, missing)
            self.assertEqual(first, second)
            self.assert_issue(first, "$model", "model_not_found")
            self.assertNotIn(secret, json.dumps(first))

            directory_issues = verify_model_file(manifest, root)
            self.assert_issue(directory_issues, "$model", "model_not_file")

            unreadable = root / manifest["file"]["name"]
            unreadable.write_bytes(b"x")
            with mock.patch("pathlib.Path.open", side_effect=PermissionError("top-secret")):
                read_issues = verify_model_file(manifest, unreadable)
            self.assert_issue(read_issues, "$model", "model_read_error")
            self.assertNotIn("top-secret", json.dumps(read_issues))

    def test_schema_example_and_placeholder_are_rejected_before_reading(self):
        invalid = copy.deepcopy(VALID_MANIFEST)
        invalid["runtime"] = "other"
        self.assert_issue(verify_model_file(invalid, Path("missing")), "$.runtime", "unsupported_value")

        example = copy.deepcopy(VALID_MANIFEST)
        example["example_only"] = True
        example["file"]["size_bytes"] = 0
        example["file"]["sha256"] = "0" * 64
        example["verification"] = {
            "desktop_smoke_tested": False,
            "device_smoke_tested": False,
        }
        issues = verify_model_file(example, Path("missing"))
        self.assert_issue(issues, "$.example_only", "example_not_verifiable")
        self.assertFalse(any(issue["code"] == "model_not_found" for issue in issues))


class DevicePreflightTest(unittest.TestCase):
    def assert_issue(self, issues, path, code):
        self.assertTrue(
            any(issue["path"] == path and issue["code"] == code for issue in issues),
            f"missing issue {code} at {path}: {issues}",
        )

    def test_compatible_device_passes_and_inputs_are_unchanged(self):
        manifest = copy.deepcopy(VALID_MANIFEST)
        original = copy.deepcopy(manifest)
        facts = DeviceFacts("arm64-v8a", 35, 8192, 4096)
        self.assertEqual([], check_device(manifest, facts))
        self.assertEqual(original, manifest)
        self.assertEqual(DeviceFacts("arm64-v8a", 35, 8192, 4096), facts)

    def test_each_unsupported_resource_has_a_stable_issue(self):
        cases = (
            (DeviceFacts("x86_64", 35, 8192, 4096), "$.device.abi", "unsupported_abi"),
            (DeviceFacts("arm64-v8a", 27, 8192, 4096), "$.device.android_api", "android_api_too_low"),
            (DeviceFacts("arm64-v8a", 35, 3071, 4096), "$.device.memory_mb", "insufficient_memory"),
            (DeviceFacts("arm64-v8a", 35, 8192, 1023), "$.device.free_storage_mb", "insufficient_storage"),
        )
        for facts, path, code in cases:
            with self.subTest(code=code):
                self.assert_issue(check_device(VALID_MANIFEST, facts), path, code)

    def test_fact_types_and_ranges_are_strict_and_bool_is_not_integer(self):
        cases = (
            (DeviceFacts("", 35, 8192, 4096), "$.device.abi", "invalid_value"),
            (DeviceFacts("arm64-v8a", True, 8192, 4096), "$.device.android_api", "invalid_type"),
            (DeviceFacts("arm64-v8a", 0, 8192, 4096), "$.device.android_api", "invalid_value"),
            (DeviceFacts("arm64-v8a", 35, True, 4096), "$.device.memory_mb", "invalid_type"),
            (DeviceFacts("arm64-v8a", 35, -1, 4096), "$.device.memory_mb", "invalid_value"),
            (DeviceFacts("arm64-v8a", 35, 8192, True), "$.device.free_storage_mb", "invalid_type"),
            (DeviceFacts("arm64-v8a", 35, 8192, -1), "$.device.free_storage_mb", "invalid_value"),
        )
        for facts, path, code in cases:
            with self.subTest(path=path, code=code):
                self.assert_issue(check_device(VALID_MANIFEST, facts), path, code)

    def test_issue_order_is_deterministic(self):
        facts = DeviceFacts("x86_64", 1, 0, 0)
        first = check_device(VALID_MANIFEST, facts)
        self.assertEqual(first, check_device(VALID_MANIFEST, facts))
        self.assertEqual(first, sorted(first, key=lambda issue: (issue["path"], issue["code"])))


class AdbPlanTest(unittest.TestCase):
    def test_plan_is_only_argument_arrays_with_manifest_limits(self):
        with mock.patch("subprocess.run") as run:
            plan = build_adb_plan(
                VALID_MANIFEST,
                local_model=Path("order-assistant-q4_k_m.gguf"),
            )
        run.assert_not_called()
        self.assertEqual(["adb", "shell", "mkdir", "-p", "/data/local/tmp/llama.cpp"], plan[0])
        self.assertEqual("adb", plan[1][0])
        self.assertEqual("push", plan[1][1])
        self.assertEqual("adb", plan[2][0])
        self.assertEqual("shell", plan[2][1])
        self.assertIn("2048", plan[2])
        self.assertIn("256", plan[2])
        self.assertTrue(all(isinstance(command, list) for command in plan))
        self.assertTrue(all(isinstance(argument, str) for command in plan for argument in command))

    def test_context_override_must_be_positive_not_bool_and_within_manifest_limit(self):
        plan = build_adb_plan(
            VALID_MANIFEST,
            local_model="order-assistant-q4_k_m.gguf",
            context_tokens=1024,
        )
        self.assertIn("1024", plan[2])
        for value in (0, -1, True, 2049):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_adb_plan(
                        VALID_MANIFEST,
                        local_model="order-assistant-q4_k_m.gguf",
                        context_tokens=value,
                    )

    def test_local_model_name_must_match_and_be_safe(self):
        unsafe = (
            "different.gguf",
            "nested/order-assistant-q4_k_m.gguf",
            "nested\\order-assistant-q4_k_m.gguf",
            "order-assistant-q4_k_m.gguf\x00",
            "order-assistant-q4_k_m.gguf\n",
        )
        for value in unsafe:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    build_adb_plan(VALID_MANIFEST, local_model=value)

    def test_remote_directory_must_be_a_safe_child_of_data_local_tmp(self):
        unsafe = (
            "/data/local/tmp",
            "/data/local/tmp/../outside",
            "/data/local/tmpfoo/model",
            "/sdcard/llama.cpp",
            "/data/local/tmp/llama;rm",
            "/data/local/tmp/llama cpp",
            "/data/local/tmp/llama\\cpp",
            "/data/local/tmp/llama\ncpp",
            "",
        )
        for value in unsafe:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    build_adb_plan(
                        VALID_MANIFEST,
                        local_model="order-assistant-q4_k_m.gguf",
                        remote_directory=value,
                    )

    def test_manifest_file_name_is_also_validated(self):
        for name in ("../order-assistant-q4_k_m.gguf", "model;rm.gguf", "model name.gguf"):
            with self.subTest(name=name):
                manifest = copy.deepcopy(VALID_MANIFEST)
                manifest["file"]["name"] = name
                with self.assertRaises(ValueError):
                    build_adb_plan(manifest, local_model=name)


class ManifestCliTest(unittest.TestCase):
    def invoke(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run_cli(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def write_manifest(self, directory, manifest=VALID_MANIFEST):
        path = Path(directory) / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return path

    def assert_one_json(self, text):
        self.assertEqual(1, len(text.strip().splitlines()))
        return json.loads(text)

    def test_validate_success_and_validation_failure_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            valid_path = self.write_manifest(directory)
            code, stdout, stderr = self.invoke(["validate", "--manifest", str(valid_path)])
            self.assertEqual(0, code)
            self.assertEqual("", stderr)
            self.assertTrue(self.assert_one_json(stdout)["ok"])

            invalid = copy.deepcopy(VALID_MANIFEST)
            invalid["runtime"] = "other"
            invalid_path = self.write_manifest(directory, invalid)
            code, stdout, stderr = self.invoke(["validate", "--manifest", str(invalid_path)])
            self.assertEqual(2, code)
            self.assertEqual("", stdout)
            self.assertFalse(self.assert_one_json(stderr)["ok"])

    def test_verify_file_success_and_mismatch(self):
        payload = b"gguf"
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["file"]["size_bytes"] = len(payload)
        manifest["file"]["sha256"] = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = self.write_manifest(directory, manifest)
            model_path = Path(directory) / manifest["file"]["name"]
            model_path.write_bytes(payload)
            code, stdout, stderr = self.invoke(
                ["verify-file", "--manifest", str(manifest_path), "--model", str(model_path)]
            )
            self.assertEqual((0, ""), (code, stderr))
            self.assertTrue(self.assert_one_json(stdout)["ok"])

            model_path.write_bytes(b"bad")
            code, stdout, stderr = self.invoke(
                ["verify-file", "--manifest", str(manifest_path), "--model", str(model_path)]
            )
            self.assertEqual((2, ""), (code, stdout))
            self.assertFalse(self.assert_one_json(stderr)["ok"])

    def test_preflight_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(directory)
            common = ["preflight", "--manifest", str(path), "--abi", "arm64-v8a"]
            code, stdout, stderr = self.invoke(
                common + ["--android-api", "35", "--memory-mb", "8192", "--free-storage-mb", "4096"]
            )
            self.assertEqual((0, ""), (code, stderr))
            self.assertTrue(self.assert_one_json(stdout)["ok"])

            code, stdout, stderr = self.invoke(
                common + ["--android-api", "27", "--memory-mb", "1", "--free-storage-mb", "1"]
            )
            self.assertEqual((2, ""), (code, stdout))
            self.assertFalse(self.assert_one_json(stderr)["ok"])

    def test_plan_adb_outputs_arrays_and_never_invokes_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(directory)
            with mock.patch("subprocess.run") as run:
                code, stdout, stderr = self.invoke(
                    [
                        "plan-adb",
                        "--manifest",
                        str(path),
                        "--model",
                        "order-assistant-q4_k_m.gguf",
                        "--remote-directory",
                        "/data/local/tmp/llama.cpp",
                    ]
                )
            run.assert_not_called()
        self.assertEqual((0, ""), (code, stderr))
        result = self.assert_one_json(stdout)
        self.assertTrue(result["ok"])
        self.assertTrue(all(isinstance(command, list) for command in result["commands"]))

    def test_example_cli_requires_allow_and_verify_always_rejects(self):
        example = copy.deepcopy(VALID_MANIFEST)
        example["example_only"] = True
        example["file"]["size_bytes"] = 0
        example["file"]["sha256"] = "0" * 64
        example["verification"] = {
            "desktop_smoke_tested": False,
            "device_smoke_tested": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(directory, example)
            rejected = self.invoke(["validate", "--manifest", str(path)])
            allowed = self.invoke(["validate", "--manifest", str(path), "--allow-example"])
            verified = self.invoke(["verify-file", "--manifest", str(path), "--model", "missing"])
        self.assertEqual(2, rejected[0])
        self.assertEqual(0, allowed[0])
        self.assertEqual(2, verified[0])
        self.assertIn("example_not_verifiable", verified[2])

    def test_argument_and_path_errors_are_single_json_on_stderr(self):
        cases = (
            [],
            ["unknown"],
            ["validate"],
            ["validate", "--manifest", "does-not-exist.json"],
            [
                "preflight",
                "--manifest",
                "does-not-exist.json",
                "--abi",
                "arm64-v8a",
                "--android-api",
                "not-an-int",
                "--memory-mb",
                "1",
                "--free-storage-mb",
                "1",
            ],
        )
        for argv in cases:
            with self.subTest(argv=argv):
                code, stdout, stderr = self.invoke(argv)
                self.assertEqual(2, code)
                self.assertEqual("", stdout)
                self.assertFalse(self.assert_one_json(stderr)["ok"])
                self.assertNotIn("usage:", stderr)
                self.assertNotIn("Traceback", stderr)

    def test_unexpected_error_is_redacted_and_keyboard_interrupt_is_nonzero(self):
        secret = "top-secret-runtime-detail"
        with mock.patch(
            "mobile_model_manifest_demo.load_manifest", side_effect=RuntimeError(secret)
        ):
            code, stdout, stderr = self.invoke(["validate", "--manifest", "manifest.json"])
        self.assertEqual((1, ""), (code, stdout))
        self.assertEqual({"ok": False, "error": {"code": "internal_error", "message": "internal error"}}, self.assert_one_json(stderr))
        self.assertNotIn(secret, stderr)

        with mock.patch(
            "mobile_model_manifest_demo.load_manifest", side_effect=KeyboardInterrupt
        ):
            code, stdout, stderr = self.invoke(["validate", "--manifest", "manifest.json"])
        self.assertNotEqual(0, code)
        self.assertEqual("", stdout)
        self.assertEqual("interrupted", self.assert_one_json(stderr)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
