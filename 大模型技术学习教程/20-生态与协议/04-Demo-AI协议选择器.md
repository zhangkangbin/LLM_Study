# Demo：AI 协议选择器

本阶段 Demo 用 Python 标准库模拟 MCP Tool 描述、OpenAPI 函数 Schema、集成方式选择和协议 Manifest 校验。

## Demo 文件

```text
20-生态与协议/
  demo/
    ai_protocols_demo.py
    tests/
      test_ai_protocols_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\20-生态与协议\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\20-生态与协议\demo\ai_protocols_demo.py'
python '.\大模型技术学习教程\20-生态与协议\demo\ai_protocols_demo.py' --surface openapi
python '.\大模型技术学习教程\20-生态与协议\demo\ai_protocols_demo.py' --surface app
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `build_mcp_tool_descriptor` | 生成 MCP 工具描述草图 |
| `build_openapi_function_schema` | 生成函数参数 Schema |
| `choose_integration_surface` | 选择 MCP、OpenAPI、App 或 SDK |
| `validate_protocol_manifest` | 校验 Manifest 必填字段 |

## 迁移到真实项目

可以继续扩展：

1. 从 OpenAPI 自动生成工具 Schema。
2. 为 MCP Server 加鉴权和审计。
3. 为不同 AI 客户端生成不同能力清单。
4. 把协议校验接入 CI。
