# v3.8 Eaglegate Shadow Attestation

## Status

This tranche adds off-path witness corroboration and append-only observation
receipts above the remotely qualified Eaglegate shadow metadata SDK.

It compares supplied immutable vLLM EAGLE metadata with supplied read-only status
exports. It does not import a runtime, connect to a service, submit a request,
load a model, allocate KV state, generate or verify tokens, or activate
speculative decoding.

## Deliberately narrow terminology

This implementation records **mechanical corroboration**. It does not claim:

- that a witness is operationally independent merely because its identity is
  distinct;
- that a metadata source is truthful;
- that a cryptographic signature has been verified;
- that a running runtime is qualified; or
- that speculative execution is permitted.

Those denials are present in every authority, witness, bundle, receipt, and
qualification report.

## Authority boundary

`EaglegateAttestationAuthorityBoundary` permanently requires:

```text
may_import_runtime: false
may_connect_network: false
may_submit_request: false
may_load_model: false
may_allocate_kv: false
may_generate_tokens: false
may_verify_tokens: false
may_commit_tokens: false
may_activate: false
may_verify_cryptographic_signature: false
may_claim_witness_independence: false
may_claim_metadata_truth: false
may_record_mechanical_corroboration: true
target_only_default: true
```

The authority record is immutable and domain-separated into a canonical root.

## Read-only status snapshot

`VLLMReadOnlyStatusSnapshot` represents a supplied exporter artifact. TDS does
not fetch it. The schema includes exact runtime, model, tokenizer, EAGLE method,
proposer, verifier, RNG, sampler ordering, logits-processor ordering,
termination, KV allocator, numerical kernel, deadline, speculative depth,
tensor-parallel sizes, model-length, parallel-drafting, and rejection-method
fields.

The snapshot also binds:

- service-instance root;
- status-exporter root;
- deterministic snapshot generation; and
- `read_only_export: true`.

Raw model paths, prompts, tokens, logits, hidden states, KV tensors, network
locations, credentials, and commands are not fields.

## Witness observation

One witness compares every comparable metadata field with one supplied status
snapshot. The result contains:

- witness identity;
- witness-tool root;
- metadata root;
- shadow-report root;
- status-snapshot root;
- exact match boolean; and
- sorted mismatch field names.

One witness can never satisfy the bundle quorum.

## Mechanical quorum

`CapabilityAttestationBundle` requires at least two observations with:

- distinct witness IDs;
- distinct witness-tool roots;
- one metadata root;
- one shadow-report root; and
- canonical observation-root ordering.

A duplicate witness or tool cannot inflate the quorum. Mixed metadata or shadow
roots fail closed.

When every observation matches, the bundle decision is `CORROBORATED`. Any
mismatch yields `TARGET_ONLY`.

Even a corroborated bundle permanently states:

```text
cryptographic_signature_verified: false
witness_independence_proven: false
metadata_truth_claimed: false
real_runtime_qualified: false
activation_authority: false
```

## Append-only observation receipts

One observation history begins at:

```text
RECEIVED
```

A matching bundle may progress:

```text
RECEIVED -> CORROBORATED -> RECORDED -> RETIRED
```

A mismatching bundle progresses:

```text
RECEIVED -> QUARANTINED
```

`RETIRED` and `QUARANTINED` are terminal. Every non-initial receipt binds the
previous receipt root. Sequence, metadata, shadow, and attestation identities
must remain exact throughout the chain.

Receipt history has no activation or production-execution authority.

## Engineer command

Run the deterministic qualification suite:

```bash
staqtapp-tds-eaglegate-attest reference --json
```

Compare two supplied files without network or runtime access:

```bash
staqtapp-tds-eaglegate-attest compare \
  --metadata ./vllm-eagle-metadata.json \
  --status ./vllm-read-only-status.json \
  --shadow-root sha256:<shadow-report-root> \
  --witness-id witness-a \
  --witness-tool-root sha256:<tool-root> \
  --json
```

Equivalent module execution:

```bash
python -m staqtapp_tds.eaglegate.attestation ...
```

A matching comparison returns one observation only. It does not build a quorum
or qualify a runtime.

## Qualification catalog

The ten canonical checks cover:

1. two distinct matching witnesses and a recorded receipt chain;
2. exact mismatch causing target-only quarantine;
3. single-witness rejection;
4. duplicate witness rejection;
5. duplicate witness-tool rejection;
6. mixed metadata-root rejection;
7. mixed shadow-report-root rejection;
8. forged predecessor-root rejection;
9. terminal quarantine; and
10. content, cryptographic-claim, independence-claim, truth-claim, and authority
   boundaries.

Additional tests cover strict status schema, deterministic roots, every-field
comparison, append-only identity preservation, retirement terminality, CLI
replay, no network/runtime/crypto dependency path, and absence of content or key
material.

## Cross-platform gates

The focused workflow runs on:

- Ubuntu 24.04 with Python 3.10;
- Ubuntu 24.04 with Python 3.13;
- macOS 14 with Python 3.13; and
- Windows Server 2022 with Python 3.13.

Every lane compiles the Eaglegate package and runs the complete foundation,
exactness, adapter, shadow, attestation, workflow, and installation contract
chain. It generates the reference report twice, requires byte identity, and
fails if any runtime, network, request, model, token, cryptographic, witness,
truth, production-qualification, content, or activation claim is widened.

## Deliberately absent

This tranche contains no:

- network client or socket;
- live runtime discovery;
- vLLM import;
- server attachment;
- request or prompt submission;
- model, tokenizer, or speculator loading;
- sampler or RNG execution;
- token verification or commit;
- KV allocation or mutation;
- cryptographic signature implementation;
- public or private key material;
- assertion of real witness independence;
- live request shadowing;
- canary, promotion, rollback, or activation;
- performance or speedup claim;
- learned router, sentinel, forest, agent pool, bandit, or online training.

## Claim boundary

A passing attestation report proves only that supplied artifacts were compared
exactly, mechanically corroborated under a bounded distinct-identity quorum,
and recorded in a tamper-evident append-only receipt chain. It does not prove
artifact provenance, witness independence, cryptographic authenticity, runtime
compatibility, model correctness, hardware identity, or lossless production
execution.

## Next bounded tranche

The next step should be a cryptographically explicit artifact-verification
contract, implemented only after selecting a reviewed signature library and key
lifecycle. Signature validity, signer authorization, witness independence, and
runtime qualification must remain separate facts. Until then, all corroborated
metadata remains observation-only and target-only for execution.
