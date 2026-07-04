# v3.0.2 Native KeyPool Safety Hotfix

v3.0.2 fixes a critical memory-safety issue in `_native_index.c` involving TinyKeyPool key-buffer reuse.

## Issue

The previous pool reused freed small-key buffers based on logical key length, even though those buffers may have been allocated with `malloc(len)` at a much smaller capacity. A short key buffer could therefore be returned for a larger key and overflow during `memcpy()`.

## Fix

TinyKeyPool now enforces a fixed-capacity invariant:

- every pooled key buffer is allocated with `pool->block_size` bytes
- every key with `0 < len <= block_size` is either served from the pool or allocated at full block size
- larger keys are allocated at exact length and are never returned to the small-key pool

This keeps the fast reuse path while making the pooled allocation capacity explicit and safe.

## Dashboard fix

The wide-desktop Operations Console hero graphic also received a layout correction so the AI and TDS nodes no longer overlap.
