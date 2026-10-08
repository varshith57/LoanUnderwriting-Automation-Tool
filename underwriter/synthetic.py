"""Invented bank statements for the demo and the tests.

Every bank, business, person, account number and figure here is made up. Two fictional
layouts are rendered so the template system has something to do:

- Harbor Bank: A4, debit and credit columns, narrations that wrap onto a second line.
- Lagoon Pay: US letter (a different page width), one signed amount column, a two-column
  summary grid and a printed transaction count.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pymupdf

from .money import ZERO, fmt

FONT = "helv"
CUSTOMERS = [
    "CHIDI OKAFOR",
    "AMAKA EZE",
    "BELLO TRADING CO",
    "FUNKE ADEYEMI",
    "IBRAHIM MUSA",
    "GRACE OKON",
    "TUNDE BAKARE",
    "NGOZI OBI",
    "EMEKA STORES",
    "HALIMA SANI",
    "SEGUN ALADE",
    "ZAINAB ALI",
]
SUPPLIERS = [
    "PRIME FOODS WHOLESALE",
    "CITYLINK LOGISTICS",
    "GOLDEN GRAINS SUPPLY",
    "SUNRISE PACKAGING",
]
LENDER = "QUICKCREDIT"


@dataclass
class Txn:
    day: date
    kind: str
    party: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    narration: str = ""
    balance: Decimal = ZERO


@dataclass
class Profile:
    owner: str
    bank: str  # "harbor" or "lagoon"
    seed: int
    opening: Decimal = Decimal("85000.00")
    start: date = date(2026, 6, 1)
    end: date = date(2026, 8, 31)
    pos_per_day: tuple[int, int] = (1, 3)
    pos_amount: tuple[int, int] = (4000, 38000)
    transfers_in_per_day: float = 0.7
    transfer_amount: tuple[int, int] = (15000, 110000)
    big_customer: str | None = None
    big_customer_odds: float = 0.0
    big_customer_amount: tuple[int, int] = (150000, 420000)
    spend_ratio: tuple[float, float] = (0.70, 0.88)
    loan: tuple[int, int] | None = None  # (amount disbursed, weekly repayment)
    self_transfers_per_month: int = 2
    unreadable_per_month: int = 1
    tamper_row: int | None = None  # print the n-th credit wrongly, balance untouched


@dataclass
class Statement:
    profile: Profile
    account_number: str
    txns: list[Txn] = field(default_factory=list)

    @property
    def closing(self) -> Decimal:
        return self.txns[-1].balance if self.txns else self.profile.opening


def amount(rng: random.Random, lo: int, hi: int) -> Decimal:
    return Decimal(rng.randrange(lo * 100, hi * 100)) / 100


def ref(rng: random.Random) -> str:
    return str(rng.randrange(10**9, 10**10))


def narration(bank: str, t: Txn, rng: random.Random, owner: str) -> str:
    r = ref(rng)
    if bank == "harbor":
        suffix = rng.choice(["", "/LAGOON PAY", "/MOBILE"])
        return {
            "pos": f"POS SETTLEMENT/TID {rng.randrange(2000, 2999)}/{r}",
            "customer": f"TRF FROM {t.party}{suffix}/{r}",
            "self": f"TRF FROM {owner}/OWN ACCOUNT/{r}",
            "supplier": f"TRF TO {t.party}/{r}",
            "fee": t.party,
            "loan_in": f"LOAN DISBURSEMENT {LENDER}/{r}",
            "loan_repayment": f"LOAN REPAYMENT {LENDER}/{r}",
            "reversal": f"REVERSAL: TRF TO {t.party}/{r}",
            "unreadable": f"MOB/UTO/{r}/ZX{rng.randrange(10, 99)}",
        }[t.kind]
    return {
        "pos": f"Card settlement - terminal {rng.randrange(7000, 7999)}",
        "customer": f"Inward transfer from {t.party.title()}",
        "self": f"Inward transfer from {owner.title()}",
        "supplier": f"Transfer to {t.party.title()}",
        "fee": t.party,
        "loan_in": f"Loan disbursed - {LENDER.title()}",
        "loan_repayment": f"Loan repayment - {LENDER.title()}",
        "reversal": f"Reversal of transfer to {t.party.title()}",
        "unreadable": f"QR {r} AX",
    }[t.kind]


def generate(p: Profile) -> Statement:
    rng = random.Random(p.seed)
    st = Statement(p, str(rng.randrange(10**9, 10**10)))
    raw: list[Txn] = []
    day = p.start
    week_in = ZERO
    months_seen: set[int] = set()
    reversal_done = False
    while day <= p.end:
        if day.weekday() < 6:  # Mon-Sat trading
            for _ in range(rng.randint(*p.pos_per_day)):
                raw.append(Txn(day, "pos", "", credit=amount(rng, *p.pos_amount)))
            for _ in range(
                (rng.random() < p.transfers_in_per_day)
                + (rng.random() < p.transfers_in_per_day / 2)
            ):
                if p.big_customer and rng.random() < p.big_customer_odds:
                    raw.append(
                        Txn(
                            day,
                            "customer",
                            p.big_customer,
                            credit=amount(rng, *p.big_customer_amount),
                        )
                    )
                else:
                    raw.append(
                        Txn(
                            day,
                            "customer",
                            rng.choice(CUSTOMERS),
                            credit=amount(rng, *p.transfer_amount),
                        )
                    )
        if day.month not in months_seen:
            months_seen.add(day.month)
            for _ in range(p.self_transfers_per_month):
                when = day + timedelta(days=rng.randrange(3, 25))
                raw.append(Txn(when, "self", p.owner, credit=amount(rng, 20000, 90000)))
            for _ in range(p.unreadable_per_month):
                when = day + timedelta(days=rng.randrange(1, 26))
                raw.append(Txn(when, "unreadable", "", credit=amount(rng, 5000, 30000)))
            if p.loan and day == p.start:
                raw.append(
                    Txn(day + timedelta(days=2), "loan_in", LENDER, credit=Decimal(p.loan[0]))
                )
        week_in += sum((t.credit for t in raw if t.day == day), ZERO)
        if day.weekday() == 4:  # Friday: pay suppliers and lenders
            budget = week_in * Decimal(str(rng.uniform(*p.spend_ratio)))
            for _ in range(2):
                raw.append(
                    Txn(
                        day,
                        "supplier",
                        rng.choice(SUPPLIERS),
                        debit=(budget / 2).quantize(Decimal("0.01")),
                    )
                )
                if not reversal_done and day > p.start + timedelta(days=30):
                    raw.append(Txn(day, "reversal", raw[-1].party, credit=raw[-1].debit))
                    reversal_done = True
            if p.loan and day > p.start + timedelta(days=7):
                raw.append(Txn(day, "loan_repayment", LENDER, debit=Decimal(p.loan[1])))
            week_in = ZERO
        if day.day == 28:
            raw.append(
                Txn(
                    day,
                    "fee",
                    "SMS ALERT CHARGES" if p.bank == "harbor" else "Stamp duty",
                    debit=Decimal("100.00") if p.bank == "harbor" else Decimal("50.00"),
                )
            )
        day += timedelta(days=1)

    raw = [t for t in raw if t.day <= p.end]
    # Within a day: money in, then money out, then any reversal of that day's payment.
    raw.sort(key=lambda t: (t.day, t.kind == "reversal", t.debit > 0))

    balance = p.opening
    for t in raw:
        if t.debit and t.debit > balance - Decimal("500"):
            continue  # never overdraw: the business would not have had the money
        t.narration = narration(p.bank, t, rng, p.owner)
        balance += t.credit - t.debit
        t.balance = balance
        st.txns.append(t)
        if t.kind in ("supplier",) and p.bank == "harbor":
            for label, fee in (
                ("NIP TRANSFER FEE", Decimal("25.00")),
                ("VAT ON NIP TRANSFER FEE", Decimal("1.88")),
            ):
                balance -= fee
                st.txns.append(
                    Txn(t.day, "fee", label, debit=fee, narration=label, balance=balance)
                )
        elif t.kind == "supplier":
            balance -= Decimal("10.00")
            st.txns.append(
                Txn(
                    t.day,
                    "fee",
                    "Transfer charge",
                    debit=Decimal("10.00"),
                    narration="Transfer charge",
                    balance=balance,
                )
            )
    return st


# ---------------------------------------------------------------------------------- rendering


def right(page: pymupdf.Page, x_right: float, y: float, text: str, size: float = 8) -> None:
    w = pymupdf.get_text_length(text, fontname=FONT, fontsize=size)
    page.insert_text((x_right - w, y), text, fontname=FONT, fontsize=size)


def left(page: pymupdf.Page, x: float, y: float, text: str, size: float = 8) -> None:
    page.insert_text((x, y), text, fontname=FONT, fontsize=size)


def wrap(text: str, width: int) -> list[str]:
    """Split on spaces only, so joining the pieces with a space gives the text back."""
    lines, current = [], ""
    for word in text.split(" "):
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    return lines + [current]


def totals(st: Statement) -> tuple[Decimal, Decimal]:
    return (sum((t.credit for t in st.txns), ZERO), sum((t.debit for t in st.txns), ZERO))


def shown_credit(st: Statement, i: int, t: Txn) -> Decimal:
    """The credit as printed. A tampered sample inflates the tamper_row-th credit by 60,000
    and leaves its balance alone, the way a hand-edited PDF usually looks."""
    n = st.profile.tamper_row
    if n is not None and i == [j for j, x in enumerate(st.txns) if x.credit][n]:
        return t.credit + Decimal("60000.00")
    return t.credit


def render_harbor(st: Statement) -> bytes:
    p = st.profile
    doc = pymupdf.open()
    credits, debits = totals(st)
    page = doc.new_page(width=595, height=842)
    left(page, 36, 50, "HARBOR BANK PLC", 16)
    left(page, 36, 68, "Statement of Account", 10)
    y = 100
    for label, value in [
        ("Account Name:", p.owner),
        ("Account Number:", st.account_number),
        ("Period:", f"{p.start:%d-%b-%Y} to {p.end:%d-%b-%Y}"),
        ("Opening Balance:", fmt(p.opening)),
        ("Total Credits:", fmt(credits)),
        ("Total Debits:", fmt(debits)),
        ("Closing Balance:", fmt(st.closing)),
    ]:
        left(page, 36, y, label, 9)
        left(page, 150, y, value, 9)
        y += 14

    def header(pg: pymupdf.Page, y: float) -> float:
        left(pg, 36, y, "Trans Date")
        left(pg, 110, y, "Narration")
        right(pg, 380, y, "Debit")
        right(pg, 460, y, "Credit")
        right(pg, 559, y, "Balance")
        return y + 16

    y = header(page, y + 20)
    for i, t in enumerate(st.txns):
        lines = wrap(t.narration, 34)
        if y + 11 * len(lines) > 800:
            page = doc.new_page(width=595, height=842)
            y = header(page, 60)
        left(page, 36, y, f"{t.day:%d-%b-%Y}")
        left(page, 110, y, lines[0])
        if t.debit:
            right(page, 380, y, fmt(t.debit))
        if t.credit:
            right(page, 460, y, fmt(shown_credit(st, i, t)))
        right(page, 559, y, fmt(t.balance))
        for extra in lines[1:]:
            y += 10
            left(page, 110, y, extra)
        y += 12
    for n, pg in enumerate(doc, start=1):
        left(pg, 270, 825, f"Page {n} of {doc.page_count}", 7)
    return doc.tobytes()


def render_lagoon(st: Statement) -> bytes:
    p = st.profile
    doc = pymupdf.open()
    credits, debits = totals(st)
    page = doc.new_page(width=612, height=792)
    left(page, 36, 50, "Lagoon Pay", 18)
    left(page, 36, 68, "Account statement", 10)
    left(page, 36, 96, "Account holder", 9)
    left(page, 150, 96, p.owner.title(), 9)
    left(page, 36, 110, "Wallet number", 9)
    left(page, 150, 110, st.account_number, 9)
    left(page, 36, 124, "Period", 9)
    left(page, 150, 124, f"{p.start:%d/%m/%Y} - {p.end:%d/%m/%Y}", 9)
    grid = [
        (("Balance at start", p.opening), ("Money in", credits)),
        (("Balance at end", st.closing), ("Money out", debits)),
    ]
    y = 150
    for (l1, v1), (l2, v2) in grid:
        left(page, 36, y, l1, 9)
        left(page, 150, y, fmt(v1), 9)
        left(page, 320, y, l2, 9)
        left(page, 430, y, fmt(v2), 9)
        y += 14
    left(page, 36, y, "Transactions", 9)
    left(page, 150, y, str(len(st.txns)), 9)

    def header(pg: pymupdf.Page, y: float) -> float:
        left(pg, 36, y, "Date")
        left(pg, 100, y, "Reference")
        left(pg, 190, y, "Description")
        right(pg, 470, y, "Amount")
        right(pg, 576, y, "Balance")
        return y + 16

    rng = random.Random(p.seed + 1)
    y = header(page, y + 30)
    for i, t in enumerate(st.txns):
        if y > 750:
            page = doc.new_page(width=612, height=792)
            y = header(page, 60)
        left(page, 36, y, f"{t.day:%d/%m/%Y}")
        left(page, 100, y, f"LP{rng.randrange(10**9, 10**10)}")
        left(page, 190, y, t.narration[:40])
        signed = f"+{fmt(shown_credit(st, i, t))}" if t.credit else f"-{fmt(t.debit)}"
        right(page, 470, y, signed)
        right(page, 576, y, fmt(t.balance))
        y += 12
    for n, pg in enumerate(doc, start=1):
        left(pg, 36, 775, f"Lagoon Pay statement - page {n}", 7)
    return doc.tobytes()


def render(st: Statement) -> bytes:
    return render_harbor(st) if st.profile.bank == "harbor" else render_lagoon(st)


SAMPLES: dict[str, Profile] = {
    "Adebayo Stores · Harbor Bank (healthy shop)": Profile("ADEBAYO STORES LTD", "harbor", seed=11),
    "Mama Ngozi Kitchen · Lagoon Pay (one big customer)": Profile(
        "MAMA NGOZI KITCHEN",
        "lagoon",
        seed=22,
        pos_per_day=(0, 2),
        transfers_in_per_day=0.6,
        big_customer="BRIGHTPATH SCHOOLS",
        big_customer_odds=0.45,
    ),
    "Bello Fabrics · Lagoon Pay (already borrowing heavily)": Profile(
        "BELLO FABRICS VENTURES",
        "lagoon",
        seed=33,
        pos_per_day=(1, 2),
        transfers_in_per_day=0.4,
        loan=(1500000, 300000),
        opening=Decimal("350000.00"),
    ),
    "Okon Phones · Harbor Bank (edited PDF)": Profile(
        "OKON PHONES AND ACCESSORIES", "harbor", seed=44, tamper_row=57
    ),
}


def sample_pdf(name: str) -> bytes:
    return render(generate(SAMPLES[name]))
