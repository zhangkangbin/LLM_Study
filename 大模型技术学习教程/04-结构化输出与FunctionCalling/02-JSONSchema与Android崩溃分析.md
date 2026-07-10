# 02. JSON Schema 与 Android 崩溃分析

## 1. 什么是 JSON Schema

JSON Schema 是描述 JSON 数据结构的标准方式。它可以定义：

- 对象有哪些字段
- 字段类型是什么
- 哪些字段必填
- 字段是否允许额外属性
- 枚举值有哪些
- 数组元素是什么类型

对大模型应用来说，JSON Schema 就像输出合同。

## 2. Android 崩溃分析结果设计

一个实用的崩溃分析结果可以包含：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `issue_type` | string | 异常或问题类型 |
| `severity` | enum | 严重程度 |
| `summary` | string | 一句话摘要 |
| `evidence` | string[] | 来自日志的关键证据 |
| `likely_causes` | string[] | 可能原因 |
| `fix_suggestions` | string[] | 修复建议 |
| `needs_more_info` | string[] | 还需要补充的信息 |

## 3. Schema 示例

```json
{
  "type": "object",
  "properties": {
    "issue_type": {"type": "string"},
    "severity": {
      "type": "string",
      "enum": ["low", "medium", "high", "unknown"]
    },
    "summary": {"type": "string"},
    "evidence": {
      "type": "array",
      "items": {"type": "string"}
    },
    "likely_causes": {
      "type": "array",
      "items": {"type": "string"}
    },
    "fix_suggestions": {
      "type": "array",
      "items": {"type": "string"}
    },
    "needs_more_info": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "required": [
    "issue_type",
    "severity",
    "summary",
    "evidence",
    "likely_causes",
    "fix_suggestions",
    "needs_more_info"
  ],
  "additionalProperties": false
}
```

## 4. 为什么要 `additionalProperties: false`

如果允许额外字段，模型可能会增加：

- `confidence`
- `root_cause`
- `solution`
- `code_example`

这些字段看起来有用，但会让前端和后端消费不稳定。

阶段四建议先严格控制字段。后续确实需要新字段时，升级 schema 版本。

## 5. 为什么 severity 要用 enum

如果不限制，模型可能输出：

```text
严重
较严重
High
critical
P0
```

这对程序不友好。用 enum 可以统一成：

```text
low / medium / high / unknown
```

Android 端就能稳定做颜色映射：

```text
low -> 灰色
medium -> 黄色
high -> 红色
unknown -> 蓝色
```

## 6. 请求体示例

Responses API 中可以这样使用：

```json
{
  "model": "gpt-5.5",
  "input": [
    {
      "role": "system",
      "content": "你是 Android 稳定性分析助手。只基于输入日志分析。"
    },
    {
      "role": "user",
      "content": "请分析下面的崩溃日志..."
    }
  ],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "android_crash_analysis",
      "strict": true,
      "schema": {}
    }
  }
}
```

## 7. 仍然需要后端校验

即使使用 Structured Outputs，后端仍然建议做二次校验：

- 字段是否存在
- enum 是否在允许范围内
- 数组是否真的是数组
- 字符串长度是否过长
- 是否包含敏感信息

结构化输出提高可靠性，但后端仍然是最后的安全边界。

## 8. Schema 版本管理

建议给 schema 命名和版本：

```text
android_crash_analysis_v1
android_crash_analysis_v2
```

如果字段有破坏性变化，就升级版本。

日志里记录：

```json
{
  "schema_version": "android_crash_analysis_v1",
  "model": "gpt-5.5",
  "prompt_version": "android_crash_prompt_v1"
}
```

## 9. 本章小结

JSON Schema 的关键不是复杂，而是稳定：

```text
字段固定
类型固定
枚举固定
额外字段关闭
版本明确
后端二次校验
```

下一章会进入 Function Calling，让模型不只是返回结果，还能请求你的系统查询数据或执行动作。
