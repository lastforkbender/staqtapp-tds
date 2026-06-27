"""Reserved namespace support for Staqtapp-TDS v1.7.1.

Reserved namespaces let a manifest protect future directory names, aliases,
and route identifiers without forcing the VFS to predict their meaning. The
feature is intentionally cold-path oriented: checks occur when creating or
registering directories, not during ordinary entry reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List


def _clean_name(value: str) -> str:
    return str(value).strip().strip("/")


@dataclass(frozen=True)
class ReservedNamespaces:
    directory_names: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)
    route_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: Dict[str, object] | None) -> "ReservedNamespaces":
        data = data or {}
        names = tuple(_clean_name(v) for v in data.get("directory_names", []) if _clean_name(v))  # type: ignore[arg-type]
        aliases = tuple(str(v).strip() for v in data.get("aliases", []) if str(v).strip())  # type: ignore[arg-type]
        route_ids = tuple(int(v) for v in data.get("route_ids", []))  # type: ignore[arg-type]
        return cls(directory_names=names, aliases=aliases, route_ids=route_ids)

    def to_dict(self) -> Dict[str, List[object]]:
        return {
            "directory_names": list(self.directory_names),
            "aliases": list(self.aliases),
            "route_ids": [int(v) for v in self.route_ids],
        }

    def is_reserved_directory(self, name: str) -> bool:
        n = _clean_name(name)
        return n in set(self.directory_names)

    def is_reserved_alias(self, alias: str) -> bool:
        return str(alias).strip() in set(self.aliases)

    def is_reserved_route_id(self, route_id: int) -> bool:
        return int(route_id) in set(self.route_ids)

    def names(self) -> List[str]:
        return list(self.directory_names)

    def with_directory_names(self, names: Iterable[str]) -> "ReservedNamespaces":
        merged = list(self.directory_names)
        for name in names:
            n = _clean_name(name)
            if n and n not in merged:
                merged.append(n)
        return ReservedNamespaces(tuple(merged), self.aliases, self.route_ids)
