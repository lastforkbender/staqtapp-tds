"""Radix path router for Staqtapp-TDS v2.1.0.

This module intentionally keeps a small Python implementation: path traversal is
still Python-facing, but child routing is no longer coupled to raw dict access.
The API mirrors the small mapping surface TDSDirectory needs while creating the
future seam for a native radix backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Generic, Iterable, Iterator, List, Optional, Tuple, TypeVar

T = TypeVar("T")


@dataclass
class _RadixNode(Generic[T]):
    edge: str = ""
    value: Optional[T] = None
    children: Dict[str, "_RadixNode[T]"] = field(default_factory=dict)


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class RadixDirectoryRouter(Generic[T]):
    """Compressed-prefix router for direct children and slash paths.

    Direct child names are still unique exactly as before. The compressed radix
    tree improves prefix-heavy path routing and gives TDS a clean radix seam
    without changing TDSDirectory's public behavior.
    """

    backend_name = "python-radix-router"

    def __init__(self) -> None:
        self._root: _RadixNode[T] = _RadixNode()
        self._items: Dict[str, T] = {}

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __setitem__(self, key: str, value: T) -> None:
        self.insert(key, value)

    def __getitem__(self, key: str) -> T:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __delitem__(self, key: str) -> None:
        self.delete(key)

    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        value = self._lookup(key)
        return default if value is None else value

    def insert(self, key: str, value: T) -> None:
        if not key:
            raise ValueError("radix key must be non-empty")
        self._items[key] = value
        node = self._root
        rest = key
        while rest:
            first = rest[0]
            child = node.children.get(first)
            if child is None:
                node.children[first] = _RadixNode(edge=rest, value=value)
                return
            cp = _common_prefix(rest, child.edge)
            if cp == len(child.edge):
                node = child
                rest = rest[cp:]
                continue
            # Split existing edge.
            suffix_old = child.edge[cp:]
            split = _RadixNode(edge=child.edge[:cp], value=None)
            child.edge = suffix_old
            split.children[suffix_old[0]] = child
            node.children[first] = split
            suffix_new = rest[cp:]
            if suffix_new:
                split.children[suffix_new[0]] = _RadixNode(edge=suffix_new, value=value)
            else:
                split.value = value
            return
        node.value = value

    def _lookup(self, key: str) -> Optional[T]:
        node = self._root
        rest = key
        while rest:
            child = node.children.get(rest[0])
            if child is None or not rest.startswith(child.edge):
                return None
            rest = rest[len(child.edge):]
            node = child
        return node.value

    def delete(self, key: str) -> Optional[T]:
        # Keep deletion conservative and rebuild. This is cold path and avoids
        # subtle compressed-trie merge bugs.
        if key not in self._items:
            return None
        removed = self._items.pop(key)
        old = list(self._items.items())
        self._root = _RadixNode()
        self._items = {}
        for k, v in old:
            self.insert(k, v)
        return removed

    def keys(self) -> List[str]:
        return list(self._items.keys())

    def values(self) -> List[T]:
        return list(self._items.values())

    def items(self) -> List[Tuple[str, T]]:
        return list(self._items.items())

    def resolve_path(self, path: str) -> T:
        """Resolve slash-separated child path through stored directory nodes."""
        parts = [p for p in path.strip('/').split('/') if p]
        if not parts:
            raise KeyError("empty radix path")
        node = self.get(parts[0])
        if node is None:
            raise KeyError(parts[0])
        for part in parts[1:]:
            node = node.cd(part)  # type: ignore[attr-defined]
        return node

    def lookup_steps(self, key: str) -> int:
        """Return the number of compressed radix edges traversed for a lookup."""
        node = self._root
        rest = key
        steps = 0
        while rest:
            child = node.children.get(rest[0])
            if child is None or not rest.startswith(child.edge):
                return steps
            steps += 1
            rest = rest[len(child.edge):]
            node = child
        return steps

    def stats(self) -> dict:
        def walk(n: _RadixNode[T], depth: int = 0) -> Tuple[int, int, int, int, int]:
            nodes = 1
            edges = len(n.children)
            max_depth = depth
            edge_chars = 0
            terminal_depth_sum = depth if n.value is not None else 0
            terminals = 1 if n.value is not None else 0
            for c in n.children.values():
                cn, ce, cm, cc, ctd, ct = walk(c, depth + 1)
                nodes += cn
                edges += ce
                max_depth = max(max_depth, cm)
                edge_chars += len(c.edge) + cc
                terminal_depth_sum += ctd
                terminals += ct
            return nodes, edges, max_depth, edge_chars, terminal_depth_sum, terminals
        nodes, edges, max_depth, edge_chars, terminal_depth_sum, terminals = walk(self._root)
        return {
            "backend": self.backend_name,
            "size": len(self),
            "nodes": nodes,
            "edges": edges,
            "max_depth": max_depth,
            "average_edge_length": (edge_chars / edges) if edges else 0.0,
            "average_lookup_steps": (terminal_depth_sum / terminals) if terminals else 0.0,
        }
