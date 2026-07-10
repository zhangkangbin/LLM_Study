# 阶段十八：大模型应用安全

本阶段目标是理解大模型应用的安全边界。大模型安全不是只在 Prompt 里写“不要泄露秘密”，而是要在输入、检索、工具、输出、权限、日志、评估和人工流程上建立多层防线。

## 本阶段你会学到什么

1. Prompt 注入、敏感信息泄露、输出处理不当和过度代理的风险。
2. 为什么 RAG、微调和系统提示词不能完全解决 Prompt 注入。
3. 如何做工具白名单、权限校验、人工确认和输出校验。
4. 如何在 Android、后端、知识库和 Agent 中落地安全边界。
5. 如何设计红队用例和安全回归测试。
6. 如何运行一个离线安全护栏 Demo。

## 章节目录

1. [Prompt 注入与数据泄露](./01-Prompt注入与数据泄露.md)
2. [工具权限、输出校验与人工确认](./02-工具权限输出校验与人工确认.md)
3. [红队测试、安全评估与合规治理](./03-红队测试安全评估与合规治理.md)
4. [Demo：离线安全护栏](./04-Demo-离线安全护栏.md)

## 安全分层

```mermaid
flowchart TD
    Input["输入检查"] --> Retrieval["检索权限过滤"]
    Retrieval --> Prompt["Prompt 隔离"]
    Prompt --> Tool["工具权限"]
    Tool --> Output["输出校验"]
    Output --> Audit["日志审计"]
    Audit --> RedTeam["红队回归"]
```

## 官方资料

- [OWASP LLM01 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OpenAI safety best practices](https://developers.openai.com/api/docs/guides/safety-best-practices)
- [OpenAI red teaming](https://developers.openai.com/api/docs/guides/red-teaming)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
