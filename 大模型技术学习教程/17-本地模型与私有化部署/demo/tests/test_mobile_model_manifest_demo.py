import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))

from mobile_model_manifest_demo import load_manifest, validate_manifest  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
