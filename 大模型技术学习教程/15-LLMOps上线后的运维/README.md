# 阶段十五：LLMOps：上线后的运维

本阶段目标是学习大模型应用上线后的监控、告警、成本、延迟、质量、灰度和回滚。LLMOps 不只是“模型运维”，而是把模型、Prompt、RAG、Agent、工具、Android 客户端和后端网关一起纳入可观测、可治理、可回滚的生产系统。

## 本阶段你会学到什么

1. 大模型应用上线后需要监控哪些指标。
2. 如何同时看质量、成本、延迟、错误率和用户反馈。
3. 如何设计 Prompt/RAG/模型版本的灰度发布。
4. 如何做限流、预算、熔断、降级和回滚。
5. 如何把评估结果和线上指标组合成发布门禁。
6. 如何运行一个离线 LLMOps 监控 Demo。

## 章节目录

1. [可观测性、日志与 Trace](./01-可观测性日志与Trace.md)
2. [成本、延迟、限流与降级](./02-成本延迟限流与降级.md)
3. [灰度发布、告警与事故复盘](./03-灰度发布告警与事故复盘.md)
4. [Demo：离线 LLMOps 监控](./04-Demo-离线LLMOps监控.md)

## 核心流程图

```mermaid
flowchart TD
    Request["用户请求"] --> Gateway["LLM Gateway"]
    Gateway --> Model["模型 / RAG / Agent"]
    Gateway --> Metrics["指标"]
    Gateway --> Logs["脱敏日志"]
    Gateway --> Trace["Trace"]
    Metrics --> Alert["告警"]
    Metrics --> Budget["预算控制"]
    Trace --> Debug["问题定位"]
    Alert --> Rollback["降级 / 回滚"]
```

## 核心指标

| 维度 | 指标 |
| --- | --- |
| 质量 | 评估通过率、人工满意度、拒答准确率 |
| 成本 | token、请求成本、单用户成本、单任务成本 |
| 延迟 | 首 token 延迟、总耗时、P95/P99 |
| 稳定性 | 错误率、超时率、重试率、供应商失败率 |
| 安全 | 拦截率、越权工具调用、敏感信息泄露 |
| 业务 | 转化率、任务完成率、人工接管率 |

## 官方资料

- [Production best practices](https://developers.openai.com/api/docs/guides/production-best-practices)
- [API deployment checklist](https://developers.openai.com/api/docs/guides/deployment-checklist)
- [Latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization)
- [Cost optimization](https://developers.openai.com/api/docs/guides/cost-optimization)
- [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
