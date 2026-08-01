# v3.8 Eaglegate Runtime Adapter Conformance

## Status

This tranche defines and adversarially exercises a fake runtime-adapter ABI above
the remotely qualified Eaglegate differential exactness laboratory. It does not
attach real EAGLE weights, a production target runtime, an accelerator kernel,
or live traffic.

## Governing authority

```text
EAGLE proposes.
Eaglegate admits.
The target verifies and samples.
The target runtime commits tokens and KV state.
```

The adapter identity is bound to the lossless foundation and exactness
qualification roots. The fake EAGLE side exposes proposal only. The fake target
runtime owns reservation, verification, rewind, commit, cancellation, release,
and target-only continuation.

## Immutable adapter identity

`EaglegateAdapterIdentity` pins:

- the foundation identity;
- the exactness qualification report;
- the adapter build;
- the target verifier;
- RNG ownership and consumption contract;
- sampler ordering;
- logits-processor ordering;
- termination behavior;
- KV allocator contract;
- numerical-kernel identity; and
- deadline contract.

Any mismatch fails before proposal execution and continues through the target-only
reference path.

## ABI v1 sequence

The machine-checkable sequence identifier is:

```text
pin-reserve-propose-verify-rewind-commit-cancel-release-v1
```

Legal transitions are replayed from the append-only trace rather than trusted as
ordinary log text. The trace validates:

- contiguous sequence numbers;
- predecessor event roots;
- contiguous before/after states;
- legal operation/state transitions;
- one active reservation at most;
- exact reservation identity across all reservation operations;
- mandatory release before fallback or close;
- target-runtime ownership of every commit; and
- a terminal closed state with no reservation outstanding.

ABI v1 intentionally supports exactly one outstanding speculative reservation.
A wider resource model requires a new ABI and qualification suite.

## Stable boundary failures

Expected fake-boundary conditions have distinct types:

- proposer failure;
- verifier failure; and
- resource exhaustion.

Those stable conditions trigger bounded cleanup and target-only fallback.
Unexpected programming defects are not converted into a successful fallback;
they fail the conformance run so the oracle cannot hide its own bugs.

## Deterministic deadlines

The fake runtime uses operation ticks, not wall-clock time. Deadline checks occur
before pin, reserve, propose, verify, rewind, and commit. If a deadline expires
with a reservation active, the target runtime cancels and releases it before
recording fallback and continuing target-only.

This proves ordering and cleanup only. A production adapter must separately bind
and qualify its actual clock, scheduler, preemption, and timeout semantics.

## Adversarial catalog

The ten canonical report checks cover:

1. complete acceptance with exact ABI order;
2. rewind before target correction commit;
3. proposer failure cleanup;
4. epoch mismatch before proposer execution;
5. execution-identity mismatch, including RNG identity;
6. deadline cleanup with an active reservation;
7. reservation exhaustion before proposer execution;
8. verifier failure cleanup;
9. request cancellation with exact committed-prefix preservation; and
10. commit-authority and content-free evidence boundaries.

Additional contract tests reject multiple outstanding reservations, forged trace
state chains, unclosed traces, non-target commit authority, invalid transitions,
and hidden programming defects.

## Evidence boundary

Canonical adapter evidence contains only:

- contract, ABI, sequence, suite, and identity roots;
- check names and booleans;
- token counts and content digests;
- committed-state and trace roots;
- bounded operation ticks;
- stable fallback/fault classes; and
- authority-denial booleans.

It contains no prompt, raw token sequence, logits, hidden state, or KV tensors.
The report permanently states:

```text
activation_authority: false
adapter_execution_authority: false
real_runtime_qualified: false
```

## Engineer command

```bash
staqtapp-tds-eaglegate-adapter-lab
staqtapp-tds-eaglegate-adapter-lab --json
python -m staqtapp_tds.eaglegate.adapter --json
```

The JSON form is deterministic for an identical source/runtime. CI generates it
twice and requires byte-identical output.

## Cross-platform qualification

The focused workflow runs on:

- Ubuntu 24.04 with Python 3.10;
- Ubuntu 24.04 with Python 3.13;
- macOS 14 with Python 3.13; and
- Windows Server 2022 with Python 3.13.

Every lane compiles the Eaglegate package; runs the foundation, exactness,
adapter, workflow, and installation contracts together; checks deterministic
report bytes; rejects content-bearing fields; and requires that no real runtime
or activation authority is claimed. An aggregate job fails unless every lane
succeeds.

## Deliberately absent

This tranche does not implement or qualify:

- a real EAGLE model or proposer;
- vLLM, TensorRT-LLM, SGLang, or another production serving adapter;
- a production sampler or RNG stream;
- CUDA, ROCm, Metal, or other accelerator kernels;
- production KV allocation or mutation;
- live request interception;
- shadow, canary, promotion, rollback, or activation;
- cross-hardware numerical identity;
- performance, throughput, or latency improvement;
- learned routing, sentinels, random forests, agent pools, bandits, or training.

## Claim boundary

A passing report qualifies the TDS fake-runtime ABI, cleanup ordering, trace
integrity, exact target-only equivalence, and authority/evidence boundaries. It
does not qualify any named external runtime or model build.

## Next bounded tranche

The next step is a shadow-only adapter for one explicitly pinned real runtime.
It must execute the named runtime/model matrix while proving that unsupported
sampler, RNG, logits-processor, termination, KV, kernel, or deadline contracts
remain target-only. A metadata-only or non-executing fixture cannot satisfy
this gate. Actual acceleration remains unadmitted until the specific runtime
adapter, H100 hardware lane, and lossless differential corpus pass together.
