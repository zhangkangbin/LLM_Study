# Android Generative Model Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a validated GGUF deployment manifest, Android/adb verification workflow, and Kotlin llama.cpp integration example for on-device generation.

**Architecture:** A Python standard-library manifest tool validates provenance, file integrity, resource limits, licenses, and verification state, then emits structured command arguments rather than executing device mutations. A Kotlin wrapper demonstrates the official llama.cpp Android `AiChat`/`InferenceEngine` lifecycle; Markdown connects model download, private storage, streaming, cancellation, rollback, and performance testing.

**Tech Stack:** Python 3 standard library, JSON, SHA-256, Java/Kotlin Android concepts, Kotlin coroutines/Flow, llama.cpp Android binding, adb, Markdown.

---

## File map

- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/mobile_model_manifest_demo.py`: manifest validation, local-file verification, device preflight, and adb command planning.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/sample_mobile_model_manifest.json`: schema example with safe placeholder file metadata explicitly marked unverified.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/tests/test_mobile_model_manifest_demo.py`: manifest and CLI tests.
- Create `大模型技术学习教程/17-本地模型与私有化部署/demo/android/OnDeviceLlmEngine.kt`: llama.cpp Kotlin lifecycle wrapper.
- Create `大模型技术学习教程/17-本地模型与私有化部署/07-生成式小模型部署到Android.md`: Android deployment tutorial.
- Modify `大模型技术学习教程/17-本地模型与私有化部署/README.md`: chapter link and outcomes.
- Modify `大模型技术学习教程/12-Android端接入大模型/README.md`: link to stage 17.
- Modify `大模型技术学习教程/阶段练习与自检.md`: Android deployment checklist.

### Task 1: Deployment manifest validation

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/tests/test_mobile_model_manifest_demo.py`
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/mobile_model_manifest_demo.py`

- [ ] **Step 1: Write failing schema tests**

Use this complete minimal manifest in tests:

```python
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
```

Test every required object, SHA format, positive size/limits, output not exceeding context, nonempty ABI, API floor, supported runtime/format, reviewed licenses, and deterministic issue ordering.

- [ ] **Step 2: Run tests to verify RED**

```powershell
python '.\大模型技术学习教程\17-本地模型与私有化部署\demo\tests\test_mobile_model_manifest_demo.py'
```

Expected: import failure because the manifest module does not exist.

- [ ] **Step 3: Implement loading and schema validation**

```python
def load_manifest(path: Path | str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    return value
```

Implement `validate_manifest(manifest)` by checking each required path with type-specific helpers, appending `code`, `message`, and JSON-style `path`, then sorting issues by `(path, code)`. Only schema `1`, runtime `llama.cpp`, and format `gguf` are accepted by the executable demo. LiteRT-LM remains a documented alternative with a different artifact format.

- [ ] **Step 4: Run schema tests to verify GREEN**

Expected: all manifest schema tests pass.

- [ ] **Step 5: Commit schema validation**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/demo/mobile_model_manifest_demo.py' '大模型技术学习教程/17-本地模型与私有化部署/demo/tests/test_mobile_model_manifest_demo.py'
git commit -m 'feat: 定义Android生成模型部署清单'
```

### Task 2: File verification, device preflight, and safe command plan

**Files:**
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/demo/tests/test_mobile_model_manifest_demo.py`
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/demo/mobile_model_manifest_demo.py`
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/sample_mobile_model_manifest.json`

- [ ] **Step 1: Write failing file/preflight/plan tests**

Test correct and incorrect file size/hash, unsupported ABI, Android API below floor, insufficient memory/storage, unsafe file names, context override above max, and returned command arrays:

```python
def test_command_plan_uses_argument_arrays(self):
    plan = build_adb_plan(self.manifest, local_model=Path("order-assistant-q4_k_m.gguf"))
    self.assertEqual(plan[0][0:2], ["adb", "push"])
    self.assertNotIn(";", " ".join(plan[0]))
```

- [ ] **Step 2: Run tests to verify RED**

Expected: verification/preflight functions are missing.

- [ ] **Step 3: Implement verification and preflight**

```python
@dataclass(frozen=True)
class DeviceFacts:
    abi: str
    android_api: int
    memory_mb: int
    free_storage_mb: int
```

Implement `verify_model_file(manifest, path)` by streaming 1 MiB chunks and comparing exact byte count and lowercase SHA-256. Implement `check_device(manifest, facts)` by comparing ABI membership and minimum API, memory, and free storage. Implement `build_adb_plan(manifest, *, local_model, remote_directory="/data/local/tmp/llama.cpp")` to return argument arrays for `adb shell mkdir -p`, `adb push`, and the `llama-cli` smoke command; execute nothing. Reject local names containing directory separators and remote directories outside `/data/local/tmp/`.

- [ ] **Step 4: Add the sample manifest and CLI**

The committed sample uses `size_bytes: 0`, sixty-four zero hash characters, and both verification flags false, with a top-level `example_only: true`. The validator permits this only with `--allow-example`; `verify-file` must reject it as unverified.

CLI commands:

```text
validate --manifest PATH [--allow-example]
verify-file --manifest PATH --model PATH
preflight --manifest PATH --abi TEXT --android-api N --memory-mb N --free-storage-mb N
plan-adb --manifest PATH --model PATH --remote-directory PATH
```

Print JSON only. `plan-adb` prints arrays, never invokes adb.

- [ ] **Step 5: Run tests and CLI smoke**

```powershell
$demo = '.\大模型技术学习教程\17-本地模型与私有化部署\demo\mobile_model_manifest_demo.py'
$manifest = '.\大模型技术学习教程\17-本地模型与私有化部署\demo\sample_mobile_model_manifest.json'
python $demo validate --manifest $manifest --allow-example
python $demo preflight --manifest $manifest --abi arm64-v8a --android-api 35 --memory-mb 8192 --free-storage-mb 4096 --allow-example
```

Expected: valid example schema and successful resource preflight; file verification remains false.

- [ ] **Step 6: Commit manifest tooling**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/demo/mobile_model_manifest_demo.py' '大模型技术学习教程/17-本地模型与私有化部署/demo/sample_mobile_model_manifest.json' '大模型技术学习教程/17-本地模型与私有化部署/demo/tests/test_mobile_model_manifest_demo.py'
git commit -m 'feat: 增加端侧模型校验与adb计划'
```

### Task 3: Kotlin llama.cpp lifecycle wrapper

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/demo/android/OnDeviceLlmEngine.kt`

- [ ] **Step 1: Pin and record the upstream API used by the example**

Record the inspected llama.cpp commit in the file header and link these upstream files:

```text
examples/llama.android/lib/src/main/java/com/arm/aichat/AiChat.kt
examples/llama.android/lib/src/main/java/com/arm/aichat/InferenceEngine.kt
```

Verify at that commit that the API contains `AiChat.getInferenceEngine(context)`, `loadModel`, `setSystemPrompt`, `sendUserPrompt(...): Flow<String>`, `cleanUp`, and `destroy`.

- [ ] **Step 2: Implement the wrapper**

Use the official binding types and coroutines:

```kotlin
class OnDeviceLlmEngine(
    context: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val inferenceDispatcher: CoroutineDispatcher = Dispatchers.Default,
) : Closeable {
    private val engine: InferenceEngine = AiChat.getInferenceEngine(context.applicationContext)
    private val generationMutex = Mutex()
    private var closed = false

    suspend fun load(modelFile: File, systemPrompt: String? = null) = withContext(ioDispatcher) {
        check(!closed) { "engine is closed" }
        require(modelFile.isFile) { "model file does not exist" }
        engine.loadModel(modelFile.absolutePath)
        if (!systemPrompt.isNullOrBlank()) engine.setSystemPrompt(systemPrompt)
    }

    fun generate(prompt: String, maxOutputTokens: Int = 256): Flow<String> = flow {
        require(prompt.isNotBlank()) { "prompt is blank" }
        require(maxOutputTokens in 1..1024) { "maxOutputTokens must be between 1 and 1024" }
        generationMutex.withLock {
            engine.sendUserPrompt(prompt, maxOutputTokens).collect { emit(it) }
        }
    }.flowOn(inferenceDispatcher)

    fun unload() = engine.cleanUp()

    override fun close() {
        if (!closed) {
            closed = true
            engine.destroy()
        }
    }
}
```

Add KDoc explaining that Flow cancellation propagates to collection, only one generation is allowed, lifecycle owners cancel their collecting job in `onStop`, and `close` is called in `onDestroy`.

- [ ] **Step 3: Review the source against the pinned upstream**

Compare imports, method names, default prediction length, state behavior, cleanup, and exception types. Do not claim standalone compilation: this file requires Android, the imported llama.cpp `lib` module, and kotlinx-coroutines.

- [ ] **Step 4: Commit the Kotlin core example**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/demo/android/OnDeviceLlmEngine.kt'
git commit -m 'feat: 增加Android端GGUF推理核心代码'
```

### Task 4: Android generative-model deployment tutorial

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/07-生成式小模型部署到Android.md`

- [ ] **Step 1: Write runtime choice and prerequisites**

Compare llama.cpp/GGUF, LiteRT-LM `.litertlm`, and ONNX Runtime Mobile. Select llama.cpp for the tutorial because Plan 2 already produces GGUF and official llama.cpp includes an Android binding. Note that MediaPipe LLM Inference is maintenance-only and LiteRT-LM is the Google migration path.

For the alternative table, pin the observed LiteRT-LM Android artifact example to `com.google.ai.edge.litertlm:litertlm-android:0.13.1` and label the observation date `2026-07-15`; instruct readers to verify current official compatibility before upgrading.

- [ ] **Step 2: Document NDK/adb CLI verification**

Copy the official CMake shape with Android NDK toolchain, `arm64-v8a`, API 28, disabled unsupported options, build/install, `adb shell mkdir`, binary/model push, and:

```sh
cd /data/local/tmp/llama.cpp
LD_LIBRARY_PATH=lib ./bin/llama-cli -m order-assistant-q4_k_m.gguf -c 2048 -n 128 -p "请用一句话说明如何查询订单"
```

Explain that every external path and commit must match the installed NDK and upstream version; the repository does not execute these commands automatically.

- [ ] **Step 3: Document Android module integration**

Explain importing `examples/llama.android/lib` from the pinned llama.cpp checkout, `implementation(project(":lib"))`, required ABI packaging, copying/importing a selected GGUF into app-private storage, `AiChat`, `InferenceEngine`, and the provided `OnDeviceLlmEngine`.

- [ ] **Step 4: Document model distribution and rollback**

Provide this state flow:

```text
download.tmp -> size check -> SHA-256 -> manifest check
-> atomic rename to models/<version>/model.gguf
-> load smoke test -> switch current-version pointer
-> retain previous known-good version -> later cleanup
```

Cover resumable download, storage preflight, private directory, no APK bundling for large models, network TLS/auth, corrupt download, incompatible schema/runtime, failed load, and rollback.

- [ ] **Step 5: Document lifecycle, error mapping, and performance**

Map missing/corrupt model, unsupported architecture, OOM, context overflow, busy generation, cancellation, background transition, thermal throttling, and native failure. Define a physical-device record with model hash, runtime commit, device/Android, quantization, context, load time, first-token latency, tokens/s, peak memory, temperature, battery delta, cancel latency, and crash/error count.

- [ ] **Step 6: Add runnable manifest commands and manual checklist**

Include all four CLI commands from Task 2, followed by desktop llama-cli, manifest verification, adb plan review, actual adb push, device CLI smoke, Kotlin integration, repeated-generation test, cancellation test, background test, and rollback test.

- [ ] **Step 7: Commit the Android deployment chapter**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/07-生成式小模型部署到Android.md'
git commit -m 'docs: 增加生成式小模型Android部署教程'
```

### Task 5: Navigation and self-check integration

**Files:**
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/README.md`
- Modify: `大模型技术学习教程/12-Android端接入大模型/README.md`
- Modify: `大模型技术学习教程/阶段练习与自检.md`

- [ ] **Step 1: Update stage 17 README**

Add chapter 7, manifest validation, app-private model storage, streaming/cancellation, and physical-device performance outcomes. Extend the architecture diagram with “model manifest -> integrity/resource preflight -> Android runtime.”

- [ ] **Step 2: Add the stage 12 forward link**

Add one concise section directing learners from cloud/API client integration to stage 17 for Java classification and on-device GGUF generation. Do not duplicate deployment commands.

- [ ] **Step 3: Update the self-check**

Require a manifest, hash verification, resource preflight, adb plan review, one real-device smoke result, lifecycle cancellation explanation, and rollback procedure.

- [ ] **Step 4: Commit navigation changes**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/README.md' '大模型技术学习教程/12-Android端接入大模型/README.md' '大模型技术学习教程/阶段练习与自检.md'
git commit -m 'docs: 串联Android端侧模型学习路径'
```

### Task 6: Full repository verification

**Files:**
- Verify all files from all three roadmap plans.

- [ ] **Step 1: Run every Python test file**

```powershell
$tests = rg --files -g 'test_*.py'
foreach ($test in $tests) {
    python $test
    if ($LASTEXITCODE -ne 0) { throw "Python test failed: $test" }
}
```

Expected: every Python test exits zero.

- [ ] **Step 2: Run Node tests**

```powershell
node '.\大模型技术学习教程\11-前端与交互体验\demo\tests\chat_ui_state.test.cjs'
```

Expected: all seven existing tests pass.

- [ ] **Step 3: Run existing and new Java tests in temporary directories**

Compile stage 12 and run `AndroidAiClientDemoTest`. Generate a fresh intent artifact, compile stage 17 `MiniJson`, `IntentModelLoader`, `MobileIntentClassifier`, and `MobileIntentClassifierTest`, then run the new Java test. Expected: both Java test mains print `OK`.

- [ ] **Step 4: Run Python syntax checks**

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m compileall '.\大模型技术学习教程'
```

Expected: no syntax failures. Remove any generated `__pycache__` only after verifying each resolved path is inside the current worktree.

- [ ] **Step 5: Validate local Markdown links**

Run a Python one-liner or existing repository checker that scans Markdown links, ignores `http`, `https`, anchors, and `mailto`, URL-decodes local targets, and verifies paths relative to each Markdown file. Expected output: `BROKEN=0`.

- [ ] **Step 6: Check no heavy artifacts are tracked**

```powershell
git ls-files | rg -i '\.(gguf|safetensors|bin|pt|pth|ckpt|onnx|tflite|litertlm|task)$'
```

Expected: no output unless a pre-existing intentional tiny fixture is documented; do not add model weights.

- [ ] **Step 7: Run Git checks and requirements review**

```powershell
git diff --check
git status --short
```

Confirm every approved design acceptance criterion maps to passing test output or an explicitly manual external smoke checklist. Do not report GPU training, NDK build, or physical-device execution as completed unless those commands were actually run on available hardware.
