from __future__ import annotations

import argparse
import json
from typing import Sequence


def record_call(
    route: str,
    tokens: int,
    cost_usd: float,
    latency_ms: int,
    success: bool,
) -> dict[str, object]:
    return {
        "route": route,
        "tokens": tokens,
        "cost_usd": round(cost_usd, 6),
        "latency_ms": latency_ms,
        "success": success,
    }


def aggregate_metrics(calls: Sequence[dict[str, object]]) -> dict[str, float]:
    if not calls:
        return {"tokens": 0, "cost_usd": 0.0, "avg_latency_ms": 0.0, "error_rate": 0.0}

    total_tokens = sum(int(call["tokens"]) for call in calls)
    total_cost = sum(float(call["cost_usd"]) for call in calls)
    avg_latency = sum(int(call["latency_ms"]) for call in calls) / len(calls)
    errors = sum(1 for call in calls if not bool(call["success"]))
    return {
        "tokens": total_tokens,
        "cost_usd": round(total_cost, 6),
        "avg_latency_ms": round(avg_latency, 2),
        "error_rate": round(errors / len(calls), 4),
    }


def check_alerts(metrics: dict[str, float], thresholds: dict[str, float]) -> list[str]:
    alerts: list[str] = []
    if metrics.get("cost_usd", 0.0) > thresholds.get("max_cost_usd", float("inf")):
        alerts.append("budget")
    if metrics.get("avg_latency_ms", 0.0) > thresholds.get("max_latency_ms", float("inf")):
        alerts.append("latency")
    if metrics.get("error_rate", 0.0) > thresholds.get("max_error_rate", float("inf")):
        alerts.append("error_rate")
    return alerts


def build_release_gate(
    *,
    eval_summary: dict[str, float],
    ops_metrics: dict[str, float],
    policy: dict[str, float],
) -> dict[str, object]:
    failed_checks: list[str] = []
    if eval_summary.get("pass_rate", 0.0) < policy.get("min_pass_rate", 0.0):
        failed_checks.append("eval_pass_rate")
    if ops_metrics.get("error_rate", 0.0) > policy.get("max_error_rate", float("inf")):
        failed_checks.append("ops_error_rate")
    if ops_metrics.get("avg_latency_ms", 0.0) > policy.get("max_latency_ms", float("inf")):
        failed_checks.append("ops_latency")
    return {
        "can_release": not failed_checks,
        "failed_checks": failed_checks,
        "policy": policy,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线 LLMOps 监控 Demo")
    parser.add_argument("--max-cost", type=float, default=1.0)
    args = parser.parse_args(argv)

    calls = [
        record_call("chat", 320, 0.012, 900, True),
        record_call("rag", 680, 0.028, 1600, True),
        record_call("agent", 1200, 0.08, 2600, False),
    ]
    metrics = aggregate_metrics(calls)
    thresholds = {"max_cost_usd": args.max_cost, "max_latency_ms": 2000, "max_error_rate": 0.1}
    print(
        json.dumps(
            {
                "metrics": metrics,
                "alerts": check_alerts(metrics, thresholds),
                "release_gate": build_release_gate(
                    eval_summary={"pass_rate": 0.92},
                    ops_metrics=metrics,
                    policy={"min_pass_rate": 0.9, "max_error_rate": 0.1, "max_latency_ms": 2000},
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
