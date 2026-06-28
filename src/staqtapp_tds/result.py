"""Structured non-halting operation results for Staqtapp-TDS."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass(frozen=True)
class TDSResult:
    ok: bool
    code: str = "OK"
    message: str = ""
    name: str = ""
    path: str = ""
    value: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, code: str = "OK", message: str = "", **kw: Any) -> "TDSResult":
        return cls(True, code, message, **kw)

    @classmethod
    def fail(cls, code: str, message: str, **kw: Any) -> "TDSResult":
        return cls(False, code, message, **kw)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "name": self.name,
            "path": self.path,
            "value": self.value,
            "meta": dict(self.meta),
        }
