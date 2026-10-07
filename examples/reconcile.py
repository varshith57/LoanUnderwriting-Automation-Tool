"""Illustration of statement reconciliation: prove an extraction instead of trusting it.

A bank statement carries its own redundancy. If every row is read correctly:

    balance[n] == balance[n-1] + credit - debit          (every row)
    opening + sum(credits) - sum(debits) == closing      (whole statement)

Misread one digit, drop a row, or put a number in the wrong column, and at least one
identity breaks, at a row you can point to. Standalone, standard library only.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Row:
    date: str
    narration: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass
class Check:
    name: str
    expected: Decimal
    found: Decimal

    @property
    def ok(self) -> bool:
        return self.expected == self.found

    @property
    def delta(self) -> Decimal:
        return self.found - self.expected


def reconcile(
    rows: list[Row],
    opening: Decimal,
    closing: Decimal,
    total_credits: Decimal,
    total_debits: Decimal,
) -> tuple[str, list[Check], list[int]]:
    """Return (status, checks, rows where the balance chain breaks)."""
    breaks = []
    previous = opening
    for i, row in enumerate(rows):
        if previous + row.credit - row.debit != row.balance:
            breaks.append(i)
        previous = row.balance

    credits = sum((r.credit for r in rows), Decimal("0"))
    debits = sum((r.debit for r in rows), Decimal("0"))
    checks = [
        Check("total credits", total_credits, credits),
        Check("total debits", total_debits, debits),
        Check("opening + credits - debits = closing", closing, opening + credits - debits),
    ]
    status = "passed" if not breaks and all(c.ok for c in checks) else "failed"
    return status, checks, breaks


def report(title: str, rows: list[Row], **printed: Decimal) -> None:
    status, checks, breaks = reconcile(rows, **printed)
    print(f"\n{title}: {status.upper()}")
    for c in checks:
        mark = "ok " if c.ok else "BAD"
        print(f"  [{mark}] {c.name}: expected {c.expected}, found {c.found}, delta {c.delta}")
    for i in breaks:
        print(f"  balance chain breaks at row {i + 1}: {rows[i].narration}")


def d(value: str) -> Decimal:
    return Decimal(value)


if __name__ == "__main__":
    # Printed by the bank on the statement's summary block (synthetic figures).
    printed = dict(
        opening=d("50000.00"),
        closing=d("118450.00"),
        total_credits=d("95000.00"),
        total_debits=d("26550.00"),
    )
    rows = [
        Row("01-Mar", "POS SETTLEMENT", d("0"), d("45000.00"), d("95000.00")),
        Row("02-Mar", "TRF TO SUPPLIER LTD", d("25000.00"), d("0"), d("70000.00")),
        Row("02-Mar", "SMS ALERT CHARGE", d("50.00"), d("0"), d("69950.00")),
        Row("04-Mar", "TRF FROM CUSTOMER A", d("0"), d("50000.00"), d("119950.00")),
        Row("05-Mar", "VAT ON TRANSFER FEE", d("1500.00"), d("0"), d("118450.00")),
    ]
    report("Correct extraction", rows, **printed)

    # The same statement with one digit misread: 50000.00 read as 56000.00.
    misread = list(rows)
    misread[3] = Row("04-Mar", "TRF FROM CUSTOMER A", d("0"), d("56000.00"), d("119950.00"))
    report("One digit misread", misread, **printed)
