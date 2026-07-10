from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    input_text: str
    actual_output: str
    required_keywords: list[str]
    threshold: float = 0.8


def build_eval_case(
    case_id: str,
    input_text: str,
    actual_output: str,
    required_keywords: Sequence[str],
    *,
    threshold: float = 0.8,
) -> EvalCase:
    if not case_id or not input_text:
        raise ValueError("case_id and input_text are required")
    return EvalCase(case_id, input_text, actual_output, list(required_keywords), threshold)


def keyword_coverage(output: str, required_keywords: Sequence[str]) -> float:
    if not required_keywords:
        return 1.0
    hit_count = sum(1 for keyword in required_keywords if keyword in output)
    return hit_count / len(required_keywords)


def run_eval_suite(cases: Iterable[EvalCase]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for case in cases:
        score = keyword_coverage(case.actual_output, case.required_keywords)
        results.append(
            {
                "case_id": case.case_id,
                "score": score,
                "passed": score >= case.threshold,
                "threshold": case.threshold,
                "missing_keywords": [
                    keyword
                    for keyword in case.required_keywords
                    if keyword not in case.actual_output
                ],
            }
        )
    return results


def summarize_results(results: Sequence[dict[str, object]]) -> dict[str, float]:
    if not results:
        return {"case_count": 0, "pass_rate": 0.0, "average_score": 0.0}

    passed_count = sum(1 for result in results if bool(result["passed"]))
    total_score = sum(float(result["score"]) for result in results)
    return {
        "case_count": len(results),
        "pass_rate": round(passed_count / len(results), 4),
        "average_score": round(total_score / len(results), 4),
    }


def detect_regression(
    *,
    baseline: dict[str, float],
    current: dict[str, float],
    tolerance: float = 0.02,
) -> dict[str, object]:
    failed_metrics: list[str] = []
    for metric in ("pass_rate", "average_score"):
        if current.get(metric, 0.0) < baseline.get(metric, 0.0) - tolerance:
            failed_metrics.append(metric)
    return {
        "has_regression": bool(failed_metrics),
        "failed_metrics": failed_metrics,
        "baseline": baseline,
        "current": current,
        "tolerance": tolerance,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线大模型评估 Demo")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args(argv)

    cases = [
        build_eval_case("qa-001", "订单状态", "订单号 123 已完成", ["订单号", "完成"], threshold=args.threshold),
        build_eval_case("qa-002", "退款状态", "退款处理中，预计 1 个工作日完成", ["退款", "处理中"], threshold=args.threshold),
    ]
    results = run_eval_suite(cases)
    print(
        json.dumps(
            {
                "cases": [asdict(case) for case in cases],
                "results": results,
                "summary": summarize_results(results),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
