import argparse
import json
import pathlib


DEFAULT_CATALOG_PATH = pathlib.Path(__file__).with_name("sample_model_catalog.json")


def load_catalog(path=DEFAULT_CATALOG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def find_model(catalog, model_id):
    for model in catalog.get("models", []):
        if model.get("id") == model_id:
            return model
    raise ValueError(f"unknown model: {model_id}")


def estimate_request_cost(model, input_tokens, output_tokens, cached_input_tokens=0):
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    regular_input_tokens = input_tokens - cached_input_tokens
    cached_price = model.get(
        "cached_input_price_per_million",
        model["input_price_per_million"],
    )

    input_cost = regular_input_tokens / 1_000_000 * model["input_price_per_million"]
    cached_input_cost = cached_input_tokens / 1_000_000 * cached_price
    output_cost = output_tokens / 1_000_000 * model["output_price_per_million"]

    return {
        "model": model["id"],
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "input_cost": round(input_cost, 6),
        "cached_input_cost": round(cached_input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + cached_input_cost + output_cost, 6),
    }


def estimate_period_cost(
    model,
    requests_per_day,
    days,
    avg_input_tokens,
    avg_output_tokens,
    avg_cached_input_tokens=0,
):
    per_request = estimate_request_cost(
        model=model,
        input_tokens=avg_input_tokens,
        output_tokens=avg_output_tokens,
        cached_input_tokens=avg_cached_input_tokens,
    )
    total_requests = requests_per_day * days
    total_cost = per_request["total_cost"] * total_requests
    return {
        "model": model["id"],
        "requests_per_day": requests_per_day,
        "days": days,
        "total_requests": total_requests,
        "per_request_cost": per_request,
        "total_cost": round(total_cost, 6),
    }


def model_score(model, task, priority, requires_tools, requires_vision):
    if requires_tools and not model.get("supports_tools"):
        return None
    if requires_vision and not model.get("supports_vision"):
        return None

    score = 0
    recommended_for = set(model.get("recommended_for", []))
    if task in recommended_for:
        score += 30

    quality = model.get("quality", 3)
    speed = model.get("speed", 3)
    cost_level = model.get("cost_level", 3)

    if priority == "quality":
        score += quality * 10
        score += speed * 2
        score -= cost_level
    elif priority == "latency":
        score += speed * 10
        score += quality * 3
        score -= cost_level * 2
    elif priority == "cost":
        score += (6 - cost_level) * 10
        score += speed * 3
        score += quality
    else:
        score += quality * 5
        score += speed * 4
        score += (6 - cost_level) * 4

    if requires_tools:
        score += 5
    if requires_vision:
        score += 5
    return score


def recommend_model(catalog, task, priority="balanced", requires_tools=False, requires_vision=False):
    candidates = []
    for model in catalog.get("models", []):
        score = model_score(
            model=model,
            task=task,
            priority=priority,
            requires_tools=requires_tools,
            requires_vision=requires_vision,
        )
        if score is not None:
            candidates.append((score, model))

    if not candidates:
        raise ValueError("no model satisfies the requirements")

    candidates.sort(key=lambda item: item[0], reverse=True)
    score, model = candidates[0]
    reasons = [
        f"priority={priority}, score={score}",
        f"task={task}",
    ]
    if task in model.get("recommended_for", []):
        reasons.append("task appears in model recommended_for list")
    if requires_tools:
        reasons.append("requires tool calling support")
    if requires_vision:
        reasons.append("requires vision input support")

    return {
        "model": model,
        "score": score,
        "reasons": reasons,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Model selection and cost estimation demo")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH), help="模型目录 JSON 文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cost = subparsers.add_parser("cost", help="估算单次或一段时间的调用成本")
    cost.add_argument("--model", required=True)
    cost.add_argument("--input-tokens", type=int, required=True)
    cost.add_argument("--output-tokens", type=int, required=True)
    cost.add_argument("--cached-input-tokens", type=int, default=0)
    cost.add_argument("--requests-per-day", type=int, default=1)
    cost.add_argument("--days", type=int, default=1)

    recommend = subparsers.add_parser("recommend", help="根据任务和优先级推荐模型")
    recommend.add_argument("--task", required=True)
    recommend.add_argument(
        "--priority",
        choices=("quality", "balanced", "cost", "latency"),
        default="balanced",
    )
    recommend.add_argument("--requires-tools", action="store_true")
    recommend.add_argument("--requires-vision", action="store_true")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog)

    if args.command == "cost":
        model = find_model(catalog, args.model)
        result = estimate_period_cost(
            model=model,
            requests_per_day=args.requests_per_day,
            days=args.days,
            avg_input_tokens=args.input_tokens,
            avg_output_tokens=args.output_tokens,
            avg_cached_input_tokens=args.cached_input_tokens,
        )
    else:
        result = recommend_model(
            catalog=catalog,
            task=args.task,
            priority=args.priority,
            requires_tools=args.requires_tools,
            requires_vision=args.requires_vision,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
