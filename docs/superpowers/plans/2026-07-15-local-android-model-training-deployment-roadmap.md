# Local and Android Model Training Deployment Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved two-track tutorial from model training through local and Android inference without adding model weights, a full Android app, or GPU requirements to repository CI.

**Architecture:** The work is split into three independently testable plans. Plan 1 produces a portable intent-classification artifact and Java runtime; Plan 2 adds executable local-model and LoRA/QLoRA training knowledge; Plan 3 adds the Android generative-model manifest, Kotlin integration example, and end-to-end verification.

**Tech Stack:** Python 3 standard library, Java/JDK, Kotlin example code, Markdown, JSON/JSONL, Ollama, llama.cpp/GGUF, optional Hugging Face Transformers/TRL/PEFT/bitsandbytes for GPU training.

---

## Plan order

1. [Portable intent classification and Java deployment](./2026-07-15-portable-intent-classification-deployment.md)
2. [Local runtime and mobile generative-model training](./2026-07-15-local-runtime-mobile-llm-training.md)
3. [Android generative-model deployment](./2026-07-15-android-generative-model-deployment.md)

Plan 1 and Plan 2 do not share implementation state and can be reviewed independently. Execute Plan 3 after Plan 2 because its manifest and Android chapter refer to the GGUF and quantization flow introduced there.

## Integration gates

- [ ] **Gate 1: Complete Plan 1**

Expected evidence: Python training exports `intent-model.json`; Java loads it; shared parity cases pass.

- [ ] **Gate 2: Complete Plan 2**

Expected evidence: Chat JSONL validation runs offline; training/merge/GGUF/quantization commands are documented; Ollama and llama.cpp commands are internally consistent.

- [ ] **Gate 3: Complete Plan 3**

Expected evidence: manifest validation and command planning pass; Kotlin wrapper matches the pinned llama.cpp Android API; Android deployment and rollback instructions are complete.

- [ ] **Gate 4: Run final repository verification**

Run the exact full-suite commands in Plan 3. Expected: all lightweight Python, Java, Node, syntax, link, and Git checks pass. GPU training, model downloads, NDK builds, and `adb` mutations remain explicit manual smoke tests.

## Commit strategy

Each task in the child plans ends with a focused commit. Do not squash during implementation; the commits isolate data validation, model math, artifact handling, Java parity, training documentation, local deployment, manifest validation, and Android integration for review.

