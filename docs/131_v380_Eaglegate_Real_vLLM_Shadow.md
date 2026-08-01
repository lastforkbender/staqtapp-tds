# v3.8 Eaglegate Real vLLM EAGLE Shadow Qualification

## Status and claim boundary

This tranche is the first real Eaglegate runtime integration. It is strictly
qualification-only and runs off the production request path. It does not add a
serving route, canary mode, promotion command, activation command, or authority
to accept tokens or commit KV state.

The target-only engine is the baseline. An attestation failure, constructor
failure, execution error, comparison failure, or cleanup uncertainty produces a
non-passing report with `fallback_required: true`. No speculative output is
returned by the adapter.

## Exact admitted matrix

| Component | Pinned value |
| --- | --- |
| vLLM release | `0.26.0` / tag `v0.26.0` |
| vLLM source commit | `568afb3a13806beb53bb2e6bd518269357b237c0` |
| Target | `meta-llama/Meta-Llama-3-8B-Instruct` |
| Target revision | `8afb486c1db24fe5011ec46dfbe5b5dccdb575c2` |
| Draft head | `yuhuili/EAGLE-LLaMA3-Instruct-8B` |
| Draft revision | `b62ec3ed0c5135290f5dd8b8cec48d055d3d10dd` |
| Tokenizer | Target model at the target revision |
| Method | `"method": "eagle"` (not `eagle3`) |
| Verification | `"rejection_sample_method": "standard"` |
| Numerical lane | NVIDIA H100, SM90, BF16 |
| Request shape | Explicit request seed, batch size 1 |
| KV cache | Explicit `kv_cache_dtype="bfloat16"`; block size 16; prefix caching disabled |
| Parallelism | Target TP 1; draft TP 1 |
| RNG contract | Target and draft inherit the explicit engine/request seed stream |
| Plans | 1, 2, and 3 speculative tokens |

The adapter dynamically executes `from vllm import LLM, SamplingParams` only
inside the qualification call. Importing TDS does not initialize vLLM, CUDA, a
model, or a tokenizer.

Before an engine is constructed, runtime attestation requires the exact vLLM
version and full build commit. The real workflow installs an editable checkout
at that commit; the adapter verifies that the imported module is under that
checkout and that `git rev-parse HEAD` is exact. It then requires an H100 device,
compute capability `(9, 0)`, and PyTorch BF16 support.

The target constructor pins the model, code revision, target tokenizer and
tokenizer revision, BF16, target tensor parallel size 1, `max_num_seqs=1`, the
request seed, KV-cache dtype `auto` (resolved from the pinned BF16 model dtype),
KV block size 16, and disabled prefix caching. The three shadow constructors add
this exact configuration:

```json
{
  "method": "eagle",
  "model": "yuhuili/EAGLE-LLaMA3-Instruct-8B",
  "revision": "b62ec3ed0c5135290f5dd8b8cec48d055d3d10dd",
  "code_revision": "b62ec3ed0c5135290f5dd8b8cec48d055d3d10dd",
  "num_speculative_tokens": 1,
  "rejection_sample_method": "standard",
  "draft_sample_method": "greedy",
  "draft_tensor_parallel_size": 1
}
```

The plan count is replaced with 2 and 3 for the remaining bounded plans. The
top-level tokenizer remains the pinned target tokenizer in every engine.

The configuration follows vLLM's documented Python
[`LLM(..., speculative_config={...})`](https://docs.vllm.ai/en/v0.26.0/examples/features/speculative_decoding/)
surface and its pinned
[`SpeculativeConfig`](https://docs.vllm.ai/en/v0.26.0/api/vllm/config/speculative/)
schema.

## Real differential gates

Each plan must pass four gates:

1. **Greedy equality.** Target-only and EAGLE token IDs and public finish reason
   must be exactly equal for every bounded case.
2. **Sampled distribution evidence.** Both paths run the same explicit sequence
   of request seeds under temperature and top-p sampling. A bounded empirical
   first-token histogram distance must remain within the recorded tolerance,
   which cannot exceed 250,000 ppm.
   This is evidence, not a proof of distribution identity.
3. **Continuation semantics.** A generated prefix is appended to target-tokenizer
   IDs and submitted as a second public request. The combined public token
   continuation must be equal.
4. **Cancellation and shutdown cleanup.** A pre-dispatch cancellation performs no
   model call, and every target/EAGLE engine must expose a successful shutdown
   path before the next engine is built.

Every report carries the exact ordered 12-entry catalog: those four gates for
plan 1, then plan 2, then plan 3. Missing, duplicated, or reordered entries are
rejected. Each executed gate's case count is checked against the bound workload;
its mismatch count must reproduce its parts-per-million metric, and its `passed`
value must agree with the exact-zero or sampled-tolerance rule. Failed early runs
retain the full catalog with the remaining entries explicitly marked
`executed: false`; they can never qualify.

The target sampler remains token authority. vLLM's standard rejection sampler
performs speculative verification, and the target runtime remains committed
token and KV authority. TDS observes results; it does not propose, accept,
sample, or commit tokens.

## KV and cancellation limitations

No direct KV tensor equivalence is claimed. The synchronous public `LLM` surface
does not expose target and draft KV tensors for comparison. The continuation
gate observes only public tokenizer and generated-token behavior after a resumed
prefix. Its report therefore states:

```text
direct_kv_tensor_equivalence_tested: false
continuation_observation_scope: public-runtime-output-only
```

Likewise, this adapter qualifies pre-dispatch cancellation and engine shutdown,
not in-flight asynchronous cancellation. The report permanently states
`in_flight_cancellation_qualified: false`. A future async-runtime tranche needs
its own pinned API, timeout, abort, and resource-release qualification.

## Bounded content-free evidence

The in-process observation queue contains only gate name, plan size, case count,
and mismatch count. It has a fixed capacity and drops new detail when full;
observer pressure cannot affect qualification decisions.

Persistent evidence contains only:

- the exact Generic Generation Authority ServingEpoch generation root and its
  complete Phase-3 binding: storage generation, Eaglegate epoch, policy plus
  ordered plans, target runtime identity, qualification bridge and summary,
  exactness report, adapter-conformance report, and receipt-chain roots;
- the complete pinned matrix, concrete settings, ordered workload prompt roots,
  runtime attestation, gate evidence, and report roots;
- bounded counters and parts-per-million metrics;
- exact public runtime/model identity, fixed H100 family, and a rooted device
  identity (never the raw device name);
- stable fallback reasons; and
- explicit authority and limitation booleans.

Prompt text, raw token sequences, logits, hidden states, and KV tensors are never
written. Token IDs exist transiently only long enough to compute comparisons and
content roots. Optional persistence uses `AtomicGenerationStore` and its normal
head-root compare-and-swap; there is no Eaglegate-specific store or second
`CURRENT` pointer.

The qualification call cannot run from a free-standing epoch root. It opens and
pins a concrete Phase-3 ServingEpoch generation and its storage dependency for
the full engine run. Before report publication, persistence opens and pins that
same generation again, validates the canonical core epoch, and compares every
field of the stored binding with the report. A mixed, retired, substituted, or
otherwise unavailable generation fails before publication.

## Manual H100 workflow

`.github/workflows/eaglegate-vllm-shadow-real.yml` is manual-only. It requires:

- a self-hosted Linux x64 runner labeled `h100` and `sm90`;
- an explicit `confirm_meta_llama_license` acknowledgement;
- a configured `HF_TOKEN` whose account can access the gated Meta Llama target;
- sufficient local disk, RAM, CUDA build tooling, and H100 memory; and
- network access to install the exact vLLM source and download both pinned model
  revisions.

The workflow checks out vLLM at the full commit, builds/installs that source,
runs the local fake-injected construction tests, provisions a canonical shadow
ServingEpoch through Generic Generation Authority, then runs the real matrix
while pinning that generation. It archives only the content-free JSON report and
Generation Authority directory. A missing token, unaccepted license, unavailable
runner, source mismatch, ServingEpoch mismatch, gate failure, or cleanup failure
fails the workflow. A green run qualifies only this off-path matrix on the
observed runner; it does not activate production use.

## Deliberately absent

- production prompt interception or output substitution;
- online shadow mirroring of user traffic;
- canary, promotion, activation, or rollback commands;
- draft ownership of acceptance, sampling, tokens, or KV state;
- persisted prompts, token IDs, logits, hidden states, or KV tensors;
- batch sizes other than one;
- GPUs other than H100 SM90;
- numerical modes other than BF16;
- model, tokenizer, draft, runtime, sampler, or plan identities outside the
  exact table above; and
- claims of direct KV-tensor or in-flight-cancellation equivalence.
