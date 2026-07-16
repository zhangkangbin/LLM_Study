# 阶段十六：微调与模型定制

本阶段目标是理解什么时候需要模型定制，什么时候不需要。对应用开发者来说，绝大多数问题应该先用 Prompt、结构化输出、RAG、工具和评估解决。只有当你有稳定任务、高质量样例、明确评估标准，并且普通方法已经到达瓶颈时，才考虑微调、适配器或其他模型定制方式。

注意：OpenAI 官方文档显示，其 fine-tuning 平台正在收缩，新用户访问和训练能力可能受限。学习本阶段时，请把重点放在“模型定制的方法论、数据准备和评估闭环”，具体平台能力以当前供应商文档为准。

## 本阶段你会学到什么

1. Prompt、RAG、微调、适配器分别解决什么问题。
2. 如何判断一个问题是否值得模型定制。
3. 如何准备训练样例、验证集和评估集。
4. 如何避免把错误业务逻辑训练进模型。
5. 如何管理定制模型的版本、回滚和成本。
6. 如何运行一个离线数据集整理 Demo。
7. 如何设计意图体系，并完成训练、校准、导出和评估闭环。
8. 如何校验 Chat JSONL，在工作站完成 LoRA/QLoRA、固定基线与评估、合并适配器，并转换和量化为 GGUF。

## 章节目录

1. [什么时候不该微调](./01-什么时候不该微调.md)
2. [训练数据、验证集与质量控制](./02-训练数据验证集与质量控制.md)
3. [模型定制上线流程](./03-模型定制上线流程.md)
4. [Demo：模型定制数据集整理](./04-Demo-模型定制数据集整理.md)
5. [意图识别与分类训练实战](./05-意图识别与分类训练实战.md)
6. [面向端侧的生成模型训练与量化](./06-面向端侧的生成模型训练与量化.md)

## 选择矩阵

| 问题 | 优先方案 |
| --- | --- |
| 回答需要最新业务知识 | RAG |
| 输出格式不稳定 | 结构化输出 + 示例 |
| 语气风格不统一 | Prompt / few-shot / 微调 |
| 工具调用不稳定 | 工具 Schema + Agent 评估 |
| 固定分类任务 | 小模型 / 微调 / 规则 |
| 成本太高 | 小模型、压缩上下文、必要时微调 |

## 官方资料

- [Model optimization](https://developers.openai.com/api/docs/guides/model-optimization)
- [Supervised fine-tuning](https://developers.openai.com/api/docs/guides/supervised-fine-tuning)
- [Fine-tuning best practices](https://developers.openai.com/api/docs/guides/fine-tuning-best-practices)
- [Vision fine-tuning](https://developers.openai.com/api/docs/guides/vision-fine-tuning)
- [Direct preference optimization](https://developers.openai.com/api/docs/guides/direct-preference-optimization)
