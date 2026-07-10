import java.util.List;
import java.util.Map;

public class AndroidAiClientDemoTest {
    public static void main(String[] args) {
        testBuildBackendRequestDoesNotExposeOpenAiKey();
        testParseSseEvent();
        testReducerStreamsTextAndCompletes();
        testCancelIgnoresLateDelta();
        testRetryPolicy();
        testErrorMapping();
        System.out.println("AndroidAiClientDemoTest OK");
    }

    private static void testBuildBackendRequestDoesNotExposeOpenAiKey() {
        AndroidAiClientDemo.BackendRequest request = AndroidAiClientDemo.buildBackendRequest(
                "https://api.example.com",
                "app-session-token",
                "解释 Android 流式输出"
        );

        assertEquals("https://api.example.com/ai/chat/stream", request.url());
        assertEquals("Bearer app-session-token", request.headers().get("Authorization"));
        assertFalse(request.headers().containsKey("OpenAI-Api-Key"));
        assertTrue(request.body().contains("解释 Android 流式输出"));
    }

    private static void testParseSseEvent() {
        AndroidAiClientDemo.StreamEvent event = AndroidAiClientDemo.parseSseEvent(
                "event: response.output_text.delta\n" +
                        "data: hello\n"
        );

        assertEquals("response.output_text.delta", event.type());
        assertEquals("hello", event.data());
    }

    private static void testReducerStreamsTextAndCompletes() {
        AndroidAiClientDemo.ChatState state = AndroidAiClientDemo.ChatState.initial();
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.UserSubmitted("空指针崩溃怎么排查"));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantStarted("trace-1"));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantDelta("先看 "));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantDelta("FATAL EXCEPTION"));
        state = AndroidAiClientDemo.reduce(
                state,
                new AndroidAiClientDemo.AssistantCompleted(
                        List.of(new AndroidAiClientDemo.Citation("[android-crash-guide#0]", "Android 崩溃排查"))
                )
        );

        AndroidAiClientDemo.Message assistant = state.messages().get(1);
        assertEquals(AndroidAiClientDemo.ChatStatus.IDLE, state.status());
        assertEquals("先看 FATAL EXCEPTION", assistant.content());
        assertEquals(AndroidAiClientDemo.MessageStatus.COMPLETED, assistant.status());
        assertEquals("Android 崩溃排查", assistant.citations().get(0).title());
    }

    private static void testCancelIgnoresLateDelta() {
        AndroidAiClientDemo.ChatState state = AndroidAiClientDemo.ChatState.initial();
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.UserSubmitted("写长文"));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantStarted("trace-2"));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantDelta("第一段"));
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.UserCancelled());
        state = AndroidAiClientDemo.reduce(state, new AndroidAiClientDemo.AssistantDelta("迟到内容"));

        AndroidAiClientDemo.Message assistant = state.messages().get(1);
        assertEquals(AndroidAiClientDemo.ChatStatus.CANCELLED, state.status());
        assertEquals("第一段", assistant.content());
        assertEquals(AndroidAiClientDemo.MessageStatus.CANCELLED, assistant.status());
    }

    private static void testRetryPolicy() {
        assertTrue(AndroidAiClientDemo.shouldRetry(408));
        assertTrue(AndroidAiClientDemo.shouldRetry(429));
        assertTrue(AndroidAiClientDemo.shouldRetry(503));
        assertFalse(AndroidAiClientDemo.shouldRetry(400));
        assertFalse(AndroidAiClientDemo.shouldRetry(401));
    }

    private static void testErrorMapping() {
        assertEquals("网络超时，请稍后重试。", AndroidAiClientDemo.toUserMessage("timeout"));
        assertEquals("请求过于频繁，请稍后再试。", AndroidAiClientDemo.toUserMessage("rate_limited"));
        assertEquals("服务暂时不可用。", AndroidAiClientDemo.toUserMessage("unknown"));
    }

    private static void assertEquals(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected=" + expected + ", actual=" + actual);
        }
    }

    private static void assertTrue(boolean value) {
        if (!value) {
            throw new AssertionError("expected true");
        }
    }

    private static void assertFalse(boolean value) {
        if (value) {
            throw new AssertionError("expected false");
        }
    }
}
