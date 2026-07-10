---
id: backend-api-errors
title: 后端 API 错误排查
source_uri: app://knowledge/backend/api-errors
tags: backend, api, observability
version: v1
owner: server-team
---

# 后端 API 错误排查

接口错误知识库应记录 HTTP 状态码、业务错误码、trace_id、请求参数摘要和下游依赖。
当移动端收到 401、403、409、429、500 等响应时，后端应能通过 trace_id 定位网关、鉴权、业务服务和数据库日志。
面向大模型问答时，文档要避免只写“接口失败”，应该说明错误语义、排查路径、用户可见表现和推荐修复动作。
权限相关文档还要标注数据敏感级别，避免被无权限用户检索到。
