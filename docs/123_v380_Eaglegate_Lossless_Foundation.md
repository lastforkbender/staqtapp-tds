# v3.8 Eaglegate lossless foundation

## Status and dependency

This contract-first, non-activating Eaglegate core is built on the completed
v3.6 Foundation and v3.7 Atomic Generation Authority commits in the canonical
Phase 1–4 convergence branch. It does not activate speculative decoding or
claim GPU acceleration. Package publication remains separate from source
candidate completion.

## Governing rule

```text
EAGLE proposes.
Eaglegate admits.
The target verifies and samples.
The target runtime commits tokens and KV state.
```

Eaglegate is a deterministic control and evidence plane. It is not a draft
model, target model, sampler, token verifier, KV owner, or semantic authority.
An Eaglegate fault may disable acceleration; it may not weaken target-model
correctness or make an otherwise valid target-only request fail.

## Lossless constitution

The machine-checkable authority contract permanently requires:

- target verification for every speculative candidate;
- target sampler ownership of token acceptance;
- target runtime ownership of committed tokens and KV state;
- target-only fallback when qualification, identity, health, or resources fail;
- exact epoch, model, tokenizer, runtime, sampler, logits-processor, KV, kernel,
  numerical-mode, and tenant identity binding;
- no approximate, semantic-similarity, or unverified-cache acceptance;
- no proposer token or KV commit authority;
- no mixed-epoch execution or online mutation of active policy; and
- no persistence of prompt content, logits, or KV tensors in episode evidence.

These rules are values in `EaglegateAuthorityBoundary`, not editable console
settings.

## Implemented surface

### Immutable contracts

The `staqtapp_tds.eaglegate.contract`, `plans`, and `admission` modules define
frozen, bounded, canonical records for:

- `EaglegateIdentity`;
- `EaglegatePlan`;
- `EaglegateAdmissionPolicy`;
- `EaglegateQualificationSummary`;
- `EaglegateSpeculationEpoch`;
- `EaglegateRequestClass`;
- `EaglegateRuntimeHealth`; and
- `EaglegateDecision`.

Every durable identity uses domain-separated canonical JSON and SHA-256 roots.
Unknown proposer families, malformed identities, duplicate plans, unsupported
selection contracts, and out-of-range resource values fail closed.

### Deterministic admission

`evaluate_admission()` returns only one of:

```text
ADMIT(plan_id)
FALLBACK(target_only, reason)
ABSTAIN(shadow_only)
FAULT(fault_code)
```

The initial selector is deliberately simple and auditable: it evaluates plans
in immutable policy order and chooses the first qualified plan that fits the
request and runtime resource envelope. There is no learned router, random
forest, sentinel process, agent pool, online training, or self-promotion.

Admission never accepts tokens and never modifies model or KV state.

### Qualification binding

`EaglegateQualificationSummary` binds exactness evidence to one immutable
identity and one ordered plan catalog. Qualification is complete only when the
required greedy, lossless-sampling, KV-lifecycle, and failure-containment lanes
all pass with non-zero case counts.

The differential exactness and fake-runtime adapter suites now produce fixed,
content-free core reports. `EaglegateQualificationBridge` binds those exact
report roots to one concrete target/runtime identity, ordered plan catalog, and
Eaglegate epoch. The bridge records `real_runtime_qualified: false`; it cannot
be used to imply that a named accelerator runtime passed.

### Content-free evidence

`staqtapp_tds.eaglegate.evidence` provides bounded receipt values:

- bounded episode receipts containing counts, timings, resource accounting,
  fallback reasons, and fault classes; and
- epoch-state receipts with predecessor-root validation.

Episode receipts reject declarations that prompt content, logits, or KV tensors
were persisted.

For a Generation Authority candidate, the implemented lifecycle is:

```text
DRAFT -> QUALIFIED -> STAGED -> SHADOW
```

The wider schema reserves later states, but the v3.8 publisher rejects CANARY
and ACTIVE. Receipts are persisted only as an immutable content-free payload in
the generic Generation Authority; they do not own a receipt log or a second
`CURRENT`. Invalid jumps, cross-epoch chains, free-text persisted reasons, and
qualification replacement inside one epoch are rejected.

### One durable ServingEpoch authority

`staqtapp_tds.eaglegate.generation` publishes one composite ServingEpoch only
through `AtomicGenerationStore`. Its domain-separated binding covers the
storage generation, policy plus ordered plan definitions, complete
target/runtime identity, candidate-bound qualification bridge, exactness and
adapter report roots, and content-free receipt chain.

The generic authority `generation_root` and publication head root are the only
durable identity and CAS lineage. Opening a ServingEpoch pins both the serving
generation and its storage dependency; a retired or unavailable dependency
fails closed before a ServingEpoch is returned.

### Configuration compiler and lock

The local project files are:

```text
eaglegate.toml   human-reviewed intent
eaglegate.lock   generated runtime/capability identity
```

Initialization writes an unresolved lock and therefore remains target-only.
Compilation fails closed until a capability snapshot resolves exact target,
tokenizer, proposer, runtime, sampler, logits-processor, KV, numerical-mode,
tenant, and resource limits.

Requested plans may narrow but never exceed the resolved capability envelope.
Configuration and lock publication use temporary-file write, file `fsync`,
atomic replacement, and best-effort directory `fsync`. Reads are bounded to a
regular control file. These local files express candidate intent only and never
create serving state.

The first profiles are:

- `observe`: target-only baseline and control-plane observation;
- `conservative`: one small plan in shadow mode; and
- `balanced`: two bounded plans in shadow mode.

There is intentionally no aggressive profile.

## Embedded engineer console

TDS installs:

```bash
staqtapp-tds-eaglegate
```

The same console is available as:

```bash
python -m staqtapp_tds.eaglegate
```

Initial commands:

```bash
staqtapp-tds-eaglegate constitution
staqtapp-tds-eaglegate init --directory ./eaglegate --profile conservative
staqtapp-tds-eaglegate resolve --directory ./eaglegate --snapshot capabilities.json
staqtapp-tds-eaglegate status --directory ./eaglegate
staqtapp-tds-eaglegate validate --directory ./eaglegate
staqtapp-tds-eaglegate diff --left ./candidate-a --right ./candidate-b
staqtapp-tds-eaglegate evaluate \
  --directory ./eaglegate \
  --request request-class.json \
  --health runtime-health.json
```

All commands emit deterministic JSON. `evaluate` is simulation-only. A resolved
local lock reports `candidate_mode: shadow` while `serving_effect` remains
`target_only`; only a separately verified Generation Authority publication can
represent a shadow head. The console has no publish, canary, promotion, or
activation endpoint and reports `activation_authority: false`.

## Deliberately absent

This slice does **not** add:

- an EAGLE model adapter or proposer execution;
- target-runtime integration;
- token verification or sampling code;
- committed-token or KV-cache mutation;
- CUDA, ROCm, Metal, or other accelerator kernels;
- production traffic admission;
- canary, promote, activation, or production rollback executors;
- raw prompt, output-token, logits, hidden-state, or KV persistence;
- learned sentinels, a C-driven agent pool, random forests, bandits, or online
  learning; or
- any Browser or console activation authority.

## Qualification in this slice

The focused tests cover:

- immutable and non-widenable lossless authority;
- canonical identity, plan, policy, qualification, and epoch roots;
- plan/resource bounds and hard publisher rejection of canary/active modes;
- deterministic shadow, target-only, canary, health, resource, and identity
  decisions;
- exact qualification binding;
- receipt transitions embedded without a parallel publication authority;
- rejection of private-content evidence;
- unresolved-lock failure and capability-bound compilation;
- epoch diff and requalification requirements; and
- console initialization, validation, capability resolution, and simulation
  without activation authority;
- composite ServingEpoch publication through head-root CAS;
- storage-dependency and ServingEpoch reader pinning; and
- stale writer, rollback, retirement, report-substitution, and mixed-binding
  rejection without a second Eaglegate `CURRENT`.

## Phase-4 successor

The explicitly pinned, qualification-only vLLM EAGLE shadow adapter is now
implemented in `staqtapp_tds.eaglegate.vllm_shadow`. It executes a named
runtime/model matrix, retains target-only fallback, persists no
prompts/logits/KV, and keeps manual real-hardware qualification distinct from
the fixed local reference-suite results.
