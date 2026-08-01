# v3.8 Eaglegate Shadow Adapter SDK

## Status

This tranche adds one named, non-executing integration fixture above the remotely
qualified Eaglegate adapter-conformance ABI:

```text
vllm-eagle-metadata-v1
```

It consumes explicit capability metadata supplied by an engineer or an off-path
qualification process. It does not import vLLM, discover a live server, load a
model, allocate KV state, generate or verify tokens, render an executable
command, or activate speculative decoding.

## Why vLLM metadata is represented

The official vLLM speculative-decoding documentation describes EAGLE and EAGLE-3
as model-based speculative methods. Its configuration examples use fields such
as `method`, `model`, `num_speculative_tokens`, and
`draft_tensor_parallel_size`; current general documentation also exposes
`max_model_len`, `parallel_drafting`, and `rejection_sample_method`.

References reviewed for this fixture:

- https://docs.vllm.ai/en/stable/features/speculative_decoding/
- https://docs.vllm.ai/en/stable/features/speculative_decoding/eagle/

Those pages are external documentation, not TDS authority. The fixture pins an
exact runtime version, a capability-source root, and a metadata-attestation root.
It never infers production compatibility merely because a field appears in
external documentation.

## Governing authority

`EaglegateShadowAuthorityBoundary` permanently requires:

```text
may_import_runtime: false
may_start_server: false
may_load_model: false
may_allocate_kv: false
may_generate_tokens: false
may_verify_tokens: false
may_commit_tokens: false
may_emit_executable_command: false
may_activate: false
target_only_default: true
```

Only a content-free preview may be rendered. The authority record is immutable
and domain-separated into its own canonical root.

## Strict metadata schema

The v1 fixture accepts only:

- runtime name `vllm`;
- exact normalized runtime version;
- method `eagle` or `eagle3`;
- target-model, tokenizer, and draft-model SHA-256 roots;
- foundation, adapter-build, target-verifier, RNG, sampler-order,
  logits-processor-order, termination, KV-allocator, numerical-kernel, and
  deadline roots;
- capability-source and metadata-attestation roots;
- bounded speculative token count;
- bounded target and draft tensor-parallel sizes;
- bounded maximum model length;
- `parallel_drafting` boolean; and
- known rejection-sample method metadata.

Unknown fields fail closed. Raw model identifiers, repository names, paths,
commands, prompts, token sequences, logits, hidden states, and KV tensors are not
schema fields.

## Shadow decisions

The SDK can produce only:

```text
OBSERVE
TARGET_ONLY
```

`OBSERVE` means that structurally complete metadata was compiled into immutable
roots for off-path inspection. It does not mean that a real runtime is qualified
or that speculative execution is permitted.

The v1 fixture returns `TARGET_ONLY` when:

- rejection metadata requests synthetic acceptance; or
- parallel drafting is enabled without a separate qualification contract.

No decision can become `ADMIT`, `EXECUTE`, `CANARY`, `ACTIVE`, or `PROMOTE`.

## Immutable output

Compilation produces:

- a vLLM metadata root;
- an Eaglegate adapter-identity root;
- a content-free shadow-preview root;
- exactness and adapter-conformance evidence bindings; and
- a canonical shadow-report root.

Every report states:

```text
runtime_imported: false
server_started: false
model_loaded: false
kv_allocated: false
tokens_generated: false
tokens_verified: false
tokens_committed: false
executable_command_emitted: false
activation_authority: false
production_execution_authority: false
real_runtime_qualified: false
```

The metadata-attestation root is pinned but not trusted by construction. A later
qualification controller must independently verify its provenance before a real
runtime can be considered.

## Engineer command

```bash
staqtapp-tds-eaglegate-shadow schema --json

staqtapp-tds-eaglegate-shadow inspect \
  --metadata ./vllm-eagle-metadata.json \
  --exactness-root sha256:<qualified-exactness-root> \
  --adapter-root sha256:<qualified-adapter-report-root> \
  --json
```

Equivalent module execution:

```bash
python -m staqtapp_tds.eaglegate.shadow schema --json
python -m staqtapp_tds.eaglegate.shadow inspect ...
```

The command emits no vLLM invocation and no shell command preview.

## Qualification

The focused tests cover:

- immutable non-widenable shadow authority;
- deterministic metadata and adapter identity roots;
- EAGLE and EAGLE-3 structural observation;
- target-only treatment of synthetic acceptance and unqualified parallel
  drafting;
- strict unknown/missing-field rejection;
- runtime, method, version, and numeric bounds;
- root-only model identity;
- qualification-root rebinding;
- deterministic CLI output;
- source inspection prohibiting vLLM imports and process execution; and
- content-free, non-activating evidence.

The cross-platform workflow runs the complete foundation, exactness, adapter,
and shadow contract chain on Ubuntu/Python 3.10, Ubuntu/Python 3.13,
macOS/Python 3.13, and Windows/Python 3.13. It compiles the package, generates
the same shadow report twice, requires byte identity, and rejects any execution,
content, production-qualification, or activation field.

## Deliberately absent

This tranche contains no:

- vLLM package import;
- live vLLM capability discovery;
- server startup or process attachment;
- real model identifier or path handling;
- model, tokenizer, or speculator loading;
- sampler or RNG execution;
- token verification or commit;
- KV allocation or mutation;
- CUDA, ROCm, Metal, or accelerator integration;
- live request shadowing;
- canary, promotion, rollback, or activation;
- performance or speedup claim;
- learned routing, sentinels, forests, agents, bandits, or online training.

## Claim boundary

A passing shadow report proves that supplied metadata was parsed strictly,
bound into immutable Eaglegate identities, rendered without content or command
execution, and kept outside runtime authority. It does not prove that the
metadata is truthful, that a named vLLM build is compatible, or that any model,
hardware, sampler, RNG, kernel, or KV implementation is lossless.

## Next bounded tranche

The next tranche should add an off-path capability-attestation verifier and a
shadow observation receipt. It may verify signed or independently reproduced
metadata and compare declared identities against a running service's exported
read-only status snapshot. It must still be unable to load a model, submit a
prompt, allocate KV state, intercept live requests, or activate speculation.
Only after that evidence plane passes should a specific runtime/hardware
qualification corpus be designed.
