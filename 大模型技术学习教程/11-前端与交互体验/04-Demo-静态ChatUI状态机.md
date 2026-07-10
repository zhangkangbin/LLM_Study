# Demo：静态 Chat UI 状态机

本阶段 Demo 是一个静态 HTML + JavaScript 的 AI 聊天界面原型。它不依赖后端，也不调用真实模型，用定时器模拟流式输出。

## Demo 文件

```text
11-前端与交互体验/
  demo/
    chat_ui_demo.html
    chat_ui_state.cjs
    tests/
      chat_ui_state.test.cjs
```

## 它演示了什么

1. 消息状态机。
2. 用户消息提交。
3. assistant 消息开始。
4. delta 追加。
5. completed 完成。
6. cancel 取消。
7. retry 重试。
8. citation 引用展示。
9. UI 控件状态派生。

## 打开 HTML Demo

直接用浏览器打开：

```text
E:\KangWorkInfo\LLM_Study\大模型技术学习教程\11-前端与交互体验\demo\chat_ui_demo.html
```

这是纯静态页面，不需要启动开发服务器。

## 运行测试

```powershell
node --test '.\大模型技术学习教程\11-前端与交互体验\demo\tests\chat_ui_state.test.cjs'
```

测试覆盖：

1. 用户消息提交。
2. 流式 delta 追加。
3. 完成状态和引用写入。
4. 取消状态。
5. 重试逻辑。
6. SSE 事件解析。
7. UI 控件状态派生。
8. 引用显示格式。

## 状态机核心

`chat_ui_state.cjs` 是 Demo 的核心，它不依赖 DOM，因此可以被 Android、Web、单元测试借鉴。

典型流程：

```javascript
let state = createInitialState();
state = submitUserMessage(state, "解释 RAG 前端体验");
state = startAssistantMessage(state, "trace-1");
state = appendAssistantDelta(state, "先显示首段内容");
state = receiveCompleted(state, citations);
```

这个写法的重点是：每个事件都返回新状态，UI 只是根据状态渲染。

## 接真实后端时怎么改

真实项目里可以替换这些部分：

| Demo 部分 | 真实项目 |
| --- | --- |
| 定时器模拟 delta | SSE / WebSocket / fetch stream |
| 固定 citations | 后端返回 RAG citations |
| 本地状态 | ViewModel / Redux / Zustand / Compose State |
| Cancel 按钮 | AbortController / 后端 cancel API |
| Retry 按钮 | 重新发送上一条 user message |

前端的关键不是和某个框架绑定，而是把模型交互拆成稳定事件和状态。
