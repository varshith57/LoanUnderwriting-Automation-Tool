from dataclasses import replace
from datetime import date
from decimal import Decimal

import pymupdf
import pytest

from underwriter import run
from underwriter.analysis import LOAN_IN, REVERSAL, SALES, SELF, UNREAD_IN, classify, same_person
from underwriter.decision import APPROVE, DECLINE, NO_DECISION, REFER
from underwriter.extract import Row, extract
from underwriter.synthetic import SAMPLES, generate, render
from underwriter.validate import FAILED, PASSED, REVIEW

NAMES = list(SAMPLES)
HEALTHY, CONCENTRATED, BORROWER, EDITED = NAMES


@pytest.fixture(scope="module")
def results():
    return {name: run(render(generate(SAMPLES[name]))) for name in NAMES}


@pytest.mark.parametrize("name", [HEALTHY, CONCENTRATED, BORROWER])
def test_every_row_is_read_exactly_as_generated(name):
    """Extraction is checked against the generator's own rows, not just against itself."""
    statement = generate(SAMPLES[name])
    ex = extract(render(statement))
    assert len(ex.rows) == len(statement.txns)
    for got, want in zip(ex.rows, statement.txns, strict=True):
        assert (got.date, got.credit, got.debit, got.balance) == (
            want.day,
            want.credit,
            want.debit,
            want.balance,
        )


def test_wrapped_harbor_narrations_are_joined_back_together():
    statement = generate(SAMPLES[HEALTHY])
    ex = extract(render(statement))
    longest = max(range(len(statement.txns)), key=lambda i: len(statement.txns[i].narration))
    assert len(statement.txns[longest].narration) > 34  # it really was wrapped
    assert ex.rows[longest].narration == statement.txns[longest].narration


@pytest.mark.parametrize("name", [HEALTHY, CONCENTRATED, BORROWER])
def test_clean_statements_reconcile_exactly(results, name):
    v = results[name].validation
    assert v.status == PASSED, v.reason
    assert all(c.ok for c in v.checks)


def test_an_edited_figure_breaks_the_chain_at_that_row_and_gets_no_decision(results):
    r = results[EDITED]
    assert r.validation.status == FAILED
    assert len(r.validation.breaks) == 1
    assert r.validation.breaks[0].delta == Decimal("-60000.00")
    assert r.decision.outcome == NO_DECISION
    assert r.decision.offer == 0


def test_each_sample_lands_on_the_outcome_it_illustrates(results):
    assert results[HEALTHY].decision.outcome == APPROVE
    assert results[CONCENTRATED].decision.outcome == REFER
    assert results[BORROWER].decision.outcome == DECLINE


def test_harbor_statement_is_not_claimed_by_lagoon_despite_naming_it_in_narrations():
    statement = generate(SAMPLES[HEALTHY])
    assert any("LAGOON PAY" in t.narration for t in statement.txns)
    assert extract(render(statement)).template_id == "harbor.v1"


def test_unknown_layout_is_reported_not_guessed():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Some Other Bank - statement", fontsize=12)
    r = run(doc.tobytes())
    assert r.extracted.template_id is None
    assert r.validation.status == REVIEW
    assert r.decision.outcome == NO_DECISION


def test_garbage_bytes_are_refused_cleanly():
    r = run(b"not a pdf at all")
    assert r.decision.outcome == NO_DECISION


def test_a_dropped_row_is_caught_by_the_totals():
    statement = generate(SAMPLES[CONCENTRATED])
    pdf = render(statement)
    ex = extract(pdf)
    del ex.rows[40]
    from underwriter.validate import validate

    v = validate(ex)
    assert v.status == FAILED
    assert len(v.breaks) == 1


def row(narration: str, credit: str = "0", debit: str = "0") -> Row:
    return Row(date(2026, 6, 1), narration, Decimal(debit), Decimal(credit), Decimal("0"), 1)


@pytest.mark.parametrize(
    ("narration", "category", "party"),
    [
        ("TRF FROM CHIDI OKAFOR/LAGOON PAY/123", SALES, "Chidi Okafor"),
        ("TRF FROM ADEBAYO STORES LTD/OWN ACCOUNT/9", SELF, "Adebayo Stores Ltd"),
        ("LOAN DISBURSEMENT QUICKCREDIT/77", LOAN_IN, "Quickcredit"),
        ("REVERSAL: TRF TO CITYLINK LOGISTICS/5", REVERSAL, "Citylink Logistics"),
        ("Inward transfer from Amaka Eze", SALES, "Amaka Eze"),
        ("MOB/UTO/123/ZX9", UNREAD_IN, None),
    ],
)
def test_counterparty_and_category(narration, category, party):
    t = classify(row(narration, credit="1000"), ["ADEBAYO STORES LTD"])
    assert (t.category, t.party) == (category, party)


def test_a_shared_surname_is_not_the_owner():
    assert not same_person("KUNLE ADEBAYO", ["ADEBAYO STORES LTD"])
    assert same_person("ADEBAYO STORES", ["ADEBAYO STORES LTD"])
    assert same_person("Bello Fabrics Ven", ["BELLO FABRICS VENTURES"])  # truncated by the bank


def test_owner_names_from_the_user_move_money_out_of_sales():
    pdf = render(generate(SAMPLES[HEALTHY]))
    base = run(pdf).analysis
    top = base.top_customer
    moved = run(pdf, [top]).analysis
    assert moved.avg_monthly_sales < base.avg_monthly_sales
    assert top not in dict(moved.top_customers)


def test_a_short_statement_is_referred_for_too_little_history():
    short = replace(SAMPLES[HEALTHY], end=date(2026, 7, 31))
    r = run(render(generate(short)))
    assert r.validation.status == PASSED
    assert r.decision.outcome == REFER
    assert any(x.name == "Months of history" and not x.passed for x in r.decision.rules)
