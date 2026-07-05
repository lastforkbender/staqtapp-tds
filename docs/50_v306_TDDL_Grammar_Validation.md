# v3.0.6 TDDL Grammar Validation

v3.0.6 adds the first non-executing TDS Driver Language (TDDL) grammar and
validation layer. This is a foundation release for the future native Driver VM,
Driver Builder and PyQt5 Driver Studio.

The parser accepts a strict source structure:

```tds-driver
driver SearchPolicyDrivers v1

manifest:
  kind = "search"

requires:
  capability registry.scan
  capability manifest.read
  adapter predicate.semantic_manifest.v1

limits:
  max_scan = 5000
  max_depth = 8
  timeout_ms = 250

program:
  SCAN scope=".tds" recursive=true limit=5000 depth=8
  READ target="manifest"
  MATCH using="predicate.semantic_manifest.v1" query="policy" threshold=0.82
  EXTRACT from="manifest" fields=["driver_id", "version"]
  EMIT mode="ranked" limit=25
  HALT
```

## Safety posture

This layer does not execute programs. It only parses and validates a stable IR.
Validation fails closed for unsafe or ambiguous behavior:

- absolute or escaping `SCAN` scopes are rejected;
- unknown instructions and operands are rejected;
- unbounded regex behavior is rejected;
- undeclared adapters are rejected;
- unsafe adapter names such as eval/exec/import/subprocess/socket are rejected;
- thresholds must be between `0.0` and `1.0`;
- programs must end with exactly one `HALT`.

## Instruction metadata table

`staqtapp_tds.drivers.instruction_specs()` exposes the self-describing instruction
metadata table intended for the future Builder and Driver Studio. The Studio can
teach syntax from the same metadata that validation uses, avoiding duplicate UI
truth.

## Execution boundary

The future native Driver VM remains separate from the Native Storage Engine.
v3.0.6 deliberately introduces syntax contracts before bytecode or runtime
execution exists.
