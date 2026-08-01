"""Engineer CLI for the non-executing Eaglegate vLLM shadow fixture."""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from .shadow_contract import (
    EAGLEGATE_SHADOW_AUTHORITY,
    EAGLEGATE_SHADOW_CONTRACT_ID,
    EAGLEGATE_VLLM_FIXTURE_ID,
    EaglegateShadowCompilationReport,
    ShadowDecisionKind,
    ShadowReason,
    VLLMEagleCapabilityMetadata,
    VLLMEagleShadowPreview,
)
from .shadow_vllm import (
    compile_vllm_eagle_shadow,
    load_vllm_eagle_metadata,
    parse_vllm_eagle_metadata,
    vllm_eagle_metadata_schema,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="staqtapp-tds-eaglegate-shadow")
    sub = parser.add_subparsers(dest="command", required=True)
    schema = sub.add_parser("schema", help="print the content-free fixture schema")
    schema.add_argument("--json", action="store_true")
    inspect = sub.add_parser("inspect", help="compile metadata into a shadow report")
    inspect.add_argument("--metadata", required=True)
    inspect.add_argument("--exactness-root", required=True)
    inspect.add_argument("--adapter-root", required=True)
    inspect.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "schema":
        payload = {
            **vllm_eagle_metadata_schema(),
            "shadow_contract_id": EAGLEGATE_SHADOW_CONTRACT_ID,
            "authority": EAGLEGATE_SHADOW_AUTHORITY.canonical_dict(),
            "authority_root": EAGLEGATE_SHADOW_AUTHORITY.authority_root,
        }
        print(json.dumps(payload, sort_keys=True, indent=2))
        return 0

    metadata = load_vllm_eagle_metadata(args.metadata)
    preview, report = compile_vllm_eagle_shadow(
        metadata,
        exactness_qualification_root=args.exactness_root,
        adapter_conformance_report_root=args.adapter_root,
    )
    payload = {**report.to_dict(), "preview": preview.canonical_dict()}
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"Eaglegate vLLM shadow: {report.decision.value}")
        print(f"reason: {report.reason.value}")
        print(f"metadata_root: {report.metadata_root}")
        print(f"preview_root: {report.preview_root}")
        print(f"report_root: {report.report_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EAGLEGATE_SHADOW_AUTHORITY",
    "EAGLEGATE_SHADOW_CONTRACT_ID",
    "EAGLEGATE_VLLM_FIXTURE_ID",
    "EaglegateShadowCompilationReport",
    "ShadowDecisionKind",
    "ShadowReason",
    "VLLMEagleCapabilityMetadata",
    "VLLMEagleShadowPreview",
    "compile_vllm_eagle_shadow",
    "load_vllm_eagle_metadata",
    "main",
    "parse_vllm_eagle_metadata",
    "vllm_eagle_metadata_schema",
]
