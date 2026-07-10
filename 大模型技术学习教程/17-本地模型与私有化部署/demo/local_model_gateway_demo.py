from __future__ import annotations

import argparse
import json
from typing import Sequence


def estimate_memory_gb(parameter_billion: float, quantization_bits: int) -> float:
    bytes_per_parameter = quantization_bits / 8
    return round(parameter_billion * bytes_per_parameter, 2)


def route_inference(
    *,
    requires_private_data: bool,
    local_available: bool,
    estimated_memory_gb: float,
    available_memory_gb: float,
) -> dict[str, object]:
    enough_capacity = local_available and estimated_memory_gb <= available_memory_gb
    if requires_private_data and enough_capacity:
        target = "local"
        reason = "隐私数据优先留在本地或私有化环境内处理。"
    elif enough_capacity and estimated_memory_gb <= available_memory_gb * 0.7:
        target = "local"
        reason = "本地容量充足，可降低外部依赖。"
    else:
        target = "cloud"
        reason = "本地容量不足或需要更强模型能力，走云端网关并加强脱敏。"
    return {"target": target, "reason": reason, "enough_capacity": enough_capacity}


def build_ollama_generate_request(model: str, prompt: str, *, stream: bool = True) -> dict[str, object]:
    if not model or not prompt:
        raise ValueError("model and prompt are required")
    return {"model": model, "prompt": prompt, "stream": stream}


def summarize_deployment_plan(target: str, scenario: str) -> dict[str, object]:
    return {
        "target": target,
        "scenario": scenario,
        "components": [
            "gateway",
            "model_runtime",
            "observability",
            "access_control",
            "fallback_route",
        ],
        "checks": [
            "模型授权与许可证确认",
            "显存/内存容量验证",
            "吞吐、延迟和并发压测",
            "私有数据脱敏与审计",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地模型网关决策 Demo")
    parser.add_argument("--params", type=float, default=7)
    parser.add_argument("--bits", type=int, default=4)
    parser.add_argument("--memory", type=float, default=8)
    args = parser.parse_args(argv)

    estimated = estimate_memory_gb(args.params, args.bits)
    route = route_inference(
        requires_private_data=True,
        local_available=True,
        estimated_memory_gb=estimated,
        available_memory_gb=args.memory,
    )
    print(
        json.dumps(
            {
                "estimated_memory_gb": estimated,
                "route": route,
                "ollama_request": build_ollama_generate_request("demo-local-model", "总结这段内部知识"),
                "deployment_plan": summarize_deployment_plan(route["target"], "internal_knowledge_base"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
