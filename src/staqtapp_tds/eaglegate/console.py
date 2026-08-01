"""Local-first Eaglegate engineer console with no activation authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from .config import (
    EAGLEGATE_CONFIG_FILENAME,
    EAGLEGATE_LOCK_FILENAME,
    compile_project,
    epoch_diff,
    initialize_project,
    load_project,
    resolve_lock_from_snapshot,
)
from .admission import (
    EaglegateRequestClass,
    EaglegateRuntimeHealth,
    evaluate_admission,
)
from .contract import (
    EAGLEGATE_CONTRACT_ID,
    EaglegateContractError,
    EaglegateSamplerClass,
    authority_snapshot,
)
from .project import _read_bounded_regular_file


def _emit(value: Mapping[str, Any], compact: bool) -> None:
    print(
        json.dumps(
            dict(value),
            sort_keys=True,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
    )


def _json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(_read_bounded_regular_file(source).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EaglegateContractError(f"could not read {source}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EaglegateContractError(f"{source} must contain one JSON object")
    return dict(value)


def _status(directory: str | Path) -> dict[str, Any]:
    root = Path(directory)
    config_path = root / EAGLEGATE_CONFIG_FILENAME
    lock_path = root / EAGLEGATE_LOCK_FILENAME
    result: dict[str, Any] = {
        "ok": True,
        "contract_id": EAGLEGATE_CONTRACT_ID,
        "directory": str(root.resolve()),
        "configuration_exists": config_path.is_file(),
        "lock_exists": lock_path.is_file(),
        "activation_authority": False,
        "token_acceptance_authority": False,
        "target_only_fallback_required": True,
        "serving_effect": "target_only",
    }
    if not config_path.is_file() or not lock_path.is_file():
        result.update(state="not_initialized", compiled=False)
        return result
    config, lock = load_project(root)
    result.update(
        state="lock_resolved" if lock.resolved else "lock_unresolved",
        profile=config.profile,
        deployment=config.mode.value,
        generation=config.generation,
        configuration_root=config.configuration_root,
        lock_root=lock.lock_root,
        lock_resolved=lock.resolved,
        compiled=False,
    )
    if lock.resolved:
        epoch = config.compile(lock)
        result.update(
            compiled=True,
            candidate_epoch_root=epoch.epoch_root,
            identity_root=epoch.identity.identity_root,
            policy_root=epoch.policy.policy_root,
            plan_roots=[plan.plan_root for plan in epoch.plans],
            qualification_root=epoch.qualification_root,
            candidate_mode=config.mode.value,
            serving_effect="target_only",
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="staqtapp-tds-eaglegate",
        description="Configure lossless Eaglegate control-plane artifacts.",
    )
    parser.add_argument("--compact", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("constitution")
    init = sub.add_parser("init")
    init.add_argument("--directory", default=".")
    init.add_argument(
        "--profile",
        choices=("observe", "conservative", "balanced"),
        default="conservative",
    )
    init.add_argument("--force", action="store_true")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--directory", default=".")
    resolve.add_argument("--snapshot", required=True)
    resolve.add_argument("--force", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--directory", default=".")
    validate = sub.add_parser("validate")
    validate.add_argument("--directory", default=".")
    diff = sub.add_parser("diff")
    diff.add_argument("--left", required=True)
    diff.add_argument("--right", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--directory", default=".")
    evaluate.add_argument("--request", required=True)
    evaluate.add_argument("--health", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "constitution":
            _emit(
                {
                    "ok": True,
                    "activation_authority": False,
                    "authority": authority_snapshot(),
                },
                args.compact,
            )
        elif args.command == "init":
            config_path, lock_path = initialize_project(
                args.directory, profile=args.profile, force=args.force
            )
            _emit(
                {
                    "ok": True,
                    "state": "initialized_fail_closed",
                    "configuration": str(config_path),
                    "lock": str(lock_path),
                    "lock_resolved": False,
                    "serving_effect": "target_only",
                    "activation_authority": False,
                },
                args.compact,
            )
        elif args.command == "resolve":
            path = resolve_lock_from_snapshot(
                args.directory, args.snapshot, force=args.force
            )
            _, lock = load_project(args.directory)
            _emit(
                {
                    "ok": True,
                    "state": "lock_resolved",
                    "lock": str(path),
                    "lock_root": lock.lock_root,
                    "capability_root": lock.capability_root,
                    "serving_effect": "target_only",
                    "activation_authority": False,
                },
                args.compact,
            )
        elif args.command == "status":
            _emit(_status(args.directory), args.compact)
        elif args.command == "validate":
            config, lock = load_project(args.directory)
            epoch = config.compile(lock)
            _emit(
                {
                    "ok": True,
                    "state": "candidate_compiled",
                    "deployment": config.mode.value,
                    "configuration_root": config.configuration_root,
                    "lock_root": lock.lock_root,
                    "identity_root": epoch.identity.identity_root,
                    "policy_root": epoch.policy.policy_root,
                    "plan_roots": [plan.plan_root for plan in epoch.plans],
                    "candidate_epoch_root": epoch.epoch_root,
                    "qualification_root": epoch.qualification_root,
                    "candidate_mode": config.mode.value,
                    "serving_effect": "target_only",
                    "activation_authority": False,
                },
                args.compact,
            )
        elif args.command == "diff":
            _emit(
                {
                    "ok": True,
                    "diff": epoch_diff(
                        compile_project(args.left), compile_project(args.right)
                    ),
                },
                args.compact,
            )
        elif args.command == "evaluate":
            epoch = compile_project(args.directory)
            request_values = _json_object(args.request)
            request_values.setdefault("identity_root", epoch.identity.identity_root)
            try:
                request_values["sampler_class"] = EaglegateSamplerClass(
                    str(request_values.get("sampler_class", "greedy"))
                )
            except ValueError as exc:
                raise EaglegateContractError("unsupported sampler class") from exc
            health_values = _json_object(args.health)
            health_values.setdefault("epoch_root", epoch.epoch_root)
            health_values.setdefault("identity_root", epoch.identity.identity_root)
            decision = evaluate_admission(
                epoch,
                EaglegateRequestClass(**request_values),
                EaglegateRuntimeHealth(**health_values),
            )
            _emit(
                {
                    "ok": True,
                    "simulation_only": True,
                    "activation_authority": False,
                    "decision": decision.canonical_dict(),
                    "decision_root": decision.decision_root,
                },
                args.compact,
            )
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
        return 0
    except EaglegateContractError as exc:
        _emit(
            {
                "ok": False,
                "fault": exc.fault.value,
                "message": str(exc),
                "serving_effect": "target_only",
                "activation_authority": False,
            },
            args.compact,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
