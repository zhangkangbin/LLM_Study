# Demo：离线 RAG 问答流水线

本阶段 Demo 用纯 Python 标准库模拟 RAG 问答链路。它不会调用真实大模型，而是用规则生成答案，重点是让你看清楚检索、上下文、Prompt、引用和兜底是如何组合的。

## Demo 文件

```text
08-RAG检索增强生成/
  demo/
    rag_pipeline_demo.py
    sample_chunks.jsonl
    tests/
      test_rag_pipeline_demo.py
```

`sample_chunks.jsonl` 可以理解为第七阶段知识库构建后的输出，每一行都是一个可检索 chunk。

## 运行问答

在项目根目录运行：

```powershell
python '.\大模型技术学习教程\08-RAG检索增强生成\demo\rag_pipeline_demo.py' answer --question '空指针崩溃怎么排查'
```

输出会包含：

1. `status`：是否回答成功。
2. `answer`：模拟生成的答案。
3. `citations`：引用来源。
4. `retrieved`：检索命中的 chunk。
5. `prompt`：实际组装出的 RAG Prompt。

## 查看 Prompt

```powershell
python '.\大模型技术学习教程\08-RAG检索增强生成\demo\rag_pipeline_demo.py' prompt --question '接口 500 错误 trace_id 怎么定位'
```

你可以重点看 Prompt 里的三块：

1. 规则：只能基于上下文回答。
2. 用户问题。
3. 检索上下文。

这就是后端最终会发给大模型的核心内容。

## 按标签过滤

```powershell
python '.\大模型技术学习教程\08-RAG检索增强生成\demo\rag_pipeline_demo.py' answer --question '接口 500 错误 trace_id 怎么定位' --tag backend
```

这模拟真实项目中的 metadata filter。比如用户只属于后端团队，就只允许检索后端知识库；用户是普通 App 用户，就不应该检索内部故障复盘。

## 没有答案的情况

```powershell
python '.\大模型技术学习教程\08-RAG检索增强生成\demo\rag_pipeline_demo.py' answer --question '今天上海天气怎么样'
```

Demo 会返回 `no_answer`，因为知识库里没有天气资料。真实系统里也应该这样处理，而不是让模型自由发挥。

## 生成 File Search 请求体示例

```powershell
python '.\大模型技术学习教程\08-RAG检索增强生成\demo\rag_pipeline_demo.py' payload --question '怎么排查退款问题' --vector-store-id 'vs_123'
```

输出示例：

```json
{
  "model": "gpt-5.5",
  "input": "怎么排查退款问题",
  "tools": [
    {
      "type": "file_search",
      "vector_store_ids": ["vs_123"],
      "max_num_results": 3
    }
  ],
  "include": ["file_search_call.results"]
}
```

这只是请求体结构示例。真实调用时还需要 API Key、SDK 或 HTTP 客户端，以及你的 Vector Store ID。

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\08-RAG检索增强生成\demo\tests'
```

测试覆盖：

1. JSONL chunk 加载。
2. 相关 chunk 排序。
3. metadata 标签过滤。
4. RAG Prompt 组装。
5. 带引用回答。
6. 无答案兜底。
7. File Search 请求体生成。

## 下一步如何接真实模型

真实项目可以把 Demo 的模块替换成：

1. `retrieve_context`：换成向量数据库、OpenAI File Search 或混合检索。
2. `build_rag_prompt`：继续保留，但按业务调整规则。
3. `synthesize_answer`：换成真实大模型调用。
4. `citations`：保留结构化引用，供前端展示。
5. `status`：保留状态码，供 Android/前端做 UI 分支。

这样你能从一个离线 Demo 平滑过渡到生产级 RAG API。
