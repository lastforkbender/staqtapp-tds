# v3.8 Eaglegate Capture Witness Corroboration and Receipts

## Status and dependency

This tranche adapts the strongest witness and append-only evidence concepts onto
the canonical Eaglegate stack:

```text
lossless foundation
  -> differential exactness laboratory
  -> fake-runtime adapter conformance
  -> EAGLE-only vLLM shadow metadata
  -> runtime-neutral offline capture
  -> mechanical witness corroboration and receipts
```

It is stacked on the offline capability capture branch. It must not merge ahead
of that branch or any lower Frontier Fabric dependency. The installed TDS version
remains unchanged.

This tranche does not import vLLM or another runtime, connect to a service, load
a model, submit a request, execute inference, accept tokens, mutate KV state,
verify a cryptographic signature, prove witness independence, claim metadata
truth, or activate speculative decoding.

## Narrow claim

The contract records **mechanical corroboration of supplied immutable
artifacts**.

It keeps these facts separate:

```text
exact field match
cryptographic signature validity
signer authorization
witness independence
metadata truth
runtime qualification
lossless production execution
activation authority
```

Only the first fact is implemented here. Every other fact remains explicitly
false in canonical evidence.

## Authority boundary

`CaptureAttestationAuthorityBoundary` permanently denies:

- runtime import;
- network connection;
- request or prompt submission;
- model loading;
- KV allocation;
- token generation, verification, or commit;
- cryptographic signature verification;
- witness-independence claims;
- metadata-truth claims; and
- activation authority.

It may only compare supplied content-free artifacts and record mechanical
corroboration. Target-only remains the execution default.

## Read-only status snapshot

`CaptureReadOnlyStatusSnapshot` is a supplied artifact. TDS does not fetch it
from a live service.

It binds exact:

- provider identity;
- offline capture root;
- provider-snapshot payload root;
- Eaglegate adapter identity root;
- runtime-distribution root;
- package-metadata root;
- source-commit root;
- environment root;
- service-instance root;
- status-exporter root; and
- monotonic snapshot generation.

The snapshot must declare:

```text
read_only_export = true
metadata_only = true
model_loaded = false
inference_performed = false
```

Unknown fields and widened activity fail closed.

## Witness observation

A witness performs exact field-by-field comparison between:

- one validated `OfflineCapabilityCaptureEnvelope` and capture decision; and
- one `CaptureReadOnlyStatusSnapshot`.

The observation records only:

- witness identity;
- witness-tool root;
- capture, provider-payload, adapter, and status roots;
- a match boolean; and
- sorted mismatch field names.

It records no prompts, token sequences, logits, hidden states, KV tensors, key
material, executable commands, or model paths.

The engineer command creates one observation only:

```bash
staqtapp-tds-eaglegate-capture-witness \
  --bundle offline-capability-capture.json \
  --status read-only-status.json \
  --witness-id witness-a \
  --witness-tool-root sha256:<tool-root> \
  --json
```

Even a matching result states:

```text
serving_effect: target_only
single_witness_only: true
quorum_satisfied: false
activation_authority: false
real_runtime_qualified: false
```

## Distinct-identity quorum

`CaptureAttestationBundle` initially requires at least two observations with:

- distinct witness IDs;
- distinct witness-tool roots;
- one capture root;
- one provider-payload root;
- one adapter identity root; and
- canonical observation-root ordering.

Duplicate identities or tools cannot inflate quorum. Mixed capture, payload, or
adapter roots fail closed.

An all-match bundle is labeled `CORROBORATED`. Any mismatch is labeled
`TARGET_ONLY`.

`CORROBORATED` does not mean signed, independently witnessed, truthful,
runtime-qualified, or executable.

## Append-only Frontier Fabric receipts

Corroborated evidence progresses:

```text
RECEIVED -> CORROBORATED -> RECORDED -> RETIRED
```

Mismatch progresses:

```text
RECEIVED -> QUARANTINED
```

Every non-initial receipt binds its exact predecessor root. Sequence, capture,
provider-payload, adapter, and attestation identities must remain unchanged.
`RETIRED` and `QUARANTINED` are terminal.

These receipts are evidence-plane facts. They do not become model, storage,
policy, or activation authority.

## Ten-check qualification catalog

The canonical suite proves:

1. two-witness mechanical corroboration and recorded history;
2. exact mismatch causing target-only quarantine;
3. single-witness rejection;
4. duplicate witness-identity rejection;
5. duplicate witness-tool rejection;
6. mixed capture-root rejection;
7. mixed adapter-root rejection;
8. forged predecessor-root rejection;
9. terminal quarantine; and
10. content, cryptographic-claim, independence-claim, truth-claim, runtime, and
    activation boundaries.

Run it with:

```bash
staqtapp-tds-eaglegate-capture-witness-lab --json
python -m staqtapp_tds.eaglegate.capture_attestation_suite --json
```

## Cross-platform qualification

The dedicated workflow runs on Ubuntu/Python 3.10, Ubuntu/Python 3.13,
macOS/Python 3.13, and Windows/Python 3.13. Every lane:

- compiles the complete Eaglegate package;
- runs the accumulated foundation, exactness, adapter, vLLM-shadow, capture,
  witness, workflow, and installation contracts;
- creates the canonical report twice and requires byte identity;
- rejects execution, content, cryptographic, truth, independence, runtime, and
  activation claims; and
- parses the attestation source to reject runtime, network, subprocess, and
  cryptographic-library imports.

An aggregate gate fails unless all lanes pass.

## Deliberately absent

This tranche contains no:

- live service fetch or attachment;
- vLLM, PyTorch, network, subprocess, or cryptographic dependency;
- real witness-independence proof;
- cryptographic signature verification;
- signer authorization, key lifecycle, rotation, or revocation;
- metadata-truth claim;
- real runtime, model, sampler, RNG, KV, kernel, scheduler, hardware, or
  performance qualification;
- live shadow inference;
- canary, promotion, rollback, or activation;
- EAGLE-3;
- learned routing, sentinels, random forests, C-driven agent pools, bandits,
  online training, or self-promotion.

## Claim boundary

A passing report proves exact comparison of supplied artifacts, bounded
distinct-identity quorum mechanics, and tamper-evident append-only receipt
history. It does not prove artifact provenance, cryptographic authenticity,
witness independence, metadata truth, runtime compatibility, model correctness,
hardware identity, or lossless production execution.

## Next bounded decision

The next tranche should not casually add cryptography. A signature-verification
proposal should begin only after selecting a reviewed library and defining:

- canonical signed bytes;
- signer authorization;
- key generation and custody;
- rotation and revocation;
- offline verification;
- algorithm agility; and
- failure and rollback behavior.

Signature validity, signer authority, witness independence, metadata truth,
runtime qualification, and activation must remain separate immutable facts.
