# Tools、Resources、Prompts 与应用扩展

MCP 和很多 Agent 框架都会区分工具、资源和提示模板。理解这三者，可以避免把所有东西都做成“工具调用”。

## Tools

Tools 是可执行动作，例如：

1. 搜索文档。
2. 创建工单。
3. 查询订单。
4. 发送通知。
5. 运行分析。

工具要有明确输入 Schema、权限、错误码和审计。

一个好 Tool 应该满足：

1. 名称动词明确，例如 `search_android_knowledge`、`create_support_ticket`。
2. 输入参数少而清楚。
3. 有 JSON Schema。
4. 有权限边界。
5. 有可预期错误码。
6. 有审计日志。
7. 高风险动作有人工确认。

示例：

```json
{
  "name": "create_debug_ticket",
  "input": {
    "title": "登录页空指针崩溃",
    "severity": "P1",
    "evidence": ["crash_log_001", "git_diff_002"]
  }
}
```

这个工具执行前，系统仍然要校验当前用户是否有创建工单权限，以及 `severity` 是否允许由模型建议。

## Resources

Resources 是上下文和数据，例如：

1. 当前项目 README。
2. 用户可见知识库列表。
3. API 文档。
4. 数据库 Schema。
5. 当前任务状态。

资源通常是只读的。它们帮助模型理解上下文，不应该承担副作用。

Resource 适合暴露稳定上下文：

```text
android://runbook/crash
android://schema/chat-events
android://project/current-readme
android://eval/latest-summary
```

资源读取也要做权限过滤。不能因为它“只是上下文”就绕过租户、项目或角色限制。

## Prompts

Prompts 是可复用工作流模板，例如：

1. 代码审查模板。
2. Bug 分析模板。
3. 周报生成模板。
4. 数据分析模板。
5. 客服回复模板。

提示模板适合沉淀团队经验。

Prompt 模板建议包含：

1. 任务目标。
2. 输入说明。
3. 输出格式。
4. 不确定时怎么办。
5. 安全边界。
6. 示例。

例如：

```text
名称：review_android_crash_log
目标：根据崩溃日志、版本信息和可见知识库资料，输出排查建议。
边界：资料不足时不要猜根因，列出需要补充的信息。
输出：异常类型、关键证据、可能原因、修复建议、需要补充的信息。
```

Prompt 模板不是把系统提示词散落到聊天记录里，而是把团队经验版本化。

## 应用扩展

如果需要给用户提供 UI，而不是只给模型一个工具，可以考虑应用扩展或插件形态。比如：

1. 在 AI 产品里展示报表。
2. 让用户选择参数。
3. 展示地图、图表、表格。
4. 完成多步表单。

协议只决定连接方式，不决定产品体验。产品体验仍然要按用户任务设计。

## 不要混淆三者

| 误用 | 更合适的做法 |
| --- | --- |
| 把“读取 README”做成会写数据库的 Tool | 做成 Resource |
| 把“创建工单”做成 Resource | 做成 Tool，并加人工确认 |
| 把一大段团队流程复制到每次对话 | 做成 Prompt 模板 |
| 只需要展示报表，却塞进纯 Tool 返回 JSON | 做成 App / 插件 UI |

## 本章小结

Tools 负责动作，Resources 负责上下文，Prompts 负责复用流程，App/插件负责用户体验。把边界分清，系统才容易权限控制、审计和维护。
