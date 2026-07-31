# v3.6.0 checksum and UTF-8 truth repair

## Scope

This is the second independently qualified native-correctness repair in the
v3.6.0 Foundation train. It closes two evidence-identity defects before atomic
dataset generations, waypoint construction, or learned ranking are permitted:

1. Python and native code could assign different 32-bit checksums to identical
   bytes.
2. The compatibility UTF-8 chunk helper could accept malformed input or split
   using a boundary rule that did not prove strict RFC 3629 validity.

This repair adds no graph, planner, sentinel, forest, neural specialist,
learned serving, cache write, dataset write, model promotion, or activation
path.

## Checksum registry

New evidence uses one explicit algorithm identity:

```text
crc32-ieee-v1
```

The historical native checksum remains available only for reading already
written manifests:

```text
fnv1a32-legacy-v1
```

The native module declares its supported algorithms and exposes scalar and
batch operations that require the algorithm name. New chunk manifests bind
`chunk_checksum_algorithm`; backend identity is retained as execution evidence
but no longer determines checksum meaning.

Historical manifests that omit the algorithm are interpreted narrowly:

- historical `native` backend -> `fnv1a32-legacy-v1`;
- historical `python` backend -> `crc32-ieee-v1`.

No historical checksum is silently rewritten.

## Immutable input ownership

Exact `bytes` may be read zero-copy under a strong reference. Every other
contiguous buffer exporter is copied exactly once while the GIL is held. The
original exporter is released before checksum or UTF-8 work releases the GIL.

The legacy `checksum32` and `checksum32_many` calls remain compatibility aliases
for historical FNV evidence, but they now follow the same immutable-snapshot
ownership rule.

## UTF-8 boundary contract

New chunk evidence binds:

```text
strict-rfc3629-complete-codepoints-v1
```

The native and Python implementations reject:

- invalid leading and continuation bytes;
- overlong encodings;
- UTF-8 encoded surrogate values;
- code points above U+10FFFF; and
- truncated sequences.

Chunks never divide a code point. A chunk may exceed its byte budget only when
one complete code point itself is wider than that budget. The full input must
be covered by strictly increasing boundaries.

## Qualification requirements

The release tranche must prove:

- CRC32 and historical FNV known vectors;
- scalar/batch and Python/native parity for both registered algorithms;
- immutable-snapshot behavior for mutable exporters;
- strict invalid-UTF-8 rejection;
- identical native/reference boundaries over every tested real split size;
- new manifest algorithm and boundary-contract identity;
- historical manifest readability;
- strict C11 warning compilation; and
- AddressSanitizer and UndefinedBehaviorSanitizer coverage.

## Authority boundary

Checksum and chunk-boundary results are mechanical evidence only. They cannot
establish semantic truth, privacy or license permission, storage authority,
model activation, or frontier-model reasoning authority.
