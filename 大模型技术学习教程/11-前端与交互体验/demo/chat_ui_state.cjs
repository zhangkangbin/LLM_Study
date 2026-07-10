function createInitialState() {
  return {
    status: "idle",
    messages: [],
    pendingInput: "",
    activeTraceId: null,
    lastError: null,
  };
}

function submitUserMessage(state, rawInput) {
  const content = String(rawInput || "").trim();
  if (!content) {
    return { ...state, lastError: "empty_input" };
  }
  return {
    ...state,
    status: "waiting",
    pendingInput: content,
    lastError: null,
    messages: [
      ...state.messages,
      {
        id: nextMessageId(state, "user"),
        role: "user",
        content,
        status: "completed",
        citations: [],
      },
    ],
  };
}

function startAssistantMessage(state, traceId) {
  return {
    ...state,
    status: "streaming",
    activeTraceId: traceId,
    messages: [
      ...state.messages,
      {
        id: nextMessageId(state, "assistant"),
        role: "assistant",
        content: "",
        status: "streaming",
        traceId,
        citations: [],
      },
    ],
  };
}

function appendAssistantDelta(state, delta) {
  const messages = state.messages.map((message, index) => {
    if (index !== state.messages.length - 1 || message.role !== "assistant") {
      return message;
    }
    return {
      ...message,
      content: message.content + String(delta || ""),
      status: "streaming",
    };
  });
  return { ...state, status: "streaming", messages };
}

function receiveCompleted(state, citations = []) {
  const messages = state.messages.map((message, index) => {
    if (index !== state.messages.length - 1 || message.role !== "assistant") {
      return message;
    }
    return {
      ...message,
      status: "completed",
      citations,
    };
  });
  return {
    ...state,
    status: "idle",
    activeTraceId: null,
    pendingInput: "",
    messages,
  };
}

function cancelAssistantMessage(state) {
  const messages = state.messages.map((message, index) => {
    if (index !== state.messages.length - 1 || message.role !== "assistant") {
      return message;
    }
    return {
      ...message,
      status: "cancelled",
    };
  });
  return {
    ...state,
    status: "cancelled",
    activeTraceId: null,
    messages,
  };
}

function retryLastAssistant(state) {
  const lastUser = [...state.messages].reverse().find((message) => message.role === "user");
  const messages = trimTrailingAssistant(state.messages);
  return {
    ...state,
    status: "waiting",
    pendingInput: lastUser ? lastUser.content : "",
    activeTraceId: null,
    lastError: null,
    messages,
  };
}

function parseSseEventBlock(block) {
  const event = { event: "", data: "" };
  for (const line of String(block || "").split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event.event = line.slice("event:".length).trim();
    }
    if (line.startsWith("data:")) {
      event.data = line.slice("data:".length).trimStart();
    }
  }
  return event;
}

function buildUiModel(state) {
  return {
    messageCount: state.messages.length,
    canSend: state.status === "idle" || state.status === "cancelled" || state.status === "error",
    canCancel: state.status === "streaming" || state.status === "waiting",
    canRetry: hasTrailingAssistant(state.messages),
    showTypingIndicator: state.status === "streaming" || state.status === "waiting",
    statusLabel: statusLabel(state.status),
  };
}

function formatCitation(citation) {
  const label = citation.label || `[${citation.docId || citation.doc_id || "source"}]`;
  const title = citation.title || citation.sourceUri || citation.source_uri || "";
  return title ? `${label} ${title}` : label;
}

function statusLabel(status) {
  const labels = {
    idle: "Ready",
    waiting: "Waiting",
    streaming: "Streaming",
    cancelled: "Cancelled",
    error: "Error",
  };
  return labels[status] || "Unknown";
}

function nextMessageId(state, role) {
  return `${role}-${state.messages.length + 1}`;
}

function trimTrailingAssistant(messages) {
  if (!messages.length) {
    return messages;
  }
  const last = messages[messages.length - 1];
  if (last.role === "assistant") {
    return messages.slice(0, -1);
  }
  return messages;
}

function hasTrailingAssistant(messages) {
  if (!messages.length) {
    return false;
  }
  return messages[messages.length - 1].role === "assistant";
}

const exported = {
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
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = exported;
}

if (typeof window !== "undefined") {
  window.chatUiState = exported;
}
