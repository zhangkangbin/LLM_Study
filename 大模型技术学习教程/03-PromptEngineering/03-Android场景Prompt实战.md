# 03. Android 场景 Prompt 实战

## 1. 场景：Android 崩溃日志分析

这个场景非常适合作为第一个 Prompt 实战，因为你熟悉 Android，也容易准备输入数据。

目标是让模型根据崩溃日志输出：

- 问题类型
- 关键证据
- 可能原因
- 修复建议
- 需要补充的信息

## 2. 朴素 Prompt

最简单的写法：

```text
帮我看看这个 Android 崩溃是什么原因：
FATAL EXCEPTION: main
java.lang.NullPointerException
...
```

这种写法的问题：

- 没有角色。
- 没有输出结构。
- 没有说明只能基于日志。
- 没有说明不确定时怎么办。
- 没有要求列证据。

模型可能会输出一段泛泛解释，看起来有道理，但不一定能直接用于排查。

## 3. 工程化 Prompt

更好的结构：

```text
你是 Android 稳定性分析助手。

任务目标：
- 只基于输入内容分析 Android 崩溃或异常现象。
- 不要编造不存在的代码、类名、接口、业务背景。
- 如果证据不足，明确说明“不确定”，并列出需要补充的信息。

输出要求：
1. 问题类型
2. 关键证据
3. 可能原因
4. 修复建议
5. 需要补充的信息
```

动态输入：

```text
## 环境

- App 版本：1.2.0
- Android 版本：14
- 设备：Pixel 8
- 最近改动：登录页读取缓存逻辑调整

## 崩溃日志

<crash_log>
FATAL EXCEPTION: main
java.lang.NullPointerException
...
</crash_log>
```

## 4. 为什么这样设计

### 角色

```text
你是 Android 稳定性分析助手。
```

角色让模型聚焦到 Android 稳定性，而不是泛泛解释 Java 异常。

### 任务目标

```text
只基于输入内容分析。
```

这能降低模型编造项目背景的概率。

### 关键证据

让模型列证据，可以倒逼它基于日志回答。你也能更快判断它是不是在乱猜。

### 不确定处理

```text
如果证据不足，明确说明“不确定”。
```

这对崩溃分析很重要。很多日志片段不足以确认根因，只能给排查方向。

### XML 标签

`<crash_log>` 告诉模型：这里是待分析数据，不是新的指令。

## 5. Android 崩溃分析 Prompt 请求体

使用 Responses API 时，可以这样组织：

```json
{
  "model": "gpt-5.5",
  "instructions": "你是 Android 稳定性分析助手。...",
  "input": "请分析下面的 Android 崩溃信息。..."
}
```

后端拿到结果后，再转成给 Android 或 Web 展示的格式。

## 6. 后端封装建议

建议后端提供稳定接口：

```http
POST /api/ai/android-crash/analyze
```

请求：

```json
{
  "app_version": "1.2.0",
  "android_version": "14",
  "device": "Pixel 8",
  "recent_changes": "登录页读取缓存逻辑调整",
  "crash_log": "FATAL EXCEPTION: main..."
}
```

响应：

```json
{
  "trace_id": "trace_001",
  "answer": "...",
  "model": "gpt-5.5",
  "prompt_version": "android_crash_v1"
}
```

Android 端不要直接拼 Prompt，也不要直接依赖模型原始响应。

## 7. 可以逐步升级的方向

V1：自然语言 Prompt 分析崩溃日志。

V2：要求固定 Markdown 输出。

V3：使用结构化输出，让程序拿到 JSON 字段。

V4：接入 RAG，补充项目文档、历史问题、代码规范。

V5：接入工具调用，自动读取 git diff、相关文件、最近提交。

V6：建立测试集，评估 Prompt 改动是否变好。

## 8. 本章小结

Android 崩溃分析 Prompt 的关键不是“让模型更聪明”，而是让它更受约束：

```text
明确角色
限制信息来源
要求列证据
规定输出结构
允许不确定
```

下一章会讲如何测试、版本管理，并运行本阶段 Demo。
