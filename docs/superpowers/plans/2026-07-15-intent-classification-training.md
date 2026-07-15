# Intent Classification Training Implementation Plan

> **Superseded:** This plan covers the original Python-only scope. Use [Local and Android Model Training Deployment Roadmap](./2026-07-15-local-android-model-training-deployment-roadmap.md) for implementation; its portable-classifier plan adds validation calibration, model artifacts, Java parity, and Android deployment.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standard-library-only intent classification training tutorial and runnable demo to stage 16, including data validation, Naive Bayes training, unknown rejection, evaluation metrics, CLI commands, and documentation.

**Architecture:** Keep the new classifier isolated in `intent_classifier_demo.py`. JSONL samples carry explicit `train` and `test` splits; the module validates them, extracts Chinese character n-grams, trains a multinomial Naive Bayes model, predicts with confidence and margin rejection, and evaluates a test set. The tutorial and self-check index explain how to use the executable workflow without changing the existing customization demo.

**Tech Stack:** Python 3 standard library, `unittest`, Markdown, JSONL, PowerShell verification commands.

---

## File map

- Create `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`: validation, feature extraction, model training, prediction, metrics, and CLI.
- Create `大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl`: reproducible train/test customer-service intent data.
- Create `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`: behavior and CLI tests.
- Create `大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md`: conceptual and runnable tutorial.
- Modify `大模型技术学习教程/16-微调与模型定制/README.md`: add learning outcomes and chapter link.
- Modify `大模型技术学习教程/阶段练习与自检.md`: replace the stage 16 exercise with an intent-classification training loop.

### Task 1: Data validation contract

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Create: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing validation tests**

Add tests that import the wished-for API and cover valid data, missing fields, duplicate/conflicting text, invalid split, missing train/test coverage, and allowed `unknown` test rows:

```python
from intent_classifier_demo import validate_examples


def test_valid_examples_have_no_issues(self):
    self.assertEqual(validate_examples(self.examples), [])


def test_conflicting_labels_are_reported(self):
    examples = self.examples + [
        {"text": "取消订单", "intent": "query_order", "split": "train"}
    ]
    codes = {issue["code"] for issue in validate_examples(examples)}
    self.assertIn("conflicting_label", codes)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\tests\test_intent_classifier_demo.py'
```

Expected: import failure because `intent_classifier_demo.py` does not exist.

- [ ] **Step 3: Implement minimal loading and validation**

Implement public function `load_examples(path: Path | str) -> list[dict[str, str]]` to read UTF-8 JSONL and public function `validate_examples(examples: Sequence[dict[str, str]]) -> list[dict[str, object]]` to return validation issues.

Issue objects use `code`, `message`, and optional `indexes`. Validation must check required string fields, split values, duplicate/conflicting normalized text, train/test intent coverage, and treat test-only `unknown` as valid.

- [ ] **Step 4: Run tests and verify GREEN**

Run the same test file. Expected: validation tests pass.

- [ ] **Step 5: Commit validation behavior**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 增加意图训练数据校验'
```

### Task 2: Feature extraction and Naive Bayes training

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing feature and training tests**

Add tests for deterministic normalization, unigram/bigram extraction, model classes, and a representative prediction:

```python
from intent_classifier_demo import extract_features, predict_intent, train_classifier


def test_extract_features_uses_normalized_unigrams_and_bigrams(self):
    self.assertEqual(extract_features("取消！"), ["取", "消", "取消"])


def test_trained_classifier_predicts_representative_intent(self):
    model = train_classifier(self.training_examples)
    result = predict_intent(
        model,
        "请帮我取消这个订单",
        confidence_threshold=0.0,
        margin_threshold=0.0,
    )
    self.assertEqual(result["intent"], "cancel_order")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Expected: missing imports for the new functions.

- [ ] **Step 3: Implement feature extraction and model training**

Add this serializable model dataclass:

```python
@dataclass(frozen=True)
class IntentClassifier:
    class_counts: dict[str, int]
    feature_counts: dict[str, dict[str, int]]
    total_features: dict[str, int]
    vocabulary: frozenset[str]
```

Implement `normalize_text(text: str) -> str`, `extract_features(text: str) -> list[str]`, `train_classifier(examples: Sequence[dict[str, str]]) -> IntentClassifier`, and `predict_intent(model: IntentClassifier, text: str, *, confidence_threshold: float = 0.45, margin_threshold: float = 0.10) -> dict[str, object]`. Use log priors, Laplace-smoothed feature likelihoods, and a numerically stable softmax. Return candidates sorted by probability.

- [ ] **Step 4: Run tests and verify GREEN**

Expected: feature and representative prediction tests pass with the validation tests.

- [ ] **Step 5: Commit classifier training**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 实现离线意图分类器训练'
```

### Task 3: Unknown rejection and evaluation metrics

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Write failing rejection and metric tests**

Cover empty-feature rejection, threshold rejection, matrix orientation, zero denominators, per-class metrics, macro F1, and error details:

```python
from intent_classifier_demo import classification_metrics, evaluate_classifier


def test_empty_features_are_rejected_as_unknown(self):
    model = train_classifier(self.training_examples)
    result = predict_intent(model, "!!!")
    self.assertEqual(result["intent"], "unknown")
    self.assertEqual(result["reason"], "no_features")


def test_confusion_matrix_rows_are_actual_labels(self):
    metrics = classification_metrics(
        actual=["cancel_order", "query_order"],
        predicted=["query_order", "query_order"],
    )
    self.assertEqual(metrics["confusion_matrix"]["cancel_order"]["query_order"], 1)
```

- [ ] **Step 2: Run tests and verify RED**

Expected: evaluation imports or assertions fail because the behavior is not implemented.

- [ ] **Step 3: Implement rejection and evaluation**

Implement `classification_metrics(actual: Sequence[str], predicted: Sequence[str]) -> dict[str, object]` and `evaluate_classifier(model: IntentClassifier, examples: Sequence[dict[str, str]], *, confidence_threshold: float = 0.45, margin_threshold: float = 0.10) -> dict[str, object]`. Reject on no features, confidence below threshold, or margin below threshold. Preserve candidates and add a `reason`. Use `0.0` for metric divisions with zero denominators.

- [ ] **Step 4: Run tests and verify GREEN**

Expected: all module tests pass.

- [ ] **Step 5: Commit rejection and evaluation**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 增加意图拒识与分类评估'
```

### Task 4: Reproducible sample data and CLI

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py`

- [ ] **Step 1: Add sample JSONL data**

Create balanced `train` and `test` rows for `query_order`, `cancel_order`, `request_refund`, and `human_service`, plus test-only `unknown` rows. Use distinct wording across splits to avoid exact-text leakage.

- [ ] **Step 2: Write failing CLI tests**

Test `main()` with captured stdout:

```python
def test_validate_command_returns_json_success(self):
    with redirect_stdout(io.StringIO()) as output:
        exit_code = main(["--data", str(SAMPLE_DATA), "validate"])
    payload = json.loads(output.getvalue())
    self.assertEqual(exit_code, 0)
    self.assertTrue(payload["valid"])


def test_predict_command_returns_candidates(self):
    with redirect_stdout(io.StringIO()) as output:
        exit_code = main([
            "--data", str(SAMPLE_DATA),
            "predict", "--text", "帮我取消订单",
        ])
    payload = json.loads(output.getvalue())
    self.assertEqual(exit_code, 0)
    self.assertIn("candidates", payload)
```

- [ ] **Step 3: Run CLI tests and verify RED**

Expected: `main` or argument parsing behavior is missing.

- [ ] **Step 4: Implement CLI commands**

Implement `build_parser()` and `main(argv=None)`. Global flags precede the subcommand. `validate` outputs count/issues, `evaluate` trains on train rows and evaluates test rows, and `predict` trains then predicts one text. Invalid data emits JSON to stderr and returns `2`.

- [ ] **Step 5: Run tests and manual CLI smoke commands**

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\intent_classifier_demo.py' validate
python '.\大模型技术学习教程\16-微调与模型定制\demo\intent_classifier_demo.py' evaluate
python '.\大模型技术学习教程\16-微调与模型定制\demo\intent_classifier_demo.py' predict --text '帮我取消订单'
```

Expected: three valid JSON documents and zero exit codes.

- [ ] **Step 6: Commit data and CLI**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/sample_intents.jsonl' '大模型技术学习教程/16-微调与模型定制/demo/intent_classifier_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_intent_classifier_demo.py'
git commit -m 'feat: 增加意图训练示例数据与命令行'
```

### Task 5: Tutorial and navigation

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md`
- Modify: `大模型技术学习教程/16-微调与模型定制/README.md`
- Modify: `大模型技术学习教程/阶段练习与自检.md`

- [ ] **Step 1: Write the new tutorial chapter**

Cover the distinctions among intent classification, slot extraction, RAG, and Agent; include a decision table for rules/Embedding/LLM/traditional classifier/fine-tuning; document taxonomy, labeling, split discipline, metrics, rejection, commands, expected JSON fields, and production migration boundaries.

- [ ] **Step 2: Update stage navigation**

Add a learning outcome and chapter link:

```markdown
7. 如何设计意图体系，并完成训练、拒识和分类评估闭环。

5. [意图识别与分类训练实战](./05-意图识别与分类训练实战.md)
```

- [ ] **Step 3: Update the stage 16 self-check**

Replace the stage 16 row with an exercise that defines four intents, labels examples, runs the classifier, inspects the confusion matrix, and explains when to use rules, Prompt classification, or training.

- [ ] **Step 4: Verify local Markdown links**

Run the repository local-link checker used during review. Expected: `BROKEN=0`.

- [ ] **Step 5: Commit tutorial documentation**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/05-意图识别与分类训练实战.md' '大模型技术学习教程/16-微调与模型定制/README.md' '大模型技术学习教程/阶段练习与自检.md'
git commit -m 'docs: 增加意图识别训练实战教程'
```

### Task 6: Full verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run all Python test files**

Discover every `test_*.py` and execute each with Python. Expected: every file exits zero, including the new intent-classifier tests.

- [ ] **Step 2: Run Node tests**

```powershell
node '.\大模型技术学习教程\11-前端与交互体验\demo\tests\chat_ui_state.test.cjs'
```

Expected: 7 tests pass.

- [ ] **Step 3: Compile and run Java tests outside the repository**

Compile stage 12 into a temporary directory and run `AndroidAiClientDemoTest`. Expected: `AndroidAiClientDemoTest OK`.

- [ ] **Step 4: Run syntax, link, and Git checks**

Run `python -m compileall`, local Markdown link validation, `git diff --check`, and `git status --short`. Expected: no syntax failures, no broken local links, no whitespace errors, and only intentional files changed before the final commit.

- [ ] **Step 5: Review requirements against the design**

Confirm the implementation provides all design-specified validation, training, rejection, metrics, CLI, sample data, tutorial, and navigation behavior, with no third-party dependency.
