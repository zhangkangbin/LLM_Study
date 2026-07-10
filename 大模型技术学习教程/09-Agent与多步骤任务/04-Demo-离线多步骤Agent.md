# Demo：离线多步骤 Agent

本阶段 Demo 用纯 Python 标准库实现一个可运行的多步骤 Agent 骨架。它不会调用真实模型，而是用 `ScriptedPlanner` 模拟模型的下一步决策。

## Demo 文件

```text
09-Agent与多步骤任务/
  demo/
    agent_workflow_demo.py
    tests/
      test_agent_workflow_demo.py
```

## 它演示了什么

1. 工具 Schema。
2. 工具注册表。
3. 工具调用执行。
4. Agent loop。
5. trace 记录。
6. 最大步数保护。
7. Responses API tool payload 示例。

## 运行普通任务

```powershell
python '.\大模型技术学习教程\09-Agent与多步骤任务\demo\agent_workflow_demo.py' run --goal '空指针崩溃怎么排查'
```

你会看到 Agent 先调用 `search_knowledge_base`，再输出最终答案。

## 运行带工单的任务

```powershell
python '.\大模型技术学习教程\09-Agent与多步骤任务\demo\agent_workflow_demo.py' run --goal '帮我创建工单跟进接口 500 trace_id 问题'
```

这次 Agent 会执行两步：

1. 调用 `search_knowledge_base` 检索资料。
2. 调用 `create_followup_ticket` 创建跟进工单。

最终输出里会包含 `TICKET-` 开头的模拟工单号。

## 查看工具 Schema

```powershell
python '.\大模型技术学习教程\09-Agent与多步骤任务\demo\agent_workflow_demo.py' schema
```

这能帮助你理解工具是如何暴露给模型的。真实项目里，模型看到的是工具名称、描述和参数 Schema；应用侧负责真正执行工具。

## 生成 Responses API 请求体示例

```powershell
python '.\大模型技术学习教程\09-Agent与多步骤任务\demo\agent_workflow_demo.py' payload --goal '排查 Android 崩溃'
```

输出会包含：

```json
{
  "model": "gpt-5.5",
  "input": "排查 Android 崩溃",
  "tools": [
    {
      "type": "function",
      "name": "search_knowledge_base"
    }
  ],
  "tool_choice": "auto"
}
```

为了便于阅读，示例里省略了完整 `parameters`。真实输出会把默认工具的完整 Schema 填入 `tools`。真实调用时，模型可能返回工具调用；你的应用执行工具后，再把工具结果交回模型，直到得到最终回答。

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\09-Agent与多步骤任务\demo\tests'
```

测试覆盖：

1. 工具 Schema 结构。
2. 未知工具错误。
3. 搜索后生成答案。
4. 搜索后创建工单。
5. 最大步数保护。
6. Responses API payload。

## 接入真实模型时怎么替换

真实项目可以逐步替换 Demo 的这些部分：

1. `ScriptedPlanner`：换成大模型调用。
2. `search_knowledge_base`：换成 RAG 检索或 File Search。
3. `create_followup_ticket`：换成真实工单系统 API。
4. `trace`：写入日志系统或观测平台。
5. `max_steps`：保留，防止循环执行。
6. `execute_tool_call`：加入权限、审批和参数校验。

这就是从“离线 Agent 骨架”过渡到“生产 Agent 服务”的核心路径。
