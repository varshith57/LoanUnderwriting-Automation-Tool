"""Money is Decimal, to the kobo, everywhere. Floats never touch a figure."""

import re
from decimal import ROUND_DOWN, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

MONEY_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)\.\d{2}$")


def is_money(text: str) -> bool:
    return bool(MONEY_RE.match(text.strip()))


def parse_money(text: str) -> Decimal:
    """'1,234.50' -> Decimal('1234.50'); '+45,000.00' and '-25.00' keep their sign."""
    cleaned = text.replace(",", "").replace("₦", "").replace("NGN", "").strip()
    try:
        return Decimal(cleaned).quantize(CENT)
    except InvalidOperation as e:
        raise ValueError(f"not an amount: {text!r}") from e


def fmt(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def naira(amount: Decimal) -> str:
    return f"₦{amount:,.0f}"


def round_down(amount: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return amount
    return (amount / step).quantize(Decimal("1"), rounding=ROUND_DOWN) * step
