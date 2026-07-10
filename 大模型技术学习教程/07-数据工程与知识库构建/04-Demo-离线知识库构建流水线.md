# Demo：离线知识库构建流水线

本阶段 Demo 用纯 Python 标准库实现一个小型知识库构建流水线。它不会调用真实大模型，也不会生成 Embedding，重点是演示 RAG 前置的数据工程流程。

## Demo 文件

```text
07-数据工程与知识库构建/
  demo/
    knowledge_base_pipeline.py
    previous_manifest.json
    source_docs/
      android_crash_guide.md
      backend_api_errors.md
      product_faq.json
    tests/
      test_knowledge_base_pipeline.py
```

## 它做了什么

1. 读取 Markdown、TXT、JSON 数据源。
2. 解析 Markdown front matter。
3. 清理空白、换行、零宽字符。
4. 按字符长度和 overlap 切分 chunk。
5. 给每个 chunk 写入 `doc_id`、`chunk_id`、`source_uri`、`tags`、`version` 等元数据。
6. 生成 `manifest.json`。
7. 和上一版 manifest 对比，生成 `sync_plan.json`。
8. 输出可继续向量化的 `chunks.jsonl`。

## 查看数据源

在项目根目录运行：

```powershell
python '.\大模型技术学习教程\07-数据工程与知识库构建\demo\knowledge_base_pipeline.py' inspect
```

你会看到每份文档的 `doc_id`、标题、来源、字符数和元数据。

## 构建知识库

```powershell
python '.\大模型技术学习教程\07-数据工程与知识库构建\demo\knowledge_base_pipeline.py' build --previous-manifest '.\大模型技术学习教程\07-数据工程与知识库构建\demo\previous_manifest.json'
```

默认会把结果写到：

```text
07-数据工程与知识库构建/demo/build/
  chunks.jsonl
  manifest.json
  sync_plan.json
```

`chunks.jsonl` 是后续生成 Embedding 的输入；`manifest.json` 是当前知识库快照；`sync_plan.json` 告诉你哪些文档需要新增、更新、删除或跳过。

## 同步计划示例

```json
{
  "created": [
    "account-delete-faq",
    "backend-api-errors",
    "product-refund-faq"
  ],
  "updated": [
    "android-crash-guide"
  ],
  "deleted": [
    "legacy-release-note"
  ],
  "unchanged": []
}
```

这个计划可以被后端任务消费：

1. `created`：生成 Embedding 并写入索引。
2. `updated`：删除旧 chunk，再写入新 chunk。
3. `deleted`：从索引中删除。
4. `unchanged`：跳过，节省成本和时间。

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\07-数据工程与知识库构建\demo\tests'
```

测试覆盖了：

1. 文本清洗。
2. Markdown front matter 解析。
3. chunk 元数据与稳定 ID。
4. manifest 生成。
5. 增量同步 diff。
6. 完整 pipeline 输出文件。

## 接入真实向量库的下一步

真实项目可以把 `chunks.jsonl` 继续送到下面任意一种后续流程：

1. 调 OpenAI Embeddings API 生成向量，再写入自建向量数据库。
2. 把规范化后的文件上传到 OpenAI Vector Store，使用 File Search。
3. 写入企业搜索引擎，做关键词 + 向量混合检索。
4. 加一层 rerank，把 Top-K 结果重新排序。
5. 建立评测集，固定一批问题检查每次知识库更新后的命中率。

本 Demo 的价值在于：即使后面换模型、换向量数据库、换托管检索服务，前面的数据规范、清洗、manifest、增量同步思路仍然能复用。
