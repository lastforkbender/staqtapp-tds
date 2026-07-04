"""Reserved namespace for the future Search & Extract driver system.

The driver language, registry, builder and optional C VM are intentionally not
implemented in v3.0.1. This package marks the extension boundary so those
features can be added without coupling them to storage hot paths.
"""

__all__: list[str] = []
