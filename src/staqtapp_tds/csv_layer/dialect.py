"""CSV dialect detection and fingerprinting."""

from __future__ import annotations

import csv
from typing import Iterable

from .artifacts import CSVDialectFingerprint


def _line_terminator_sample(text: str) -> str:
    # Search bounded windows so common early line endings stop immediately,
    # while a newline-free source makes two C-level passes instead of the
    # former three full-string searches.
    window = 64 << 10
    for start in range(0, len(text), window):
        end = min(start + window, len(text))
        lf = text.find("\n", start, end)
        cr = text.find("\r", start, end)
        if lf < 0 and cr < 0:
            continue
        if cr >= 0 and (lf < 0 or cr < lf):
            if cr + 1 < len(text) and text[cr + 1] == "\n":
                return "\r\n"
            return "\r"
        return "\n"
    return "\n"


def _delimiter_score(text: str, delimiter: str) -> int:
    rows = [line for line in text.splitlines()[:20] if line.strip()]
    return _delimiter_score_rows(rows, delimiter)


def _delimiter_score_rows(rows: list[str], delimiter: str) -> int:
    if not rows:
        return 0
    counts = [line.count(delimiter) for line in rows]
    positive = [c for c in counts if c > 0]
    if not positive:
        return 0
    return min(positive) * len(positive) - (max(positive) - min(positive))


def detect_csv_dialect(text: str, *, delimiters: Iterable[str] = (",", ";", "\t", "|")) -> CSVDialectFingerprint:
    """Return a stable dialect fingerprint for CSV text.

    The stdlib sniffer is used first. When it cannot decide, TDS falls back to a
    deterministic delimiter score so imports remain non-halting for unusual but
    still parseable CSV files.
    """
    sample = text[:65536]
    delimiters = tuple(delimiters)
    warnings: list[str] = []
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters="".join(delimiters))
        source = "sniffer"
        delimiter = sniffed.delimiter
        quotechar = sniffed.quotechar or '"'
        escapechar = sniffed.escapechar
        doublequote = bool(sniffed.doublequote)
        skipinitialspace = bool(sniffed.skipinitialspace)
        quoting = int(sniffed.quoting)
        confidence = 0.92
    except Exception:
        source = "deterministic-fallback"
        rows = [line for line in sample.splitlines()[:20] if line.strip()]
        scores = {
            candidate: _delimiter_score_rows(rows, candidate)
            for candidate in delimiters
        }
        delimiter = max(delimiters, key=scores.__getitem__)
        quotechar = '"'
        escapechar = None
        doublequote = True
        skipinitialspace = False
        quoting = int(csv.QUOTE_MINIMAL)
        confidence = 0.60 if scores[delimiter] > 0 else 0.25
        warnings.append("sniffer_failed")
    try:
        has_header = bool(csv.Sniffer().has_header(sample))
    except Exception:
        has_header = False
        warnings.append("header_sniffer_failed")
    if warnings and source == "sniffer":
        source = "sniffer-with-fallbacks"
    return CSVDialectFingerprint(
        delimiter=delimiter,
        quotechar=quotechar,
        escapechar=escapechar,
        doublequote=doublequote,
        skipinitialspace=skipinitialspace,
        lineterminator=_line_terminator_sample(text),
        quoting=quoting,
        has_header=has_header,
        confidence=confidence,
        source=source,
    )


def dialect_to_csv_kwargs(dialect: CSVDialectFingerprint) -> dict[str, object]:
    """Convert a TDS fingerprint to csv.reader/csv.writer kwargs."""
    return {
        "delimiter": dialect.delimiter,
        "quotechar": dialect.quotechar,
        "escapechar": dialect.escapechar,
        "doublequote": dialect.doublequote,
        "skipinitialspace": dialect.skipinitialspace,
        "quoting": dialect.quoting,
    }
