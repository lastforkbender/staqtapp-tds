# v3.8 Eaglegate vLLM EAGLE Shadow Integration

## Status and dependency

This tranche adds one explicitly named, non-executing integration fixture above
the Eaglegate runtime-adapter conformance ABI:

```text
runtime: vLLM
method:  EAGLE
mode:    metadata-only shadow translation
```

It is stacked on the lossless foundation, differential exactness laboratory,
and fake-runtime adapter conformance work. It must not merge ahead of those
layers. The installed TDS version is unchanged.

This code does not import vLLM, import PyTorch, load a model, start an engine,
contact a network, spawn a subprocess, execute inference, sample a token, mutate
KV state, or activate speculative decoding.

## Why vLLM is named now

A generic adapter contract proves TDS ordering and authority but does not prove
that an engineer can bind a real runtime's configuration vocabulary without
silently widening the contract. This fixture performs that narrower step.

The normalized metadata reflects vLLM's documented EAGLE configuration shape:

- speculative method `eagle`;
- one identified draft model artifact;
- an explicit `num_speculative_tokens`; and
- draft tensor parallel size one for the initial EAGLE profile.

The fixture stores content roots rather than a model name or path. It is informed
by public vLLM documentation but deliberately does not call the vLLM API.

Official references used when defining the fixture:

- https://docs.vllm.ai/en/stable/features/spec_decode/eagle/
- https://docs.vllm.ai/en/stable/features/spec_decode/

A change in vLLM documentation or implementation does not mutate this contract.
A different runtime/API behavior requires a new pinned metadata snapshot and
requalification.

## Permanent authority boundary

`VllmShadowAuthorityBoundary` requires:

```text
metadata_translation_only:       true
runtime_import_allowed:          false
model_loading_allowed:           false
inference_allowed:               false
network_io_allowed:              false
subprocess_allowed:              false
token_acceptance_authority:      false
target_rng_authority:            false
kv_commit_authority:             false
activation_authority:            false
configuration_mutation_allowed:  false
target_only_execution_required:  true
```

These values are not engineer settings. Attempting to widen any one of them is a
contract failure.

## Immutable capability snapshot

`VllmEagleCapabilitySnapshot` binds exact roots for:

- vLLM runtime version and build;
- engine API contract;
- Eaglegate foundation identity;
- differential exactness qualification;
- adapter-conformance qualification;
- shadow translator build;
- target model and tokenizer;
- EAGLE draft model;
- target verifier;
- target RNG ownership and consumption;
- sampler order;
- logits-processor order;
- termination behavior;
- KV allocator;
- numerical kernels;
- deadline behavior; and
- scheduler behavior.

It also binds bounded values for candidate tokens, target tensor parallelism,
batch, concurrency, context, KV pressure, workspace, and qualified sampler
classes.

The runtime version must be one exact Semantic Version. `latest`, ranges,
wildcards, and incomplete versions are rejected. The reference fixture uses a
synthetic version (`0.0.0-fixture.1`) so it cannot be mistaken for qualification
of a released vLLM build.

## Initial method scope

The first contract accepts only:

```text
runtime_name = "vllm"
method = "eagle"
draft_tensor_parallel_size = 1
fixture_only = true
```

`eagle3` is not silently treated as equivalent. It requires a separately pinned
contract and qualification because a new method name may imply different model,
runtime, scheduler, or verification behavior.

## Translation result

A complete compatible snapshot returns:

```text
compatible: true
serving_effect: shadow_metadata_only
runtime_invoked: false
model_invoked: false
inference_performed: false
real_runtime_qualified: false
```

Compatibility means only that supplied metadata can be translated into the
existing immutable Eaglegate adapter identity.

Any mismatch in snapshot identity, sampler class, candidate bound, or target
tensor parallelism returns:

```text
compatible: false
serving_effect: target_only
```

The fixture has no execution handoff and no activation endpoint.

## Engineer commands

Validate caller-supplied metadata:

```bash
staqtapp-tds-eaglegate-vllm-shadow \
  --snapshot vllm-capability.json \
  --requirement request-requirement.json \
  --json
```

Run the deterministic synthetic qualification fixture:

```bash
staqtapp-tds-eaglegate-vllm-shadow-lab --json
python -m staqtapp_tds.eaglegate.vllm_shadow_suite --json
```

## Ten-check reference suite

The reference fixture proves:

1. deterministic metadata translation;
2. stale/foreign snapshot rejection;
3. unsupported sampler rejection;
4. candidate-width rejection;
5. target tensor-parallel identity enforcement;
6. exact runtime-version enforcement;
7. EAGLE-only method scope;
8. draft tensor-parallel profile enforcement;
9. unknown-field rejection; and
10. non-widenable authority plus content-free evidence.

The reference snapshot binds the passing adapter-conformance report root. It
therefore cannot detach itself from the preceding fake-runtime qualification.

## Evidence boundary

Canonical reports contain roots, bounded configuration values, check names,
booleans, and stable fault reasons. They contain no prompt, raw token sequence,
logits, hidden state, or KV tensors.

Every report states:

```text
runtime_invoked: false
model_invoked: false
inference_performed: false
token_acceptance_authority: false
kv_commit_authority: false
activation_authority: false
real_runtime_qualified: false
```

## Cross-platform qualification

The focused workflow runs on Ubuntu/Python 3.10, Ubuntu/Python 3.13,
macOS/Python 3.13, and Windows/Python 3.13. Every lane:

- compiles the complete Eaglegate package;
- runs the foundation, exactness, adapter, shadow, workflow, and install tests;
- creates the synthetic report twice and requires byte-identical JSON;
- rejects authority widening and content-bearing fields; and
- parses the translator source to reject vLLM, PyTorch, network, or subprocess
  imports.

An aggregate job fails unless all lanes pass.

## Deliberately absent

This tranche does not implement or qualify:

- an installed vLLM package;
- any real vLLM version or build;
- real target or EAGLE model weights;
- a production sampler or RNG stream;
- CUDA, ROCm, or other accelerator kernels;
- production KV allocation or mutation;
- request interception;
- live shadow inference;
- canary, promotion, rollback, or activation;
- throughput, latency, acceptance-rate, or speedup claims;
- EAGLE-3;
- learned routing, sentinels, random forests, agent pools, bandits, or training.

## Claim boundary

A passing report qualifies only the TDS metadata translator, schema bounds,
identity binding, target-only failure behavior, and no-authority/no-content
evidence contract. It does not qualify vLLM itself or any model/hardware/runtime
combination.

## Next bounded tranche

The next step should be a runtime-neutral shadow SDK interface plus a captured,
offline capability export from one exact vLLM build. The capture process must be
separate from TDS serving, produce only immutable metadata, and still invoke no
model. Real shadow inference remains unadmitted until a named runtime build,
model pair, hardware lane, sampler/RNG contract, KV lifecycle, and lossless
differential corpus pass together.
