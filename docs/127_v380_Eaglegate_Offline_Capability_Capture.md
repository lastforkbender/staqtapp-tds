# v3.8 Eaglegate Offline Capability Capture

## Status

This tranche adds a runtime-neutral importer for capability metadata produced
outside the TDS serving process. It is stacked on the named, non-executing vLLM
EAGLE shadow fixture.

TDS still does not import a serving runtime, load a model, execute inference,
accept tokens, mutate KV state, contact a network, spawn a subprocess, or
activate speculative decoding.

## Purpose

A named metadata fixture proves that TDS can represent one runtime vocabulary.
The next operational requirement is a reproducible handoff format so software
engineers can capture exact package/build metadata in an isolated environment
and validate it in TDS without giving TDS runtime authority.

The capture format therefore separates:

```text
external capture producer
        ↓ immutable metadata bundle
TDS offline importer
        ↓ validated provider snapshot
Eaglegate shadow metadata only
```

No live serving process participates in this handoff.

## Authority boundary

`OfflineCaptureAuthorityBoundary` permanently requires metadata import only and
forbids TDS runtime imports, model loading, inference, network access,
subprocesses, token acceptance, RNG authority, KV commit, activation, and raw
model-content persistence.

An envelope also attests:

```text
metadata_only = true
model_loaded = false
inference_performed = false
network_used = false
subprocess_used = false
```

Any widened declaration is rejected before provider translation.

## Immutable envelope

`OfflineCapabilityCaptureEnvelope` binds:

- provider identity;
- monotonic capture sequence;
- capture-tool identity;
- runtime distribution identity;
- package metadata identity;
- source commit identity;
- capture environment identity;
- adapter-conformance qualification;
- exact provider-snapshot payload root; and
- optional predecessor capture root.

The payload root is recomputed by TDS. Any change to provider metadata invalidates
the envelope and returns target-only behavior.

## Provider registry

The first registered provider is:

```text
vllm-eagle-v1
```

The importer dispatch is explicit and closed. Unknown providers are not loaded
dynamically and cannot select Python code. They return target-only.

The registered vLLM translator remains the metadata-only fixture from the prior
tranche. Its adapter-conformance root must equal the envelope root. A provider
snapshot cannot detach itself from the qualified fake-runtime ABI.

## Content boundary

Capture payloads are recursively rejected if they contain fields for prompts,
raw token sequences, logits, hidden states, or KV tensors. The importer publishes
only roots, bounded metadata, stable fault classes, and authority booleans.

## Engineer commands

Validate an external bundle:

```bash
staqtapp-tds-eaglegate-capture \
  --bundle offline-capability-capture.json \
  --json
```

Run the synthetic importer qualification:

```bash
staqtapp-tds-eaglegate-capture-lab --json
python -m staqtapp_tds.eaglegate.offline_capture_suite --json
```

## Ten-check qualification catalog

1. valid metadata capture;
2. canonical envelope roundtrip;
3. payload tamper detection;
4. unsupported-provider rejection;
5. adapter-conformance binding;
6. malformed-provider-snapshot rejection;
7. private-content rejection;
8. unknown-field rejection;
9. forbidden-activity rejection; and
10. non-widenable authority and content-free evidence.

## Deliberately absent

This tranche does not implement the external vLLM capture producer. It does not
qualify a real vLLM build, model, sampler, RNG stream, kernel, KV allocator,
scheduler, or hardware platform. It does not perform live shadow inference or
create canary, promotion, rollback, or activation authority.

## Claim boundary

A passing report qualifies the TDS bundle schema, payload-root validation,
provider dispatch, adapter binding, target-only failure behavior, and
no-authority/no-content boundary. It does not prove that externally supplied
metadata is truthful; provenance and signature verification require a later
qualified producer and trust policy.

## Next bounded tranche

The next step should define a separate capture-producer protocol and signed
attestation policy. That producer may inspect one exact installed runtime in an
isolated process but must not load model weights or execute inference. Until the
producer, trust roots, exact vLLM build, hardware lane, model pair, and lossless
differential corpus all pass, real EAGLE execution remains unadmitted.
