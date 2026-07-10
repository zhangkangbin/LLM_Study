import argparse
import json
import os


DEFAULT_MODEL = "gpt-5.5"


def build_android_crash_instructions():
    return """你是 Android 稳定性分析助手。

任务目标：
- 只基于输入内容分析 Android 崩溃或异常现象。
- 不要编造不存在的代码、类名、接口、业务背景。
- 如果证据不足，明确说明“不确定”，并列出需要补充的信息。

输出要求：
1. 问题类型：一句话说明崩溃或异常类型。
2. 关键证据：列出来自日志或上下文的证据。
3. 可能原因：按可信度排序，避免过度推断。
4. 修复建议：给出 Android 开发者可以执行的修改方向。
5. 需要补充的信息：如果无法确认根因，列出下一步需要的日志或代码。

回答风格：
- 使用中文。
- 简洁、具体、面向工程排查。
- 不输出和输入无关的通用科普。"""


def build_android_crash_input(
    app_version,
    android_version,
    device,
    recent_changes,
    crash_log,
):
    return f"""请分析下面的 Android 崩溃信息。

## 环境

- App 版本：{app_version}
- Android 版本：{android_version}
- 设备：{device}
- 最近改动：{recent_changes}

## 崩溃日志

<crash_log>
{crash_log}
</crash_log>
"""


def build_naive_prompt(crash_log):
    return f"帮我看看这个 Android 崩溃是什么原因：\n{crash_log}"


def build_responses_payload(model, instructions, user_input):
    return {
        "model": model,
        "instructions": instructions,
        "input": user_input,
    }


def build_prompt_comparison(
    crash_log,
    app_version,
    android_version,
    device,
    recent_changes,
    model,
):
    engineered_input = build_android_crash_input(
        app_version=app_version,
        android_version=android_version,
        device=device,
        recent_changes=recent_changes,
        crash_log=crash_log,
    )
    return {
        "naive": {
            "model": model,
            "input": build_naive_prompt(crash_log),
        },
        "engineered": build_responses_payload(
            model=model,
            instructions=build_android_crash_instructions(),
            user_input=engineered_input,
        ),
    }


def read_text_argument(value):
    if value and value.startswith("@"):
        path = value[1:]
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    return value or ""


def build_parser():
    parser = argparse.ArgumentParser(description="Prompt Engineering demo for Android crash analysis")
    parser.add_argument("--crash-log", required=True, help="崩溃日志文本；也可使用 @path 读取文件")
    parser.add_argument("--app-version", default="unknown")
    parser.add_argument("--android-version", default="unknown")
    parser.add_argument("--device", default="unknown")
    parser.add_argument("--recent-changes", default="unknown")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--mode",
        choices=("engineered", "naive", "compare"),
        default="compare",
        help="输出工程化 Prompt、朴素 Prompt，或二者对比",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    crash_log = read_text_argument(args.crash_log)
    comparison = build_prompt_comparison(
        crash_log=crash_log,
        app_version=args.app_version,
        android_version=args.android_version,
        device=args.device,
        recent_changes=args.recent_changes,
        model=args.model,
    )

    if args.mode == "naive":
        output = comparison["naive"]
    elif args.mode == "engineered":
        output = comparison["engineered"]
    else:
        output = comparison

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
