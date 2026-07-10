# Demo：综合项目蓝图生成器

本阶段 Demo 用 Python 标准库生成综合项目蓝图、里程碑、验收清单和阶段映射。

## Demo 文件

```text
21-综合实战项目/
  demo/
    capstone_blueprint_demo.py
    tests/
      test_capstone_blueprint_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\21-综合实战项目\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\21-综合实战项目\demo\capstone_blueprint_demo.py'
python '.\大模型技术学习教程\21-综合实战项目\demo\capstone_blueprint_demo.py' --name '企业内部知识库助手'
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `build_capstone_blueprint` | 生成项目组件蓝图 |
| `build_milestone_plan` | 生成 4 个里程碑 |
| `build_acceptance_checklist` | 生成验收清单 |
| `map_feature_to_stage` | 把功能映射回学习阶段 |

## 怎么使用

你可以把 Demo 输出当作真实项目的初始实施清单。后续如果要继续，我可以基于这个蓝图生成：

1. 后端接口设计。
2. Android 页面和 ViewModel 设计。
3. RAG 数据库表结构。
4. 评估集模板。
5. 发布和运维清单。
