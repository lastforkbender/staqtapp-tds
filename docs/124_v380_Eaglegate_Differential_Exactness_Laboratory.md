# v3.8 Eaglegate Differential Exactness Laboratory

## Status

This tranche is a deterministic qualification oracle stacked on the Eaglegate
lossless foundation. It does not execute a real EAGLE model, intercept live
requests, mutate production KV state, or activate speculative decoding.

## Governing authority

```text
EAGLE proposes.
Eaglegate admits.
The target verifies and samples.
The target runtime commits tokens and KV state.
```

The laboratory makes that boundary executable. The scripted proposer has no
commit API. The reference KV ledger rejects every authority other than
`target-runtime`. Epoch mismatch and proposer failure continue through the
ordinary target-only path.

## Differential oracle

For one deterministic target token stream, the laboratory runs:

1. a target-only reference execution; and
2. a scripted speculative execution whose proposals are verified token by token
   against the same target stream.

The two paths must finish with equal:

- token count;
- token-sequence digest;
- committed-state digest; and
- cancellation prefix.

Every speculative reservation must be released, including after mismatch,
cancellation, and proposer failure. All committed tokens must be attributed to
the target runtime.

## Exact sampled-distribution proof

The one-step sampling oracle uses `fractions.Fraction`; floating-point masses are
rejected. For target mass `p` and draft mass `q`, it computes:

```text
accepted(x) = min(p(x), q(x))
residual(x) = max(p(x) - q(x), 0)
output(x)   = accepted(x) + residual(x)
```

The gate requires exact tokenwise equality `output(x) == p(x)` and exact total
mass equality. This proves the finite one-step acceptance/correction identity.
It is not yet a qualification of any external runtime's RNG ownership, sampler
ordering, numerical kernels, or multi-step implementation.

## Reference cases

The bounded suite covers:

- complete proposal acceptance;
- immediate rejection;
- rejection after a matching prefix;
- proposer exception with target-only continuation;
- mixed-epoch rejection before the proposer is called;
- cancellation within a candidate and reservation cleanup;
- observer-ring overflow without generation interference;
- exact rational distribution recovery;
- direct proposer-commit denial; and
- content-free evidence publication.

## Observer isolation

The laboratory observer accepts only fixed `kind` and integer `count` fields.
When the bounded ring is full, event detail is dropped and the dropped counter
increments. Observer overflow cannot alter token verification, committed state,
or fallback behavior.

## Evidence boundary

Canonical reports contain only:

- contract and suite identities;
- check names and booleans;
- counts;
- content digests;
- committed-state digests;
- bounded fallback facts; and
- a canonical report root.

They contain no prompt, raw token sequence, logits, hidden states, or KV tensors,
and they carry no activation authority.

## Engineer command

```bash
staqtapp-tds-eaglegate-lab
staqtapp-tds-eaglegate-lab --json
python -m staqtapp_tds.eaglegate.exactness --json
```

The JSON form is deterministic for an identical source and runtime. CI runs it
twice and requires byte-identical output.

## Qualification workflow

The focused workflow runs on:

- Ubuntu 24.04 with Python 3.10;
- Ubuntu 24.04 with Python 3.13;
- macOS 14 with Python 3.13; and
- Windows Server 2022 with Python 3.13.

Every lane compiles the Eaglegate package, runs the foundation, exactness,
workflow, and installation contracts, generates the report twice, compares the
bytes, verifies the content-free boundary, and emits CI-archived observer evidence. An
aggregate job fails unless every matrix lane succeeds.

## Deliberately absent

This tranche does not provide or claim:

- real EAGLE weights or proposer execution;
- CUDA, ROCm, Metal, or accelerator kernels;
- production target-runtime integration;
- live rejection sampling;
- committed production KV mutation;
- live traffic shadowing, canarying, promotion, or rollback;
- cross-hardware bit identity;
- learned routing, sentinels, random forests, agents, or online training; or
- a production speedup measurement.

## Claim boundary

A passing reference report proves that the TDS oracle, authority separation,
bounded evidence path, and finite exact sampling identity behave as specified.
It does not prove that a named external EAGLE implementation, model build,
sampler, RNG stream, logits-processor sequence, KV allocator, accelerator
kernel, or serving runtime is lossless. Those identities must be pinned and
qualified through the next adapter-conformance gate.

## Completed successor gate

The runtime-adapter conformance ABI now defines exact identity and
reserve/propose/verify/commit/rewind/cancel/release sequencing against the
adversarial fake runtime. Its report remains explicitly
`real_runtime_qualified: false` and gains candidate scope only through the
Generation Authority qualification bridge. A named real runtime still requires
the separate hardware-backed shadow gate.
