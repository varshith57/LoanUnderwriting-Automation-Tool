"""Verified rows -> who paid whom, what counts as sales, and monthly cash flow.

Turnover is not sales. Before anything is scored, money that is not trading income is taken
out, each with the rows that caused it:

- self-transfers (the owner moving their own money in from another account),
- loan disbursements (borrowed money is not revenue),
- reversals (a failed payment coming back).

A wording no grammar can read is kept as "unidentified" with its amount, never quietly
counted as sales or as "no counterparty".
"""

import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .extract import Row
from .money import ZERO

GRAMMARS = json.loads((Path(__file__).parent / "grammars.json").read_text())
COMPILED = [(g, re.compile(g["pattern"], re.IGNORECASE)) for g in GRAMMARS]

# Category labels shown in the UI.
SALES = "Sales"
SELF = "Own money moved in/out"
LOAN_IN = "Loan received"
LOAN_OUT = "Loan repayment"
REVERSAL = "Reversal"
FEES = "Bank charges"
PAY_OUT = "Payment out"
UNREAD_IN = "Unidentified money in"
UNREAD_OUT = "Unidentified money out"

POS_PARTY = "Card payments (POS)"
LOW_BALANCE = Decimal("10000")
NAME_NOISE = {
    "LTD",
    "LIMITED",
    "NIG",
    "NIGERIA",
    "ENTERPRISES",
    "ENT",
    "VENTURES",
    "AND",
    "&",
    "CO",
    "PLC",
    "STORES",
    "STORE",
    "SHOP",
    "MR",
    "MRS",
    "MS",
}


@dataclass
class Txn:
    row: Row
    party: str | None
    category: str
    grammar: str | None


@dataclass
class Month:
    label: str
    money_in: Decimal = ZERO
    sales: Decimal = ZERO
    money_out: Decimal = ZERO
    loan_repayments: Decimal = ZERO


@dataclass
class Analysis:
    txns: list[Txn]
    months: list[Month]
    full_months: int
    avg_monthly_sales: Decimal
    sales_volatility: float  # coefficient of variation of monthly sales
    top_customer: str | None
    top_customer_share: float  # of total sales
    avg_monthly_loan_repayments: Decimal
    unidentified_share: float  # of money in
    avg_daily_balance: Decimal
    low_balance_days_share: float
    by_category: dict[str, Decimal] = field(default_factory=dict)
    top_customers: list[tuple[str, Decimal]] = field(default_factory=list)


def name_tokens(name: str) -> set[str]:
    words = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    return {w for w in words if w not in NAME_NOISE and len(w) > 1}


def same_person(party: str, owners: list[str]) -> bool:
    p = name_tokens(party)
    if not p:
        return False
    for owner in owners:
        o = name_tokens(owner)
        if not o:
            continue
        if p == o or len(p & o) / len(p | o) >= 0.6:
            return True
        # One name inside the other ("ADEBAYO JOHNSON" in "ADEBAYO JOHNSON OLU") counts only
        # when the shorter one has two or more words: a lone surname is shared by strangers.
        smaller = min(p, o, key=len)
        if len(smaller) >= 2 and (p <= o or o <= p):
            return True
    return False


def tidy(party: str) -> str:
    return " ".join(party.split()).title()


def classify(row: Row, owners: list[str]) -> Txn:
    incoming = row.credit > 0
    for g, rx in COMPILED:
        m = rx.search(row.narration)
        if not m:
            continue
        kind = g["kind"]
        party = tidy(m.group("party")) if "party" in rx.groupindex else None
        if kind == "pos":
            return Txn(row, POS_PARTY, SALES if incoming else PAY_OUT, g["id"])
        if kind == "fee":
            return Txn(row, None, FEES, g["id"])
        if kind == "reversal":
            return Txn(row, party, REVERSAL, g["id"])
        if kind == "loan_in":
            return Txn(row, party, LOAN_IN, g["id"])
        if kind == "loan_repayment":
            return Txn(row, party, LOAN_OUT, g["id"])
        if party and same_person(party, owners):
            return Txn(row, party, SELF, g["id"])
        if kind == "transfer_in":
            return Txn(row, party, SALES, g["id"])
        return Txn(row, party, PAY_OUT, g["id"])
    return Txn(row, None, UNREAD_IN if incoming else UNREAD_OUT, None)


def daily_balances(rows: list[Row]) -> list[Decimal]:
    """End-of-day balance for every calendar day in the statement, carried forward."""
    eod: dict[date, Decimal] = {}
    for r in rows:
        eod[r.date] = r.balance
    day, last = rows[0].date, rows[-1].date
    out, current = [], eod[day]
    while day <= last:
        current = eod.get(day, current)
        out.append(current)
        day += timedelta(days=1)
    return out


def analyse(rows: list[Row], owners: list[str]) -> Analysis:
    txns = [classify(r, owners) for r in rows]

    months: dict[str, Month] = {}
    by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
    customers: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for t in txns:
        key = t.row.date.strftime("%Y-%m")
        m = months.setdefault(key, Month(t.row.date.strftime("%b %Y")))
        m.money_in += t.row.credit
        m.money_out += t.row.debit
        by_category[t.category] += t.row.credit + t.row.debit
        if t.category == SALES:
            m.sales += t.row.credit
            if t.party and t.party != POS_PARTY:
                customers[t.party] += t.row.credit
        if t.category == LOAN_OUT:
            m.loan_repayments += t.row.debit

    ordered = [months[k] for k in sorted(months)]
    full = full_months(rows)
    scored = [months[k] for k in sorted(months) if k in full] or ordered
    total_sales = sum((m.sales for m in scored), ZERO)
    avg_sales = (total_sales / len(scored)).quantize(Decimal("0.01"))
    monthly = [float(m.sales) for m in scored]
    volatility = (
        statistics.pstdev(monthly) / statistics.mean(monthly)
        if len(monthly) > 1 and statistics.mean(monthly) > 0
        else 0.0
    )

    all_sales = sum((t.row.credit for t in txns if t.category == SALES), ZERO)
    top = sorted(customers.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top_amount = top[0] if top else (None, ZERO)
    money_in = sum((r.credit for r in rows), ZERO)
    unread = sum((t.row.credit for t in txns if t.category == UNREAD_IN), ZERO)
    balances = daily_balances(rows)

    return Analysis(
        txns=txns,
        months=ordered,
        full_months=len(full),
        avg_monthly_sales=avg_sales,
        sales_volatility=volatility,
        top_customer=top_name,
        top_customer_share=float(top_amount / all_sales) if all_sales else 0.0,
        avg_monthly_loan_repayments=(
            sum((m.loan_repayments for m in scored), ZERO) / len(scored)
        ).quantize(Decimal("0.01")),
        unidentified_share=float(unread / money_in) if money_in else 0.0,
        avg_daily_balance=(sum(balances, ZERO) / len(balances)).quantize(Decimal("0.01")),
        low_balance_days_share=sum(1 for b in balances if b < LOW_BALANCE) / len(balances),
        by_category=dict(by_category),
        top_customers=top[:10],
    )


def full_months(rows: list[Row]) -> set[str]:
    """Months the statement covers from (near) the first to the last day.

    A statement that starts on the 20th has 10 days of that month; averaging it as a full
    month would understate sales. Allow a few days' slack for weekends and holidays.
    """
    first, last = rows[0].date, rows[-1].date
    out = set()
    for key in {r.date.strftime("%Y-%m") for r in rows}:
        y, m = map(int, key.split("-"))
        start = date(y, m, 1)
        end = (date(y + m // 12, m % 12 + 1, 1)) - timedelta(days=1)
        if first <= start + timedelta(days=4) and last >= end - timedelta(days=4):
            out.add(key)
    return out
