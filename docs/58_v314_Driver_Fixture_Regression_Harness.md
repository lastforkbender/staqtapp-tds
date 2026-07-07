# v3.1.4 Driver Fixture Regression Harness

TDS v3.1.4 adds the deterministic fixture/regression layer that should exist before admin batch approval, native driver runtime expansion, or the full PyQt5 Driver Studio.

The core idea is simple:

```text
Compiled .tdd Bytecode Package
   │
   │ named fixture cases only
   ▼
Driver Regression Harness
   │
   │ calls Runtime Manager
   ▼
DriverExecutionEvidence per case
   │
   │ deterministic expectation comparison
   ▼
DriverRegressionReport
```

## Why v3.1.4 comes before Studio

Studio can make driver creation pleasant, but it should not become the source of truth for safety. Admin approval and Studio displays need repeatable proof that a candidate behaves the same way across known inputs. That proof is now modeled as fixture cases plus Runtime Manager evidence.

## Public API

v3.1.4 adds:

- `DriverFixtureCase`
- `RegressionMismatch`
- `DriverRegressionResult`
- `DriverRegressionReport`
- `RegressionStatus`
- `DriverRegressionHarness`
- `runtime_fixture_hash()`
- `regression_harness_capability_matrix()`

## Authority boundaries

The harness may:

- run a compiled package through `DriverRuntimeManager`
- compare evidence to expected fixture outcomes
- produce deterministic report hashes
- lock golden evidence hashes for later regression replay

The harness may not:

- approve drivers
- sign drivers
- activate drivers
- write storage
- execute arbitrary Python
- bypass Runtime Manager policy

This keeps the existing ownership model intact:

```text
Storage engine owns data.
Driver VM owns bytecode execution.
Runtime Manager owns trust/evidence gating.
Foundry owns AI-safe proposal/testing.
Registry owns approval/signature/activation trust.
Regression Harness owns repeatable fixture proof.
Studio comes after runtime/evidence maturity.
```

## Fixture cases

A `DriverFixtureCase` contains named in-memory fixtures and optional expectations:

- `expected_ok`
- `expected_status`
- `expected_recommendation`
- `expected_vm_status`
- `expected_emitted_count`
- `expected_trace_complete`
- `expected_fault_codes`
- `expected_evidence_hash`

If an expectation is omitted, the harness does not compare that field. This allows incremental test maturity: early cases may check broad status and emitted count; mature Class A cases may lock exact evidence hashes.

## Golden evidence hashes

The harness can compare `expected_evidence_hash` against the Runtime Manager result. This is the regression bridge to future admin review:

```text
same package + same fixture + same runtime policy
      │
      ▼
same evidence hash expected
```

A golden hash mismatch is not treated as an exception. It becomes a structured `RegressionMismatch` so UI, Admin Review, and CI can display the precise field that drifted.

## Report semantics

`DriverRegressionReport` includes:

- package identity
- driver identity
- case count
- passed and failed counts
- per-case evidence
- deterministic report hash
- recommendation

If all cases pass, the recommendation is `batch_review_ready`.
If any case fails, the recommendation is `hold`.

Importantly, `batch_review_ready` is not approval. Approval remains with the Registry/Admin trust path.

## Testing added in v3.1.4

v3.1.4 adds tests proving:

- harness capability matrix denies trust authority and storage writes
- multi-fixture success produces a batch-ready report
- report hashes are deterministic for the same package and fixtures
- expectation mismatches are structured and non-halting
- golden evidence hashes can be locked
- expected Runtime Manager policy rejections can pass as regression cases
- malformed case definitions return input-rejected reports instead of host exceptions
