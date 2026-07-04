"""Platform-aware, non-halting native engine manager.

The manager is the single authority for optional native extension loading.  It
keeps platform/ABI/capability diagnostics out of storage hot paths and prevents
native import failures from halting AI systems that use TDS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import importlib
import platform
import sys
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from staqtapp_tds.result import TDSResult, TDSResultCode
from staqtapp_tds.version import __version__

TDS_NATIVE_ABI_VERSION = 1


@dataclass(frozen=True, slots=True)
class NativeRuntimePlatform:
    """Runtime details used to select and validate native engines."""

    system: str
    machine: str
    python_implementation: str
    python_version: str
    python_tag: str
    extension_suffixes: tuple[str, ...]

    @classmethod
    def detect(cls) -> "NativeRuntimePlatform":
        try:
            from importlib.machinery import EXTENSION_SUFFIXES
        except Exception:
            suffixes: tuple[str, ...] = ()
        else:
            suffixes = tuple(EXTENSION_SUFFIXES)
        vi = sys.version_info
        return cls(
            system=platform.system() or "unknown",
            machine=platform.machine() or "unknown",
            python_implementation=platform.python_implementation() or "unknown",
            python_version=f"{vi.major}.{vi.minor}.{vi.micro}",
            python_tag=f"cp{vi.major}{vi.minor}" if platform.python_implementation() == "CPython" else platform.python_implementation().lower(),
            extension_suffixes=suffixes,
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NativeLoadReport:
    """Immutable native engine load/capability report."""

    requested: str
    selected_backend: str
    native_loaded: bool
    fallback_used: bool
    compatible: bool
    module_name: str
    binary_present: bool
    abi_expected: int
    abi_actual: int | None
    tds_version: str
    platform: NativeRuntimePlatform
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    exception_type: str = ""
    exception_message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["platform"] = self.platform.as_dict()
        data["capabilities"] = dict(self.capabilities)
        return data


class NativeEngineManager:
    """Central non-halting manager for optional compiled TDS engines."""

    def __init__(self, *, expected_abi: int = TDS_NATIVE_ABI_VERSION) -> None:
        self.expected_abi = int(expected_abi)
        self.platform = NativeRuntimePlatform.detect()
        self._last_reports: Dict[str, NativeLoadReport] = {}

    def _empty_report(self, name: str, requested: str, reason: str, *, exception: BaseException | None = None) -> NativeLoadReport:
        return NativeLoadReport(
            requested=requested,
            selected_backend="python",
            native_loaded=False,
            fallback_used=True,
            compatible=False,
            module_name=f"staqtapp_tds._native_{name}",
            binary_present=False,
            abi_expected=self.expected_abi,
            abi_actual=None,
            tds_version=__version__,
            platform=self.platform,
            reason=reason,
            exception_type=type(exception).__name__ if exception else "",
            exception_message=str(exception) if exception else "",
        )

    def inspect_module(self, module_name: str) -> tuple[ModuleType | None, NativeLoadReport]:
        """Import a native module once and return a report instead of raising."""
        short = module_name.rsplit("_native_", 1)[-1]
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            report = self._empty_report(short, "auto", "native module import failed", exception=exc)
            self._last_reports[short] = report
            return None, report

        abi_actual = getattr(module, "TDS_NATIVE_ABI_VERSION", None)
        if abi_actual is None:
            # Existing v2 native binaries do not expose the ABI constant yet.  We
            # accept them as ABI 1 and report that assumption for diagnostics.
            abi_actual = 1
            reason = "native module loaded; ABI assumed from v3.0.1 compatibility policy"
        else:
            reason = "native module loaded"

        compatible = int(abi_actual) == self.expected_abi
        capabilities = {
            "has_native_handle_index": hasattr(module, "NativeHandleIndex"),
            "has_checksum32": hasattr(module, "checksum32"),
            "has_spiral_rank_scores": hasattr(module, "spiral_rank_scores"),
            "has_utf8_chunk_bounds": hasattr(module, "utf8_chunk_bounds"),
            "has_diag_snapshot": hasattr(module, "diag_snapshot"),
        }
        report = NativeLoadReport(
            requested="auto",
            selected_backend="native" if compatible else "python",
            native_loaded=compatible,
            fallback_used=not compatible,
            compatible=compatible,
            module_name=module_name,
            binary_present=True,
            abi_expected=self.expected_abi,
            abi_actual=int(abi_actual),
            tds_version=__version__,
            platform=self.platform,
            capabilities=capabilities,
            reason=reason if compatible else "native ABI mismatch; Python fallback selected",
        )
        self._last_reports[short] = report
        return (module if compatible else None), report

    def load_index_backend(self, *, shards: int = 64, requested: str = "auto", factory: Callable[..., Any] | None = None) -> tuple[Any | None, NativeLoadReport]:
        """Load the native EntryIndex backend or return a fallback report."""
        selected = (requested or "auto").lower()
        if selected == "python":
            report = self._empty_report("index", selected, "Python backend explicitly requested")
            self._last_reports["index"] = report
            return None, report
        try:
            module, report = self.inspect_module("staqtapp_tds._native_index")
            if module is None:
                return None, report
            if factory is None:
                from staqtapp_tds.backends.native_index import NativeEntryIndexBackend
                factory = NativeEntryIndexBackend
            backend = factory(shards=shards)
            report = NativeLoadReport(
                requested=selected,
                selected_backend="native",
                native_loaded=True,
                fallback_used=False,
                compatible=True,
                module_name=report.module_name,
                binary_present=report.binary_present,
                abi_expected=report.abi_expected,
                abi_actual=report.abi_actual,
                tds_version=report.tds_version,
                platform=report.platform,
                capabilities=report.capabilities,
                reason="native index backend loaded",
            )
            self._last_reports["index"] = report
            return backend, report
        except Exception as exc:
            report = self._empty_report("index", selected, "native backend construction failed", exception=exc)
            self._last_reports["index"] = report
            return None, report

    def status_result(self) -> TDSResult:
        """Return non-halting native manager status for diagnostics."""
        return TDSResult.success(
            TDSResultCode.NATIVE_MANAGER_OK,
            "Native engine manager status collected.",
            value={name: report.as_dict() for name, report in self._last_reports.items()},
            meta={"platform": self.platform.as_dict(), "expected_abi": self.expected_abi},
        )

    def capabilities_result(self) -> TDSResult:
        """Return platform and last-known native capability diagnostics."""
        return TDSResult.success(
            TDSResultCode.NATIVE_CAPABILITY_OK,
            "Native platform and capability details collected.",
            value={
                "platform": self.platform.as_dict(),
                "expected_abi": self.expected_abi,
                "reports": {name: report.as_dict() for name, report in self._last_reports.items()},
            },
        )


_MANAGER = NativeEngineManager()


def get_native_manager() -> NativeEngineManager:
    return _MANAGER


def native_status_result() -> TDSResult:
    return _MANAGER.status_result()


def native_capabilities_result() -> TDSResult:
    return _MANAGER.capabilities_result()
