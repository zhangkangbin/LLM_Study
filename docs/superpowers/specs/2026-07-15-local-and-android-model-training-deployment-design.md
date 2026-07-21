# 本地与 Android 端侧模型训练部署设计

## 文档关系

本设计扩展并修订《意图识别与分类训练专题设计》。发生冲突时，以本设计为准，尤其是以下范围变化：

1. 数据拆分由 `train/test` 调整为 `train/validation/test`。
2. 分类器不再只在每次 CLI 调用时临时训练，而是能够校准、导出、重新加载和跨语言部署。
3. 原设计中“不包含模型服务部署”的限制仍适用于生产服务平台，但新增轻量的 Java/Android 端侧部署闭环。
4. 新增生成式小模型的 LoRA/QLoRA 训练、GGUF 转换、量化、本地验证和 Android 部署知识。

后续应编写一份新的整合实施计划，替代现有只覆盖 Python 意图分类器的实施计划。

## 背景与目标

现有教程已经覆盖模型定制数据整理、本地模型运行时、私有化网关和 Android 云端 API 接入，但还缺少两条能够从训练一直走到手机推理的完整路径：

```text
分类数据 -> 训练与校准 -> 模型制品 -> Java/Android 离线分类

对话数据 -> LoRA/QLoRA -> 合并与量化 -> GGUF -> Android 端侧生成
```

本次扩展仍保持仓库现有的轻量教程风格：提供核心 Python、Java、Kotlin 代码和命令行验证，不创建完整 Android Studio App，不提交模型权重，不要求仓库测试环境具有 GPU。

完成后，学习者应能：

1. 运行一个详细、可解释、可评估的意图分类训练流程。
2. 将分类器导出为稳定的 JSON 制品，并在纯 Java 中得到一致的推理结果。
3. 理解手机生成模型的选型、数据、LoRA/QLoRA、合并、GGUF 转换和量化流程。
4. 使用 Ollama 和 llama.cpp 在电脑上真实运行本地模型。
5. 使用 llama.cpp 的 Android 路径在手机上验证 GGUF 模型，并理解 Kotlin 集成边界。
6. 对模型文件、设备资源、运行时状态、许可证和回滚策略做基本治理。

## 设计原则

### 按任务选择运行时

意图分类使用标准库实现的字符 n-gram + 多项式朴素贝叶斯。它的重点是意图体系、数据质量、拒识、评估和跨端一致性，不为展示移动框架而引入神经网络依赖。

生成式小模型使用 LoRA/QLoRA 完成参数高效训练，使用 GGUF 和 llama.cpp 完成桌面与 Android 运行。LiteRT-LM 作为 Android 生成模型的重要备选方案讲解，但不作为本次代码主路径。

### 训练和部署通过制品契约解耦

训练代码只负责生成带版本和校验信息的模型制品；端侧代码只依赖制品契约。训练实现、模型参数或运行时可以独立演进，但必须通过版本、哈希和兼容性检查。

### 重型流程可执行但不进入轻量 CI

Python/Java 分类流程和部署清单校验器必须能够在仓库环境中自动测试。LoRA/QLoRA、模型合并、GGUF 转换和 Android native 推理提供真实命令与预期产物，但不在仓库测试中下载权重或执行 GPU 训练。

## 范围

### 包含

1. 现有意图分类训练专题的完整性审查和补充。
2. `train/validation/test` 数据纪律和未知意图样本规则。
3. 训练、阈值校准、拒识、评估、导出、加载和预测 CLI。
4. JSON 分类模型制品及 Python/Java 跨运行时一致性。
5. Java 端侧分类核心代码和命令行测试。
6. 面向手机生成模型的选型、Chat 数据和 LoRA/QLoRA 流程。
7. 合并模型、转换 GGUF、4-bit 量化和桌面 smoke test。
8. Ollama 与 llama.cpp 的真实本地部署命令。
9. llama.cpp Android/Kotlin 核心集成代码和 `adb` 验证路径。
10. 生成模型部署 manifest、哈希、资源门槛、许可证和回滚。
11. LiteRT-LM、ONNX Runtime Mobile 和 llama.cpp 的选型边界。

### 不包含

1. 完整 Android Studio 工程、Compose UI 或应用商店发布。
2. 在仓库中保存基础模型、adapter、GGUF、训练 checkpoint 或缓存。
3. 在仓库测试中安装 PyTorch、Transformers、PEFT、TRL、CUDA 或 Android NDK。
4. 生产级训练平台、自动调参平台、模型注册中心和在线发布系统。
5. 多标签、层级意图、槽位抽取或端到端 Transformer 分类器训练。
6. 在手机上训练生成式大模型；训练在工作站或服务器完成，手机负责推理。
7. 对所有 Android 芯片、GPU/NPU 和厂商 ROM 做兼容性承诺。

## 教程结构

### 阶段十六：训练与模型制品

完善和新增：

```text
大模型技术学习教程/16-微调与模型定制/
  05-意图识别与分类训练实战.md
  06-面向端侧的生成模型训练与量化.md
  demo/
    intent_classifier_demo.py
    sample_intents.jsonl
    intent_parity_cases.jsonl
    tests/
      test_intent_classifier_demo.py
```

阶段十六负责数据、训练、校准、评估和模型制品生成，不负责 Android 生命周期或界面。

### 阶段十七：本地与 Android 部署

新增：

```text
大模型技术学习教程/17-本地模型与私有化部署/
  05-Ollama与llama.cpp本地部署实战.md
  06-意图分类模型部署到Android.md
  07-生成式小模型部署到Android.md
  demo/
    mobile_model_manifest_demo.py
    sample_mobile_model_manifest.json
    android/
      MiniJson.java
      IntentModelLoader.java
      MobileIntentClassifier.java
      MobileIntentClassifierTest.java
      OnDeviceLlmEngine.kt
    tests/
      test_mobile_model_manifest_demo.py
```

阶段十七负责本地运行时、设备预检、制品加载、端侧推理、生命周期、性能和故障处理。

### 导航更新

同步修改：

```text
大模型技术学习教程/16-微调与模型定制/README.md
大模型技术学习教程/17-本地模型与私有化部署/README.md
大模型技术学习教程/12-Android端接入大模型/README.md
大模型技术学习教程/阶段练习与自检.md
```

阶段十二只增加后续学习入口，不重复阶段十七的端侧推理内容。

## 轨道一：意图分类训练与 Android 部署

### 数据契约

JSONL 样本结构：

```json
{"text":"我想取消刚才下的订单","intent":"cancel_order","split":"train"}
```

`split` 允许：

- `train`：只用于估计类别和特征统计量。
- `validation`：只用于选择拒识阈值和检查模型选择。
- `test`：只用于最终一次无偏评估。

`unknown` 不作为普通训练标签。它可以出现在 `validation` 和 `test` 中，用来校准和验证域外拒识。

数据校验必须发现：

1. 缺失字段、空文本、非法 intent 名和非法 split。
2. 完全重复文本、同文异标和跨 split 重复。
3. 规范化后相同但原文不同的泄漏。
4. 训练标签缺少 validation 或 test 覆盖。
5. validation/test 中出现训练集未知的普通标签；`unknown` 除外。
6. 空训练集、空 validation 集或空 test 集。

训练报告记录规范化后的数据 SHA-256 指纹，保证制品能够追溯到输入数据版本。

### 特征与训练

文本规范化契约在 Python 和 Java 中保持一致：

1. 使用与区域无关的小写规则。
2. 以 Unicode code point 遍历文本。
3. 只保留字母和数字，移除空白和标点。
4. 提取字符 unigram 和 bigram。

训练仍使用多项式朴素贝叶斯和拉普拉斯平滑。该模型足够小、可解释，且能够完整导出统计量，不需要在 Android 中嵌入 Python 或第三方 ML Runtime。

### 阈值校准

原设计中的固定默认阈值改为：

1. 在训练集上拟合模型。
2. 在 validation 集上搜索 `confidence_threshold` 和 `margin_threshold`。
3. 使用明确的排序规则选择阈值：先满足最低已接受样本准确率，再最大化 macro F1，最后最大化覆盖率。
4. 如果没有候选阈值满足最低准确率，返回校准失败，不静默选择一个低质量阈值。
5. 阈值确定后写入模型制品；test 集不得参与阈值选择。

阈值搜索范围、步长、最低准确率和最终选择原因写入训练报告，避免出现无法解释的“魔法数字”。

### 评估

评估输出：

1. Accuracy。
2. 每类 Precision、Recall、F1 和 support。
3. Macro Precision、Recall、F1。
4. 真实标签为行、预测标签为列的混淆矩阵。
5. 拒识率和覆盖率。
6. 已接受样本准确率。
7. 错误与拒识明细，包括置信度、margin、候选和原因。

所有零分母返回 `0.0`。报告必须同时区分“错误分类”和“被拒识”，不能用提高拒识率伪造高准确率。

### 分类模型制品

训练命令生成 `intent-model.json`。顶层结构包含：

```json
{
  "schema_version": 1,
  "model_version": "intent-demo-20260715",
  "algorithm": "multinomial_naive_bayes",
  "normalization": {},
  "labels": [],
  "thresholds": {},
  "statistics": {},
  "training_metadata": {},
  "evaluation_summary": {}
}
```

具体字段包括：

- 规范化版本、n-gram 范围和 Unicode 处理策略。
- 标签、类别计数、各类特征计数、总特征数和有序词表。
- 置信度与 margin 阈值。
- 数据指纹、训练时间、样本计数和训练工具版本。
- validation 校准摘要和 test 评估摘要。

导出采用稳定排序和 UTF-8，保证相同输入产生语义一致、便于 diff 的制品。加载时必须拒绝未知 schema、缺失字段、非有限数字、计数为负、标签不一致和阈值越界。

### CLI 契约

命令以真实制品为中心：

```powershell
python intent_classifier_demo.py validate --data sample_intents.jsonl
python intent_classifier_demo.py train --data sample_intents.jsonl --model intent-model.json
python intent_classifier_demo.py evaluate --data sample_intents.jsonl --model intent-model.json
python intent_classifier_demo.py predict --model intent-model.json --text "帮我取消订单"
python intent_classifier_demo.py inspect --model intent-model.json
```

规则：

- `train` 执行数据校验、训练、validation 校准、test 评估和原子写入。
- `evaluate` 只加载已有模型并评估，不重新训练或修改阈值。
- `predict` 只加载已有模型。
- `inspect` 输出制品元数据、标签、阈值和数据指纹，不输出全部特征计数。
- 文件、JSON、校验或校准错误输出结构化错误并返回非零退出码。

### Java 端推理

Java 示例只依赖 JDK：

- `MiniJson` 解析本教程固定模型 schema，不试图成为通用 JSON 库。
- `IntentModelLoader` 验证 schema 和统计量，构造不可变模型对象。
- `MobileIntentClassifier` 实现规范化、n-gram、log 概率、softmax、候选排序和拒识。
- 主方法接受 `--model` 和 `--text`，以 JSON 形式打印结果。

`intent_parity_cases.jsonl` 保存跨运行时测试输入及预期标签/拒识原因。Python 和 Java 都读取同一组样例。验收要求：

1. 预测标签和拒识原因完全相同。
2. 候选排序相同。
3. 概率、置信度和 margin 在指定浮点容差内一致。
4. Python 导出再加载后的结果与训练内存模型一致。

## 轨道二：生成式小模型训练与 Android 部署

### 模型选择

教程以“中文能力可接受、GGUF/llama.cpp 已支持、约 0.5B 到 1B 参数的开放权重 Instruct 模型”为示例范围，不把流程绑定到一个永远不变的最新版模型名称。

选型表至少检查：

1. 基础模型和数据许可证是否允许目标用途、量化和再分发。
2. tokenizer、chat template 和 llama.cpp 转换支持。
3. 参数量、量化后文件大小、KV cache 和目标上下文。
4. 中文、目标领域、结构化输出和安全表现。
5. 最低 Android 版本、arm64-v8a、可用内存和存储空间。
6. 在目标真机而不是模拟器上的首 token 延迟、tokens/s、发热和耗电。

教程允许学习者替换模型 ID，但所有命令必须通过变量集中声明基础模型、输出目录和量化类型，避免散落硬编码。

### 对话数据

训练数据使用 Chat JSONL，每行包含稳定的消息角色：

```json
{"messages":[{"role":"system","content":"你是离线助手"},{"role":"user","content":"如何查看订单"},{"role":"assistant","content":"请打开订单页面查看状态。"}]}
```

数据章节覆盖：

- system/user/assistant 角色和 chat template 对齐。
- train/validation/test 拆分与近重复去除。
- 长度分布、截断率、空回复和角色顺序校验。
- 隐私、版权、许可证和危险内容审查。
- 基础模型回复作为 baseline，不能只报告训练后结果。

### LoRA/QLoRA 训练

教程提供可执行的环境和命令模板，覆盖：

1. 固定依赖版本和随机种子。
2. 加载基础模型与 tokenizer。
3. 4-bit QLoRA 或普通 LoRA 的选择条件。
4. target modules、rank、alpha、dropout、学习率、batch、梯度累积和最大长度。
5. validation loss、任务样例评估、checkpoint 和 early stopping。
6. 保存 adapter、训练参数、基础模型 commit 和评估报告。

仓库不提供伪造的“训练成功”轻量脚本。轻量代码只校验数据或部署清单；真正训练命令明确要求独立 GPU 环境。

### 合并、GGUF 与量化

产物流：

```text
base model + LoRA adapter
-> 合并后的 Hugging Face 模型
-> llama.cpp convert_hf_to_gguf.py
-> F16/BF16 GGUF
-> llama-quantize
-> Q4 GGUF
-> llama-cli smoke test
```

每一步记录输入、输出、工具 commit、命令和 SHA-256。量化前后使用同一组固定 prompts 对比：

- 回答是否为空或乱码。
- chat template 是否生效。
- 任务关键样例是否明显退化。
- 首 token 延迟、tokens/s、峰值内存和输出稳定性。

教程默认讲解 4-bit 量化，但明确指出量化类型应以目标真机实测为准，而不是只比较文件大小。

### 生成模型部署 manifest

`sample_mobile_model_manifest.json` 表达端侧部署契约：

```json
{
  "schema_version": 1,
  "model_id": "example-mobile-llm",
  "runtime": "llama.cpp",
  "format": "gguf",
  "quantization": "Q4",
  "file": {},
  "context": {},
  "device_requirements": {},
  "provenance": {},
  "licenses": {},
  "verification": {}
}
```

校验器检查：

1. 文件名、大小和 SHA-256。
2. 基础模型、adapter、转换工具和量化工具来源。
3. tokenizer/chat template 标识。
4. 上下文长度、最大输出、最低内存、最低存储和 ABI。
5. 模型与数据许可证确认状态。
6. 桌面 smoke test 和真机 smoke test 状态。

校验器可以输出 `adb push`、设备目录和 smoke test 命令计划，但不会自行下载模型或修改设备。

## 本地部署实战

### Ollama

教程给出：

1. 安装后版本和服务健康检查。
2. 拉取一个可替换的小模型。
3. CLI 对话、HTTP 非流式调用和流式调用。
4. 使用 Modelfile 管理 system prompt、参数和本地 GGUF。
5. Python 标准库客户端调用。
6. 模型列表、磁盘占用、服务地址和局域网暴露的安全提醒。
7. 端口冲突、模型不存在、内存不足和请求超时排查。

### llama.cpp

教程给出：

1. 固定源码 commit 后构建。
2. 使用 `llama-cli` 加载 GGUF。
3. 使用 `llama-server` 暴露本地 HTTP 服务。
4. 上下文、线程、batch、GPU offload 和内存之间的关系。
5. 使用同一 GGUF 完成电脑验证和 Android 验证。

Ollama 适合快速体验和 API 接入；llama.cpp 适合理解 GGUF、量化、底层参数和 Android native 路径。

## Android 生成模型核心代码

`OnDeviceLlmEngine.kt` 是核心集成示例，不是完整 App。它围绕 llama.cpp Android binding 展示：

1. 从应用私有目录加载已经校验的 GGUF。
2. 后台初始化推理引擎，禁止阻塞主线程。
3. 使用 Kotlin `Flow` 流式返回 token。
4. 显式状态：`Unloaded`、`Loading`、`Ready`、`Generating`、`Error`、`Closed`。
5. 单会话互斥、取消、超时、关闭和重新加载。
6. 输入长度、上下文、最大输出、温度和线程限制。
7. 将 native 异常映射为可处理的领域错误。

由于仓库不内置 llama.cpp Android AAR/源码，该 Kotlin 文件通过文档契约和官方 API 对照审查；真实模型执行通过桌面 CLI 和 Android `adb` CLI 完成验证。

### 模型分发

大型 GGUF 不放入 APK。正式 App 应：

1. 下载到应用私有目录的临时文件。
2. 支持断点续传和足够磁盘空间检查。
3. 下载完成后校验 SHA-256 和 manifest。
4. 原子切换当前模型版本。
5. 保留一个已知可用版本用于回滚。
6. 在没有活动会话时清理旧模型。

### 设备预检和性能

加载前检查：

- ABI 是否为 manifest 支持的架构。
- 文件和哈希是否正确。
- 可用存储和内存是否达到安全门槛。
- 请求上下文是否超过模型和设备限制。

真机至少记录：

- 模型加载时间。
- 首 token 延迟。
- tokens/s。
- 峰值内存。
- 生成前后温度和电量变化。
- 取消响应时间、错误率和异常退出。

性能结论必须标注设备型号、Android 版本、运行时 commit、模型哈希、量化方式和上下文长度。

## 错误处理

### 分类训练错误

- 数据 schema 或 split 非法：停止训练并返回结构化问题。
- validation 无法选出满足约束的阈值：返回校准失败。
- 模型文件已存在：默认拒绝覆盖，显式 `--force` 才允许。
- 写入中断：使用临时文件和原子替换，避免留下半个 JSON。

### 分类端侧错误

- schema 不支持、字段缺失、计数非法或非有限数字：拒绝加载。
- 文本无有效特征：正常返回 `unknown/no_features`。
- 置信度或 margin 不足：正常拒识，不作为异常。
- 模型加载失败：保留旧模型，不切换当前版本。

### 生成模型错误

- manifest、许可证确认或哈希失败：禁止加载。
- 设备内存或磁盘不足：在 native 加载前返回明确错误。
- native 初始化失败或 OOM：释放会话并建议更小量化、上下文或模型。
- 生成取消：停止 token 流并释放当前推理状态。
- App 进入后台：按客户端策略取消或限制长任务。
- 温度过高或连续长时间生成：允许上层暂停任务并提示用户。

## 测试策略

### Python 分类测试

1. 数据字段、冲突、重复和跨 split 泄漏。
2. Unicode 规范化和 n-gram 稳定性。
3. 朴素贝叶斯训练和候选概率。
4. validation 阈值校准不读取 test。
5. 拒识、覆盖率、已接受准确率和分类指标。
6. 模型导出、稳定排序、重新加载和损坏制品。
7. CLI 成功、参数错误和退出码。

### Java 分类测试

1. 编译所有 Java 示例。
2. 加载 Python 生成的临时模型制品。
3. 执行共享 parity cases。
4. 比较标签、原因、排序和浮点容差。
5. 验证未知 schema、缺失字段和非法计数被拒绝。

### 生成部署测试

1. manifest 合法与非法字段。
2. SHA-256、文件大小、上下文和设备门槛检查。
3. 生成的 `adb` 计划不包含未转义的用户输入。
4. 文档中的命令、文件名和章节链接与代码保持一致。

### 全仓库验证

1. 所有 Python `test_*.py`。
2. 阶段十一 Node 测试。
3. 阶段十二和新增阶段十七 Java 编译测试。
4. Python `compileall`。
5. Markdown 本地链接检查。
6. `git diff --check` 和工作树状态检查。

不自动执行 Ollama 拉取、GPU 训练、GGUF 转换、NDK 构建或 `adb push`，这些步骤需要外部依赖、模型权重或真实设备，使用手工 smoke test 清单验收。

## 验收标准

1. 意图分类数据具有 train、validation 和 test，且 test 不参与阈值选择。
2. 分类器能够训练一次并导出 JSON，后续 evaluate/predict 只加载制品。
3. Python 和 Java 对共享样例返回相同标签、拒识原因和候选顺序。
4. 分类报告同时包含分类指标、拒识率、覆盖率和已接受准确率。
5. 损坏或不兼容的模型制品不会被 Python 或 Java 静默接受。
6. 生成模型章节覆盖数据、LoRA/QLoRA、验证、合并、GGUF 和量化。
7. Ollama 与 llama.cpp 章节包含真实可执行的本地运行和 HTTP 命令。
8. Android 章节包含可编译测试的 Java 分类代码和边界明确的 Kotlin 生成代码。
9. manifest 能描述并校验模型来源、哈希、资源门槛、许可证和验证状态。
10. 教程不提交权重，不让轻量 CI 依赖 GPU、NDK 或真实手机。
11. 新增测试和仓库原有 Python、Java、Node 测试全部通过。
12. 阶段 README、练习、自检、章节内容、文件名和命令保持一致。

## 官方参考资料

- Ollama API：<https://docs.ollama.com/api/introduction>
- llama.cpp Android：<https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md>
- llama.cpp 构建：<https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md>
- LiteRT-LM：<https://github.com/google-ai-edge/LiteRT-LM>
- LiteRT-LM Kotlin API：<https://github.com/google-ai-edge/LiteRT-LM/blob/main/docs/api/kotlin/getting_started.md>
- ONNX Runtime Mobile：<https://onnxruntime.ai/docs/tutorials/mobile/>

实现教程时，应固定或记录真实使用的模型、训练库和转换工具版本；官方文档链接用于解释当前能力，不以 `latest.release` 作为可复现构建版本。
