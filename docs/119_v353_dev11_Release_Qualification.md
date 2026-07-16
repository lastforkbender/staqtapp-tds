# v3.5.3 — Phase 11 Release Qualification

Phase 11 converts the Guaranteed Storage development sequence into auditable
release gates. It does not treat a passing happy-path migration as sufficient.
Fault injection, corruption, concurrency, soak behavior, performance shape,
platform coverage, documentation, APIs, packaging, and publication authority
must all be accounted for.

## GC defects found during qualification

The Phase 9 collector originally derived references from
`list_generations(valid_only=True)`. That was suitable for recovery selection,
but unsafe for deletion: an unreadable generation was silently omitted from the
reference universe, so remaining segments from a partially damaged generation
could be destroyed.

The original collector also reused one reachability scan for an entire deletion
batch and did not revalidate the candidate filesystem object immediately before
unlink. A newly published reference or a replaced path could therefore make the
deletion proof stale.

Phase 11 corrects those defects as follows:

1. Every recognized generation is inventoried. Any invalid generation blocks
   destructive GC while preserving the exact invalid-generation list.
2. Public reference accounting also fails closed when the reference universe is
   incomplete.
3. Reachability is recomputed for each candidate, then recomputed again after
   the last pre-delete fault boundary.
4. Type, device, inode, size, mode, mtime, and ctime must still match the scanned
   candidate before unlink.
5. Changed candidates are retained and reported separately; only successful
   unlinks contribute to removed-object and removed-byte accounting.
6. Mutation exclusion covers the complete scan/recheck/delete interval, and an
   interrupted run can be resumed without affecting the current generation.

## GC qualification matrix

`tests/test_v353_release_gc_qualification.py` covers:

- malformed-generation blocking;
- partially damaged generation salvage preservation;
- a reference injected at the final deletion boundary;
- inode replacement and same-inode content mutation;
- symlink replacement without external-target deletion;
- interruption and idempotent resumption;
- competing public mutation exclusion;
- exact physical-byte accounting.

`tests/test_v353_release_qualification.py` adds a 129-generation incremental
soak. It performs three torn-pointer recoveries, verifies one-segment physical
writes for every logical generation, deletes all superseded manifests, compares
dry-run and destructive candidate inventories, collects 65 unreachable
segments, and re-verifies the current generation and complete logical bytes.

## Controlled activation audit

Phase 10 is a required release predecessor and is documented both at repository
root and in `docs/118_v353_dev10_Controlled_Activation.md`. The default remains
legacy. Qualification cannot activate implicitly. Activation and rollback use
different exact acknowledgements, repeat integrity/equivalence proof under the
mutation lock, and publish authority only after the replacement mount is fully
verified.

## Browser documentation audit

The misleading single Dashboard image and its unsupported CSV description were
removed. `docs/screenshots/browser_pages/` contains 19 distinct 1280×800
captures, one per Browser navigation entry. The reproducible capture fixture
commits real CSV evidence through performance-gate completion, verifies
`monitor_ready`, publishes real TDS and Spiral Rank observer data, and serves it
through the packaged local `AdminPanelServer`. The capture driver clicks and
validates each active navigation target before writing its image. Both READMEs
embed all 19 files vertically in navigation order.

## Platform and publication gates

The release workflow now requires:

- the source hygiene and generated-document audit;
- the monolithic suite on Python 3.10, 3.11, 3.12, 3.13, and 3.14 on Linux;
- the monolithic pure-Python suite on Windows and macOS;
- native-extension builds and native-active suites on Linux and macOS;
- PEP 517 sdist/wheel construction, `twine check`, and isolated wheel import;
- a single tag-only publication job that depends on all earlier gates and uses
  PyPI trusted publishing rather than a repository token.

The first draft-PR runs added four release findings. The generated result-code
check originally imported the complete package before dependencies were
installed; it now loads `result.py` directly. Windows raw descriptors were
opened without `O_BINARY`, allowing CRT newline translation to corrupt TDS
indexes, generation lengths, segment hashes, migration copies, and downstream
GC evidence. Every byte-exact descriptor writer now uses one binary-open helper.
Windows readers also detach an immutable snapshot and release the source handle
before validation, so an existing reader cannot block atomic path replacement.
Apple Clang also contracted the native Spiral weighted terms and produced a
one-ULP difference from Python; the native operation boundaries now mirror the
Python expression while the strict equality test remains in place.

Draft-PR qualification does not grant release authority. A v3.5.3 tag remains
prohibited until every GitHub Actions gate on the candidate head is green.

## Evidence status

Local Phase 11 qualification is complete. Exact evidence is recorded in
`DEV11_RELEASE_QUALIFICATION_STATUS.txt`:

- 133 v3.5.3 storage tests passed;
- the overlapping v3.5.3/workflow/Browser/CSV group passed all 157 tests;
- the pure monolithic run collected 843 tests, with 832 passed and 11 skipped;
- the native-active monolithic run passed all 843 tests;
- both PEP 517 artifacts passed `twine check`, archive inspection, metadata
  inspection, and isolated wheel activation/rollback/GC smoke qualification;
- the Programmer Core API Guide's v3.5.3 supplement was rendered and visually
  checked; all 634 light-blue signature strips retain their text with zero
  heading intersections, and the older API Surface PDF is explicitly labeled
  historical;
- source hygiene and generated-result documentation checks passed.

The local pre-push qualification was completed before draft PR #1 opened.
Review-branch commits and CI runs are qualification evidence only; no tag or
publication has been performed. A v3.5.3 tag remains prohibited until the
complete GitHub Actions matrix on the candidate head is green.
