# Demo：综合项目蓝图生成器

本阶段 Demo 用 Python 标准库生成综合项目蓝图、里程碑、验收清单和阶段映射。

它不是代码生成器，也不会替你创建 Android 或后端工程。它的作用是把综合项目拆成可讨论、可排期、可验收的结构，帮助你从“想做一个 AI 助手”落到“先做哪些模块、每个阶段怎么验收”。

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

## 输出如何对应本阶段文档

| Demo 输出 | 对应文档 | 用法 |
| --- | --- | --- |
| `blueprint.components` | `01-项目范围与总体架构.md` | 检查模块职责是否完整 |
| `milestones` | `02-里程碑拆解与实现顺序.md` | 作为排期和迭代计划的初稿 |
| `acceptance` | `03-验收标准上线清单与扩展方向.md` | 作为上线门禁的起点 |
| `feature_map` | 前 20 个阶段 | 发现某个能力应该回看哪一阶段 |

## 怎么使用

你可以把 Demo 输出当作真实项目的初始实施清单。后续如果要继续，我可以基于这个蓝图生成：

1. 后端接口设计。
2. Android 页面和 ViewModel 设计。
3. RAG 数据库表结构。
4. 评估集模板。
5. 发布和运维清单。

真实项目里，建议把 Demo 输出扩展成项目文档：

```text
docs/
  project-blueprint.md
  api-contracts.md
  android-state-machine.md
  rag-data-model.md
  eval-cases.jsonl
  release-checklist.md
```

这样每次迭代都能看见范围、接口、数据、评估和发布门禁，而不是只停留在口头讨论。
