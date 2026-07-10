# Demo：离线 LLMOps 监控

本阶段 Demo 用 Python 标准库模拟大模型调用指标聚合、告警判断和发布门禁。

## Demo 文件

```text
15-LLMOps上线后的运维/
  demo/
    llmops_monitor_demo.py
    tests/
      test_llmops_monitor_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\15-LLMOps上线后的运维\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\15-LLMOps上线后的运维\demo\llmops_monitor_demo.py'
```

也可以降低预算阈值观察告警：

```powershell
python '.\大模型技术学习教程\15-LLMOps上线后的运维\demo\llmops_monitor_demo.py' --max-cost 0.05
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `record_call` | 记录一次模型调用 |
| `aggregate_metrics` | 汇总 token、成本、延迟、错误率 |
| `check_alerts` | 根据阈值产生告警 |
| `build_release_gate` | 组合评估和运维指标决定是否发布 |

## 迁移到真实项目

真实项目中，这些数据可以来自：

1. 后端网关日志。
2. APM 和 Prometheus 指标。
3. 模型供应商 usage 字段。
4. Android 客户端埋点。
5. 用户反馈和人工标注。

先把调用链路看见，再谈优化。看不见的系统没有真正上线。
