"""PDF statement -> rows, using one small JSON template per bank layout.

Generic table detection is unreliable on bank statements, so this reads every word with its
coordinates, groups words into lines by their vertical position, and assigns each word to a
column by where its centre falls, as a fraction of the page width (some banks size the page
to its content, so absolute positions do not carry over between files).

Nothing here decides whether the rows are right. That is validate.py's job: extraction reads,
validation proves.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymupdf

from .money import ZERO, parse_money

TEMPLATE_DIR = Path(__file__).parent / "templates"
LINE_TOLERANCE = 3.0  # points; words whose tops are this close share a line


@dataclass
class Row:
    date: date
    narration: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    page: int
    reference: str = ""


@dataclass
class Extracted:
    template_id: str | None
    bank: str | None
    pages: int
    summary: dict = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Line:
    y: float
    words: list[tuple[float, float, str]]  # (x0, x1, text)

    @property
    def text(self) -> str:
        return " ".join(w[2] for w in self.words)


def load_templates() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(TEMPLATE_DIR.glob("*.json"))]


def page_lines(page: pymupdf.Page) -> list[Line]:
    words = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
    lines: list[Line] = []
    for x0, y0, x1, _y1, text, *_ in words:
        if lines and abs(y0 - lines[-1].y) <= LINE_TOLERANCE:
            lines[-1].words.append((x0, x1, text))
        else:
            lines.append(Line(y0, [(x0, x1, text)]))
    for line in lines:
        line.words.sort()
    return lines


def header_index(lines: list[Line], marker: str) -> int | None:
    for i, line in enumerate(lines):
        if marker.lower() in line.text.lower():
            return i
    return None


def detect(first_page_lines: list[Line], templates: list[dict]) -> tuple[dict | None, str]:
    """Pick the template whose phrases all appear in the page-1 header area.

    Only the text above the transaction table counts: narrations name other banks all the
    time ("TRF FROM ... /LAGOON PAY"), and reading them would let one bank's template claim
    another bank's statement.
    """
    matches = []
    for t in templates:
        cut = header_index(first_page_lines, t["table"]["header_marker"])
        if cut is None:
            continue
        header_text = "\n".join(line.text for line in first_page_lines[:cut]).lower()
        if all(phrase.lower() in header_text for phrase in t["detect"]):
            matches.append(t)
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, "No layout template recognises this statement (unknown bank or layout)."
    names = ", ".join(t["id"] for t in matches)
    return None, f"More than one template claims this statement ({names}); refusing to guess."


def read_summary(header_lines: list[Line], spec: dict) -> dict:
    text = "\n".join(line.text for line in header_lines)
    out: dict = {}
    for name, rule in spec.items():
        m = re.search(rule["pattern"], text)
        if not m:
            continue
        value = m.group(1).strip()
        if rule["type"] == "money":
            out[name] = parse_money(value)
        elif rule["type"] == "int":
            out[name] = int(value)
        else:
            out[name] = value
    return out


def cells(line: Line, columns: dict[str, list[float]], width: float) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for x0, x1, text in line.words:
        centre = (x0 + x1) / 2 / width
        for name, (lo, hi) in columns.items():
            if lo <= centre < hi:
                out.setdefault(name, []).append(text)
                break
    return {k: " ".join(v) for k, v in out.items()}


def amount(cell: str, warnings: list[str], where: str) -> Decimal:
    if not cell:
        return ZERO
    try:
        return parse_money(cell)
    except ValueError:
        # Keep the row with a zero so the totals check fails loudly at this row,
        # rather than dropping it and hoping someone notices.
        warnings.append(f"{where}: could not read amount {cell!r}")
        return ZERO


def extract(pdf: bytes) -> Extracted:
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except Exception:
        return Extracted(None, None, 0, warnings=["This file is not a readable PDF."])

    with doc:
        pages = [page_lines(p) for p in doc]
        widths = [p.rect.width for p in doc]

    result = Extracted(None, None, len(pages))
    for n, lines in enumerate(pages, start=1):
        if not lines:
            result.warnings.append(
                f"Page {n} has no text layer (scanned image?). It was not guessed at."
            )
    if not pages or not pages[0]:
        result.warnings.append("No readable text on the first page.")
        return result

    template, problem = detect(pages[0], load_templates())
    if template is None:
        result.warnings.append(problem)
        return result

    table = template["table"]
    result.template_id, result.bank = template["id"], template["bank"]
    first_header = header_index(pages[0], table["header_marker"])
    result.summary = read_summary(pages[0][:first_header], template["summary"])

    date_re = re.compile(table["date_pattern"])
    footer_re = re.compile(table["footer_pattern"])
    columns = table["columns"]

    for page_no, (lines, width) in enumerate(zip(pages, widths, strict=True), start=1):
        start = header_index(lines, table["header_marker"])
        if start is None:
            if lines:
                result.warnings.append(f"Page {page_no}: table header not found; page skipped.")
            continue
        for line in lines[start + 1 :]:
            if footer_re.match(line.text):
                continue
            c = cells(line, columns, width)
            where = f"page {page_no}, line '{line.text[:40]}'"
            if date_re.match(c.get("date", "")):
                if table["amounts"] == "signed":
                    signed = amount(c.get("amount", ""), result.warnings, where)
                    debit, credit = (-signed, ZERO) if signed < 0 else (ZERO, signed)
                else:
                    debit = amount(c.get("debit", ""), result.warnings, where)
                    credit = amount(c.get("credit", ""), result.warnings, where)
                result.rows.append(
                    Row(
                        date=datetime.strptime(c["date"], table["date_format"]).date(),
                        narration=c.get("narration", ""),
                        debit=debit,
                        credit=credit,
                        balance=amount(c.get("balance", ""), result.warnings, where),
                        page=page_no,
                        reference=c.get("reference", ""),
                    )
                )
            elif table["narration_wraps"] and result.rows and set(c) == {"narration"}:
                result.rows[-1].narration += " " + c["narration"]
            else:
                result.warnings.append(f"{where}: not a transaction row; ignored.")
    return result
