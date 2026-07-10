# Demo：本地模型网关决策

本阶段 Demo 用 Python 标准库模拟本地模型部署中的容量估算、路由决策、Ollama 风格请求和部署计划。

## Demo 文件

```text
17-本地模型与私有化部署/
  demo/
    local_model_gateway_demo.py
    tests/
      test_local_model_gateway_demo.py
```

## 运行测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\17-本地模型与私有化部署\demo\tests'
```

## 运行 Demo

```powershell
python '.\大模型技术学习教程\17-本地模型与私有化部署\demo\local_model_gateway_demo.py'
python '.\大模型技术学习教程\17-本地模型与私有化部署\demo\local_model_gateway_demo.py' --params 7 --bits 4 --memory 8
```

## 核心函数

| 函数 | 作用 |
| --- | --- |
| `estimate_memory_gb` | 粗略估算权重内存 |
| `route_inference` | 根据隐私和容量选择本地或云端 |
| `build_ollama_generate_request` | 构造本地模型请求草图 |
| `summarize_deployment_plan` | 输出私有化部署组件和检查项 |

## 迁移到真实项目

真实项目中可以把 Demo 扩展成：

1. 读取当前机器 GPU/内存容量。
2. 调用本地模型健康检查接口。
3. 根据租户策略做模型路由。
4. 对本地和云端模型做统一接口封装。
5. 把延迟、错误率和队列长度接入监控。
