#!/usr/bin/env python3
"""Update v3.7 candidate status without altering screenshots or key links."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

ENGLISH_TOP_OLD = """> **v3.6.0 Foundation Closure source candidate**
>
> This source candidate closes the native correctness and Frontier authority substrate:
> fail-closed ABI/lifecycle admission, strict checksum and UTF-8 truth,
> generation-bound handles, bounded C11 diagnostics, immutable packed reads,
> and exact x86-64/AArch64 semantics. It adds no Atomic Generation Plane,
> Eaglegate execution, learned serving, or activation authority.

> **v3.6.0 release security contract**
>
> At-rest encryption is not implemented. Requests using `DirFlags.ENCRYPTED` fail closed instead of storing plaintext. New v2 persistence files require their integrity sidecar. `.tds` input should be treated as trusted until explicit resource-budget hardening is complete. Native extensions are optional and are built only when `STAQTAPP_TDS_BUILD_NATIVE=1` is set.

# Staqtapp-TDS v3.6.0

> **Repository status:** `3.6.0` is the qualified Foundation source candidate. The current production PyPI release remains `3.5.3.post2` until the exact merged and tagged release matrix passes and publication completes.
"""

ENGLISH_TOP_NEW = """> **v3.7.0 Atomic Generation Authority source candidate**
>
> This branch adds the generic immutable Generation Authority above the v3.6
> Foundation substrate: canonical manifests, content-addressed payloads,
> append-only lifecycle and publication receipts, atomic `CURRENT`
> compare-and-swap, pinned readers, deterministic recovery, rollback, and
> retirement. CSV is the first qualification fixture, not the architectural
> limit. Eaglegate execution, learned serving, model authority, and activation
> authority remain absent.

> **v3.6.0 Foundation substrate**
>
> The source line retains fail-closed native ABI/lifecycle admission, strict
> checksum and UTF-8 truth, generation-bound handles, bounded C11 diagnostics,
> immutable packed reads, and exact x86-64/AArch64 semantics.

> **Current security contract**
>
> At-rest encryption is not implemented. Requests using `DirFlags.ENCRYPTED` fail closed instead of storing plaintext. New v2 persistence files require their integrity sidecar. `.tds` input should be treated as trusted until explicit resource-budget hardening is complete. Native extensions are optional and are built only when `STAQTAPP_TDS_BUILD_NATIVE=1` is set.

# Staqtapp-TDS v3.7.0 Atomic Generation Authority candidate

> **Repository status:** v3.7.0 is a source candidate under review, not a published package. The current production PyPI release remains `3.5.3.post2`. The v3.6 Foundation and v3.7 Generation Authority must complete canonical merge, tag-bound qualification, and publication before their package identities are presented as production releases.
"""

ENGLISH_INSTALL_OLD = """```bash
# Current production PyPI release; includes both UIs
python -m pip install staqtapp-tds==3.5.3.post2

# Candidate package identity; use this command only after 3.6.0 publication
python -m pip install staqtapp-tds==3.6.0

# Launch the main TDS telemetry UI
staqtapp-tds

# Source checkout; includes both UIs
python -m pip install .
```"""

ENGLISH_INSTALL_NEW = """```bash
# Current production PyPI release; includes both UIs
python -m pip install staqtapp-tds==3.5.3.post2

# Launch the main TDS telemetry UI
staqtapp-tds

# v3.7 source candidate checkout; includes both UIs
git checkout agent/v370-generation-convergence
python -m pip install .
```"""

ENGLISH_VALIDATION_MARKER = """## Validation status

The v3.6.0 Foundation source closes the native and authority repair train with"""

ENGLISH_VALIDATION_NEW = """## Validation status

The v3.7.0 Atomic Generation Authority source candidate adds one generic,
immutable publication primitive for storage generations and future Eaglegate
epochs. The focused qualification covers deterministic identity, exact
authoritative-byte round trip, lifecycle adjacency, all declared crash
boundaries, current-head CAS, concurrent publication conflict, pinned readers,
restart access, corruption rejection, deterministic recovery, rollback,
retirement, and namespace isolation. It grants no semantic, ranking, model,
Browser, Studio, or activation authority. See
`docs/130_v370_Atomic_Generation_Authority.md`.

The v3.6.0 Foundation source closes the native and authority repair train with"""

JAPANESE_TOP_OLD = """# Staqtapp-TDS v3.6.0

> **Repository status:** `3.6.0` は qualified Foundation source candidate です。Exact merged/tagged release matrix と publication が完了するまで、production PyPI release は `3.5.3.post2` のままです。

> **v3.6.0 Foundation Closure source candidate:** fail-closed native ABI / lifecycle、strict
> checksum / UTF-8 truth、generation-bound handle、bounded C11 diagnostics、
> immutable packed read、x86-64 / AArch64 semantic parity を閉じます。
> Atomic Generation Plane、Eaglegate execution、learned serving、activation
> authority はこの release に含まれません。
"""

JAPANESE_TOP_NEW = """# Staqtapp-TDS v3.7.0 Atomic Generation Authority candidate

> **Repository status:** v3.7.0 は review 中の source candidate であり、published package ではありません。Current production PyPI release は `3.5.3.post2` のままです。v3.6 Foundation と v3.7 Generation Authority は canonical merge、tag-bound qualification、publication 完了後にのみ production package として扱われます。

> **v3.7.0 Atomic Generation Authority source candidate:** canonical manifest、content-addressed payload、append-only lifecycle / publication receipt、atomic `CURRENT` CAS、pinned reader、deterministic recovery、rollback、retirementを generic primitive として追加します。CSV は最初の qualification fixture ですが、architecture の上限ではありません。Eaglegate execution、learned serving、model authority、activation authority は含まれません。

> **v3.6.0 Foundation substrate:** fail-closed native ABI / lifecycle、strict checksum / UTF-8 truth、generation-bound handle、bounded C11 diagnostics、immutable packed read、x86-64 / AArch64 semantic parity を保持します。
"""

JAPANESE_INSTALL_OLD = """```bash
# Current production PyPI release（両方の UI を含む）
python -m pip install staqtapp-tds==3.5.3.post2

# Candidate package identity（3.6.0 publication 完了後に使用）
python -m pip install staqtapp-tds==3.6.0

# main TDS telemetry UI を起動
staqtapp-tds

# Source checkout（両方の UI を含む）
python -m pip install .
```"""

JAPANESE_INSTALL_NEW = """```bash
# Current production PyPI release（両方の UI を含む）
python -m pip install staqtapp-tds==3.5.3.post2

# main TDS telemetry UI を起動
staqtapp-tds

# v3.7 source candidate checkout（両方の UI を含む）
git checkout agent/v370-generation-convergence
python -m pip install .
```"""

JAPANESE_VALIDATION_MARKER = """## Validation status

v3.6.0 Foundation source は process-state ledger、deterministic closure"""

JAPANESE_VALIDATION_NEW = """## Validation status

v3.7.0 Atomic Generation Authority source candidate は storage generation と
future Eaglegate epoch のための generic immutable publication primitive を
追加します。Focused qualification は deterministic identity、authoritative
byte round trip、lifecycle adjacency、全 crash boundary、CURRENT CAS、
concurrent publication conflict、pinned reader、restart access、corruption
rejection、deterministic recovery、rollback、retirement、namespace isolation
を対象とします。Semantic、ranking、model、Browser、Studio、activation
authority は付与しません。詳細は
`docs/130_v370_Atomic_Generation_Authority.md` を参照してください。

v3.6.0 Foundation source は process-state ledger、deterministic closure"""

IMPORTANT_ENGLISH_LINKS = (
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/README_ja.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/main/CHANGELOG.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/LICENSE",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/docs/reference/Programmers_API_Reference.md",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "https://github.com/lastforkbender/staqtapp-tds/blob/v3.5.3/tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)

IMPORTANT_JAPANESE_LINKS = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "docs/reference/Programmers_API_Reference.md",
    "tds_api_docs/Staqtapp_TDS_API_Surface_Reference.pdf",
    "tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label} expected exactly once; found {text.count(old)}")
    return text.replace(old, new, 1)


def image_sources(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', text, flags=re.IGNORECASE))


def update(path: Path, replacements, important_links) -> None:
    original = path.read_text(encoding="utf-8")
    before_images = image_sources(original)
    if len(before_images) != 19:
        raise SystemExit(f"{path.name} must contain exactly 19 screenshots before update")
    for link in important_links:
        if link not in original:
            raise SystemExit(f"{path.name} missing important link before update: {link}")
    updated = original
    for old, new, label in replacements:
        updated = replace_once(updated, old, new, label)
    after_images = image_sources(updated)
    if after_images != before_images:
        raise SystemExit(f"{path.name} screenshot sources changed")
    for link in important_links:
        if link not in updated:
            raise SystemExit(f"{path.name} important link removed: {link}")
    if "src/staqtapp_tds/generation/" not in updated:
        updated = updated.replace(
            "src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR\n",
            "src/staqtapp_tds/generation/ generic immutable generations, CAS, pinning, recovery\n"
            "src/staqtapp_tds/csv_layer CSV evidence, transactions, Interpole, Semantic IR\n",
            1,
        )
    path.write_text(updated, encoding="utf-8", newline="\n")


def main() -> int:
    update(
        ROOT / "README.md",
        (
            (ENGLISH_TOP_OLD, ENGLISH_TOP_NEW, "English top status"),
            (ENGLISH_INSTALL_OLD, ENGLISH_INSTALL_NEW, "English install"),
            (
                ENGLISH_VALIDATION_MARKER,
                ENGLISH_VALIDATION_NEW,
                "English validation",
            ),
        ),
        IMPORTANT_ENGLISH_LINKS,
    )
    update(
        ROOT / "README_ja.md",
        (
            (JAPANESE_TOP_OLD, JAPANESE_TOP_NEW, "Japanese top status"),
            (JAPANESE_INSTALL_OLD, JAPANESE_INSTALL_NEW, "Japanese install"),
            (
                JAPANESE_VALIDATION_MARKER,
                JAPANESE_VALIDATION_NEW,
                "Japanese validation",
            ),
        ),
        IMPORTANT_JAPANESE_LINKS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
