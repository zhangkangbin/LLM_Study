# ViewModel 状态、错误恢复与体验细节

Android AI 聊天界面最容易出问题的地方是状态混乱。推荐先定义状态，再写 UI。

## UI 状态

```kotlin
data class ChatUiState(
    val status: ChatStatus = ChatStatus.Idle,
    val messages: List<ChatMessage> = emptyList(),
    val activeTraceId: String? = null,
    val pendingInput: String = "",
    val lastError: String? = null
)
```

状态枚举：

```kotlin
enum class ChatStatus {
    Idle,
    Waiting,
    Streaming,
    Cancelled,
    Error
}
```

消息对象：

```kotlin
data class ChatMessage(
    val id: String,
    val role: Role,
    val content: String,
    val status: MessageStatus,
    val traceId: String? = null,
    val citations: List<Citation> = emptyList()
)
```

## 事件驱动

把后端事件转换成 ViewModel 事件：

| 后端事件 | ViewModel 事件 |
| --- | --- |
| `message.started` | `AssistantStarted(traceId)` |
| `message.delta` | `AssistantDelta(text)` |
| `message.completed` | `AssistantCompleted(citations)` |
| `response.error` | `AssistantFailed(errorCode)` |
| 用户点击取消 | `UserCancelled` |

这样 UI 不需要知道网络细节，只订阅 `ChatUiState`。

## Compose UI 规则

按钮状态可以从 `ChatUiState` 派生：

```kotlin
val canSend = state.status == Idle || state.status == Error || state.status == Cancelled
val canCancel = state.status == Waiting || state.status == Streaming
val showTyping = state.status == Waiting || state.status == Streaming
```

渲染规则：

1. `Waiting`：显示等待状态。
2. `Streaming`：逐步追加 assistant 文本。
3. `Completed`：显示复制、引用、反馈按钮。
4. `Error`：显示重试。
5. `Cancelled`：保留已生成内容，允许重试。

## 重试策略

Android 端可以对部分错误显示“重试”：

| 错误 | 是否建议重试 |
| --- | --- |
| 408 超时 | 是 |
| 429 限流 | 稍后重试 |
| 5xx 后端错误 | 是 |
| 400 参数错误 | 否 |
| 401 未登录 | 重新登录 |
| 用户取消 | 可重新生成 |

真实重试要避免重复创建工单、重复提交 Agent 动作。这类任务需要后端幂等键。

## 引用展示

RAG 答案里的引用应该保留结构化数据：

```kotlin
data class Citation(
    val label: String,
    val title: String,
    val sourceUri: String
)
```

Android 端可以展示成横向标签、底部弹窗或文档跳转。不要只把引用混进普通文本，否则后续无法点击、追踪和调试。

## 体验细节

1. 首 token 慢时显示“正在连接”。
2. 流式输出期间禁用发送按钮。
3. 取消按钮要立即响应。
4. 页面旋转后保留消息。
5. 失败后保留用户输入，方便重试。
6. 长答案滚动到底部，但用户手动上滑后不要强行拉回。
7. 对代码块、表格、长链接做移动端适配。
8. 调试环境显示 trace_id，正式环境放到反馈入口。
