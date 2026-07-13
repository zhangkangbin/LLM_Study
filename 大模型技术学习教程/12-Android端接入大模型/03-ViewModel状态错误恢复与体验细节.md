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

## ViewModel 状态转换例子

下面的 reducer 伪代码展示了“状态先行”的写法：

```kotlin
fun reduce(event: ChatEvent) {
    state = when (event) {
        is ChatEvent.AssistantStarted -> state.copy(
            status = ChatStatus.Waiting,
            activeTraceId = event.traceId,
            lastError = null
        )
        is ChatEvent.AssistantDelta -> {
            if (state.status != ChatStatus.Streaming && state.status != ChatStatus.Waiting) {
                state
            } else {
                state.copy(
                    status = ChatStatus.Streaming,
                    messages = appendDelta(state.messages, event.messageId, event.text)
                )
            }
        }
        is ChatEvent.AssistantCompleted -> state.copy(
            status = ChatStatus.Idle,
            messages = completeMessage(state.messages, event.messageId, event.citations)
        )
        is ChatEvent.UserCancelled -> state.copy(
            status = ChatStatus.Cancelled,
            messages = markActiveMessageCancelled(state.messages)
        )
        is ChatEvent.AssistantFailed -> state.copy(
            status = ChatStatus.Error,
            lastError = event.userMessage
        )
    }
}
```

注意 `AssistantDelta` 的分支：如果当前状态已经是 `Cancelled` 或 `Error`，迟到 delta 不应该改变 UI。这条规则能同时处理取消、断网、切换会话和重新生成。

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

## Repository 错误映射例子

Repository 可以把后端错误转换成 UI 能理解的稳定错误：

| 后端/网络错误 | `AiFailure` | 用户文案 | 可重试 |
| --- | --- | --- | --- |
| 无网络 | `NetworkUnavailable` | 当前网络不可用，请检查连接 | 是 |
| 408 或读超时 | `TimeoutBeforeFirstDelta` | 连接超时，已保留你的问题 | 是 |
| 429 | `RateLimited` | 当前请求较多，请稍后再试 | 按 `retry_after_seconds` |
| 401 | `Unauthorized` | 登录状态已失效，请重新登录 | 否 |
| 5xx | `ServerError(traceId)` | 服务暂时不可用，可稍后重试 | 是 |
| 用户取消 | `UserCancelled` | 已停止生成 | 可重新生成 |

这样做的好处是 UI 文案、重试按钮和反馈入口都由业务错误决定，而不是散落在网络层异常判断里。

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
