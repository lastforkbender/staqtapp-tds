# v3.1.5 Admin Batch Review Layer

v3.1.5 adds the evidence-first admin batch review seam that should exist before
full PyQt5 Driver Studio review controls. The layer consumes deterministic
`DriverRegressionReport` objects from v3.1.4, creates one immutable admin
`DriverReviewDecision` per driver, and returns a deterministic
`DriverBatchReviewReport` for audit, CLI, service, or future GUI display.

The batch review layer is intentionally not a Driver VM, not a Foundry, and not
a signing authority. It organizes and records human review decisions while
preserving the existing trust boundaries:

```text
Foundry proposes/tests candidates
Regression Harness proves fixture behavior
Admin Batch Review records approve/hold/reject/quarantine decisions
Registry owns approval/signature/activation state
Driver Studio displays and submits review workflows
```

## Public API

The new public types are exported from `staqtapp_tds.drivers`:

- `DriverBatchReviewBoard`
- `BatchReviewPolicy`
- `DriverReviewItem`
- `DriverReviewDecision`
- `DriverBatchReviewReport`
- `ReviewAction`
- `ReviewDecisionStatus`
- `BatchReviewStatus`
- `ReviewFault`
- `batch_review_capability_matrix()`

## Authority Matrix

`DriverBatchReviewBoard.capability_matrix()` is designed for future Driver
Studio display. The default board can consume regression reports and create
per-driver audit decisions, but it cannot sign, activate, execute drivers,
write storage, execute Python, or bypass policy.

Registry approval is opt-in and disabled by default:

```python
from staqtapp_tds.drivers import BatchReviewPolicy, batch_review_capability_matrix

batch_review_capability_matrix()["call_registry_approve"]
# False

batch_review_capability_matrix(BatchReviewPolicy(allow_registry_approval=True))["call_registry_approve"]
# True
```

Even when `allow_registry_approval=True`, the board can only ask
`DriverRegistry.approve()` to approve clean candidates. It still has no API for
attaching signatures or activating drivers.

## Review Actions

A review can request one of four actions:

- `approve`
- `hold`
- `reject`
- `quarantine`

A clean regression report requested for approval becomes `approval_ready` by
default. If `apply_registry=True` and the policy allows registry approval, a
clean candidate can become `registry_approved` through `DriverRegistry.approve()`.

Failed reports are not approved. By default, a failed report requested for
approval becomes `held` so the admin can inspect the evidence before rejection
or quarantine. Explicit reject/quarantine actions remain per-driver decisions.

## Negative Evidence Guard

A regression report can pass because it correctly detected an expected policy
rejection or malformed fixture. That is useful for regression testing, but it is
not approval evidence for an operational driver. v3.1.5 therefore defaults to
`BatchReviewPolicy.require_runtime_execution_ok=True`, which prevents expected
negative runtime evidence from becoming approval-ready.

This distinction is important for Driver Studio:

- green fixture regression means expectations were met
- approval-ready means the driver also produced clean runtime evidence

## Deterministic Audit Hashing

Every `DriverReviewDecision` receives a deterministic `review_hash` based on:

- driver identity
- driver version
- requested and final action
- status
- reviewer id
- rationale
- regression report hash
- package hash
- evidence summary
- registry state before/after
- fault codes
- tags

Every `DriverBatchReviewReport` receives a deterministic `batch_hash` derived
from the decision hashes and optional batch id.

This makes the layer suitable for future GUI replay, batch comparison, and
chain-of-custody displays.

## Studio Readiness

v3.1.5 prepares the future PyQt5 Driver Studio for feature-rich trust review
without giving the GUI unsafe authority. Studio can render:

- review queue rows
- evidence summaries
- risk cards
- batch approve/hold/reject/quarantine controls
- registry-state before/after columns
- deterministic review hashes
- per-driver audit records

The Studio should not own bytecode execution, Runtime Manager policy, Registry
signing, or activation. It should submit review intents and display the resulting
evidence-backed decisions.
