# v3.8 Eaglegate ServingEpoch Generation Authority

## Decision

Eaglegate has no independent durable publication mechanism. The generic v3.7
`AtomicGenerationStore` owns immutable materialization, publication head-root
CAS, `CURRENT`, recovery, rollback, reader pins, and retirement for every
ServingEpoch.

Local `eaglegate.toml` and `eaglegate.lock` files are bounded human intent and
capability inputs. `EaglegateEpochReceipt` values are content-free evidence
inside a generation payload. None grants serving authority.

## Composite binding

`EaglegateServingEpochBinding` binds all of the following into one immutable
Generation Authority manifest:

| Binding | Meaning |
|---|---|
| `storage_generation_root` | Exact immutable storage/data dependency |
| `eaglegate_policy_root` | Policy plus ordered plan definitions |
| `target_runtime_identity_root` | Target, tokenizer, proposer, runtime, sampler, logits, KV, kernel, numerical, and tenant identity |
| `exactness_qualification_root` | Candidate-bound bridge over fixed core evidence |
| `qualification_summary_root` | Derived identity/plan qualification summary |
| `exactness_report_root` | Fixed differential exactness report |
| `adapter_conformance_root` | Fixed fake-runtime ABI report |
| `receipt_chain_root` | Generated content-free candidate receipt sequence |

The bridge explicitly records `real_runtime_qualified: false`. Phase 4 real
runtime evidence publishes a distinct content-free qualification artifact; it
cannot relabel the reference suite.

## Publication and reading

`build_eaglegate_serving_candidate()` verifies that the source is a published
generation, derives qualification from the fixed reports, checks the
Eaglegate predecessor against the generic authority parent, and builds a
non-authoritative JSON payload set. `publish_eaglegate_serving_candidate()`
delegates to `AtomicGenerationStore.publish(..., expected_head_root=...)`.

`open_eaglegate_serving_generation()` pins and verifies the ServingEpoch, then
pins its storage generation. Mixed roots, report substitution, retired storage,
and broken receipt or parent lineage fail before a ServingEpoch is returned.

## Authority boundary

Only `target_only` and `shadow` candidates are accepted. CANARY and ACTIVE are
reserved schema values and are rejected by configuration and the canonical
publisher. There is no production token/KV commit, traffic admission,
promotion, activation, or online mutation path in this tranche.
