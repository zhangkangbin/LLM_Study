# 生成式小模型部署到 Android

阶段 16 已经完成 LoRA/QLoRA、合并、GGUF 转换和 Q4_K_M 量化；本章把同一个 GGUF 放到 Android 真机，用命令行先验证，再接入 Kotlin。先阅读[面向端侧的生成模型训练与量化](../16-微调与模型定制/06-面向端侧的生成模型训练与量化.md)和[Ollama 与 llama.cpp 本地部署实战](./05-Ollama与llama.cpp本地部署实战.md)。

本章只提供核心 Kotlin 集成片段和命令行验证，不创建完整 Android 工程、UI 或 Gradle wrapper。仓库也不会自动执行 NDK 构建、`adb` 或真机测试，更不会下载或提交 GGUF。手机只负责推理；训练、合并与量化仍在工作站完成。

> **版本边界**：llama.cpp 固定到 commit `505b1ed15ca80e2a19f12ff4ac365e40fb374053`。模型文件统一写作 `order-assistant-q4_k_m.gguf`。如果更换 runtime commit、NDK、GGUF 或 chat template，必须作为新组合重新完成桌面与真机验收。

## 1. 运行时选择

| 方案 | 模型格式 | Android 集成 | 适合情况 | 本章结论 |
| --- | --- | --- | --- | --- |
| llama.cpp | GGUF | 官方仓库包含 `examples/llama.android/lib`；也能交叉编译 CLI | 已经有 GGUF，希望桌面、adb、App 使用同一 runtime 系列 | **采用** |
| LiteRT-LM | `.litertlm` | 官方 Kotlin API，面向 LiteRT CPU/GPU/NPU 后端 | 模型已在官方兼容矩阵内，愿意建立另一条转换与评测链 | 作为后续替代方案 |
| ONNX Runtime Mobile | ONNX | 官方 Android AAR 与移动端执行提供程序 | 已有受支持的 ONNX 图，并能自行处理 tokenizer、chat template、KV cache | 不直接加载本章 GGUF |

选择 llama.cpp 不是声称它在所有手机上最快，而是因为前章已经产出 GGUF，而且官方仓库同时给出 [Android binding](https://github.com/ggml-org/llama.cpp/tree/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android) 和 [NDK 交叉编译说明](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/docs/android.md)。这样可以把格式转换变量降到最低。

Google 官方 [MediaPipe LLM Inference Android 指南](https://developers.google.com/edge/mediapipe/solutions/genai/llm_inference/android)已明确标注该 API 进入 maintenance-only mode，并建议 Android 项目迁移到 [LiteRT-LM Kotlin API](https://developers.google.com/edge/litert-lm/android)。因此不要为新项目另起一条 MediaPipe `.task` 路线。

截至 **2026-07-15**，本计划观察并记录过 Android artifact：

```kotlin
implementation("com.google.ai.edge.litertlm:litertlm-android:0.13.1")
```

这只是带观察日期的替代方案记录，本教程不实现它。官方文档目前允许从 Google Maven 选择版本；升级前必须重新检查 artifact、`.litertlm` 模型、后端、ABI、Android 版本和设备的官方兼容性，不能把上面的历史版本或 `latest.release` 当作可复现锁定。

ONNX Runtime Mobile 的入口见[官方 Mobile 文档](https://onnxruntime.ai/docs/get-started/with-mobile.html)和[官方 Android 构建文档](https://onnxruntime.ai/docs/build/android.html)。GGUF 不能直接交给 ONNX Runtime；转换图、tokenizer、模板和生成循环都属于另一套需独立验收的制品链。

## 2. 前置条件与资源门禁

### 2.1 工作站和手机

准备以下环境：

- 64 位工作站、Git、CMake、Android SDK Platform Tools（`adb`）和 Android NDK。
- 一台允许 USB 调试的 `arm64-v8a` 真机；模拟器不能替代内存、温升和取消延迟验收。
- 已在桌面 `llama-cli` 通过固定 Prompt suite 的真实 `order-assistant-q4_k_m.gguf`。
- 与 GGUF 配套的真实部署 manifest：大小、SHA-256、基座 revision、adapter SHA、llama.cpp commit、量化、上下文和许可状态均已填写。
- 模型与训练数据许可已经人工复核，允许目标 App 的使用与分发方式。

仓库中的[示例 manifest](./demo/sample_mobile_model_manifest.json)写了 `arm64-v8a`、API 28、3 GB 内存和 1 GB 可用空间，但这些只是演示校验器的**最低示例值**，不是速度、稳定性或可运行承诺。实际门槛要由真机测试反推，并写入真实 manifest。

还要区分两个 Android 门槛：

| 路径 | 固定提交中的门槛 | 含义 |
| --- | --- | --- |
| 本章交叉编译的 adb CLI | `ANDROID_PLATFORM=android-28` | CLI 二进制的 NDK 目标 API |
| 固定提交的 `examples/llama.android/lib` | `minSdk=33` | 官方 Kotlin binding 模块的原始 Gradle 门槛 |

固定提交的 `lib/build.gradle.kts` 还声明 `compileSdk=36`、NDK `29.0.13113456`、CMake `3.31.6`、Java/Kotlin 17。manifest 的 API 28 不能覆盖这些模块约束。直接导入官方 binding 时，有效 App 下限按 **API 33**；若要下探，只能维护自己的移植分支并重新做 AGP、JNI、ART 和真机验证，本教程不作兼容承诺。

### 2.2 加载前门禁

对每个“模型 + runtime + 设备”组合至少检查：

1. ABI 包含 `arm64-v8a`，Android API 同时满足 CLI 或 App binding 的真实下限。
2. 文件大小和 SHA-256 与可信 manifest 完全一致；SHA 只证明字节一致，不能证明发布者身份。
3. `filesDir` 的可用空间覆盖临时下载、当前版、上一个 known-good 版本和运行期余量。
4. RAM 能容纳权重、KV cache、runtime、输入输出缓冲和 App 本身；不能用“GGUF 文件只有几百 MB”推导峰值内存。
5. manifest schema、runtime commit、GGUF 架构、量化、chat template 与上下文上限兼容。
6. 设备温度、电量和系统内存状态允许开始；低内存或过热时延迟加载或拒绝任务。

## 3. 固定源码并交叉编译 CLI

以下命令是给目标工作站执行的复现实验，不会被仓库自动运行。`ANDROID_NDK_HOME` 必须指向已安装 NDK 根目录。命令对源码、build、install 和 staging 目录都采用“已存在就失败”，避免旧产物混入新实验。

固定提交的 Android 文档明确关闭 `GGML_OPENMP` 与 `GGML_LLAMAFILE`；这里还使用该提交真实存在的 `LLAMA_OPENSSL`、tests、server、UI、examples 和 app 选项，收紧到 CLI 所需工具。该提交把 `tools/cli` 放在 `LLAMA_BUILD_SERVER` 条件内，所以 server gate 必须为 `ON`，同时关闭 UI，最终 staging 仍只取 `llama-cli`。升级提交前先查对应版本的 CMake 选项，不要照搬。

### 3.1 Windows PowerShell

```powershell
$ErrorActionPreference = 'Stop'
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$SourceRoot = 'C:\src'
$LlamaRepo = Join-Path $SourceRoot "llama.cpp-$LlamaCommit"
$BuildDir = Join-Path $LlamaRepo 'build-android'
$InstallDir = Join-Path $LlamaRepo 'install-android'
$StageDir = "C:\staging\llama-android-$LlamaCommit"
$Ndk = $env:ANDROID_NDK_HOME

if ([string]::IsNullOrWhiteSpace($Ndk)) { throw 'ANDROID_NDK_HOME 未设置' }
$Toolchain = Join-Path $Ndk 'build\cmake\android.toolchain.cmake'
if (-not (Test-Path -LiteralPath $Toolchain -PathType Leaf)) {
  throw "NDK toolchain 不存在: $Toolchain"
}
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
  New-Item -ItemType Directory -Path $SourceRoot | Out-Null
}
foreach ($path in @($LlamaRepo, $StageDir)) {
  if (Test-Path -LiteralPath $path) { throw "目录已存在，请人工换 fresh 路径: $path" }
}

git clone --filter=blob:none --no-checkout `
  https://github.com/ggml-org/llama.cpp.git $LlamaRepo
if ($LASTEXITCODE -ne 0) { throw 'clone llama.cpp 失败' }
git -C $LlamaRepo fetch --depth 1 origin $LlamaCommit
if ($LASTEXITCODE -ne 0) { throw 'fetch pinned commit 失败' }
git -C $LlamaRepo checkout --detach $LlamaCommit
if ($LASTEXITCODE -ne 0) { throw 'checkout pinned commit 失败' }

$ActualCommit = (git -C $LlamaRepo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualCommit -ne $LlamaCommit) {
  throw "llama.cpp commit 不一致: $ActualCommit"
}
foreach ($path in @($BuildDir, $InstallDir)) {
  if (Test-Path -LiteralPath $path) { throw "fresh 输出目录已存在: $path" }
}

cmake -S $LlamaRepo -B $BuildDir `
  "-DCMAKE_TOOLCHAIN_FILE=$Toolchain" `
  '-DANDROID_ABI=arm64-v8a' `
  '-DANDROID_PLATFORM=android-28' `
  '-DCMAKE_C_FLAGS=-march=armv8.7a' `
  '-DCMAKE_CXX_FLAGS=-march=armv8.7a' `
  '-DCMAKE_BUILD_TYPE=Release' `
  '-DGGML_OPENMP=OFF' `
  '-DGGML_LLAMAFILE=OFF' `
  '-DLLAMA_OPENSSL=OFF' `
  '-DLLAMA_BUILD_TESTS=OFF' `
  '-DLLAMA_BUILD_SERVER=ON' `
  '-DLLAMA_BUILD_UI=OFF' `
  '-DLLAMA_BUILD_EXAMPLES=OFF' `
  '-DLLAMA_BUILD_APP=OFF' `
  '-DLLAMA_BUILD_TOOLS=ON' `
  '-DLLAMA_TOOLS_INSTALL=ON'
if ($LASTEXITCODE -ne 0) { throw 'Android CMake configure 失败' }

cmake --build $BuildDir --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw 'Android CMake build 失败' }
cmake --install $BuildDir --prefix $InstallDir --config Release
if ($LASTEXITCODE -ne 0) { throw 'Android CMake install 失败' }

$LlamaCli = Join-Path $InstallDir 'bin\llama-cli'
$InstalledLibDir = Join-Path $InstallDir 'lib'
if (-not (Test-Path -LiteralPath $LlamaCli -PathType Leaf)) {
  throw "install 未生成 llama-cli: $LlamaCli"
}
$RuntimeLibs = @(Get-ChildItem -LiteralPath $InstalledLibDir -Filter '*.so' -File)
if ($RuntimeLibs.Count -eq 0) { throw "install 未生成共享库: $InstalledLibDir" }

$StageBin = Join-Path $StageDir 'bin'
$StageLib = Join-Path $StageDir 'lib'
New-Item -ItemType Directory -Path $StageBin | Out-Null
New-Item -ItemType Directory -Path $StageLib | Out-Null
Copy-Item -LiteralPath $LlamaCli -Destination $StageBin
$RuntimeLibs | Copy-Item -Destination $StageLib

if (-not (Test-Path -LiteralPath (Join-Path $StageBin 'llama-cli') -PathType Leaf)) {
  throw 'staging llama-cli 失败'
}
Write-Output "PINNED_COMMIT=$ActualCommit"
Write-Output "STAGING=$StageDir"
```

输入是固定 commit 和本机 NDK；输出是 `$StageDir\bin\llama-cli` 与 `$StageDir\lib\*.so`。不要把 `build-android`、`install-android` 或 staging 目录提交到教程仓库。

### 3.2 Linux / macOS

```bash
set -euo pipefail

LLAMA_COMMIT='505b1ed15ca80e2a19f12ff4ac365e40fb374053'
SOURCE_ROOT="${HOME}/src"
LLAMA_REPO="${SOURCE_ROOT}/llama.cpp-${LLAMA_COMMIT}"
BUILD_DIR="${LLAMA_REPO}/build-android"
INSTALL_DIR="${LLAMA_REPO}/install-android"
STAGE_DIR="${HOME}/staging/llama-android-${LLAMA_COMMIT}"
ANDROID_NDK="${ANDROID_NDK_HOME:?ANDROID_NDK_HOME is required}"
TOOLCHAIN="${ANDROID_NDK}/build/cmake/android.toolchain.cmake"

test -f "$TOOLCHAIN"
mkdir -p "$SOURCE_ROOT" "$(dirname "$STAGE_DIR")"
test ! -e "$LLAMA_REPO" || { echo "source path already exists" >&2; exit 1; }
test ! -e "$STAGE_DIR" || { echo "staging path already exists" >&2; exit 1; }

git clone --filter=blob:none --no-checkout \
  https://github.com/ggml-org/llama.cpp.git "$LLAMA_REPO"
git -C "$LLAMA_REPO" fetch --depth 1 origin "$LLAMA_COMMIT"
git -C "$LLAMA_REPO" checkout --detach "$LLAMA_COMMIT"
ACTUAL_COMMIT="$(git -C "$LLAMA_REPO" rev-parse HEAD)"
test "$ACTUAL_COMMIT" = "$LLAMA_COMMIT"
test ! -e "$BUILD_DIR"
test ! -e "$INSTALL_DIR"

cmake -S "$LLAMA_REPO" -B "$BUILD_DIR" \
  "-DCMAKE_TOOLCHAIN_FILE=$TOOLCHAIN" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-28 \
  '-DCMAKE_C_FLAGS=-march=armv8.7a' \
  '-DCMAKE_CXX_FLAGS=-march=armv8.7a' \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_OPENMP=OFF \
  -DGGML_LLAMAFILE=OFF \
  -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_BUILD_UI=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_APP=OFF \
  -DLLAMA_BUILD_TOOLS=ON \
  -DLLAMA_TOOLS_INSTALL=ON

cmake --build "$BUILD_DIR" --config Release --parallel
cmake --install "$BUILD_DIR" --prefix "$INSTALL_DIR" --config Release
test -x "$INSTALL_DIR/bin/llama-cli"
compgen -G "$INSTALL_DIR/lib/*.so" >/dev/null

mkdir -p "$STAGE_DIR/bin" "$STAGE_DIR/lib"
cp "$INSTALL_DIR/bin/llama-cli" "$STAGE_DIR/bin/"
cp "$INSTALL_DIR"/lib/*.so "$STAGE_DIR/lib/"
printf 'PINNED_COMMIT=%s\nSTAGING=%s\n' "$ACTUAL_COMMIT" "$STAGE_DIR"
```

macOS 主机也使用 Android NDK toolchain，生成的仍是 Android `arm64-v8a` ELF，不是 macOS 可执行文件。

## 4. manifest 校验与安全的 adb 计划

仓库提供[manifest 工具](./demo/mobile_model_manifest_demo.py)。它只打印 JSON，`plan-adb` 只返回 argv 数组，**绝不执行 adb**。

### 4.1 示例 manifest 只能演示 schema 和资源预检

在仓库根目录执行：

```powershell
$Demo = (Resolve-Path -LiteralPath `
  '.\大模型技术学习教程\17-本地模型与私有化部署\demo\mobile_model_manifest_demo.py').Path
$ExampleManifest = (Resolve-Path -LiteralPath `
  '.\大模型技术学习教程\17-本地模型与私有化部署\demo\sample_mobile_model_manifest.json').Path

python $Demo validate --manifest $ExampleManifest --allow-example
if ($LASTEXITCODE -ne 0) { throw '示例 manifest schema 校验失败' }

python $Demo preflight --manifest $ExampleManifest `
  --abi arm64-v8a --android-api 35 `
  --memory-mb 8192 --free-storage-mb 4096 --allow-example
if ($LASTEXITCODE -ne 0) { throw '示例资源预检失败' }
```

成功输出是 `{"ok":true,...}`。该 sample 的 `size_bytes=0`、全零 SHA 和两项 smoke flag 都是占位符；它不能用于 `verify-file`、`plan-adb` 或发布。

### 4.2 真实 manifest 才能校验文件并生成计划

先把真实 manifest 和真实 GGUF 放在 `C:\models`。工具为避免路径注入，`--model` 只接受与 manifest 完全一致的安全文件名，因此先切到模型目录；`$Demo` 已解析成绝对路径。

```powershell
$RealManifest = 'C:\models\order-assistant.manifest.json'
$ModelDirectory = 'C:\models'
$ModelName = 'order-assistant-q4_k_m.gguf'
$RemoteDirectory = '/data/local/tmp/llama.cpp'
$PlanFile = 'C:\models\order-assistant-adb-plan.json'

if (-not (Test-Path -LiteralPath $RealManifest -PathType Leaf)) {
  throw "真实 manifest 不存在: $RealManifest"
}
if (-not (Test-Path -LiteralPath (Join-Path $ModelDirectory $ModelName) -PathType Leaf)) {
  throw "真实 GGUF 不存在: $ModelName"
}

Push-Location $ModelDirectory
try {
  python $Demo verify-file --manifest $RealManifest --model $ModelName
  if ($LASTEXITCODE -ne 0) { throw '真实 GGUF 大小/SHA 校验失败' }

  $PlanJson = python $Demo plan-adb --manifest $RealManifest `
    --model $ModelName --remote-directory $RemoteDirectory `
    --context-tokens 2048
  if ($LASTEXITCODE -ne 0) { throw '生成 adb 计划失败' }
  $PlanJson | Set-Content -LiteralPath $PlanFile -Encoding UTF8
  $PlanJson
} finally {
  Pop-Location
}
```

四个子命令的输入/输出边界如下：

| 子命令 | 输入 | 成功输出 | 是否改手机 |
| --- | --- | --- | --- |
| `validate` | manifest；example 需 `--allow-example` | schema issues 为空的 JSON | 否 |
| `verify-file` | 真实 manifest + 真实模型 | size/SHA issues 为空的 JSON | 否 |
| `preflight` | manifest + 人工采集的设备事实 | 资源 issues 为空的 JSON | 否 |
| `plan-adb` | 真实 manifest + 安全文件名 + remote 目录 | 命令参数数组 JSON | 否 |

必须打开 `$PlanFile` 人工检查每个参数，尤其是本地文件名、远端目录、上下文和输出 token。当前 `plan-adb` 给出与 runtime 无关的最小 smoke argv，不包含 Qwen3 专用 `--reasoning off`；第 5 节人工执行时会显式加入，并把这项已审查差异记入测试记录。不要把 JSON 当脚本执行，也不要让 manifest 工具替你调用 `adb`。

## 5. 真机 CLI smoke test

### 5.1 采集设备事实

连接唯一目标设备后执行：

```powershell
adb devices -l
if ($LASTEXITCODE -ne 0) { throw 'adb devices 失败' }
adb shell getprop ro.product.cpu.abilist
adb shell getprop ro.build.version.sdk
adb shell cat /proc/meminfo
adb shell df -k /data/local/tmp
```

从输出记录 ABI、API、`MemTotal` 和 `/data/local/tmp` 可用 KiB，换算成 manifest 工具需要的 MiB，再用**真实 manifest**重跑 `preflight`。不能只把示例里的 `8192/4096` 复制成设备事实。

### 5.2 人工执行已审查的 push

下面是 Windows 主机的实际变更命令。只有在 manifest verification、resource preflight 和 JSON plan 均已通过人工审查后才执行：

```powershell
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$StageDir = "C:\staging\llama-android-$LlamaCommit"
$Model = 'C:\models\order-assistant-q4_k_m.gguf'
$Remote = '/data/local/tmp/llama.cpp'
$StageCli = Join-Path $StageDir 'bin\llama-cli'
$StageLib = Join-Path $StageDir 'lib'

if (-not (Test-Path -LiteralPath $StageCli -PathType Leaf)) {
  throw 'staging llama-cli 不存在'
}
if (-not (Test-Path -LiteralPath $StageLib -PathType Container)) {
  throw 'staging lib 不存在'
}
if (-not (Test-Path -LiteralPath $Model -PathType Leaf)) { throw 'GGUF 不存在' }
$StageLibraries = @(Get-ChildItem -LiteralPath $StageLib -Filter '*.so' -File)
if ($StageLibraries.Count -eq 0) { throw 'staging 中没有 Android .so' }

adb shell mkdir -p "$Remote/bin" "$Remote/lib"
if ($LASTEXITCODE -ne 0) { throw '创建远端目录失败' }
adb push $StageCli "$Remote/bin/llama-cli"
if ($LASTEXITCODE -ne 0) { throw 'push llama-cli 失败' }
foreach ($Library in $StageLibraries) {
  adb push $Library.FullName "$Remote/lib/$($Library.Name)"
  if ($LASTEXITCODE -ne 0) { throw "push 共享库失败: $($Library.Name)" }
}
adb push $Model "$Remote/order-assistant-q4_k_m.gguf"
if ($LASTEXITCODE -ne 0) { throw 'push GGUF 失败' }
adb shell chmod 755 "$Remote/bin/llama-cli"
adb shell ls -l "$Remote/bin" "$Remote/lib" "$Remote/order-assistant-q4_k_m.gguf"
```

`bin` 和 `lib` 必须来自同一个固定 checkout 的同一次 install/staging。不要把桌面 `Release\llama-cli.exe`、另一提交的 `.so` 或另一 SHA 的 GGUF 混进来。

进入 `adb shell` 后执行设备端 smoke：

```sh
cd /data/local/tmp/llama.cpp
LD_LIBRARY_PATH=lib ./bin/llama-cli -m order-assistant-q4_k_m.gguf -c 2048 -n 128 --reasoning off -p '请用一句话说明如何查询订单'
```

`LD_LIBRARY_PATH=lib` 与 staging 布局一致。Qwen3 在该固定 commit 下使用 `--reasoning off`，与训练、桌面和量化评测的非思考模式保持一致。若桌面基线还固定了 conversation/chat-template 选项，真机也必须使用同一组，不要靠删除 `<think>` 文本掩盖模板漂移。

该 smoke 的输出应保存为真实证据，但“进程返回 0”只证明一次加载和生成路径可走通，不证明质量、并发、取消、温升或长期稳定。

## 6. 导入官方 Android binding

App 集成不复用 `/data/local/tmp`。该目录只用于开发 smoke；正式模型必须进入 App 私有目录，例如：

```kotlin
val modelFile = File(context.filesDir, "models/$version/model.gguf")
require(modelFile.isFile) { "active model is missing" }
```

从**同一个固定 checkout** 导入 `examples/llama.android/lib`。假设 App 工程旁边保存只读 vendor checkout：

```kotlin
// settings.gradle.kts
include(":lib")
project(":lib").projectDir =
    file("../vendor/llama.cpp-505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib")
```

App module 只展示必要依赖和 ABI 约束：

```kotlin
// app/build.gradle.kts（片段）
android {
    defaultConfig {
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }
}

dependencies {
    implementation(project(":lib"))
}
```

上游 `lib` 使用固定 checkout 的 Gradle version catalog aliases；宿主工程必须合并对应的 `libs.versions.toml` 定义，并满足前述 compileSdk、NDK、CMake、JDK 17 和 minSdk 33，不能只复制两行 Gradle 就声称构建成功。升级 binding 时同步核对[固定 settings](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/settings.gradle.kts)、[固定 lib Gradle](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/build.gradle.kts)和 ABI 打包结果。

本仓库提供的[OnDeviceLlmEngine.kt](./demo/android/OnDeviceLlmEngine.kt)直接使用官方 [`AiChat`](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/AiChat.kt) 与 [`InferenceEngine`](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/InferenceEngine.kt)，负责：

- 在后台 dispatcher 加载 app-private GGUF。
- 用 `Flow<String>` 流式返回 token。
- 用 mutex 保证同一时刻最多一个 load/generate/unload。
- 在仍有 native 操作时拒绝 `close()`，避免 destroy 与 generation 竞争。

## 7. 核心 Kotlin 生命周期用法

下面只展示 owner 层，不包含 UI。`ownerScope` 不能使用会在 `onDestroy` 之前自动取消的 `lifecycleScope`，否则最终清理协程可能没有机会执行。

```kotlin
import android.content.Context
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LlmSessionOwner(context: Context) {
    private val engine = OnDeviceLlmEngine(context.applicationContext)
    private val ownerScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val closing = AtomicBoolean(false)
    private var activeJob: Job? = null

    fun load(modelFile: File, onResult: (Result<Unit>) -> Unit) {
        check(!closing.get()) { "owner is closing" }
        check(activeJob?.isActive != true) { "model operation is already running" }
        activeJob = ownerScope.launch {
            try {
                engine.load(
                    modelFile = modelFile,
                    systemPrompt = "你是订单助手。回答简洁；信息不足时明确说明。",
                )
                onResult(Result.success(Unit))
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Throwable) {
                onResult(Result.failure(failure))
            }
        }
    }

    fun generate(
        prompt: String,
        onToken: (String) -> Unit,
        onError: (Throwable) -> Unit,
    ) {
        check(!closing.get()) { "owner is closing" }
        check(activeJob?.isActive != true) { "model operation is already running" }

        activeJob = ownerScope.launch {
            engine.generate(prompt, maxOutputTokens = 128)
                .catch { failure -> onError(failure) }
                .collect { token -> onToken(token) }
        }
    }

    // Activity/Fragment 的 onStop 调用：先发出取消，不阻塞主线程。
    fun onStop() {
        activeJob?.cancel()
    }

    // 最终 owner 的 onDestroy 调用；异步等待 collection 结束后再 destroy native engine。
    fun onDestroy() {
        if (!closing.compareAndSet(false, true)) return
        ownerScope.launch {
            activeJob?.cancelAndJoin()
            activeJob = null
            try {
                withContext(Dispatchers.Default) {
                    engine.close()
                }
            } finally {
                ownerScope.cancel()
            }
        }
    }
}
```

`Flow` collection 被取消后，取消会沿协程传播，但这不等于 native 计算必然瞬间停止。`onStop()` 先取消，`onDestroy()` 再 `cancelAndJoin()` 确认 load/generation job 已结束，最后从非 UI dispatcher 调 `close()`。不要在主线程 `runBlocking`，也不要在 native 操作活跃时直接 destroy。应记录“用户取消到 job 真正结束”的 cancel latency。

如果这个 engine 是进程级单例，配置变更时不要随 Activity 销毁；把 owner 放在 Application 或明确的长期 service/repository 生命周期中，只在该 owner 永久结束时 close。

## 8. 模型下载、激活与回滚

大型 GGUF 不要打进 APK，也不要长期从 Downloads、共享外部存储或 `/data/local/tmp` 加载。生产下载使用 TLS、服务端认证/授权、最小权限临时凭据和 App 私有目录；日志不得包含下载 token、完整 URL query 或用户 Prompt。

先从可信来源获取并认证/验签 manifest，再按下列状态流处理模型字节。要求的激活语义是：

```text
download.tmp -> size check -> SHA-256 -> manifest check
-> atomic rename to models/<version>/model.gguf
-> load smoke test -> switch current-version pointer
-> retain previous known-good version -> later cleanup
```

逐步解释：

1. **storage preflight**：预留临时文件、新版本、上一 known-good 和安全余量；不足就不开始。
2. **download.tmp**：在目标私有目录的同一文件系统内写唯一临时名；断点续传必须验证服务器的 ETag/版本与已下载偏移，远端对象变化就重新开始。
3. **size / SHA**：关闭并同步写句柄后校验 manifest 中的精确字节数和小写 SHA-256。
4. **manifest check**：校验 schema、runtime、format、quantization、context、ABI/API、基座/adapter/runtime provenance、许可和发布代次。
5. **atomic rename**：同目录原子移动到 `filesDir/models/<version>/model.gguf`；禁止覆盖已存在的不可变版本。
6. **load smoke**：从最终 version 路径再次校验并加载固定短 Prompt；失败不切 pointer。
7. **switch pointer**：先把当前版本记为 previous，再原子切换小型 `current-version` 指针；读取方每次都严格解析并复验目标。
8. **rollback**：新版本损坏、schema/runtime 不兼容、加载失败、OOM 或 smoke 不通过时继续使用 previous known-good；只有稳定观察期结束后才清理更老版本。

SHA-256 不是数字签名。若 manifest 与模型来自同一可篡改响应，攻击者可以同时替换两者。manifest 必须来自经过认证且最好签名验证的可信发布通道，并包含防回滚的单调发布代次；App 要持久化已经接受的最高代次。

下载失败或进程被杀后，启动恢复只能处理符合命名规则的私有 staged 文件；对 size、ETag、SHA 和 manifest 重新验证，不因 `.tmp` 存在就直接续用。任何失败都不得破坏 current pointer 或删除 previous known-good。

## 9. 错误映射与恢复动作

| 类别 | 检测信号 | 面向用户 | 结构化日志与恢复 |
| --- | --- | --- | --- |
| 模型缺失/损坏 | 文件不存在，size/SHA 不符 | “模型需要重新下载” | 记录版本、阶段、expected/actual size；不记录下载凭据；回滚或重下 |
| 不支持的架构/API | ABI/API 或 JNI load 失败 | “此设备暂不支持离线模型” | 记录 ABI、API、打包 ABI、runtime commit；禁用入口 |
| OOM/进程被杀 | 分配失败、系统 low-memory、进程重启 | “内存不足，请关闭其他应用或降低上下文” | 记录 context、峰值内存、并发、机型；回退更小模型/上下文 |
| context overflow | 输入 + 输出超过 manifest/runtime 上限 | “内容过长，请缩短输入” | 记录 token 数与上限；截断必须由明确业务策略决定 |
| busy generation | 已有活跃 job/mutex 等待 | “上一条仍在生成” | 串行、取消上一条或排队；记录队列等待，不并发打 native |
| cancellation | `CancellationException` / job cancelled | 静默停止或显示“已停止” | 记录 cancel latency；等待 job 结束后才 unload/close |
| 进入后台 | `onStop`、进程可见性变化 | 暂停流式输出 | 取消并等待；按产品策略保留已生成片段，不后台偷跑 |
| thermal throttling | Thermal API、tokens/s 持续下降 | “设备温度较高，请稍后再试” | 记录温度级别、时间、tokens/s；降载或停止 |
| native failure | JNI exception、signal、非零 CLI code | “离线模型暂不可用” | 记录脱敏错误码、commit、模型 SHA、最后状态；重启 owner 或回滚 |

不要把异常 `message`、原始 Prompt 或生成正文直接上传。日志至少要有脱敏 request ID、状态阶段、稳定错误码和版本证据，供定位“模型问题、runtime 问题还是设备资源问题”。

## 10. 真机性能与稳定性记录

不承诺任意机型的 tokens/s、内存或温升。只有模型 SHA、runtime commit、模板、Prompt、上下文、量化、采样参数和设备状态相同，数据才可比较。

| 字段 | 实际值 |
| --- | --- |
| 时间 / 测试人 | `待填` |
| model id / SHA-256 | `待填` |
| llama.cpp commit | `505b1ed15ca80e2a19f12ff4ac365e40fb374053` |
| 设备 / SoC / RAM | `待填` |
| Android / ABI | `待填` |
| quantization / 文件大小 | `Q4_K_M / 待填` |
| chat template / reasoning | `待填 / off` |
| context / max output | `2048 / 128` |
| 冷/热加载时间 | `待填 ms` |
| TTFT | `待填 ms` |
| decode tokens/s | `待填` |
| peak memory | `待填 MiB` |
| 起止温度 / thermal status | `待填` |
| 起止电量 / battery delta | `待填` |
| cancel latency | `待填 ms` |
| 重复轮次 / crash / error count | `待填` |

至少覆盖冷启动一次、热启动多次、长 Prompt、接近 context 上限、连续生成、取消、前后台切换和新版本回滚。温度或系统负载变化时单独分组，不能挑最快一轮报告。

## 11. 手工验收清单

下面全部是目标工作站/真机的待办，不是本仓库已执行结果：

| 状态 | 验收项 | 真实结果 |
| --- | --- | --- |
| [ ] | 桌面固定 commit 的 `llama-cli` 对真实 GGUF 跑固定 Prompt suite | 未执行 / 待填 |
| [ ] | 真实 manifest schema、许可、provenance、size 和 SHA 复核 | 未执行 / 待填 |
| [ ] | 从目标手机采集 ABI/API/RAM/空间并通过真实 preflight | 未执行 / 待填 |
| [ ] | 人工审查 `plan-adb` JSON 参数数组 | 未执行 / 待填 |
| [ ] | 实际 push 同一次 staging 的 bin/lib 与相同 SHA 的 GGUF | 未执行 / 待填 |
| [ ] | 设备端 exact `llama-cli` smoke，保存 exit code 和输出 | 未执行 / 待填 |
| [ ] | App 导入固定 `examples/llama.android/lib` 并核对 APK ABI | 未执行 / 待填 |
| [ ] | App-private 最终路径加载，Kotlin Flow 收到 token | 未执行 / 待填 |
| [ ] | 连续多次生成，无 stale state、重复 token 或 native failure | 未执行 / 待填 |
| [ ] | 生成中取消并等待 job 结束，记录 cancel latency | 未执行 / 待填 |
| [ ] | `onStop`/后台切换不继续偷跑，最终 owner 按顺序 close | 未执行 / 待填 |
| [ ] | 故意提供损坏/不兼容新版本，current 不切换且回滚成功 | 未执行 / 待填 |
| [ ] | 填写 TTFT、tokens/s、峰值内存、温度、电量和错误数 | 未执行 / 待填 |

## 12. 本章验证边界

本章编写时只静态核对了命令、链接、固定提交 API、manifest CLI 参数和 Kotlin 生命周期关系。以下外部动作**没有执行**：

- 没有进行 GPU 训练、LoRA/QLoRA 合并、GGUF 转换或量化。
- 没有下载、复制或提交任何模型权重、GGUF 或 `.litertlm`。
- 没有在本机执行 Android NDK build/install/staging。
- 没有执行 `adb push`、设备 CLI smoke、APK 构建或真机 Kotlin 推理。
- 没有测量手机 TTFT、tokens/s、峰值内存、温升、电量或取消延迟。

这些结果只能由你在真实工作站和目标手机上按清单填写。教程中的 3 GB/1 GB、API 28、上下文 2048 都是门禁示例或固定实验参数，不是性能保证。

## 13. 官方资料

- [llama.cpp pinned Android 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/docs/android.md)
- [llama.cpp pinned Android binding](https://github.com/ggml-org/llama.cpp/tree/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android)
- [llama.cpp pinned AiChat.kt](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/AiChat.kt)
- [llama.cpp pinned InferenceEngine.kt](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/InferenceEngine.kt)
- [Android NDK stable APIs](https://developer.android.com/ndk/guides/stable_apis)
- [Android adb 文档](https://developer.android.com/tools/adb)
- [Google MediaPipe LLM Inference maintenance notice](https://developers.google.com/edge/mediapipe/solutions/genai/llm_inference/android)
- [Google LiteRT-LM Android Kotlin API](https://developers.google.com/edge/litert-lm/android)
- [Google LiteRT-LM repository](https://github.com/google-ai-edge/LiteRT-LM)
- [ONNX Runtime Mobile](https://onnxruntime.ai/docs/get-started/with-mobile.html)

### 本章小结

端侧生成模型上线不是“把 GGUF push 到手机”这一条命令，而是一条可回放的证据链：固定模型与 runtime、校验可信 manifest、资源预检、CLI smoke、App 私有安装、串行 Flow 生命周期、激活后回滚和真机性能记录。任何一环变化，都要重新验证，不能用桌面成功或一次设备输出代替发布验收。
