# Ollama 与 llama.cpp 本地部署实战

本章把上一阶段得到的生成模型制品接到桌面运行时：先用 Ollama 快速验证模型和 HTTP 调用，再用固定版本的 llama.cpp 对同一个 GGUF 做可复现的命令行与服务验证。内容只保留核心命令、标准库 Python 客户端、安全边界和基准记录，不搭建额外生产框架。

本章使用两个不同来源的示例：

- Ollama 官方仓库模型：`qwen3:0.6b`，用于快速打通 CLI 和 `/api/generate`。
- 上一章生成的本地模型：`C:\models\mobile-llm-q4_k_m.gguf`，用于 Ollama 导入和 llama.cpp 验证。

模型能启动不等于可以发布。下载前检查具体 tag 的文件大小、模型/数据许可、任务能力和 chat template；部署自训 GGUF 时继续遵守[训练与量化章节](../16-微调与模型定制/06-面向端侧的生成模型训练与量化.md)中冻结的非思考模式、评测集和制品清单。

> **版本边界**：本文按 2026-07-16 可查到的 Ollama 官方文档编写。llama.cpp 命令固定到完整 commit `505b1ed15ca80e2a19f12ff4ac365e40fb374053`，不会把浮动的 `main` 当作可复现版本。运行前仍要查看本机 `--help`，升级 runtime 后重新做全部 smoke test。

## 1. 选择运行时

| 需求 | Ollama | llama.cpp |
| --- | --- | --- |
| 快速下载并交互 | CLI 和模型仓库流程简单 | 通常自行准备 GGUF |
| 自定义 SYSTEM / 参数 | Modelfile | CLI flags、GGUF chat template |
| HTTP 接入 | 原生 API，默认端口 `11434` | `llama-server`，默认端口 `8080` |
| 精确冻结运行时 | 记录 Ollama 版本 | 固定源码 commit 和构建参数 |
| 端侧/嵌入式集成前验证 | 适合桌面基线 | 更接近后续 GGUF/runtime 调优 |

两者都只是运行时，不会自动解决鉴权、限流、审计、许可证或业务质量问题。对外服务仍应经过业务网关。

## 2. 安装 Ollama 并完成 CLI 健康检查

只从官方入口安装：

- [Ollama Download](https://ollama.com/download)：Windows、macOS 的官方安装入口。
- [Ollama Linux](https://docs.ollama.com/linux)：Linux 安装、服务和日志说明。
- [Ollama Quickstart](https://docs.ollama.com/quickstart)：官方首个模型调用流程。
- [qwen3:0.6b 官方模型页](https://ollama.com/library/qwen3:0.6b)：当前 tag 的大小、参数、模板和许可元数据入口。

安装并启动 Ollama 后，在 PowerShell 中依次执行。`pull` 会下载模型，先确认磁盘空间和许可；`run` 的输入是终端里的自然语言，输出是模型生成文本。

```powershell
$Model = 'qwen3:0.6b'

ollama --version
if ($LASTEXITCODE -ne 0) { throw 'Ollama CLI 不可用' }

ollama list
if ($LASTEXITCODE -ne 0) { throw '读取本地模型列表失败' }

ollama ps
if ($LASTEXITCODE -ne 0) { throw '读取已加载模型失败' }

ollama pull $Model
if ($LASTEXITCODE -ne 0) { throw "下载模型失败: $Model" }

ollama run $Model
if ($LASTEXITCODE -ne 0) { throw "交互推理失败: $Model" }
```

进入交互模式后输入 `请用一句话说明如何查询订单`，观察正文、格式和是否出现不需要的思考内容；输入 `/bye` 退出。`ollama ps` 的 `PROCESSOR` 列可辅助确认 CPU/GPU 分配，但不能替代峰值内存和延迟测量。

本地 API 默认基地址是 `http://localhost:11434/api`。下面的输入是版本端点，输出应为 JSON 版本对象；它只证明进程可访问，不证明目标模型已经加载或质量合格。

```powershell
$OllamaVersionUri = 'http://127.0.0.1:11434/api/version'
$Version = Invoke-RestMethod -Method Get -Uri $OllamaVersionUri -TimeoutSec 10
$Version | ConvertTo-Json -Depth 4
```

如果连接被拒绝，先确认 Ollama 应用/服务已启动、端口没有冲突，再看官方[Troubleshooting](https://docs.ollama.com/troubleshooting)。

## 3. 调用 `/api/generate`

Ollama 的 `/api/generate` 默认返回 NDJSON 流；请求中设置 `"stream": false` 后返回一个 JSON 对象。下列三种客户端都把模型名和 Prompt 当作输入，把生成正文当作输出。

### 3.1 PowerShell：非流式

`ConvertTo-Json` 负责转义中文和引号，不要手拼包含用户输入的 JSON。

```powershell
$Model = 'qwen3:0.6b'
$GenerateUri = 'http://127.0.0.1:11434/api/generate'
$Prompt = '请用一句话说明如何查询订单'
$Payload = [ordered]@{
    model = $Model
    prompt = $Prompt
    stream = $false
    options = [ordered]@{ num_ctx = 2048 }
}
$Body = $Payload | ConvertTo-Json -Depth 5 -Compress
$Response = Invoke-RestMethod `
    -Method Post `
    -Uri $GenerateUri `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($Body)) `
    -TimeoutSec 120
$Response.response
```

### 3.2 Windows `curl.exe`：非流式

PowerShell 的 `curl` 可能是别名，因此明确调用 `curl.exe`。请求写入无 BOM 的 UTF-8 临时文件；输出是服务端 JSON，`--fail-with-body` 让 HTTP 错误返回非零状态并保留错误体。

```powershell
$Model = 'qwen3:0.6b'
$GenerateUri = 'http://127.0.0.1:11434/api/generate'
$Prompt = '请用一句话说明如何查询订单'
$Payload = [ordered]@{
    model = $Model
    prompt = $Prompt
    stream = $false
    options = [ordered]@{ num_ctx = 2048 }
}
$Body = $Payload | ConvertTo-Json -Depth 5 -Compress
$BodyFile = Join-Path ([IO.Path]::GetTempPath()) 'ollama-generate.json'
[IO.File]::WriteAllText($BodyFile, $Body, [Text.UTF8Encoding]::new($false))
try {
    curl.exe --fail-with-body --silent --show-error `
        --max-time 120 `
        -H 'Content-Type: application/json; charset=utf-8' `
        --data-binary "@$BodyFile" `
        $GenerateUri
    if ($LASTEXITCODE -ne 0) { throw "curl.exe 调用失败，exit=$LASTEXITCODE" }
}
finally {
    Remove-Item -LiteralPath $BodyFile -ErrorAction SilentlyContinue
}
```

若 Prompt 含敏感数据，不要把请求文件放在共享目录，也不要在失败日志中打印 `$Body`。

### 3.3 标准库 Python：非流式与 NDJSON 流式

把下面代码保存为 `ollama_generate.py`。它只使用标准库，严格按 UTF-8 编解码；覆盖连接失败、HTTP 错误体、超时、JSON/Unicode 错误和 `Ctrl+C`。错误写入 stderr，成功正文写入 stdout，失败返回非零退出码；脚本不会打印请求体、Prompt 或环境变量。

```python
from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:11434/api/generate"
MAX_ERROR_BYTES = 4096


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="调用本机 Ollama /api/generate")
    parser.add_argument("--model", default="qwen3:0.6b")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    return args


def encode_payload(model: str, prompt: str, stream: bool) -> bytes:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {"num_ctx": 2048},
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def decode_json(raw: bytes, context: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} 不是合法 UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{context} 顶层必须是 JSON object")
    return value


def response_text(value: dict[str, Any], context: str) -> str:
    error = value.get("error")
    if error is not None:
        raise RuntimeError(f"{context} 返回错误: {error!s}"[:512])
    text = value.get("response")
    if not isinstance(text, str):
        raise ValueError(f"{context} 缺少字符串 response")
    return text


def run_non_streaming(response: BinaryIO) -> None:
    value = decode_json(response.read(), "Ollama 响应")
    print(response_text(value, "Ollama 响应"))


def run_streaming(response: BinaryIO) -> None:
    line_number = 0
    saw_done = False
    while True:
        raw_line = response.readline()
        if raw_line == b"":
            break
        line_number += 1
        if not raw_line.strip():
            continue
        value = decode_json(raw_line, f"NDJSON 第 {line_number} 行")
        chunk = response_text(value, f"NDJSON 第 {line_number} 行")
        print(chunk, end="", flush=True)
        done = value.get("done")
        if not isinstance(done, bool):
            raise ValueError(f"NDJSON 第 {line_number} 行缺少布尔值 done")
        if done:
            saw_done = True
            break
    if not saw_done:
        raise ValueError("NDJSON 在 done=true 前结束")
    print()


def bounded_http_error(error: HTTPError) -> str:
    raw = error.read(MAX_ERROR_BYTES)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "<响应体不是合法 UTF-8>"
    return "".join(character if character.isprintable() else " " for character in text)


def main() -> int:
    args = parse_args()
    try:
        data = encode_payload(args.model, args.prompt, args.stream)
        request = Request(
            args.url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urlopen(request, timeout=args.timeout) as response:
            if args.stream:
                run_streaming(response)
            else:
                run_non_streaming(response)
        return 0
    except HTTPError as error:
        body = bounded_http_error(error)
        print(f"HTTP {error.code}: {body}", file=sys.stderr)
        return 2
    except socket.timeout:
        print("Ollama 请求超时", file=sys.stderr)
        return 3
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ConnectionRefusedError):
            message = "Ollama 连接被拒绝；确认服务和 127.0.0.1:11434"
        elif isinstance(reason, socket.timeout):
            message = "Ollama 连接超时"
        else:
            message = f"Ollama 连接失败: {reason!s}"[:512]
        print(message, file=sys.stderr)
        return 4
    except (UnicodeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"响应解析失败: {error!s}"[:512], file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        print("用户取消请求", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
```

非流式输入是一条 Prompt，输出是一行完整回复：

```powershell
python .\ollama_generate.py --model 'qwen3:0.6b' --prompt '请用一句话说明如何查询订单'
if ($LASTEXITCODE -ne 0) { throw "非流式调用失败: $LASTEXITCODE" }
```

流式输入相同，输出会随 NDJSON 分片实时追加；按 `Ctrl+C` 取消并得到退出码 `130`：

```powershell
python .\ollama_generate.py --stream --model 'qwen3:0.6b' --prompt '列出三个离线推理注意事项'
if ($LASTEXITCODE -ne 0) { throw "流式调用失败或已取消: $LASTEXITCODE" }
```

官方协议定义见 [Generate API](https://docs.ollama.com/api/generate) 和 [Streaming](https://docs.ollama.com/api/streaming)。

## 4. 用 Modelfile 固定行为

先创建一个基于仓库模型的 `Modelfile`。输入是已下载的 `$Model`，输出是新的本地模型名 `mobile-assistant`。

```text
FROM qwen3:0.6b
SYSTEM 你是离线订单助手。只回答用户问题，不编造订单状态；信息不足时明确说明。
PARAMETER temperature 0.2
PARAMETER num_ctx 2048
```

在 `Modelfile` 所在目录执行：

```powershell
$CustomModel = 'mobile-assistant'
$Modelfile = '.\Modelfile'

ollama create $CustomModel -f $Modelfile
if ($LASTEXITCODE -ne 0) { throw '创建 Ollama 模型失败' }

ollama show --modelfile $CustomModel
if ($LASTEXITCODE -ne 0) { throw '读取 Modelfile 失败' }

ollama run $CustomModel '请说明查询订单需要哪些信息'
if ($LASTEXITCODE -ne 0) { throw '自定义模型推理失败' }
```

导入上一章生成的本地 GGUF 时，将 `FROM` 改成绝对路径。官方 Modelfile 允许 GGUF 使用绝对路径，或使用相对 `Modelfile` 的路径：

```text
FROM C:\models\mobile-llm-q4_k_m.gguf
SYSTEM 你是端侧离线助手。信息不足时明确说明，不输出推理过程。
PARAMETER temperature 0.2
PARAMETER num_ctx 2048
```

```powershell
$ImportedModel = 'mobile-llm-local'
$GgufModelfile = '.\Modelfile.gguf'

ollama create $ImportedModel -f $GgufModelfile
if ($LASTEXITCODE -ne 0) { throw '导入 GGUF 失败' }

ollama show --modelfile $ImportedModel
ollama run $ImportedModel '请用一句话说明如何查询订单'
if ($LASTEXITCODE -ne 0) { throw '导入后的 GGUF 推理失败' }
```

不要仅凭 `create` 成功判断模板正确。对相同 Prompt 比较 merged、F16 GGUF、Q4 GGUF、Ollama 导入结果，检查角色泄漏、停止符和非思考模式。

## 5. Ollama 的网络与安全边界

Ollama 官方 FAQ 说明：默认绑定 `127.0.0.1:11434`；官方[认证说明](https://docs.ollama.com/api/authentication)明确指出本地 API 不要求鉴权。它适合本机开发，但**绝不能把原始 Ollama 端口裸露到公网**。

如果确有局域网接入需求，至少同时完成：

1. 防火墙只允许明确的应用网关或管理网段访问，不开放任意来源。
2. 由反向代理或业务 AI Gateway 提供身份认证、授权、限流、请求大小限制和 TLS。
3. 将管理接口与业务接口分离，记录模型版本、耗时、状态码和审计 ID。
4. Prompt、回复和日志按敏感数据处理；默认不记录正文，调试采样先脱敏并设置短保留期。
5. 部署前复核基座、adapter、GGUF 与训练数据的许可和分发边界。

下面只是展示绑定变量，**不要在未完成防火墙和网关时执行公网绑定**。Windows 改成全网卡后，需要退出并重新启动 Ollama 应用：

```powershell
$RiskyHost = '0.0.0.0:11434'
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', $RiskyHost, 'User')
Write-Warning '已配置全网卡监听；重启前先完成防火墙、认证网关、限流和 TLS'
```

验证完成后恢复 loopback，并重启 Ollama：

```powershell
$LoopbackHost = '127.0.0.1:11434'
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', $LoopbackHost, 'User')
Write-Output '已恢复 loopback 配置；退出并重启 Ollama 后生效'
```

Linux systemd 服务通过 `systemctl edit ollama.service` 在 `[Service]` 下设置 `Environment="OLLAMA_HOST=..."`，然后 `daemon-reload` 和 `restart`。测试结束把值恢复为 `127.0.0.1:11434`；不要把 `0.0.0.0` 写进教程脚本后自动执行。具体平台步骤见官方 [Ollama FAQ](https://docs.ollama.com/faq)。

`OLLAMA_HOST` 只改变监听地址，不会增加鉴权。反向代理也必须显式配置认证和限流；仅仅加一层 Nginx 不等于安全。

## 6. 固定 llama.cpp 源码并构建

本节继续使用训练章节相同的 commit 和 Q4 文件：

- llama.cpp commit：`505b1ed15ca80e2a19f12ff4ac365e40fb374053`
- GGUF：`C:\models\mobile-llm-q4_k_m.gguf`

### 6.1 Windows CPU 构建

命令输入是官方仓库和完整 commit，输出是 detached HEAD 下的 Release 可执行文件。要求 CMake、Git 和 C++ 构建工具已在 `PATH`。如果目标目录已存在，先人工确认来源，不要覆盖复用成“新实验”。

```powershell
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$LlamaRepo = "C:\src\llama.cpp-$LlamaCommit"
$LlamaBuild = Join-Path $LlamaRepo 'build'

if (Test-Path -LiteralPath $LlamaRepo) { throw "源码目录已存在: $LlamaRepo" }
git clone --no-checkout https://github.com/ggml-org/llama.cpp.git $LlamaRepo
if ($LASTEXITCODE -ne 0) { throw 'clone llama.cpp 失败' }

git -C $LlamaRepo fetch --no-tags origin $LlamaCommit
if ($LASTEXITCODE -ne 0) { throw 'fetch pinned commit 失败' }
git -C $LlamaRepo checkout --detach $LlamaCommit
if ($LASTEXITCODE -ne 0) { throw 'checkout pinned commit 失败' }

$ActualCommit = (git -C $LlamaRepo rev-parse HEAD).Trim()
if ($ActualCommit -ne $LlamaCommit) { throw "commit 不一致: $ActualCommit" }

cmake -S $LlamaRepo -B $LlamaBuild
if ($LASTEXITCODE -ne 0) { throw 'CMake 配置失败' }
cmake --build $LlamaBuild --config Release -j 8
if ($LASTEXITCODE -ne 0) { throw 'CMake Release 构建失败' }

$LlamaCli = Join-Path $LlamaBuild 'bin\Release\llama-cli.exe'
$LlamaServer = Join-Path $LlamaBuild 'bin\Release\llama-server.exe'
foreach ($Tool in @($LlamaCli, $LlamaServer)) {
    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) { throw "缺少构建产物: $Tool" }
}

git -C $LlamaRepo status --short
& $LlamaCli --version
& $LlamaServer --version
```

不同生成器可能把 Windows 文件放在 `build\bin` 而不是 `build\bin\Release`。以构建日志和实际文件为准，记录最终绝对路径；不要静默改用另一个下载来的二进制。

### 6.2 Linux / macOS CPU 构建

输入和 commit 相同，输出位于 `build/bin`：

```bash
set -euo pipefail
LLAMA_COMMIT='505b1ed15ca80e2a19f12ff4ac365e40fb374053'
LLAMA_REPO="$HOME/src/llama.cpp-$LLAMA_COMMIT"
LLAMA_BUILD="$LLAMA_REPO/build"

test ! -e "$LLAMA_REPO"
git clone --no-checkout https://github.com/ggml-org/llama.cpp.git "$LLAMA_REPO"
git -C "$LLAMA_REPO" fetch --no-tags origin "$LLAMA_COMMIT"
git -C "$LLAMA_REPO" checkout --detach "$LLAMA_COMMIT"
test "$(git -C "$LLAMA_REPO" rev-parse HEAD)" = "$LLAMA_COMMIT"

cmake -S "$LLAMA_REPO" -B "$LLAMA_BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$LLAMA_BUILD" --config Release -j 8

LLAMA_CLI="$LLAMA_BUILD/bin/llama-cli"
LLAMA_SERVER="$LLAMA_BUILD/bin/llama-server"
test -x "$LLAMA_CLI"
test -x "$LLAMA_SERVER"
git -C "$LLAMA_REPO" status --short
"$LLAMA_CLI" --version
"$LLAMA_SERVER" --version
```

macOS 默认构建会使用官方构建配置支持的本机后端；Linux GPU 分支按硬件阅读 pinned commit 的[官方 build 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/docs/build.md)。例如 NVIDIA CUDA 使用独立 build 目录：

```bash
set -euo pipefail
LLAMA_COMMIT='505b1ed15ca80e2a19f12ff4ac365e40fb374053'
LLAMA_REPO="$HOME/src/llama.cpp-$LLAMA_COMMIT"
LLAMA_CUDA_BUILD="$LLAMA_REPO/build-cuda"

test "$(git -C "$LLAMA_REPO" rev-parse HEAD)" = "$LLAMA_COMMIT"
cmake -S "$LLAMA_REPO" -B "$LLAMA_CUDA_BUILD" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$LLAMA_CUDA_BUILD" --config Release -j 8
test -x "$LLAMA_CUDA_BUILD/bin/llama-cli"
test -x "$LLAMA_CUDA_BUILD/bin/llama-server"
```

## 7. 用 `llama-cli` 验证同一 GGUF

固定 commit 支持以下核心参数：

| 参数 | 含义 | 调整时观察什么 |
| --- | --- | --- |
| `-c 2048` | Prompt 与生成共享的上下文上限 | 越大通常需要更多 KV cache |
| `-n 128` | 最多生成 128 token | 影响总延迟和输出截断 |
| `-t 8` | 生成阶段 CPU 线程数 | 不是越多越快，要实测 |
| `-b 512` | Prompt 处理的逻辑 batch 上限 | 影响 prompt 吞吐与内存 |
| `-ngl 0/all` | GPU offload 层数；`0` 为 CPU，`all` 尝试全部 offload | 受 VRAM 和构建后端限制 |

Windows CPU 路径中，输入是 GGUF 和 Prompt，输出是生成正文及 runtime timing：

```powershell
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$LlamaCli = "C:\src\llama.cpp-$LlamaCommit\build\bin\Release\llama-cli.exe"
$Gguf = 'C:\models\mobile-llm-q4_k_m.gguf'
$Prompt = '请用一句话说明如何查询订单'
if (-not (Test-Path -LiteralPath $Gguf -PathType Leaf)) { throw "GGUF 不存在: $Gguf" }

& $LlamaCli `
    -m $Gguf `
    -c 2048 `
    -n 128 `
    -t 8 `
    -b 512 `
    -ngl 0 `
    --reasoning off `
    -cnv `
    -st `
    -p $Prompt
if ($LASTEXITCODE -ne 0) { throw 'llama-cli CPU 推理失败' }
```

GPU 构建通过后才尝试 offload；Windows NVIDIA CUDA 分支使用独立目录，不覆盖 CPU 构建。若 OOM，逐步减少 `-ngl`，不要把系统内存回退当作正常速度：

```powershell
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$LlamaRepo = "C:\src\llama.cpp-$LlamaCommit"
$LlamaCudaBuild = Join-Path $LlamaRepo 'build-cuda'
if ((git -C $LlamaRepo rev-parse HEAD).Trim() -ne $LlamaCommit) { throw 'llama.cpp commit 漂移' }
cmake -S $LlamaRepo -B $LlamaCudaBuild -DGGML_CUDA=ON
if ($LASTEXITCODE -ne 0) { throw 'CUDA CMake 配置失败' }
cmake --build $LlamaCudaBuild --config Release -j 8
if ($LASTEXITCODE -ne 0) { throw 'CUDA Release 构建失败' }
$LlamaCli = Join-Path $LlamaCudaBuild 'bin\Release\llama-cli.exe'
if (-not (Test-Path -LiteralPath $LlamaCli -PathType Leaf)) { throw "缺少 CUDA CLI: $LlamaCli" }
$Gguf = 'C:\models\mobile-llm-q4_k_m.gguf'
$Prompt = '请用一句话说明如何查询订单'

& $LlamaCli `
    -m $Gguf `
    -c 2048 `
    -n 128 `
    -t 8 `
    -b 512 `
    -ngl all `
    --reasoning off `
    -cnv `
    -st `
    -p $Prompt
if ($LASTEXITCODE -ne 0) { throw 'llama-cli GPU offload 推理失败' }
```

Linux/macOS 的 CPU 命令：

```bash
set -euo pipefail
LLAMA_COMMIT='505b1ed15ca80e2a19f12ff4ac365e40fb374053'
LLAMA_CLI="$HOME/src/llama.cpp-$LLAMA_COMMIT/build/bin/llama-cli"
GGUF='/models/mobile-llm-q4_k_m.gguf'
PROMPT='请用一句话说明如何查询订单'
test -x "$LLAMA_CLI"
test -f "$GGUF"
"$LLAMA_CLI" -m "$GGUF" -c 2048 -n 128 -t 8 -b 512 -ngl 0 --reasoning off -cnv -st -p "$PROMPT"
```

`--reasoning off` 与训练章节的 `enable_thinking=false` 保持一致。若仍出现 `<think>`、角色标记或错误停止，先检查 GGUF 内嵌 chat template 与转换链，不要用字符串删除来掩盖问题。

## 8. 启动 `llama-server` 并调用 API

服务只绑定 loopback。`--alias mobile-llm` 给 API 一个稳定的模型名；输入是本地 GGUF，输出是监听在 `127.0.0.1:8080` 的服务。

```powershell
$LlamaCommit = '505b1ed15ca80e2a19f12ff4ac365e40fb374053'
$LlamaServer = "C:\src\llama.cpp-$LlamaCommit\build\bin\Release\llama-server.exe"
$Gguf = 'C:\models\mobile-llm-q4_k_m.gguf'
$ServerHost = '127.0.0.1'
$ServerPort = 8080
$ServerAlias = 'mobile-llm'

& $LlamaServer `
    -m $Gguf `
    --alias $ServerAlias `
    -c 2048 `
    -n 128 `
    -t 8 `
    -b 512 `
    -ngl 0 `
    --reasoning off `
    --host $ServerHost `
    --port $ServerPort
```

这个命令占用当前终端。在另一个 PowerShell 运行 health smoke；加载中可能返回 `503`，就等待模型加载完成后重试，成功输出 `{"status":"ok"}`：

```powershell
$HealthUri = 'http://127.0.0.1:8080/health'
$Health = Invoke-RestMethod -Method Get -Uri $HealthUri -TimeoutSec 10
$Health | ConvertTo-Json -Depth 4
```

Windows `curl.exe` 等价检查：

```powershell
$HealthUri = 'http://127.0.0.1:8080/health'
curl.exe --fail-with-body --silent --show-error --max-time 10 $HealthUri
if ($LASTEXITCODE -ne 0) { throw "llama-server health 失败: $LASTEXITCODE" }
```

固定 commit 官方支持 OpenAI-compatible `/v1/chat/completions`。PowerShell 输入是 messages，输出是 `choices[0].message.content`：

```powershell
$ChatUri = 'http://127.0.0.1:8080/v1/chat/completions'
$ServerAlias = 'mobile-llm'
$Payload = [ordered]@{
    model = $ServerAlias
    messages = @(
        [ordered]@{ role = 'system'; content = '你是离线订单助手。信息不足时明确说明。' },
        [ordered]@{ role = 'user'; content = '请用一句话说明如何查询订单' }
    )
    max_tokens = 128
    stream = $false
    chat_template_kwargs = [ordered]@{ enable_thinking = $false }
}
$Body = $Payload | ConvertTo-Json -Depth 8 -Compress
$Chat = Invoke-RestMethod `
    -Method Post `
    -Uri $ChatUri `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($Body)) `
    -TimeoutSec 120
$Chat.choices[0].message.content
```

`curl.exe` 版本同样使用 UTF-8 无 BOM 文件，输出完整 JSON：

```powershell
$ChatUri = 'http://127.0.0.1:8080/v1/chat/completions'
$ServerAlias = 'mobile-llm'
$Payload = [ordered]@{
    model = $ServerAlias
    messages = @([ordered]@{ role = 'user'; content = '请用一句话说明如何查询订单' })
    max_tokens = 128
    stream = $false
    chat_template_kwargs = [ordered]@{ enable_thinking = $false }
}
$Body = $Payload | ConvertTo-Json -Depth 8 -Compress
$BodyFile = Join-Path ([IO.Path]::GetTempPath()) 'llama-chat.json'
[IO.File]::WriteAllText($BodyFile, $Body, [Text.UTF8Encoding]::new($false))
try {
    curl.exe --fail-with-body --silent --show-error `
        --max-time 120 `
        -H 'Content-Type: application/json; charset=utf-8' `
        --data-binary "@$BodyFile" `
        $ChatUri
    if ($LASTEXITCODE -ne 0) { throw "llama-server API 失败: $LASTEXITCODE" }
}
finally {
    Remove-Item -LiteralPath $BodyFile -ErrorAction SilentlyContinue
}
```

Linux/macOS 服务与 smoke：

```bash
set -euo pipefail
LLAMA_COMMIT='505b1ed15ca80e2a19f12ff4ac365e40fb374053'
LLAMA_SERVER="$HOME/src/llama.cpp-$LLAMA_COMMIT/build/bin/llama-server"
GGUF='/models/mobile-llm-q4_k_m.gguf'
SERVER_HOST='127.0.0.1'
SERVER_PORT='8080'
SERVER_ALIAS='mobile-llm'
test -x "$LLAMA_SERVER"
test -f "$GGUF"
"$LLAMA_SERVER" -m "$GGUF" --alias "$SERVER_ALIAS" -c 2048 -n 128 -t 8 -b 512 -ngl 0 --reasoning off --host "$SERVER_HOST" --port "$SERVER_PORT"
```

另一个终端运行：

```bash
set -euo pipefail
curl --fail-with-body --silent --show-error --max-time 10 'http://127.0.0.1:8080/health'
curl --fail-with-body --silent --show-error --max-time 120 \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary '{"model":"mobile-llm","messages":[{"role":"user","content":"请用一句话说明如何查询订单"}],"max_tokens":128,"stream":false,"chat_template_kwargs":{"enable_thinking":false}}' \
  'http://127.0.0.1:8080/v1/chat/completions'
```

API、health、参数和 timing 字段以 pinned commit 的[官方 server 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/tools/server/README.md)为准。CLI 交互行为见[官方 CLI 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/tools/cli/README.md)。

## 9. 常见问题排查

| 症状 | 先检查 | 处理方式 |
| --- | --- | --- |
| `model not found` | Ollama 名称/tag 是否精确，`ollama list` 是否存在 | 先确认官方模型页，再显式 `ollama pull $Model`；自定义模型检查 `create` 名称 |
| `unsupported GGUF` | GGUF 架构、版本和 runtime commit | 回到 pinned converter/runtime 验证；升级 commit 要作为新实验完整复测 |
| OOM / 进程退出 | 模型大小、`-c`、`-b`、并发、`-ngl`、KV cache | 降低上下文/batch/offload 或换更小量化；记录参数变化 |
| 首 token 很慢 | 冷启动、模型加载、Prompt 长度、磁盘和模板 | 区分冷/热请求，先用 health 等待加载完成，再记录 TTFT |
| tokens/s 低 | 线程数、GPU backend、offload、热降频、内存回退 | 固定 Prompt 后扫描少量 `-t/-ngl/-b` 组合；每次只改一项 |
| 输出乱码/角色泄漏 | UTF-8、tokenizer、GGUF chat template、EOS/stop | 比较 merged → F16 → Q4 → runtime，定位首次偏离阶段 |
| 端口冲突 | `11434` 或 `8080` 是否已监听 | 停止重复实例或显式换端口；客户端 URI 同步修改 |
| 请求 timeout | 模型是否仍加载、Prompt/context、队列和生成上限 | 查看服务日志，缩短输入或 `-n`；不要无限延长客户端超时 |

Ollama 日志位置和平台差异以官方 [Troubleshooting](https://docs.ollama.com/troubleshooting) 为准。日志中不要写 token、代理密码、完整用户 Prompt 或模型仓库凭据。

## 10. 基准记录模板

只有在同一硬件、同一电源/散热状态、同一模型 SHA、同一 Prompt、相同上下文/batch/线程/offload/chat template/reasoning 设置下，横向速度才有意义。至少分别记录一次冷启动和多次热请求；不要拿桌面 tokens/s 推断手机性能。

先记录模型哈希：

```powershell
$Gguf = 'C:\models\mobile-llm-q4_k_m.gguf'
$ModelSha256 = (Get-FileHash -Algorithm SHA256 $Gguf).Hash.ToLowerInvariant()
$ModelSha256
```

每次实验复制一行填写：

| 时间 | runtime / 版本 / commit | 模型 SHA-256 / quant | CPU / GPU / RAM | `-t` / `-ngl` | `-c` / `-b` | Prompt / 输出 token | TTFT | tokens/s | 峰值内存 | 冷/热 | 完整命令 / chat template / reasoning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `YYYY-MM-DD HH:mm:ss Z` | `Ollama x.y.z` 或 `llama.cpp 505b...` | `<sha256>` / `Q4_K_M` | `<型号与容量>` | `8` / `0` | `2048` / `512` | `<输入>` / `<输出>` | `<ms>` | `<token/s>` | `<MiB>` | `<cold/warm>` | `<完整 argv>` / `<template hash或来源>` / `off` |

还应在实验附件保存：

- Ollama `--version`，或 llama.cpp 完整 HEAD、origin、source status 与构建参数。
- 操作系统、CPU/GPU 驱动、RAM/VRAM、供电模式和测试时间。
- 固定 Prompt suite 的 SHA-256、每例输入/输出 token、错误率和业务判定。
- server 返回的 timing/usage 字段，或 CLI timing 原文；注明 TTFT 的测量边界。
- 峰值进程内存、温度/降频观察，以及 warm-up 次数。

## 11. 完成门禁与未执行项

完成一次本地部署验证，至少满足：

1. 运行时版本已记录；llama.cpp HEAD 等于完整 pinned commit，源码没有混入本地修改。
2. 模型来源、具体 tag/revision、SHA-256、文件大小和许可复核已记录。
3. CLI 与 HTTP 都使用同一固定 Prompt suite，正文、拒绝、格式、模板和非思考模式通过。
4. Ollama 与 llama-server 均保持 loopback，任何跨机器访问都经过鉴权、限流、TLS 和防火墙。
5. 冷/热延迟、TTFT、tokens/s、峰值内存和完整参数有可比较的原始记录。
6. Git 中没有 GGUF、模型权重、构建目录、临时请求体、日志或密钥。

本教程编写和静态验证期间**没有执行**以下重型或设备相关操作，因此不作虚假成功声明：

- 没有下载 `qwen3:0.6b` 或任何模型权重。
- 没有导入、复制或提交本地 GGUF。
- 没有真实构建 pinned llama.cpp。
- 没有运行 Ollama、`llama-cli`、`llama-server` 或真实生成请求。
- 没有做 GPU offload、手机真机、温升、峰值内存或性能基准。

这些步骤必须由你在目标工作站和手机上按本章命令执行，并把真实结果写入基准记录。

## 12. 官方资料

- [Ollama Download](https://ollama.com/download)
- [Ollama CLI Reference](https://docs.ollama.com/cli)
- [Ollama API Introduction](https://docs.ollama.com/api/introduction)
- [Ollama API Authentication](https://docs.ollama.com/api/authentication)
- [Ollama Generate API](https://docs.ollama.com/api/generate)
- [Ollama Streaming](https://docs.ollama.com/api/streaming)
- [Ollama Modelfile Reference](https://docs.ollama.com/modelfile)
- [Ollama FAQ](https://docs.ollama.com/faq)
- [qwen3:0.6b 模型页](https://ollama.com/library/qwen3:0.6b)
- [llama.cpp pinned build 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/docs/build.md)
- [llama.cpp pinned CLI 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/tools/cli/README.md)
- [llama.cpp pinned server 文档](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/tools/server/README.md)
- [llama.cpp pinned 参数源码](https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/common/arg.cpp)

### 本章小结

Ollama 适合快速打通下载、Modelfile 和 API，llama.cpp 适合把 GGUF、运行时 commit、构建参数和 offload 调优纳入可复现证据链。无论使用哪一个，真正的部署门槛都是固定模型与模板、可重复的质量和性能评测，以及不把无鉴权的本地端口暴露给不可信网络。
