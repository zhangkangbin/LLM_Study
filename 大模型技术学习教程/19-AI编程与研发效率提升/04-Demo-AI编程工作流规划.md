# Demo：AI 编程工作流规划

本阶段 Demo 用 Python 标准库模拟 AI 编程中的任务分类、Review 清单、diff 风险摘要和协作步骤。

## Demo 文件

```text
19-AI编程与研发效率提升/
  demo/
    ai_coding_workflow_demo.py
    tests/
      test_ai_coding_workflow_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\19-AI编程与研发效率提升\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\19-AI编程与研发效率提升\demo\ai_coding_workflow_demo.py'
python '.\大模型技术学习教程\19-AI编程与研发效率提升\demo\ai_coding_workflow_demo.py' --task '修复登录闪退 bug'
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `classify_coding_task` | 判断任务类型和第一步 |
| `build_code_review_checklist` | 生成 Review 检查清单 |
| `summarize_diff_risk` | 根据文件和改动量估计风险 |
| `plan_ai_pairing_workflow` | 生成 AI 结对编程步骤 |

## 迁移到真实项目

可以继续接入：

1. Git diff 解析。
2. 单测命令建议。
3. 代码所有者规则。
4. PR 模板。
5. 自动生成 Review 评论。
