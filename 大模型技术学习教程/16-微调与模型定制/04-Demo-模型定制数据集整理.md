# Demo：模型定制数据集整理

本阶段 Demo 用 Python 标准库模拟模型定制前的数据检查、训练/验证拆分、JSONL 转换和策略选择。

## Demo 文件

```text
16-微调与模型定制/
  demo/
    customization_dataset_demo.py
    tests/
      test_customization_dataset_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\16-微调与模型定制\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\16-微调与模型定制\demo\customization_dataset_demo.py'
python '.\大模型技术学习教程\16-微调与模型定制\demo\customization_dataset_demo.py' --strategy style
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `validate_training_examples` | 检查 input/output 是否完整 |
| `split_examples` | 拆分训练集和验证集 |
| `to_jsonl_lines` | 生成一行一个样例的 JSONL |
| `choose_customization_strategy` | 判断优先用 Prompt、RAG 还是模型定制 |

## 迁移到真实项目

真实项目可以继续补：

1. 敏感信息扫描。
2. 重复样例检测。
3. 标签分布统计。
4. 人工审核状态。
5. 数据集版本号。
6. 与评估集联动。
