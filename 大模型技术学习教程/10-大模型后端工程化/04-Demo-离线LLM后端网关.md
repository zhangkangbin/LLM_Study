# Demo：离线 LLM 后端网关

本阶段 Demo 用纯 Python 标准库模拟一个 LLM Backend Gateway。它不启动 Web 服务，也不调用真实模型，而是把后端工程化的关键函数拆出来。

## Demo 文件

```text
10-大模型后端工程化/
  demo/
    llm_backend_gateway.py
    tests/
      test_llm_backend_gateway.py
```

## 它演示了什么

1. 请求对象 `LlmRequest`。
2. 模型配置 `ModelProfile`。
3. token 估算。
4. 模型路由。
5. 用户级限流。
6. token 预算拒绝。
7. transient error 重试。
8. SSE 风格流式事件。
9. 日志脱敏。
10. Responses API payload 示例。

## 运行模型路由

```powershell
python '.\大模型技术学习教程\10-大模型后端工程化\demo\llm_backend_gateway.py' route --task-type rag --prompt 'Android 崩溃知识库问答'
```

输出会显示选择的模型 profile，例如 `balanced-rag`。

## 运行模拟请求

```powershell
python '.\大模型技术学习教程\10-大模型后端工程化\demo\llm_backend_gateway.py' chat --prompt '请分析 Android 空指针崩溃'
```

输出包含：

1. `status`。
2. `trace_id`。
3. `model` 和 `provider_model`。
4. `output_text`。
5. `usage`。
6. 脱敏后的 `log`。

## 运行流式模拟

```powershell
python '.\大模型技术学习教程\10-大模型后端工程化\demo\llm_backend_gateway.py' chat --prompt '解释 RAG 后端架构' --stream
```

Demo 会生成类似 SSE 的事件：

```text
event: response.output_text.delta
data: ...
```

真实项目里，你可以把 OpenAI Responses API 的 stream 事件转换成自己的 Android/Web 客户端事件协议。

## 生成 Responses API 请求体

```powershell
python '.\大模型技术学习教程\10-大模型后端工程化\demo\llm_backend_gateway.py' payload --prompt '生成长报告' --background
```

这会展示 `stream`、`background`、`model`、`input` 等请求字段如何被组装。

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\10-大模型后端工程化\demo\tests'
```

测试覆盖：

1. token 估算。
2. 模型路由。
3. 限流。
4. 重试。
5. 日志脱敏。
6. SSE 事件。
7. 正常请求处理。
8. token 预算拒绝。
9. rate limit 拒绝。

## 接入真实后端框架

把这个 Demo 迁移到真实后端时，可以这样对应：

| Demo 函数 | 真实后端位置 |
| --- | --- |
| `handle_chat_request` | Controller / Service |
| `InMemoryRateLimiter` | Redis / API Gateway / Bucket4j |
| `pick_model` | 模型路由服务 |
| `retry_with_backoff` | HTTP client retry policy |
| `sse_events_from_text` | SSE/WebSocket 输出层 |
| `build_safe_log` | 日志中间件 / APM |
| `FakeModelClient` | OpenAI SDK / HTTP client |

后端工程化的核心不是某个框架，而是这些边界和治理能力。
