# Demo：离线 Android AI 客户端

本阶段 Demo 用 Java 标准库模拟 Android 端 AI 客户端的核心逻辑。因为当前环境没有 Kotlin 编译器，所以 Demo 使用可编译运行的 Java 21；教程正文里仍给出 Kotlin/ViewModel 的落地骨架。

## Demo 文件

```text
12-Android端接入大模型/
  demo/
    src/
      AndroidAiClientDemo.java
      AndroidAiClientDemoTest.java
```

## 它演示了什么

1. Android 请求自己的后端网关。
2. 请求头只放 App 会话 token，不暴露模型 API Key。
3. 解析 SSE 风格事件。
4. 管理聊天状态。
5. 流式追加 assistant 文本。
6. 用户取消后忽略迟到 delta。
7. 判断哪些 HTTP 错误适合重试。
8. 把错误码映射成用户文案。

## 编译并运行测试

在项目根目录执行：

```powershell
New-Item -ItemType Directory -Force '.\大模型技术学习教程\12-Android端接入大模型\demo\build\classes'
javac -encoding UTF-8 -d '.\大模型技术学习教程\12-Android端接入大模型\demo\build\classes' '.\大模型技术学习教程\12-Android端接入大模型\demo\src\AndroidAiClientDemo.java' '.\大模型技术学习教程\12-Android端接入大模型\demo\src\AndroidAiClientDemoTest.java'
java -cp '.\大模型技术学习教程\12-Android端接入大模型\demo\build\classes' AndroidAiClientDemoTest
```

成功后会输出：

```text
AndroidAiClientDemoTest OK
```

## 运行 Demo

```powershell
java -cp '.\大模型技术学习教程\12-Android端接入大模型\demo\build\classes' AndroidAiClientDemo
```

输出会显示模拟聊天状态：

```json
{
  "status": "IDLE",
  "messageCount": 2,
  "assistant": "Android 端应连接自己的后端网关..."
}
```

## 核心代码说明

`buildBackendRequest` 演示 Android 端应该如何构造后端请求：

```java
headers.put("Authorization", "Bearer " + appSessionToken);
headers.put("Accept", "text/event-stream");
```

注意它没有 `OpenAI-Api-Key`。模型供应商密钥只应该存在于后端。

`reduce` 演示状态机：

1. `UserSubmitted`：写入用户消息，进入 `WAITING`。
2. `AssistantStarted`：创建 assistant 消息，进入 `STREAMING`。
3. `AssistantDelta`：追加文本。
4. `AssistantCompleted`：写入引用，回到 `IDLE`。
5. `UserCancelled`：标记取消。
6. `AssistantFailed`：标记错误。

## 迁移到真实 Android 项目

真实 Android 项目可以这样迁移：

| Demo 概念 | Android 实现 |
| --- | --- |
| `ChatState` | `ChatUiState` |
| `reduce` | ViewModel 内部 reducer |
| `BackendRequest` | OkHttp / Retrofit / Ktor 请求 |
| `parseSseEvent` | SSE parser / streaming reader |
| `shouldRetry` | Repository 重试策略 |
| `toUserMessage` | UI 错误文案映射 |

当你接真实后端时，先保持这套状态机，再替换网络层即可。
