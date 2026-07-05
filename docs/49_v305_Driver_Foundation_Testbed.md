# v3.0.6 Driver Foundation Testbed

v3.0.6 prepares TDS for the future native Driver VM, Driver Builder,
Registry, signing workflow and PyQt5 Driver Studio without introducing driver
execution yet.

## Scope

Implemented in this release:

- `staqtapp_tds.drivers` foundation namespace.
- Draft `DriverManifest` model for future `.tddl` / `.tdd` driver artifacts.
- Deterministic manifest validation and canonical signing payloads.
- Registry state model: `candidate`, `approved`, `signed`, `active`, `retired`, `revoked`.
- Mock signature policy for regression testing trust rules.
- Deterministic trace-ranking fixtures for future search/extraction drivers.

Not implemented yet:

- Native Driver VM.
- TDS Driver Language parser.
- `.tdd` binary package loader.
- PyQt5 Driver Studio.
- AI evolution engine.

## Trust contract

The foundation tests encode the future registry rule:

```text
unsigned driver      -> reject
bad signature        -> reject
unknown signer       -> reject
revoked signature    -> reject
approved signature   -> may activate
```

The runtime storage engine remains separate. Driver foundation code does not
access native storage internals and does not execute driver programs.

## Why this exists before the VM

The Driver VM should plug into stable contracts rather than invent trust,
manifest and ranking behavior while the native interpreter is being built. This
release gives the future VM a tested landing zone.
