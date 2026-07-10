import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class AndroidAiClientDemo {
    private AndroidAiClientDemo() {
    }

    public enum ChatStatus {
        IDLE,
        WAITING,
        STREAMING,
        CANCELLED,
        ERROR
    }

    public enum MessageStatus {
        COMPLETED,
        STREAMING,
        CANCELLED,
        ERROR
    }

    public record BackendRequest(String url, Map<String, String> headers, String body) {
    }

    public record StreamEvent(String type, String data) {
    }

    public record Citation(String label, String title) {
    }

    public record Message(
            String id,
            String role,
            String content,
            MessageStatus status,
            String traceId,
            List<Citation> citations
    ) {
    }

    public record ChatState(
            ChatStatus status,
            List<Message> messages,
            String activeTraceId,
            String pendingInput,
            String lastError
    ) {
        public static ChatState initial() {
            return new ChatState(ChatStatus.IDLE, List.of(), null, "", null);
        }
    }

    public sealed interface ChatEvent permits UserSubmitted, AssistantStarted, AssistantDelta,
            AssistantCompleted, UserCancelled, AssistantFailed {
    }

    public record UserSubmitted(String text) implements ChatEvent {
    }

    public record AssistantStarted(String traceId) implements ChatEvent {
    }

    public record AssistantDelta(String text) implements ChatEvent {
    }

    public record AssistantCompleted(List<Citation> citations) implements ChatEvent {
    }

    public record UserCancelled() implements ChatEvent {
    }

    public record AssistantFailed(String errorCode) implements ChatEvent {
    }

    public static BackendRequest buildBackendRequest(String baseUrl, String appSessionToken, String prompt) {
        String safeBaseUrl = trimTrailingSlash(baseUrl);
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Authorization", "Bearer " + appSessionToken);
        headers.put("Content-Type", "application/json; charset=utf-8");
        headers.put("Accept", "text/event-stream");
        String body = "{\"message\":\"" + escapeJson(prompt) + "\",\"stream\":true}";
        return new BackendRequest(safeBaseUrl + "/ai/chat/stream", headers, body);
    }

    public static StreamEvent parseSseEvent(String block) {
        String type = "";
        String data = "";
        for (String line : block.split("\\R")) {
            if (line.startsWith("event:")) {
                type = line.substring("event:".length()).trim();
            }
            if (line.startsWith("data:")) {
                data = line.substring("data:".length()).stripLeading();
            }
        }
        return new StreamEvent(type, data);
    }

    public static ChatState reduce(ChatState state, ChatEvent event) {
        if (event instanceof UserSubmitted submitted) {
            String text = submitted.text().trim();
            if (text.isEmpty()) {
                return new ChatState(state.status(), state.messages(), state.activeTraceId(), state.pendingInput(), "empty_input");
            }
            List<Message> next = new ArrayList<>(state.messages());
            next.add(new Message(nextMessageId(next, "user"), "user", text, MessageStatus.COMPLETED, null, List.of()));
            return new ChatState(ChatStatus.WAITING, List.copyOf(next), null, text, null);
        }
        if (event instanceof AssistantStarted started) {
            List<Message> next = new ArrayList<>(state.messages());
            next.add(new Message(nextMessageId(next, "assistant"), "assistant", "", MessageStatus.STREAMING, started.traceId(), List.of()));
            return new ChatState(ChatStatus.STREAMING, List.copyOf(next), started.traceId(), state.pendingInput(), null);
        }
        if (event instanceof AssistantDelta delta) {
            if (state.status() == ChatStatus.CANCELLED || state.status() == ChatStatus.ERROR) {
                return state;
            }
            return updateLastAssistant(state, message -> new Message(
                    message.id(),
                    message.role(),
                    message.content() + delta.text(),
                    MessageStatus.STREAMING,
                    message.traceId(),
                    message.citations()
            ), ChatStatus.STREAMING, null);
        }
        if (event instanceof AssistantCompleted completed) {
            if (state.status() == ChatStatus.CANCELLED) {
                return state;
            }
            return updateLastAssistant(state, message -> new Message(
                    message.id(),
                    message.role(),
                    message.content(),
                    MessageStatus.COMPLETED,
                    message.traceId(),
                    List.copyOf(completed.citations())
            ), ChatStatus.IDLE, null);
        }
        if (event instanceof UserCancelled) {
            return updateLastAssistant(state, message -> new Message(
                    message.id(),
                    message.role(),
                    message.content(),
                    MessageStatus.CANCELLED,
                    message.traceId(),
                    message.citations()
            ), ChatStatus.CANCELLED, null);
        }
        if (event instanceof AssistantFailed failed) {
            return updateLastAssistant(state, message -> new Message(
                    message.id(),
                    message.role(),
                    message.content(),
                    MessageStatus.ERROR,
                    message.traceId(),
                    message.citations()
            ), ChatStatus.ERROR, failed.errorCode());
        }
        return state;
    }

    public static boolean shouldRetry(int httpCode) {
        return httpCode == 408 || httpCode == 409 || httpCode == 429 || httpCode >= 500;
    }

    public static String toUserMessage(String errorCode) {
        return switch (errorCode) {
            case "timeout" -> "网络超时，请稍后重试。";
            case "rate_limited" -> "请求过于频繁，请稍后再试。";
            case "token_budget_exceeded" -> "内容太长，请缩短后再试。";
            case "unauthorized" -> "登录状态已失效，请重新登录。";
            default -> "服务暂时不可用。";
        };
    }

    public static void main(String[] args) {
        ChatState state = ChatState.initial();
        state = reduce(state, new UserSubmitted("Android 端如何接入大模型流式输出？"));
        state = reduce(state, new AssistantStarted("trace-demo"));
        state = reduce(state, new AssistantDelta("Android 端应连接自己的后端网关，"));
        state = reduce(state, new AssistantDelta("由后端负责模型密钥、RAG、Agent 和权限控制。"));
        state = reduce(state, new AssistantCompleted(List.of(new Citation("[android-client#0]", "Android AI Client"))));
        System.out.println(toJsonLike(state));
    }

    private interface MessageMapper {
        Message map(Message message);
    }

    private static ChatState updateLastAssistant(ChatState state, MessageMapper mapper, ChatStatus nextStatus, String error) {
        if (state.messages().isEmpty()) {
            return new ChatState(nextStatus, state.messages(), state.activeTraceId(), state.pendingInput(), error);
        }
        List<Message> next = new ArrayList<>(state.messages());
        int lastIndex = next.size() - 1;
        Message last = next.get(lastIndex);
        if (!"assistant".equals(last.role())) {
            return state;
        }
        next.set(lastIndex, mapper.map(last));
        String traceId = nextStatus == ChatStatus.STREAMING ? state.activeTraceId() : null;
        return new ChatState(nextStatus, List.copyOf(next), traceId, state.pendingInput(), error);
    }

    private static String nextMessageId(List<Message> messages, String role) {
        return role + "-" + (messages.size() + 1);
    }

    private static String trimTrailingSlash(String value) {
        if (value.endsWith("/")) {
            return value.substring(0, value.length() - 1);
        }
        return value;
    }

    private static String escapeJson(String value) {
        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
    }

    private static String toJsonLike(ChatState state) {
        Message last = state.messages().isEmpty() ? null : state.messages().get(state.messages().size() - 1);
        return "{\n"
                + "  \"status\": \"" + state.status() + "\",\n"
                + "  \"messageCount\": " + state.messages().size() + ",\n"
                + "  \"assistant\": \"" + (last == null ? "" : escapeJson(last.content())) + "\"\n"
                + "}";
    }
}
