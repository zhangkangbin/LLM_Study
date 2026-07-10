const assert = require("node:assert/strict");
const test = require("node:test");

const {
  appendAssistantDelta,
  buildUiModel,
  cancelAssistantMessage,
  createInitialState,
  formatCitation,
  parseSseEventBlock,
  receiveCompleted,
  retryLastAssistant,
  startAssistantMessage,
  submitUserMessage,
} = require("../chat_ui_state.cjs");

test("submitUserMessage appends a user message and moves to waiting", () => {
  const state = submitUserMessage(createInitialState(), "  解释 RAG 前端体验  ");

  assert.equal(state.status, "waiting");
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].role, "user");
  assert.equal(state.messages[0].content, "解释 RAG 前端体验");
});

test("streaming assistant message accumulates deltas and completes", () => {
  let state = submitUserMessage(createInitialState(), "空指针崩溃怎么排查");
  state = startAssistantMessage(state, "trace-1");
  state = appendAssistantDelta(state, "先看 ");
  state = appendAssistantDelta(state, "FATAL EXCEPTION");
  state = receiveCompleted(state, [
    { label: "[android-crash-guide#0]", title: "Android 崩溃排查" },
  ]);

  const assistant = state.messages.at(-1);
  assert.equal(state.status, "idle");
  assert.equal(assistant.role, "assistant");
  assert.equal(assistant.content, "先看 FATAL EXCEPTION");
  assert.equal(assistant.status, "completed");
  assert.equal(assistant.citations[0].title, "Android 崩溃排查");
});

test("cancelAssistantMessage marks current assistant response as cancelled", () => {
  let state = submitUserMessage(createInitialState(), "写长文");
  state = startAssistantMessage(state, "trace-2");
  state = appendAssistantDelta(state, "正在生成");
  state = cancelAssistantMessage(state);

  const assistant = state.messages.at(-1);
  assert.equal(state.status, "cancelled");
  assert.equal(assistant.status, "cancelled");
});

test("retryLastAssistant removes failed assistant and reuses last user input", () => {
  let state = submitUserMessage(createInitialState(), "解释流式输出");
  state = startAssistantMessage(state, "trace-3");
  state = appendAssistantDelta(state, "失败前内容");
  state = { ...state, status: "error", messages: state.messages.map((message, index) => index === 1 ? { ...message, status: "error" } : message) };

  state = retryLastAssistant(state);

  assert.equal(state.status, "waiting");
  assert.equal(state.messages.length, 1);
  assert.equal(state.pendingInput, "解释流式输出");
});

test("parseSseEventBlock extracts event and data", () => {
  const event = parseSseEventBlock("event: response.output_text.delta\ndata: hello\n");

  assert.deepEqual(event, {
    event: "response.output_text.delta",
    data: "hello",
  });
});

test("buildUiModel exposes control states", () => {
  let state = submitUserMessage(createInitialState(), "hello");
  state = startAssistantMessage(state, "trace-4");
  const ui = buildUiModel(state);

  assert.equal(ui.canSend, false);
  assert.equal(ui.canCancel, true);
  assert.equal(ui.showTypingIndicator, true);
});

test("formatCitation creates compact display text", () => {
  const label = formatCitation({
    label: "[backend-api-errors#0]",
    title: "后端 API 错误排查",
    sourceUri: "app://knowledge/backend/api-errors",
  });

  assert.equal(label, "[backend-api-errors#0] 后端 API 错误排查");
});
