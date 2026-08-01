# v3.8 Eaglegate Isolated Capability Capture Producer

## Status and dependency

This tranche adds a bounded producer for the runtime-neutral offline capability
capture bundle. It is stacked on the mechanically corroborated capture and
append-only receipt branch.

The producer may inspect an installed Python distribution's metadata and hash
bounded package files. It does not import the provider runtime, load model
artifacts, probe an accelerator, use the network, spawn a subprocess, execute
dynamic code, execute inference, accept tokens, mutate KV state, verify source
provenance, or activate Eaglegate.

The installed TDS version remains unchanged.

## Architecture

```text
isolated engineer process
  -> inspect importlib distribution metadata
  -> hash bounded installed package files
  -> bind exact EAGLE provider snapshot
  -> construct offline capture envelope
  -> revalidate through canonical offline importer
  -> emit content-free bundle and evidence
```

The command is intended for an isolated engineering environment, not the model
serving process.

## Permanent authority boundary

`CaptureProducerAuthorityBoundary` allows only:

- distribution metadata inspection; and
- bounded hashing of ordinary installed package files.

It permanently denies:

- provider runtime import;
- model loading or model-artifact reads;
- accelerator probing;
- network access;
- subprocesses;
- dynamic code execution;
- inference;
- token acceptance;
- KV commit;
- source-commit verification; and
- activation.

Target-only remains required outside metadata preparation.

## Initial producer profile

The first profile is deliberately narrow:

```text
profile:      vllm-wheel-metadata-only-v1
provider:     vllm-eagle-v1
distribution: vllm
method scope: EAGLE only, inherited from the provider snapshot
```

The producer requires the exact installed distribution version to equal the
pinned `VllmEagleCapabilitySnapshot.runtime_version`. `latest`, version ranges,
and a merely compatible version are insufficient.

No vLLM module is imported. Inspection uses Python's standard
`importlib.metadata` distribution interface.

## Distribution identity

The producer requires and hashes:

- `METADATA`;
- `WHEEL`;
- `RECORD`; and
- every qualified regular file exposed by the installed distribution manifest.

Every file identity contains a canonical relative path, exact byte size, and
SHA-256 digest. File paths and records are sorted before the manifest root is
computed.

The initial limits are bounded and configurable only by constructing a narrower
`CaptureProducerLimits` value:

```text
max_files:          200,000
max_file_bytes:     512 MiB
max_total_bytes:    8 GiB
max_metadata_bytes: 16 MiB per required metadata file
```

Duplicate paths, missing files, non-regular files, symlinks, traversal outside
the distribution root, and mutation during hashing fail closed.

## Model-artifact boundary

The initial producer rejects common model-weight formats, including:

```text
.bin .ckpt .gguf .onnx .ot .pt .pth .safetensors .tflite
```

The producer qualifies package/runtime bytes only. It does not hash target or
EAGLE model weights in this tranche.

## Environment identity

The capture binds a content root over ordinary host facts available without
hardware probing:

- Python implementation and exact version;
- Python cache tag;
- operating system and release;
- machine architecture;
- pointer width; and
- byte order.

It explicitly records that no accelerator probe, network operation, or
subprocess occurred.

GPU identity remains outside this tranche.

## Source-commit boundary

The engineer supplies a `source_commit_root` reference. The producer binds that
root but explicitly records:

```text
source_commit_verified: false
```

A later provenance policy may verify source relationships. This producer does
not claim that the supplied root truthfully describes the installed wheel.

## Producer result

A successful result binds:

- producer profile root;
- producer-tool source root;
- environment root;
- installed-distribution root;
- package-metadata root;
- file-manifest root;
- offline capture root; and
- canonical offline-import decision root.

The produced bundle is immediately replayed through
`validate_offline_capability_capture()`. A bundle that cannot pass the canonical
importer is not emitted as success.

## Engineer commands

Produce a bundle from an exact installed vLLM distribution:

```bash
staqtapp-tds-eaglegate-capture-produce \
  --provider-snapshot vllm-eagle-capability.json \
  --source-commit-root sha256:<source-reference> \
  --capture-sequence 1 \
  --output offline-capability-capture.json \
  --json
```

Run the deterministic synthetic qualification:

```bash
staqtapp-tds-eaglegate-capture-producer-lab --json
python -m staqtapp_tds.eaglegate.capture_producer_suite --json
```

If vLLM is missing, the version differs, any file exceeds the profile, a model
artifact appears, or the bundle cannot pass the offline importer, the command
returns target-only failure evidence.

## Ten-check qualification catalog

The canonical synthetic suite proves:

1. deterministic distribution, envelope, and result roots across different
   filesystem locations;
2. exact installed-version binding;
3. closed provider/profile scope;
4. path-traversal rejection;
5. model-artifact rejection;
6. file-count bounds;
7. byte-budget bounds;
8. duplicate-member rejection;
9. downstream offline-import and exact witness binding; and
10. non-widenable authority, content-free evidence, and explicit unverified
    source-commit status.

## Cross-platform qualification

The dedicated workflow runs on Ubuntu/Python 3.10, Ubuntu/Python 3.13,
macOS/Python 3.13, and Windows/Python 3.13. Every lane:

- compiles the complete Eaglegate package;
- runs the accumulated foundation, exactness, adapter, vLLM-shadow, capture,
  witness, producer, workflow, and installation contracts;
- generates the canonical producer report twice and requires byte identity;
- rejects content and authority widening; and
- parses the producer source to reject provider-runtime, accelerator, network,
  subprocess, cryptographic, and dynamic-import/execution surfaces.

An aggregate gate fails unless all lanes pass.

## Deliberately absent

This tranche contains no:

- imported or executed vLLM module;
- real model weights;
- GPU or driver inspection;
- live target verifier, sampler, RNG, scheduler, KV allocator, or kernel;
- request interception or live shadow inference;
- source-commit verification or provenance signature;
- witness-independence proof;
- canary, promotion, rollback, or activation;
- throughput, latency, acceptance-rate, or speedup claim;
- EAGLE-3;
- learned routing, sentinels, random forests, C-driven agent pools, bandits,
  online training, or self-promotion.

## Claim boundary

A passing producer report proves deterministic, bounded inspection of an
installed Python distribution and successful construction of the existing
metadata-only capture bundle. It does not qualify vLLM behavior, model weights,
accelerator hardware, sampler/RNG semantics, KV lifecycle, source provenance,
production losslessness, or performance.

## Next bounded decision

The next useful non-cryptographic work is a real, pinned vLLM wheel qualification
lane that installs one exact wheel and runs this producer without importing the
runtime. That lane must remain separate from model and GPU qualification.

A later model/hardware tranche must independently bind target and EAGLE weights,
tokenizer, numerical kernels, sampler/RNG behavior, KV lifecycle, cancellation,
and the full differential losslessness corpus before any live shadow inference
is admitted.
