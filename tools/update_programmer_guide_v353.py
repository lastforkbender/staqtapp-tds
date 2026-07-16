#!/usr/bin/env python3
"""Prepend the v3.5.3 release supplement to the Programmer Core API PDF.

The historical guide is intentionally retained because it documents the broad
v3.5.2 API surface.  This script makes the new v3.5.3 storage control and
release-safety contract the first material a reader sees.  A metadata marker
keeps repeated runs idempotent by replacing, rather than duplicating, the
supplement pages.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


SUPPLEMENT_MARKER = "TDS v3.5.3 Controlled Activation and Release Qualification"
SUPPLEMENT_METADATA_KEY = "/TDSV353SupplementPages"
LABEL_SPACING_METADATA_KEY = "/TDSLightBlueLabelSpacing"
LABEL_SPACING_VERSION = "v1"
LIGHT_BLUE_SIGNATURE_FILL = (0.917647, 0.94902, 1.0)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    navy = colors.HexColor("#17324D")
    blue = colors.HexColor("#2474A6")
    muted = colors.HexColor("#536273")
    return {
        "title": ParagraphStyle(
            "ReleaseTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=navy,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "ReleaseSubtitle",
            parent=base["Heading2"],
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            textColor=blue,
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "ReleaseH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=navy,
            spaceBefore=8,
            spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "ReleaseH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=blue,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ReleaseBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.2,
            textColor=colors.HexColor("#202832"),
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "ReleaseSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.7,
            leading=10.2,
            textColor=muted,
        ),
        "code": ParagraphStyle(
            "ReleaseCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.2,
            leading=9.2,
            leftIndent=8,
            rightIndent=8,
            borderColor=colors.HexColor("#C7D7E4"),
            borderWidth=0.6,
            borderPadding=7,
            backColor=colors.HexColor("#F4F8FB"),
            spaceBefore=4,
            spaceAfter=8,
        ),
        "callout": ParagraphStyle(
            "ReleaseCallout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.1,
            leading=12.5,
            textColor=colors.HexColor("#17324D"),
            borderColor=colors.HexColor("#3C95C7"),
            borderWidth=0.8,
            borderPadding=8,
            backColor=colors.HexColor("#EAF5FB"),
            spaceBefore=14,
            spaceAfter=10,
        ),
    }


def _bullet(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f"&#8226;&nbsp; {text}", style)


def _footer(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#C7D7E4"))
    canvas.setLineWidth(0.5)
    canvas.line(0.7 * inch, 0.52 * inch, 7.8 * inch, 0.52 * inch)
    canvas.setFillColor(colors.HexColor("#536273"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(0.7 * inch, 0.32 * inch, "Staqtapp-TDS v3.5.3 - Programmer Core API Guide release supplement")
    canvas.drawRightString(7.8 * inch, 0.32 * inch, f"Supplement page {doc.page}")
    canvas.restoreState()


def _phase_table(styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ["Phase", "Release meaning", "Completion evidence"],
        ["9", "Incremental immutable segments", "Content addressing, reuse, recovery, dry-run GC"],
        ["10", "Controlled activation", "Explicit qualification, mode publication, verified rollback"],
        ["11", "Release qualification", "GC adversarial tests, soak, docs, package and workflow gates"],
    ]
    table = Table(rows, colWidths=[0.58 * inch, 2.15 * inch, 4.02 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.8),
                ("LEADING", (0, 0), (-1, -1), 10.2),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#AFC4D3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FB")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _build_supplement(path: Path) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.7 * inch,
        title="Staqtapp-TDS v3.5.3 Programmer Core API Guide release supplement",
        author="Staqtapp-TDS contributors",
        subject=SUPPLEMENT_MARKER,
    )
    story = []

    story.extend(
        [
            Paragraph("Staqtapp-TDS v3.5.3", styles["title"]),
            Paragraph("Programmer Core API Guide - Release Supplement", styles["subtitle"]),
            Paragraph(
                "This supplement is the authoritative v3.5.3 update to the broad v3.5.2 guide that follows. "
                "It makes the previously missing Phase 10 predecessor explicit, documents the Phase 11 "
                "safety corrections, and records the local release evidence without implying that remote "
                "cross-platform CI has already run.",
                styles["callout"],
            ),
            Paragraph("Phase progression", styles["h1"]),
            _phase_table(styles),
            Spacer(1, 8),
            Paragraph("Safe default and authority boundary", styles["h1"]),
            Paragraph(
                "If no storage mode record exists, <b>legacy TDSPersistence remains authoritative</b>. "
                "Qualification creates evidence but cannot activate the segmented path. Activation requires "
                "the exact acknowledgement <font name='Courier'>activate-guaranteed-segmented</font> and "
                "repeats the migration proof under the mutation lock immediately before atomic mode publication.",
                styles["body"],
            ),
            _bullet("No constructor, qualification call, Browser poll, or ordinary legacy commit can switch modes implicitly.", styles["body"]),
            _bullet("A corrupt, non-canonical, incomplete, stale, or mismatched control record fails closed.", styles["body"]),
            _bullet("Rollback reconstructs the current guaranteed bytes into a new verified legacy mount before authority changes.", styles["body"]),
            Paragraph("New public v3.5.3 types", styles["h1"]),
            Paragraph(
                "<font name='Courier'>StorageMode</font>, <font name='Courier'>ControlledActivationError</font>, "
                "<font name='Courier'>ActivationQualification</font>, <font name='Courier'>StorageActivationStatus</font>, "
                "<font name='Courier'>ControlledCommitReport</font>, <font name='Courier'>ControlledStorage</font>, "
                "<font name='Courier'>SegmentReference</font>, <font name='Courier'>SegmentGenerationInfo</font>, "
                "<font name='Courier'>SegmentCommitReport</font>, <font name='Courier'>SegmentGCReport</font>, and "
                "<font name='Courier'>ImmutableSegmentStore</font> are exported from <font name='Courier'>staqtapp_tds</font>.",
                styles["body"],
            ),
            Paragraph(
                "Detailed design and qualification records: docs/118_v353_dev10_Controlled_Activation.md and "
                "docs/119_v353_dev11_Release_Qualification.md.",
                styles["small"],
            ),
            Spacer(1, 8),
            Paragraph("Current API index", styles["h2"]),
            Paragraph(
                "Use docs/reference/Programmers_API_Reference.md for the current v3.5.3 storage API index. "
                "The separate Staqtapp_TDS_API_Surface_Reference.pdf is a historical v3.1.23 Driver/Studio "
                "reference and is not an exhaustive inventory of v3.5.3.",
                styles["body"],
            ),
        ]
    )

    story.append(PageBreak())
    story.extend(
        [
            Paragraph("Controlled activation operational contract", styles["h1"]),
            Paragraph(
                "Construct the controller with separate guaranteed and legacy roots. First inspect the default mode, "
                "then qualify exact equivalence. Passing the qualification object alone is insufficient: the explicit "
                "acknowledgement is a separate operator-intent gate.",
                styles["body"],
            ),
            Preformatted(
                """from staqtapp_tds import ControlledStorage, StorageMode

store = ControlledStorage(guaranteed_root, legacy_mount)
assert store.status().mode is StorageMode.LEGACY

qualification = store.qualify_activation()
assert qualification.activation_eligible

active = store.activate(
    qualification,
    acknowledgement=store.ACTIVATE_ACKNOWLEDGEMENT,
)
assert active.mode is StorageMode.GUARANTEED_SEGMENTED
assert active.current_generation_verified""",
                styles["code"],
            ),
            Paragraph("Mode-aware commit", styles["h2"]),
            Paragraph(
                "<font name='Courier'>commit_filesystem(fs, parallel_nodes=True)</font> writes through the currently "
                "authorized path and returns <font name='Courier'>ControlledCommitReport</font>. The report identifies "
                "the mode, generation when applicable, archived file and source-byte counts, created/reused segments, "
                "and physical bytes written.",
                styles["body"],
            ),
            Paragraph("Verified rollback", styles["h2"]),
            Preformatted(
                """rolled = store.rollback_to_legacy(
    acknowledgement=store.ROLLBACK_ACKNOWLEDGEMENT,
)
assert rolled.mode is StorageMode.LEGACY
assert rolled.previous_mode is StorageMode.GUARANTEED_SEGMENTED""",
                styles["code"],
            ),
            Paragraph(
                "The rollback acknowledgement is exactly <font name='Courier'>rollback-to-legacy</font>. The original "
                "legacy mount is never overwritten. The current segmented generation is materialized to a private "
                "destination, its exact inventory and logical reopen behavior are verified, and only that new mount "
                "can become authoritative.",
                styles["body"],
            ),
            Paragraph("Observation", styles["h2"]),
            Paragraph(
                "<font name='Courier'>status(verify_current=True)</font> returns a bounded typed view containing mode, "
                "revision, qualification and current generation identifiers, activation verification, current-generation "
                "verification, rollback availability, and the authoritative legacy mount. Admin/Browser status exposes "
                "the same storage mode without becoming a control path.",
                styles["body"],
            ),
            Paragraph(
                "<b>Operator rule.</b> Treat qualification receipts and mode state as authority records. "
                "Do not edit them manually, reuse a "
                "qualification after source changes, or automate the acknowledgement strings as an implicit fallback.",
                styles["callout"],
            ),
        ]
    )

    story.append(PageBreak())
    story.extend(
        [
            Paragraph("Phase 11 GC and release qualification", styles["h1"]),
            Paragraph("Closed-world segment collection", styles["h2"]),
            Paragraph(
                "Destructive collection now inventories every recognized generation. If any generation is invalid or "
                "unreadable, collection is blocked and reports its identifier; public reference accounting also fails "
                "closed. For each candidate, reachability is recomputed twice and the regular-file type, device, inode, "
                "size, mode, mtime, and ctime are revalidated immediately before unlink.",
                styles["body"],
            ),
            Preformatted(
                """from staqtapp_tds import ImmutableSegmentStore

segments = ImmutableSegmentStore(root)
preview = segments.collect_unreferenced_segments(dry_run=True)
if preview.blocked:
    raise RuntimeError(preview.invalid_generations)

# Destructive and explicit. Recomputes protection; does not trust preview.
report = segments.collect_unreferenced_segments(dry_run=False)
assert not report.blocked""",
                styles["code"],
            ),
            _bullet("Changed candidates are retained and reported separately; only successful unlinks count toward removed bytes.", styles["body"]),
            _bullet("The mutation lock covers scan, both rechecks, and delete; interrupted collection is idempotently resumable.", styles["body"]),
            _bullet("Partially damaged generations preserve salvageable segments because incomplete evidence blocks deletion.", styles["body"]),
            Paragraph("Browser documentation evidence", styles["h2"]),
            Paragraph(
                "The prior single Dashboard image and unsupported CSV description were removed. The repository now "
                "contains 19 distinct 1280 x 800 captures made by selecting every real Browser navigation control. "
                "Page 07 is the actual CSV Interpole Monitor after a real evidence chain reached Monitor Ready.",
                styles["body"],
            ),
            Paragraph("Local release evidence", styles["h2"]),
            _bullet("Pure monolithic suite: 832 passed, 11 skipped (843 collected) in 55.07 seconds.", styles["body"]),
            _bullet("Native-extension build/install and native-active monolithic suite: 843 passed in 55.89 seconds.", styles["body"]),
            _bullet("Overlapping v3.5.3, workflow, Browser visual, and CSV monitor qualification group: 157 passed.", styles["body"]),
            _bullet("PEP 517 wheel and sdist built; both passed twine metadata validation and archive-content audit.", styles["body"]),
            _bullet("The isolated pure wheel exercised version, qualification, activation, rollback, and destructive GC successfully.", styles["body"]),
            Paragraph(
                "Local qualification makes a review-branch push eligible. No push, tag, or publication is performed by "
                "this record. A v3.5.3 tag and PyPI publication remain prohibited until the configured Linux, Windows, "
                "macOS, Python 3.10-3.14, native, source-hygiene, and package jobs are green in GitHub Actions.",
                styles["callout"],
            ),
        ]
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _normalize_light_blue_signature_strips(
    writer: PdfWriter,
    *,
    first_base_page: int,
) -> int:
    """Remove excess top padding that overlaps the heading above each strip.

    The historical guide has exactly two strip geometries. Keeping the lower
    edge fixed while reducing only the height leaves every signature and the
    following description in place. The resulting two-point top inset clears
    the preceding class/method heading consistently.
    """
    changed = 0
    for page in writer.pages[first_base_page:]:
        contents = page.get_contents()
        if contents is None:
            continue
        stream = ContentStream(contents, writer)
        fill: tuple[float, float, float] | None = None
        page_changed = False
        for operands, operator in stream.operations:
            if operator == b"rg":
                fill = tuple(round(float(value), 6) for value in operands)
                continue
            if operator != b"re" or fill != LIGHT_BLUE_SIGNATURE_FILL:
                continue
            height = float(operands[3])
            if abs(height - 14.0) < 0.01:
                operands[3] = FloatObject(12.0)
            elif abs(height - 21.2) < 0.01:
                operands[3] = FloatObject(15.0)
            else:
                raise RuntimeError(f"unexpected light-blue signature strip height: {height}")
            changed += 1
            page_changed = True
        if page_changed:
            page.replace_contents(stream)
    return changed


def update_guide(input_path: Path, output_path: Path) -> None:
    reader = PdfReader(str(input_path))
    spacing_already_fixed = (
        (reader.metadata or {}).get(LABEL_SPACING_METADATA_KEY)
        == LABEL_SPACING_VERSION
    )
    raw_count = (reader.metadata or {}).get(SUPPLEMENT_METADATA_KEY, "0")
    try:
        prior_supplement_pages = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("invalid existing supplement page marker") from exc
    if prior_supplement_pages < 0 or prior_supplement_pages >= len(reader.pages):
        raise RuntimeError("existing supplement page marker is out of range")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tds-v353-pdf-") as raw_temp:
        temp_dir = Path(raw_temp)
        supplement_path = temp_dir / "v353-release-supplement.pdf"
        staged_output = temp_dir / "programmer-guide.pdf"
        _build_supplement(supplement_path)
        supplement = PdfReader(str(supplement_path))

        writer = PdfWriter()
        writer.append(supplement, import_outline=False)
        supplement_count = len(supplement.pages)
        writer.add_outline_item("v3.5.3 release supplement", 0, bold=True)
        writer.add_outline_item("Controlled activation operational contract", 1)
        writer.add_outline_item("Phase 11 GC and release qualification", 2)
        writer.append(
            reader,
            pages=(prior_supplement_pages, len(reader.pages)),
            import_outline=True,
        )
        if not spacing_already_fixed:
            normalized = _normalize_light_blue_signature_strips(
                writer,
                first_base_page=supplement_count,
            )
            if normalized != 634:
                raise RuntimeError(
                    f"expected 634 light-blue signature strips, normalized {normalized}"
                )

        metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
        metadata.update(
            {
                "/Title": "Staqtapp-TDS v3.5.3 Programmer Core API Guide",
                "/Subject": SUPPLEMENT_MARKER,
                "/Author": "Staqtapp-TDS contributors",
                SUPPLEMENT_METADATA_KEY: str(supplement_count),
                LABEL_SPACING_METADATA_KEY: LABEL_SPACING_VERSION,
            }
        )
        writer.add_metadata(metadata)
        with staged_output.open("wb") as handle:
            writer.write(handle)

        check = PdfReader(str(staged_output))
        if len(check.pages) != len(reader.pages) - prior_supplement_pages + supplement_count:
            raise RuntimeError("updated guide page count is incorrect")
        if (check.metadata or {}).get(SUPPLEMENT_METADATA_KEY) != str(supplement_count):
            raise RuntimeError("updated guide is missing its supplement marker")
        if (check.metadata or {}).get(LABEL_SPACING_METADATA_KEY) != LABEL_SPACING_VERSION:
            raise RuntimeError("updated guide is missing its label-spacing marker")

        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            replacement = Path(handle.name)
            handle.write(staged_output.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(replacement, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("tds_api_docs/Staqtapp_TDS_Programmer_Core_API_Guide.pdf"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input
    update_guide(args.input, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
