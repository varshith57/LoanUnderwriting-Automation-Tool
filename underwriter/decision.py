"""Policy rules -> approve / refer / decline, each with the figure and the threshold behind it.

The decision is only as good as the figures, so it is gated on validation first: a statement
that does not reconcile gets no decision at all, rather than a decision built on numbers we
already know are wrong.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .analysis import Analysis
from .money import ZERO, naira, round_down
from .validate import FAILED, REVIEW, Validation

POLICY = json.loads((Path(__file__).parent / "policy.json").read_text())

APPROVE, REFER, DECLINE, NO_DECISION = (
    "Approve",
    "Refer to an underwriter",
    "Decline",
    "No decision",
)


@dataclass
class Rule:
    name: str
    value: str
    threshold: str
    passed: bool
    effect: str  # what failing it does: "decline" or "refer"
    why: str


@dataclass
class Decision:
    outcome: str
    headline: str
    offer: Decimal = ZERO
    rules: list[Rule] = field(default_factory=list)


def pct(x: float) -> str:
    return f"{x:.0%}"


def decide(validation: Validation, analysis: Analysis | None, policy: dict = POLICY) -> Decision:
    if validation.status == FAILED or analysis is None:
        return Decision(
            NO_DECISION,
            "The figures could not be proved, so no decision is made. " + validation.reason,
        )

    a, p = analysis, policy
    burden = (
        float(a.avg_monthly_loan_repayments / a.avg_monthly_sales) if a.avg_monthly_sales else 1.0
    )
    rules = [
        Rule(
            "Statement figures proved",
            validation.status.replace("_", " "),
            "passed",
            validation.status != REVIEW,
            "refer",
            "A person must check a statement the engine could not fully verify.",
        ),
        Rule(
            "Months of history",
            str(a.full_months),
            f"at least {p['min_full_months']}",
            a.full_months >= p["min_full_months"],
            "refer",
            "Too short a history says little about a business's normal months.",
        ),
        Rule(
            "Average monthly sales",
            naira(a.avg_monthly_sales),
            f"at least {naira(Decimal(p['min_avg_monthly_sales']))}",
            a.avg_monthly_sales >= p["min_avg_monthly_sales"],
            "decline",
            "Sales exclude own-money transfers, loans received and reversals.",
        ),
        Rule(
            "Existing loan repayments / sales",
            pct(burden),
            f"at most {pct(p['max_loan_burden'])}",
            burden <= p["max_loan_burden"],
            "decline",
            "Repayments already owed to other lenders come out of the same cash.",
        ),
        Rule(
            "Largest single customer's share",
            pct(a.top_customer_share),
            f"at most {pct(p['max_top_customer_share'])}",
            a.top_customer_share <= p["max_top_customer_share"],
            "refer",
            f"Losing {a.top_customer or 'one customer'} would cut sales sharply.",
        ),
        Rule(
            "Money in we could not read",
            pct(a.unidentified_share),
            f"at most {pct(p['max_unidentified_share'])}",
            a.unidentified_share <= p["max_unidentified_share"],
            "refer",
            "Unread money might be the owner's own, or a loan; a person should look.",
        ),
        Rule(
            "Month-to-month swing in sales",
            pct(a.sales_volatility),
            f"at most {pct(p['max_sales_volatility'])}",
            a.sales_volatility <= p["max_sales_volatility"],
            "refer",
            "Very uneven months make a fixed repayment risky.",
        ),
        Rule(
            "Days ending under ₦10,000",
            pct(a.low_balance_days_share),
            f"at most {pct(p['max_low_balance_days_share'])}",
            a.low_balance_days_share <= p["max_low_balance_days_share"],
            "refer",
            "A business that is usually near empty has no cushion for a repayment.",
        ),
    ]

    offer = round_down(
        min(
            Decimal(p["offer_cap"]),
            a.avg_monthly_sales * Decimal(str(p["offer_share_of_monthly_sales"]))
            - a.avg_monthly_loan_repayments,
        ),
        Decimal(p["offer_round_to"]),
    )
    offer = max(offer, ZERO)

    failed = [r for r in rules if not r.passed]
    if any(r.effect == "decline" for r in failed):
        names = ", ".join(r.name.lower() for r in failed if r.effect == "decline")
        return Decision(DECLINE, f"Outside policy on: {names}.", ZERO, rules)
    if failed:
        names = ", ".join(r.name.lower() for r in failed)
        return Decision(REFER, f"Needs a person to look at: {names}.", offer, rules)
    return Decision(APPROVE, "Within policy on every rule.", offer, rules)
