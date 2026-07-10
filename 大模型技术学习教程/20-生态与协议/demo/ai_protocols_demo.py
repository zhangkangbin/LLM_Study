from __future__ import annotations

import argparse
import json
from typing import Sequence


def build_mcp_tool_descriptor(
    name: str,
    description: str,
    fields: dict[str, str],
) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {
                field: {"type": field_type}
                for field, field_type in fields.items()
            },
            "required": list(fields.keys()),
        },
    }


def build_openapi_function_schema(name: str, required_fields: Sequence[str]) -> dict[str, object]:
    return {
        "name": name,
        "parameters": {
            "type": "object",
            "properties": {field: {"type": "string"} for field in required_fields},
            "required": list(required_fields),
        },
    }


def choose_integration_surface(
    *,
    needs_ai_client_interop: bool,
    needs_public_http_api: bool,
    needs_embedded_ui: bool,
) -> dict[str, str]:
    if needs_embedded_ui:
        return {"surface": "app_sdk", "reason": "需要把业务 UI 嵌入 AI 产品体验。"}
    if needs_ai_client_interop:
        return {"surface": "mcp", "reason": "多个 AI 客户端共享工具、资源和提示模板。"}
    if needs_public_http_api:
        return {"surface": "openapi", "reason": "面向普通开发者或第三方系统集成。"}
    return {"surface": "sdk", "reason": "内部服务优先用语言 SDK 或普通 API 封装。"}


def validate_protocol_manifest(manifest: dict[str, object]) -> dict[str, object]:
    required = ["name", "version", "tools"]
    missing = [field for field in required if field not in manifest]
    return {"valid": not missing, "missing": missing}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 生态协议选择 Demo")
    parser.add_argument("--surface", choices=["mcp", "openapi", "app"], default="mcp")
    args = parser.parse_args(argv)

    decision = choose_integration_surface(
        needs_ai_client_interop=args.surface == "mcp",
        needs_public_http_api=args.surface == "openapi",
        needs_embedded_ui=args.surface == "app",
    )
    descriptor = build_mcp_tool_descriptor("search_docs", "检索文档", {"query": "string"})
    print(
        json.dumps(
            {
                "decision": decision,
                "mcp_tool": descriptor,
                "openapi_function": build_openapi_function_schema("create_ticket", ["title", "priority"]),
                "manifest_validation": validate_protocol_manifest(
                    {"name": "demo", "version": "1.0.0", "tools": [descriptor]}
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
