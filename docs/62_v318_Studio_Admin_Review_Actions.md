# v3.1.8 Studio Admin Review Actions

v3.1.8 adds the first bounded Studio admin-action submission layer:
`DriverStudioAdminReviewActions`. It sits above the v3.1.7 read-only evidence
console and below the existing Admin Batch Review / Registry authority boundary.

The new layer lets the future PyQt5 Driver Studio capture admin intent for
review actions without turning the Studio itself into a trust authority.

## New components

- `DriverStudioAdminReviewActions`
- `StudioReviewSubmissionPolicy`
- `StudioReviewActionRequest`
- `StudioReviewActionDecision`
- `StudioReviewActionEvent`
- `StudioReviewSubmissionReport`
- `StudioReviewSubmissionStatus`
- `StudioReviewActionStatus`
- `studio_admin_review_capability_matrix()`

## Core rule

Studio may submit review actions.

Studio still does not approve, sign, activate, execute, mutate registry state,
write storage, edit bytecode, edit TDDL, bypass policy, or store private keys.

The actual trust chain remains:

```text
Driver Studio
  │ captures admin intent + creates action audit records
  ▼
DriverBatchReviewBoard
  │ validates regression evidence and review policy
  ▼
DriverRegistry
  │ owns candidate approval/signature/activation state transitions
  ▼
Runtime Manager / Driver VM
  │ own execution evidence and bytecode execution boundaries
```

## Submission behavior

`DriverStudioAdminReviewActions.submit_actions()` accepts a verified
`DriverStudioConsoleSnapshot`, `DriverEvidenceBundle`, bundle mapping, or bundle
JSON string plus one or more `StudioReviewActionRequest` objects.

If no regression reports are supplied, the Studio records a deterministic
submission report and audit events only. This is useful for GUI rehearsals,
operator workflows, and approval queues.

If regression reports are supplied, the Studio routes the request to
`DriverBatchReviewBoard`. The review board owns the authoritative approval-ready,
hold, reject, quarantine, and optional registry-approval result.

## Registry approval routing

Registry approval routing is deliberately two-keyed:

1. Studio submission policy must enable `allow_registry_approval_request`.
2. Batch review policy must enable `BatchReviewPolicy.allow_registry_approval`.

Even then, Studio never calls `DriverRegistry.approve()` directly. The call can
only occur inside `DriverBatchReviewBoard`, and only if the Registry and report
evidence accept the transition.

## Audit properties

Every accepted, rejected, or policy-rejected Studio action produces deterministic
hash material:

- `decision_hash` per action decision
- `submission_hash` per submission report
- `tds-studio-audit-*` action events
- optional authority batch hash when routed to `DriverBatchReviewBoard`

This preserves the Driver Studio cockpit design: all operator actions are
visible, replayable, and hashable before they are trusted.

## Capability boundary

The new capability matrix explicitly allows:

- loading a read-only console snapshot
- submitting review actions
- creating action audit records
- routing to batch review authority
- optionally requesting a registry approval route

It explicitly denies:

- direct driver approval/rejection/quarantine authority
- direct Registry approval
- signing or signature attachment
- activation
- Driver VM execution
- TDDL/bytecode editing
- storage writes
- Python execution
- private key storage
- policy bypass

## Testing

v3.1.8 adds `tests/test_v318_studio_admin_review_actions.py`, covering:

- submission capability boundaries
- deterministic action recording without authority routing
- action routing to `DriverBatchReviewBoard`
- tampered bundle rejection before authority routing
- registry approval route gating by both Studio policy and review-board policy
- proof that Studio still has no approve/sign/activate/execute methods
