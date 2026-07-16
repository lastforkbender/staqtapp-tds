# v3.5.2 Single-Process Test Investigation

## Question

Does the complete TDS test suite degrade or hang when all tests execute in one Python interpreter?

## Finding

No. The apparent timeout was caused by observation of an external execution wrapper rather than the lifetime of its child pytest process. Direct process observation showed pytest continuing at high CPU utilization and completing normally.

## Reproduction evidence

```text
python -m pytest -q --disable-warnings
696 passed, 11 skipped in 55.77s
```

The final corrected suite collected 707 tests, including the new release-pipeline regression test. No test failed.

## Memory evidence

The complete process peaked near 695 MB RSS in this environment. The atomic-batch module by itself peaked near 694 MB and completed 21 tests in 22.43 seconds. Therefore, the high-water memory mark is not evidence of cumulative retention across the preceding suite. It is a workload/runtime footprint that should be optimized separately.

## Release rule

Normal monolithic pytest is the authoritative CI release gate. The parallel shard helper is retained only as an optional wall-clock accelerator and must not be used to conceal a failure of the monolithic suite.

## Corrective lesson

A wrapper timeout is not proof that its child process is hung. Future liveness findings require all three: child-process state, elapsed child runtime, and final child exit status.
