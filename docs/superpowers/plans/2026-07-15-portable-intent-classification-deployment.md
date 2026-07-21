# Portable Intent Classification Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible intent classifier that uses train/validation/test data, calibrates unknown rejection, exports a versioned JSON artifact, and produces matching Python and Java predictions.

**Architecture:** A Python standard-library module owns validation, character n-gram training, calibration, metrics, artifact I/O, and CLI commands. Java standard-library classes load the fixed artifact schema and reproduce inference; shared JSONL parity cases prevent training/runtime drift.

**Tech Stack:** Python 3 standard library, `unittest`, Java 17-compatible source, `javac`, JSON/JSONL, Markdown, PowerShell.

---

## File map

- Create `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`: data validation, model math, calibration, artifact I/O, metrics, and CLI.
- Create `大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl`: balanced train/validation/test examples.
- Create `大模型技术学习教程/16-微调与模型定制/demo/intent_parity_cases.jsonl`: shared cross-runtime inputs and expected decisions.
- Create `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`: Python unit and CLI tests.
- Create `大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md`: runnable classification tutorial.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MiniJson.java`: fixed-schema JSON parser.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/android/IntentModelLoader.java`: artifact validation and immutable model object.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifier.java`: Java inference and CLI.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifierTest.java`: Java loader, prediction, rejection, and parity tests.
- Create `大模型技术学习教程/17-本地模型与私有化部署/06-意图分类模型部署到Android.md`: export-to-device tutorial.
- Modify `大模型技术学习教程/16-微调与模型定制/README.md`: outcomes and chapter link.
- Modify `大模型技术学习教程/17-本地模型与私有化部署/README.md`: Android classification chapter link.
- Modify `大模型技术学习教程/阶段练习与自检.md`: train/export/Java parity exercise.

### Task 1: Train/validation/test data contract

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Create: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing validation tests**

Create the test module with a path-safe import and these concrete cases:

```python
class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.valid = [
            {"text": "查询订单", "intent": "query_order", "split": "train"},
            {"text": "订单在哪里", "intent": "query_order", "split": "validation"},
            {"text": "查看物流", "intent": "query_order", "split": "test"},
            {"text": "今天天气", "intent": "unknown", "split": "validation"},
            {"text": "播放音乐", "intent": "unknown", "split": "test"},
        ]

    def test_valid_three_way_split_has_no_issues(self):
        self.assertEqual(validate_examples(self.valid), [])

    def test_cross_split_normalized_duplicate_is_rejected(self):
        rows = self.valid + [
            {"text": "查询，订单！", "intent": "query_order", "split": "test"}
        ]
        codes = {item["code"] for item in validate_examples(rows)}
        self.assertIn("cross_split_leakage", codes)

    def test_unknown_cannot_be_a_training_label(self):
        rows = self.valid + [
            {"text": "随便问问", "intent": "unknown", "split": "train"}
        ]
        codes = {item["code"] for item in validate_examples(rows)}
        self.assertIn("unknown_in_train", codes)
```

Also cover missing fields, blank normalized text, invalid snake-case intent, invalid split, same-split duplicates, conflicting labels, empty split, and test-only ordinary labels.

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\tests\test_intent_classifier_demo.py'
```

Expected: import failure because `intent_classifier_demo.py` does not exist.

- [ ] **Step 3: Implement loading, normalization, and validation**

Implement these public APIs and structured issue shape:

```python
VALID_SPLITS = frozenset({"train", "validation", "test"})
INTENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

def normalize_text(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())

def load_examples(path: Path | str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}: expected object")
            rows.append(value)
    return rows
```

Implement `validate_examples(examples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]`. It performs field checks before indexing a row, accumulates indexes by exact and normalized text, computes ordinary labels per split, appends issue objects with `code`, `message`, and sorted `indexes`, then sorts the final list by `(code, indexes)`. It must compare normalized text across all splits and exempt only `unknown` from the requirement that validation/test labels exist in train.

- [ ] **Step 4: Run validation tests to verify GREEN**

Run the same test module. Expected: all validation tests pass.

- [ ] **Step 5: Commit the data contract**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 定义三段式意图训练数据契约'
```

### Task 2: Naive Bayes training and prediction

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing feature and model tests**

Add tests for code-point unigrams/bigrams, training-only statistics, sorted candidates, stable softmax, and no-feature rejection:

```python
def test_extract_features_uses_unigrams_then_bigrams(self):
    self.assertEqual(extract_features("取消！"), ["取", "消", "取消"])

def test_training_ignores_validation_and_test_rows(self):
    model = train_classifier(self.rows)
    self.assertEqual(model.class_counts, {"cancel_order": 2, "query_order": 2})

def test_empty_normalized_text_returns_unknown(self):
    model = train_classifier(self.rows)
    result = predict_intent(model, "！！！", confidence_threshold=0.0, margin_threshold=0.0)
    self.assertEqual(result["intent"], "unknown")
    self.assertEqual(result["reason"], "no_features")
```

- [ ] **Step 2: Run focused tests to verify RED**

Expected: imports for `extract_features`, `train_classifier`, or `predict_intent` fail.

- [ ] **Step 3: Implement model math**

Use immutable model data and explicit feature ordering:

```python
@dataclass(frozen=True)
class IntentClassifier:
    class_counts: dict[str, int]
    feature_counts: dict[str, dict[str, int]]
    total_features: dict[str, int]
    vocabulary: tuple[str, ...]

def extract_features(text: str) -> list[str]:
    normalized = normalize_text(text)
    chars = list(normalized)
    return chars + [chars[index] + chars[index + 1] for index in range(len(chars) - 1)]
```

Implement `train_classifier(examples)`: filter only train rows, update one `Counter` per label with `extract_features`, compute totals from those counters, construct the sorted union vocabulary, and convert every counter to a key-sorted dictionary. Reject an empty train split.

Implement `predict_intent(model, text, *, confidence_threshold, margin_threshold)`: calculate `log(class_count / total_class_count)` plus `count(feature) * log((feature_count + 1) / (total_features + vocabulary_size))`; convert scores with max-shifted softmax; and sort candidates by `(-probability, intent)`. Rejection reasons are exactly `no_features`, `low_confidence`, and `low_margin`; accepted predictions use `reason="accepted"`.

- [ ] **Step 4: Run the module tests to verify GREEN**

Expected: validation and model tests pass.

- [ ] **Step 5: Commit classifier math**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 实现可移植意图分类模型'
```

### Task 3: Metrics and validation-only threshold calibration

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing metric and calibration tests**

Add exact matrix orientation and leakage guards:

```python
def test_confusion_matrix_rows_are_actual_labels(self):
    report = classification_metrics(
        actual=["cancel_order", "query_order"],
        predicted=["query_order", "query_order"],
    )
    self.assertEqual(report["confusion_matrix"]["cancel_order"]["query_order"], 1)

def test_calibration_reads_only_validation_rows(self):
    changed_test = [
        dict(row, text="完全不同的测试文本") if row["split"] == "test" else row
        for row in self.rows
    ]
    first = calibrate_thresholds(train_classifier(self.rows), self.rows)
    second = calibrate_thresholds(train_classifier(changed_test), changed_test)
    self.assertEqual(first, second)
```

Also test macro metrics with zero denominators, rejection rate, coverage, accepted accuracy, deterministic threshold tie-breaking, and calibration failure when no pair reaches the minimum accepted accuracy.

- [ ] **Step 2: Run tests to verify RED**

Expected: metric/calibration APIs are missing.

- [ ] **Step 3: Implement metrics and calibration**

Add:

```python
@dataclass(frozen=True)
class Thresholds:
    confidence: float
    margin: float
    minimum_accepted_accuracy: float
```

Implement `classification_metrics(actual, predicted)` with the sorted union of labels, actual-label rows, predicted-label columns, and a `safe_divide` helper that returns `0.0` on a zero denominator. Implement `evaluate_classifier(model, examples, *, split, thresholds)` by predicting only the requested split, separating accepted from rejected rows, and adding `rejection_rate`, `coverage`, `accepted_accuracy`, and details to the classification report.

Implement `calibrate_thresholds(model, examples, *, confidence_values=(0.35, 0.45, 0.55, 0.65), margin_values=(0.05, 0.10, 0.20, 0.30), minimum_accepted_accuracy=0.75)`. Evaluate the Cartesian product on validation rows only, discard candidates below the accepted-accuracy floor, and select by descending macro F1, descending coverage, ascending confidence, then ascending margin. Raise `ValueError("no threshold pair satisfies minimum accepted accuracy")` when no pair remains.

- [ ] **Step 4: Run tests to verify GREEN**

Expected: all metric and calibration tests pass, including the test-split mutation guard.

- [ ] **Step 5: Commit evaluation behavior**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 增加意图拒识校准与覆盖率评估'
```

### Task 4: Versioned JSON artifact

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing artifact round-trip tests**

Test stable serialization, SHA-256 metadata, round-trip predictions, atomic overwrite refusal, unknown schema, negative counts, non-finite thresholds, and label/statistic mismatches:

```python
def test_artifact_round_trip_preserves_prediction(self):
    artifact = build_artifact(self.model, self.thresholds, self.rows, model_version="demo-v1")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "intent-model.json"
        save_artifact(artifact, path)
        loaded = load_artifact(path)
    self.assertEqual(
        predict_with_artifact(artifact, "帮我取消订单"),
        predict_with_artifact(loaded, "帮我取消订单"),
    )

def test_existing_artifact_requires_force(self):
    with self.assertRaises(FileExistsError):
        save_artifact(self.artifact, self.path, force=False)
```

- [ ] **Step 2: Run tests to verify RED**

Expected: artifact APIs are missing.

- [ ] **Step 3: Implement the fixed schema and atomic save**

Define `SCHEMA_VERSION = 1` and build this complete top-level set:

```python
REQUIRED_ARTIFACT_KEYS = frozenset({
    "schema_version",
    "model_version",
    "algorithm",
    "normalization",
    "labels",
    "thresholds",
    "statistics",
    "training_metadata",
    "evaluation_summary",
})
```

`training_metadata` contains UTC `trained_at`, per-split counts, and a SHA-256 over canonical JSON rows sorted by `(split, intent, normalized_text, text)`. Save JSON with `ensure_ascii=False`, `sort_keys=True`, and `indent=2`; write beside the target and replace atomically only after a successful flush/close.

- [ ] **Step 4: Run artifact tests to verify GREEN**

Expected: artifact validation and round-trip tests pass.

- [ ] **Step 5: Commit artifact handling**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 支持意图模型制品导出与加载'
```

### Task 5: Sample data, parity cases, and artifact-oriented CLI

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl`
- Create: `大模型技术学习教程/16-微调与模型定制/demo/intent_parity_cases.jsonl`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Add balanced sample rows**

Use four ordinary labels—`query_order`, `cancel_order`, `request_refund`, `human_service`—with at least six train, two validation, and two test rows per label. Add at least four `unknown` rows to validation and four different `unknown` rows to test. Do not reuse normalized text across splits.

- [ ] **Step 2: Add shared parity cases**

Create JSONL records with this exact contract:

```json
{"text":"帮我取消订单","expected_intent":"cancel_order","expected_reason":"accepted"}
{"text":"！！！","expected_intent":"unknown","expected_reason":"no_features"}
```

Include accepted examples for all four labels plus low-confidence, low-margin, no-feature, Latin letter, digit, and mixed Chinese/Latin inputs.

- [ ] **Step 3: Write failing CLI tests**

Exercise `validate`, `train`, `evaluate`, `predict`, and `inspect`. Verify `train` refuses overwrite without `--force`, `evaluate` does not mutate the model file, stdout is JSON, user errors return `2`, and unexpected failures return `1`.

- [ ] **Step 4: Implement the CLI**

Use this command shape:

```text
validate --data PATH
train --data PATH --model PATH --model-version TEXT [--force]
evaluate --data PATH --model PATH --split {validation,test}
predict --model PATH --text TEXT
inspect --model PATH
```

`train` validates all splits, trains on train, calibrates on validation, evaluates validation and test for the report, and writes once. `evaluate` and `predict` load the artifact without retraining.

- [ ] **Step 5: Run tests and manual smoke commands**

```powershell
$demo = '.\大模型技术学习教程\16-微调与模型定制\demo\intent_classifier_demo.py'
$data = '.\大模型技术学习教程\16-微调与模型定制\demo\sample_intents.jsonl'
$model = Join-Path $env:TEMP 'intent-model.json'
Remove-Item -ErrorAction SilentlyContinue -LiteralPath $model
python $demo validate --data $data
python $demo train --data $data --model $model --model-version 'tutorial-v1'
python $demo evaluate --data $data --model $model --split test
python $demo predict --model $model --text '帮我取消订单'
python $demo inspect --model $model
```

Expected: five JSON documents, zero exit codes, and `cancel_order/accepted` for the prediction.

- [ ] **Step 6: Commit data and CLI**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl' '大模型技术学习教程/16-微调与模型定制/demo/intent_parity_cases.jsonl' '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 增加可复现意图训练命令行'
```

### Task 6: Java JSON loader and artifact validation

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MiniJson.java`
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/IntentModelLoader.java`
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifierTest.java`

- [ ] **Step 1: Write the failing Java loader test**

Create a test main that takes the generated model path as `args[0]`, loads it, verifies schema/version/labels/thresholds, creates corrupted temporary copies, and exits nonzero on assertion failure:

```java
public static void main(String[] args) throws Exception {
    require(args.length == 1, "expected model path");
    IntentModelLoader.IntentModel model = IntentModelLoader.load(Path.of(args[0]));
    require(model.schemaVersion() == 1, "schema version");
    require(model.labels().contains("cancel_order"), "cancel_order label");
    System.out.println("MobileIntentClassifierTest OK");
}
```

- [ ] **Step 2: Compile to verify RED**

```powershell
$src = '.\大模型技术学习教程\17-本地模型与私有化部署\demo\android'
$out = Join-Path $env:TEMP 'intent-java-classes'
New-Item -ItemType Directory -Force $out | Out-Null
javac -encoding UTF-8 -d $out "$src\MobileIntentClassifierTest.java"
```

Expected: compile errors because loader classes do not exist.

- [ ] **Step 3: Implement `MiniJson`**

Provide `static Object parse(String source)` with a recursive-descent parser for object, array, string escapes, finite JSON numbers, booleans, and null. Reject trailing characters, duplicate object keys, invalid escapes, and non-JSON numeric tokens. Keep the class package-free so the existing command-line Java style can compile it directly.

- [ ] **Step 4: Implement `IntentModelLoader`**

Use immutable records and defensive copies:

```java
public final class IntentModelLoader {
    public record Thresholds(double confidence, double margin) {}
    public record IntentModel(
        int schemaVersion,
        String modelVersion,
        List<String> labels,
        Thresholds thresholds,
        Map<String, Integer> classCounts,
        Map<String, Map<String, Integer>> featureCounts,
        Map<String, Integer> totalFeatures,
        Set<String> vocabulary
    ) {}

    public static IntentModel load(Path path) throws IOException {
        Object root = MiniJson.parse(Files.readString(path, StandardCharsets.UTF_8));
        return validateAndConvert(root);
    }
}
```

Reject schema other than `1`, algorithm other than `multinomial_naive_bayes`, missing labels, duplicate labels, thresholds outside `[0,1]`, negative counts, feature labels outside `labels`, total/count inconsistencies, and vocabulary mismatches.

- [ ] **Step 5: Compile and run the loader test**

Generate a temporary model with the Python CLI, compile all Java sources, and run the test. Expected: `MobileIntentClassifierTest OK`.

- [ ] **Step 6: Commit the loader**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/demo/android/MiniJson.java' '大模型技术学习教程/17-本地模型与私有化部署/demo/android/IntentModelLoader.java' '大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifierTest.java'
git commit -m 'feat: 增加Java意图模型制品加载器'
```

### Task 7: Java classifier and Python/Java parity

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifier.java`
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifierTest.java`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`

- [ ] **Step 1: Add failing Java prediction assertions**

Load the model, assert `取消订单` is accepted as `cancel_order`, punctuation is `unknown/no_features`, candidates are probability-descending with label tie-breaks, and all probabilities sum to `1.0` within `1e-9`.

- [ ] **Step 2: Compile to verify RED**

Expected: `MobileIntentClassifier` is missing.

- [ ] **Step 3: Implement Java inference and CLI**

Expose:

```java
public final class MobileIntentClassifier {
    public record Candidate(String intent, double probability) {}
    public record Prediction(
        String intent,
        String reason,
        double confidence,
        double margin,
        List<Candidate> candidates
    ) {}

    public MobileIntentClassifier(IntentModelLoader.IntentModel model) {}
    public Prediction predict(String text) {}
    public static String normalizeText(String text) {}
    public static List<String> extractFeatures(String text) {}
    public static void main(String[] args) throws Exception {}
}
```

Iterate Unicode code points, use `Character.isLetterOrDigit`, lower with `Locale.ROOT`, and reproduce Python log-prior/Laplace/softmax math. CLI arguments are `--model PATH --text TEXT`; print UTF-8 JSON and return user-error exit code `2`.

- [ ] **Step 4: Add a Python-driven parity integration test**

The Python test must:

1. Train a temporary artifact.
2. Compile all four Java files to a temporary class directory.
3. Invoke Java once per `intent_parity_cases.jsonl` row.
4. Compare intent, reason, candidate order, and probability/margin tolerance `1e-9`.
5. Skip only when `javac` or `java` is absent, with an explicit skip reason.

- [ ] **Step 5: Run Python and Java tests**

Expected: Python module tests pass and Java prints `MobileIntentClassifierTest OK`.

- [ ] **Step 6: Commit Java inference parity**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifier.java' '大模型技术学习教程/17-本地模型与私有化部署/demo/android/MobileIntentClassifierTest.java' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 实现Android意图分类核心推理'
```

### Task 8: Classification tutorials and navigation

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md`
- Create: `大模型技术学习教程/17-本地模型与私有化部署/06-意图分类模型部署到Android.md`
- Modify: `大模型技术学习教程/16-微调与模型定制/README.md`
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/README.md`
- Modify: `大模型技术学习教程/阶段练习与自检.md`

- [ ] **Step 1: Write the training tutorial**

Use this exact section order: problem boundary; rules/Embedding/LLM/classifier decision table; taxonomy and `unknown`; three-way data split; leakage checks; n-gram and Naive Bayes intuition; calibration objective; classification and rejection metrics; CLI walkthrough; artifact schema; production migration limits.

Include all five smoke commands from Task 5 and explain that test results are reported after thresholds are fixed, never used to select them.

- [ ] **Step 2: Write the Android classification tutorial**

Document: Python export; Java compile; Java test; Java predict; copy-to-assets versus runtime download; private storage; SHA-256; atomic version switch; rollback; model incompatibility; background execution; input privacy; when to replace this classifier with ONNX Runtime Mobile.

Use concrete compile/run commands that generate the model into `$env:TEMP`, compile with `javac -encoding UTF-8`, and run the package-free classes.

- [ ] **Step 3: Update README and self-check navigation**

Add stage 16 outcome “完成训练、校准、导出和评估闭环,” stage 17 outcome “在 Java/Android 中加载分类模型,” chapter links, and a self-check exercise that requires comparing Python and Java output.

- [ ] **Step 4: Verify Markdown links**

Run the repository local-link checker described in the final verification task. Expected: `BROKEN=0`.

- [ ] **Step 5: Commit classification documentation**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md' '大模型技术学习教程/17-本地模型与私有化部署/06-意图分类模型部署到Android.md' '大模型技术学习教程/16-微调与模型定制/README.md' '大模型技术学习教程/17-本地模型与私有化部署/README.md' '大模型技术学习教程/阶段练习与自检.md'
git commit -m 'docs: 补全意图训练与Android部署教程'
```

### Task 9: Plan 1 verification

**Files:**
- Verify every file changed by this plan.

- [ ] **Step 1: Run Python tests**

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\tests\test_intent_classifier_demo.py'
```

Expected: all tests pass without third-party Python packages.

- [ ] **Step 2: Run manual Python and Java smoke flow**

Generate a fresh model, compile the Java sources into a fresh temp directory, run `MobileIntentClassifierTest`, and predict `帮我取消订单`. Expected: test OK and `cancel_order/accepted`.

- [ ] **Step 3: Run syntax and diff checks**

```powershell
python -m compileall '.\大模型技术学习教程\16-微调与模型定制\demo'
git diff --check
git status --short
```

Expected: compileall and diff check exit zero; status lists only intentional uncommitted verification artifacts, ideally none.

- [ ] **Step 4: Review the Plan 1 acceptance evidence**

Confirm: test does not influence calibration; artifact reload is mandatory; Java parity uses the same artifact and cases; no generated model is tracked; both tutorials match actual commands.
