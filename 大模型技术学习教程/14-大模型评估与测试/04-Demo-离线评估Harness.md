# Demo：离线评估 Harness

本阶段 Demo 用 Python 标准库实现一个最小评估 Harness。它不调用真实模型，而是用固定输出模拟模型结果，演示评估集、关键词打分、汇总和回归检测。

## Demo 文件

```text
14-大模型评估与测试/
  demo/
    eval_harness_demo.py
    tests/
      test_eval_harness_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\14-大模型评估与测试\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\14-大模型评估与测试\demo\eval_harness_demo.py'
```

输出会包含：

1. 评估用例。
2. 每条用例的分数。
3. 是否通过阈值。
4. 汇总通过率和平均分。

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `build_eval_case` | 构造评估用例 |
| `keyword_coverage` | 计算关键词覆盖率 |
| `run_eval_suite` | 运行一组评估 |
| `summarize_results` | 汇总通过率和平均分 |
| `detect_regression` | 和基线对比，判断是否退化 |

## 迁移到真实项目

真实项目里可以把 Demo 替换成：

1. 从数据库或 JSONL 加载评估集。
2. 调用真实后端网关，而不是直接调模型。
3. 保存每次运行的版本、Prompt、模型、检索结果和输出。
4. 在 CI 里设置门禁。
5. 把失败样例回流到 Prompt、RAG 或训练数据优化。
