"""Prove the extracted rows against the figures the bank printed.

A statement carries its own redundancy:

    balance[n] == balance[n-1] + credit - debit          (every row)
    opening + sum(credits) - sum(debits) == closing      (whole statement)

A dropped row, a digit misread or a number in the wrong column breaks at least one of these,
at a row we can point to. So accuracy is proved, not estimated, and a statement that does not
reconcile is reported with the exact difference, never smoothed over.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from .extract import Extracted
from .money import ZERO, fmt

PASSED, REVIEW, FAILED = "passed", "review_required", "failed"


@dataclass
class Check:
    name: str
    expected: str
    found: str
    ok: bool


@dataclass
class Break:
    index: int  # 0-based row index
    expected_balance: Decimal
    printed_balance: Decimal

    @property
    def delta(self) -> Decimal:
        return self.printed_balance - self.expected_balance


@dataclass
class Validation:
    status: str
    reason: str
    checks: list[Check] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)


def money_check(name: str, expected: Decimal, found: Decimal) -> Check:
    delta = found - expected
    found_text = fmt(found) if delta == 0 else f"{fmt(found)} (off by {fmt(delta)})"
    return Check(name, fmt(expected), found_text, delta == 0)


def validate(ex: Extracted) -> Validation:
    if ex.template_id is None:
        reason = ex.warnings[0] if ex.warnings else "Statement layout not recognised."
        return Validation(REVIEW, reason)
    if not ex.rows:
        return Validation(REVIEW, "The layout was recognised but no transactions were read.")

    s = ex.summary
    rows = ex.rows
    checks: list[Check] = []

    # Balance chain. Without a printed opening balance, start from the first row itself.
    if "opening" in s:
        previous = s["opening"]
        start = 0
    else:
        previous = rows[0].balance
        start = 1
    breaks: list[Break] = []
    for i in range(start, len(rows)):
        row = rows[i]
        expected = previous + row.credit - row.debit
        if expected != row.balance:
            breaks.append(Break(i, expected, row.balance))
        previous = row.balance
    checks.append(
        Check(
            "Running balance on every row",
            f"{len(rows) - start} rows follow on",
            "all rows" if not breaks else f"{len(breaks)} row(s) break the chain",
            not breaks,
        )
    )

    credits = sum((r.credit for r in rows), ZERO)
    debits = sum((r.debit for r in rows), ZERO)
    if "total_credits" in s:
        checks.append(money_check("Total money in (printed)", s["total_credits"], credits))
    if "total_debits" in s:
        checks.append(money_check("Total money out (printed)", s["total_debits"], debits))
    if "opening" in s and "closing" in s:
        checks.append(
            money_check(
                "Opening + money in - money out = closing",
                s["closing"],
                s["opening"] + credits - debits,
            )
        )
        checks.append(money_check("Last row's balance = printed closing", s["closing"], previous))
    if "count" in s:
        checks.append(
            Check(
                "Number of transactions (printed)",
                str(s["count"]),
                str(len(rows)),
                s["count"] == len(rows),
            )
        )

    printed_totals = any(k in s for k in ("total_credits", "total_debits", "closing"))
    if not all(c.ok for c in checks):
        failed = [c.name for c in checks if not c.ok]
        return Validation(FAILED, "Does not reconcile: " + "; ".join(failed) + ".", checks, breaks)
    if ex.warnings:
        return Validation(
            REVIEW, "Reconciles, but some lines need a look: " + ex.warnings[0], checks, breaks
        )
    if not printed_totals:
        # Parsing cleanly is not the same as being verified.
        return Validation(REVIEW, "No printed totals to verify against.", checks, breaks)
    return Validation(
        PASSED, "Every figure reconciles exactly with the bank's printed totals.", checks, breaks
    )
