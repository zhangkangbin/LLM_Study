from __future__ import annotations

import argparse
import json
from typing import Sequence


def build_capstone_blueprint(project_name: str) -> dict[str, object]:
    return {
        "project_name": project_name,
        "components": {
            "android_app": "聊天、语音、图片、引用展示和任务状态",
            "backend_gateway": "鉴权、限流、模型路由、日志和成本控制",
            "rag_pipeline": "文档清洗、切分、向量索引、检索和引用",
            "agent_tools": "受控工具调用与人工确认",
            "eval_harness": "质量、回归、安全和成本评估",
            "llmops": "监控、告警、灰度、回滚和审计",
        },
    }


def build_milestone_plan() -> list[dict[str, object]]:
    return [
        {"name": "MVP", "goals": ["文本问答", "后端网关", "基础日志"]},
        {"name": "知识库增强", "goals": ["文档导入", "RAG 引用", "评估集"]},
        {"name": "多模态体验", "goals": ["语音", "图片理解", "Android 状态机"]},
        {"name": "上线准备", "goals": ["安全红队", "监控告警", "灰度回滚"]},
    ]


def build_acceptance_checklist() -> list[str]:
    return [
        "核心问答链路可用",
        "RAG 引用可追溯",
        "质量评估通过",
        "监控告警可用",
        "安全红队用例通过",
        "Android 弱网与取消流程可用",
    ]


def map_feature_to_stage(feature: str) -> dict[str, object]:
    mapping = [
        (14, ["评估", "回归", "测试"]),
        (15, ["监控", "告警", "上线", "运维"]),
        (18, ["安全", "红队", "注入"]),
        (13, ["语音", "图片", "多模态"]),
        (8, ["rag", "知识库", "引用"]),
    ]
    lowered = feature.lower()
    for stage, keywords in mapping:
        if any(keyword in lowered for keyword in keywords):
            return {"stage": stage, "feature": feature}
    return {"stage": 21, "feature": feature}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="综合实战项目蓝图 Demo")
    parser.add_argument("--name", default="Android 知识库助手")
    args = parser.parse_args(argv)

    print(
        json.dumps(
            {
                "blueprint": build_capstone_blueprint(args.name),
                "milestones": build_milestone_plan(),
                "acceptance": build_acceptance_checklist(),
                "feature_map": map_feature_to_stage("模型评估与回归测试"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
