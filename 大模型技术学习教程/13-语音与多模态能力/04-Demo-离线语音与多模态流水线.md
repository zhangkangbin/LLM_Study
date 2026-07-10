# Demo：离线语音与多模态流水线

本阶段 Demo 用 Python 标准库模拟语音与多模态应用的核心工程逻辑。它不调用真实模型 API，也不需要 API Key，目的是让你先把路由、payload、权限和状态边界想清楚。

## Demo 文件

```text
13-语音与多模态能力/
  demo/
    multimodal_pipeline_demo.py
    tests/
      test_multimodal_pipeline_demo.py
```

## 它演示了什么

1. 把音频字节切成稳定分片。
2. 合并 partial/final 转写事件。
3. 根据用户输入判断应该走图片理解、实时语音、转写、TTS 还是多模态 RAG。
4. 生成文本 + 图片的 Responses payload。
5. 生成语音转文字请求草图。
6. 生成文字转语音请求草图。
7. 生成 Realtime 会话配置草图。
8. 生成 Android 权限与上传边界建议。

Demo 里的模型名都是占位值。真实项目中应该从后端配置、灰度策略或供应商文档中读取当前可用模型。

## 运行测试

在项目根目录执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s '.\大模型技术学习教程\13-语音与多模态能力\demo\tests'
```

成功后会输出：

```text
Ran 9 tests

OK
```

## 运行 Demo

任务路由：

```powershell
python '.\大模型技术学习教程\13-语音与多模态能力\demo\multimodal_pipeline_demo.py' route --text '实时语音问答' --low-latency
```

生成图文 payload：

```powershell
python '.\大模型技术学习教程\13-语音与多模态能力\demo\multimodal_pipeline_demo.py' payload --text '这张图有什么问题' --image-url 'app://image/screenshot.png'
```

生成 Realtime 会话配置：

```powershell
python '.\大模型技术学习教程\13-语音与多模态能力\demo\multimodal_pipeline_demo.py' realtime --voice marin
```

模拟音频分片：

```powershell
python '.\大模型技术学习教程\13-语音与多模态能力\demo\multimodal_pipeline_demo.py' audio-chunks --text 'fake audio bytes' --chunk-size 4
```

合并转写事件：

```powershell
python '.\大模型技术学习教程\13-语音与多模态能力\demo\multimodal_pipeline_demo.py' transcript
```

## 关键函数

| 函数 | 作用 |
| --- | --- |
| `chunk_audio_bytes` | 把音频字节切成固定大小分片 |
| `merge_transcript_events` | 合并 partial/final 转写事件 |
| `route_multimodal_task` | 根据场景选择推荐能力 |
| `build_multimodal_responses_payload` | 构造文本 + 图片输入 |
| `build_speech_to_text_request` | 构造转写请求草图 |
| `build_text_to_speech_request` | 构造 TTS 请求草图 |
| `build_realtime_session_config` | 构造实时会话配置草图 |
| `build_android_permission_plan` | 给出 Android 权限和上传边界 |

## 迁移到真实项目

真实项目可以按这个顺序替换 Demo：

1. 把 `route_multimodal_task` 放到后端网关，统一决定走哪个模型能力。
2. 把 `build_*_request` 替换成真实供应商 SDK 或 HTTP 调用。
3. Android 端只保留权限、采集、压缩、上传、播放和状态管理。
4. Realtime 场景由后端创建短时会话，Android 使用短时凭证连接。
5. 把测试保留下来，增加“超大文件、取消、重试、权限拒绝、会话过期”等用例。
