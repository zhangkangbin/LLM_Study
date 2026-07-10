from __future__ import annotations

import argparse
import json
from typing import Sequence


def classify_coding_task(description: str) -> dict[str, object]:
    lowered = description.lower()
    if any(keyword in lowered for keyword in ["bug", "崩溃", "闪退", "修复", "报错"]):
        return {"type": "bugfix", "first_step": "reproduce failing behavior"}
    if any(keyword in lowered for keyword in ["重构", "refactor"]):
        return {"type": "refactor", "first_step": "map current callers and tests"}
    if any(keyword in lowered for keyword in ["review", "代码审查", "检查"]):
        return {"type": "review", "first_step": "inspect diff and risk areas"}
    return {"type": "feature", "first_step": "clarify acceptance criteria"}


def build_code_review_checklist(areas: Sequence[str]) -> list[str]:
    checklist = ["correctness", "tests", "maintainability", "rollback"]
    if any(area in {"api", "auth", "payment", "data"} for area in areas):
        checklist.append("security")
    if "android" in areas:
        checklist.append("lifecycle")
    return checklist


def summarize_diff_risk(changes: Sequence[dict[str, object]]) -> dict[str, object]:
    risk_signals: list[str] = []
    for change in changes:
        path = str(change["path"]).lower()
        if "auth" in path and "auth" not in risk_signals:
            risk_signals.append("auth")
        if "payment" in path and "payment" not in risk_signals:
            risk_signals.append("payment")
        if int(change.get("added", 0)) + int(change.get("removed", 0)) > 500 and "large_diff" not in risk_signals:
            risk_signals.append("large_diff")
    return {
        "files_changed": len(changes),
        "lines_changed": sum(int(item.get("added", 0)) + int(item.get("removed", 0)) for item in changes),
        "risk_signals": risk_signals,
    }


def plan_ai_pairing_workflow(task: str) -> list[dict[str, str]]:
    return [
        {"phase": "understand", "action": f"读需求与相关代码：{task}"},
        {"phase": "plan", "action": "拆成小步骤，确认影响面和测试点"},
        {"phase": "implement", "action": "小步修改，保持可回滚"},
        {"phase": "review", "action": "让 AI 做问题导向的代码审查"},
        {"phase": "verify", "action": "运行测试、构建或可复现验收命令"},
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 编程协作流程 Demo")
    parser.add_argument("--task", default="实现 RAG 引用展示")
    args = parser.parse_args(argv)

    print(
        json.dumps(
            {
                "classification": classify_coding_task(args.task),
                "workflow": plan_ai_pairing_workflow(args.task),
                "review_checklist": build_code_review_checklist(["api", "auth"]),
                "diff_risk": summarize_diff_risk(
                    [
                        {"path": "app/AuthService.kt", "added": 20, "removed": 5},
                        {"path": "app/RagScreen.kt", "added": 80, "removed": 10},
                    ]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
