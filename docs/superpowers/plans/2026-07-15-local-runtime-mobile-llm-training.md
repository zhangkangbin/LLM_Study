# Local Runtime and Mobile LLM Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add executable local-model deployment knowledge and a complete workstation-to-GGUF LoRA/QLoRA training path for models intended to run on Android.

**Architecture:** A standard-library Chat JSONL validator makes the data chapter runnable in lightweight CI. Markdown chapters contain pinned-environment training, merge, conversion, quantization, Ollama, and llama.cpp commands; heavyweight steps remain explicit manual workflows because they require external repositories, weights, and GPU hardware.

**Tech Stack:** Python 3 standard library, JSONL, Hugging Face Transformers/TRL/PEFT/bitsandbytes, Ollama, llama.cpp, GGUF, Markdown, PowerShell/bash command examples.

---

## File map

- Create `大模型技术学习教程/16-微调与模型定制/demo/mobile_llm_dataset_demo.py`: Chat JSONL validation and summary CLI.
- Create `大模型技术学习教程/16-微调与模型定制/demo/sample_mobile_llm_chat.jsonl`: small train/validation/test conversational dataset.
- Create `大模型技术学习教程/16-微调与模型定制/demo/tests/test_mobile_llm_dataset_demo.py`: data-contract tests.
- Create `大模型技术学习教程/16-微调与模型定制/06-面向端侧的生成模型训练与量化.md`: model selection, LoRA/QLoRA, evaluation, merge, GGUF, and quantization.
- Create `大模型技术学习教程/17-本地模型与私有化部署/05-Ollama与llama.cpp本地部署实战.md`: real local runtime commands.
- Modify `大模型技术学习教程/16-微调与模型定制/README.md`: generative training outcome and chapter link.
- Modify `大模型技术学习教程/17-本地模型与私有化部署/README.md`: local deployment outcome and chapter link.
- Modify `大模型技术学习教程/阶段练习与自检.md`: local deployment and mobile-model training exercise.

### Task 1: Chat JSONL contract

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_mobile_llm_dataset_demo.py`
- Create: `大模型技术学习教程/16-微调与模型定制/demo/mobile_llm_dataset_demo.py`

- [ ] **Step 1: Write failing validation tests**

Use records shaped as:

```python
VALID_ROW = {
    "id": "train-001",
    "split": "train",
    "messages": [
        {"role": "system", "content": "你是离线助手"},
        {"role": "user", "content": "如何查看订单"},
        {"role": "assistant", "content": "请打开订单页面查看状态。"},
    ],
}
```

Test missing/duplicate IDs, invalid split, empty split, invalid role order, empty content, missing final assistant reply, consecutive identical roles, exact conversation duplicate, cross-split normalized duplicate, excessive character length, and valid rows.

- [ ] **Step 2: Run tests to verify RED**

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\tests\test_mobile_llm_dataset_demo.py'
```

Expected: import failure because the validator does not exist.

- [ ] **Step 3: Implement the validator APIs**

```python
VALID_SPLITS = frozenset({"train", "validation", "test"})
VALID_ROLES = frozenset({"system", "user", "assistant"})
```

Implement `load_conversations(path)` by reading nonblank UTF-8 JSONL objects and including the source line in every `ValueError`. Implement `validate_conversations(rows, *, max_characters=4096)` with issue objects containing `code`, `message`, and sorted `indexes`; sort results by `(code, indexes)`. Conversation order permits optional leading `system`, then one or more `user/assistant` pairs, and requires the last role to be `assistant`.

Implement `summarize_conversations(rows)` with split counts, total conversations/messages, and character `min`, `max`, and arithmetic `mean`; return zeros for all length values when no messages exist.

- [ ] **Step 4: Run tests to verify GREEN**

Expected: all data-contract tests pass.

- [ ] **Step 5: Commit the Chat data contract**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/mobile_llm_dataset_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_mobile_llm_dataset_demo.py'
git commit -m 'feat: 增加端侧生成模型数据校验'
```

### Task 2: Sample Chat data and CLI

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/demo/sample_mobile_llm_chat.jsonl`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/mobile_llm_dataset_demo.py`
- Modify: `大模型技术学习教程/16-微调与模型定制/demo/tests/test_mobile_llm_dataset_demo.py`

- [ ] **Step 1: Add non-leaking sample conversations**

Create at least eight train, two validation, and two test conversations. Cover order lookup, cancellation, refund, human handoff, concise summarization, refusal of unsafe requests, and offline limitation disclosure. Use different user wording and assistant text in every split.

- [ ] **Step 2: Write failing CLI tests**

Test:

```text
validate --data PATH --max-characters 4096
summarize --data PATH
```

Valid data returns JSON and exit `0`; validation issues return JSON and exit `2`; malformed JSON returns a line-numbered JSON error and exit `2`.

- [ ] **Step 3: Implement the CLI**

Default `--data` to the sibling sample file. `validate` outputs `valid`, `count`, and `issues`; `summarize` validates first, then outputs split and length statistics.

- [ ] **Step 4: Run tests and smoke commands**

```powershell
$demo = '.\大模型技术学习教程\16-微调与模型定制\demo\mobile_llm_dataset_demo.py'
python $demo validate
python $demo summarize
```

Expected: two valid JSON documents and exit code zero.

- [ ] **Step 5: Commit sample data and CLI**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/demo/sample_mobile_llm_chat.jsonl' '大模型技术学习教程/16-微调与模型定制/demo/mobile_llm_dataset_demo.py' '大模型技术学习教程/16-微调与模型定制/demo/tests/test_mobile_llm_dataset_demo.py'
git commit -m 'feat: 增加端侧生成模型示例数据'
```

### Task 3: Mobile-oriented LoRA/QLoRA training chapter

**Files:**
- Create: `大模型技术学习教程/16-微调与模型定制/06-面向端侧的生成模型训练与量化.md`

- [ ] **Step 1: Write prerequisites and model-selection matrix**

Cover: 0.5B–1B starting range; Chinese and task baseline; open-weight and dataset licenses; tokenizer/chat-template compatibility; llama.cpp conversion support; model/adapter revision capture; disk/RAM/KV-cache estimates; why phone training is out of scope.

Use `Qwen/Qwen3-0.6B` as the concrete small-model command example while making `MODEL_ID` configurable. State that users must re-check the model card and llama.cpp support before using a different revision.

- [ ] **Step 2: Add a reproducible training environment**

Document a dedicated virtual environment and a lock capture:

```powershell
python -m venv .venv-mobile-llm
.\.venv-mobile-llm\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install 'transformers' 'datasets' 'accelerate' 'trl[peft]' 'bitsandbytes'
pip freeze | Set-Content -Encoding UTF8 training-requirements-lock.txt
```

Explain that the lock from the successful run, CUDA/driver version, GPU model, Python version, base-model revision, seed, and command must be stored with the experiment report; the repository does not commit that environment-specific lock.

- [ ] **Step 3: Add complete LoRA and QLoRA code listings**

The chapter must include a runnable `SFTTrainer` listing that:

- loads local JSONL with `load_dataset("json", data_files=...)`;
- selects `train` and `validation` by the row `split` field;
- uses `LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")`;
- uses `SFTConfig` with a fixed seed, evaluation/save strategy, `assistant_only_loss=True`, max length, gradient accumulation, and output directory;
- uses `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)` only on the QLoRA branch;
- calls `trainer.train()` and `trainer.save_model(ADAPTER_DIR)`;
- writes training arguments and evaluation metrics beside the adapter.

Explain how to inspect the target module names instead of blindly copying `q_proj/v_proj`, and why validation loss is insufficient without fixed task prompts.

- [ ] **Step 4: Add baseline, evaluation, and merge instructions**

Define a fixed JSONL prompt suite and compare base, adapter, and merged model for nonempty output, task correctness, refusal behavior, format, and latency. Include `PeftModel.from_pretrained`, assign the result of `merge_and_unload()`, then `save_pretrained(..., safe_serialization=True)` and save the tokenizer.

- [ ] **Step 5: Add exact GGUF and quantization flow**

Use a pinned llama.cpp checkout recorded by `git rev-parse HEAD` and these command forms:

```powershell
python .\convert_hf_to_gguf.py 'C:\models\mobile-llm-merged' --outfile 'C:\models\mobile-llm-f16.gguf' --outtype f16
.\build\bin\Release\llama-quantize.exe 'C:\models\mobile-llm-f16.gguf' 'C:\models\mobile-llm-q4_k_m.gguf' Q4_K_M
.\build\bin\Release\llama-cli.exe -m 'C:\models\mobile-llm-q4_k_m.gguf' -c 2048 -n 128 -p '请用一句话说明如何查询订单'
Get-FileHash -Algorithm SHA256 'C:\models\mobile-llm-q4_k_m.gguf'
```

Document Windows/Linux executable-path differences, quantized-versus-merged prompt comparison, chat-template verification, and artifact records.

- [ ] **Step 6: Commit the training chapter**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/06-面向端侧的生成模型训练与量化.md'
git commit -m 'docs: 增加端侧生成模型训练与量化教程'
```

### Task 4: Ollama and llama.cpp local deployment chapter

**Files:**
- Create: `大模型技术学习教程/17-本地模型与私有化部署/05-Ollama与llama.cpp本地部署实战.md`

- [ ] **Step 1: Add Ollama install and health checks**

Document platform-specific installation links, then use `$Model = 'qwen3:0.6b'` in PowerShell examples for `ollama --version`, `ollama list`, `ollama ps`, `ollama pull $Model`, and `ollama run $Model`. Link the official Ollama model page and explain how to replace the variable after checking size, license, and capability.

- [ ] **Step 2: Add real API calls**

Include PowerShell `Invoke-RestMethod`, `curl.exe`, and Python `urllib.request` examples for `/api/generate`, both `stream:false` and line-delimited streaming. Handle connection refusal, HTTP error body, UTF-8 decoding, timeout, and cancellation.

- [ ] **Step 3: Add Modelfile and security sections**

Provide a concrete Modelfile using `FROM`, `SYSTEM`, `PARAMETER temperature`, and `PARAMETER num_ctx`. Explain local GGUF import, service bind address, firewall, authentication gateway, sensitive logs, and why raw Ollama should not be exposed directly to a public network.

- [ ] **Step 4: Add llama.cpp CLI and server sections**

Document clone, commit capture, CMake build, `llama-cli`, `llama-server`, health/API smoke calls, `-c`, `-n`, `-t`, `-b`, and GPU-offload flags. Include Windows executable layout and Linux/macOS layout. Show the same Q4 GGUF used by the training chapter.

- [ ] **Step 5: Add troubleshooting and benchmark records**

Use a table for model-not-found, unsupported GGUF, OOM, slow first token, low tokens/s, garbled chat output, port conflict, and timeout. Define a benchmark record containing runtime commit, model hash, quantization, CPU/GPU, context, prompt tokens, output tokens, first-token latency, tokens/s, and peak memory.

- [ ] **Step 6: Commit the local deployment chapter**

```powershell
git add -- '大模型技术学习教程/17-本地模型与私有化部署/05-Ollama与llama.cpp本地部署实战.md'
git commit -m 'docs: 增加Ollama与llama.cpp本地部署实战'
```

### Task 5: Plan 2 navigation and verification

**Files:**
- Modify: `大模型技术学习教程/16-微调与模型定制/README.md`
- Modify: `大模型技术学习教程/17-本地模型与私有化部署/README.md`
- Modify: `大模型技术学习教程/阶段练习与自检.md`

- [ ] **Step 1: Update stage navigation**

Add stage 16 outcome and chapter 6 link; add stage 17 outcome and chapter 5 link. Preserve existing numbering and relative-link style.

- [ ] **Step 2: Update exercises**

Require learners to validate Chat JSONL, record a base-model baseline, describe one LoRA and one QLoRA choice, produce a GGUF manifest draft, run one Ollama HTTP request, and compare Ollama with llama.cpp.

- [ ] **Step 3: Run lightweight tests**

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\tests\test_mobile_llm_dataset_demo.py'
python '.\大模型技术学习教程\16-微调与模型定制\demo\mobile_llm_dataset_demo.py' validate
python '.\大模型技术学习教程\16-微调与模型定制\demo\mobile_llm_dataset_demo.py' summarize
python -m compileall '.\大模型技术学习教程\16-微调与模型定制\demo'
git diff --check
```

Expected: tests and commands pass; no GPU package is imported by the lightweight validator.

- [ ] **Step 4: Check documentation consistency**

Verify every command names an input and output, every external tool is linked to official documentation, no model weight is tracked, and local Markdown links resolve.

- [ ] **Step 5: Commit navigation**

```powershell
git add -- '大模型技术学习教程/16-微调与模型定制/README.md' '大模型技术学习教程/17-本地模型与私有化部署/README.md' '大模型技术学习教程/阶段练习与自检.md'
git commit -m 'docs: 串联生成模型训练与本地部署路径'
```
