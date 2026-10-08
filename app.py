"""Statement Analyzer demo: streamlit run app.py"""

import pandas as pd
import streamlit as st

from underwriter import Result, run
from underwriter.analysis import SALES
from underwriter.decision import APPROVE, DECLINE, NO_DECISION, POLICY
from underwriter.money import naira
from underwriter.synthetic import SAMPLES, sample_pdf
from underwriter.validate import FAILED, PASSED

REPO = "https://github.com/varshith57/LoanUnderwriting-Automation-Tool"
UPLOAD = "Upload a PDF"

st.set_page_config(page_title="Statement Analyzer", page_icon="📑", layout="wide")


@st.cache_data(show_spinner=False)
def sample(name: str) -> bytes:
    return sample_pdf(name)


@st.cache_data(show_spinner=False, max_entries=20)
def analyse(pdf: bytes, owners: tuple[str, ...]) -> Result:
    return run(pdf, list(owners))


def money_col(label: str) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format="localized")


# ------------------------------------------------------------------------------------ sidebar

with st.sidebar:
    st.header("1. Pick a statement")
    choice = st.radio("Sample statements (all invented)", [*SAMPLES, UPLOAD], index=0)
    pdf: bytes | None = None
    if choice == UPLOAD:
        st.caption(
            "This demo only knows the two invented layouts (Harbor Bank, Lagoon Pay), so a "
            "real bank's statement will be reported as an unknown layout, which is the "
            "correct answer. Please don't upload real statements: files are read in memory "
            "and not stored, but there is no reason to send them."
        )
        upload = st.file_uploader("Statement PDF", type=["pdf"])
        if upload is not None:
            pdf = upload.getvalue()
    else:
        pdf = sample(choice)
        st.download_button(
            "Download this PDF to look at it",
            pdf,
            file_name=choice.split(" · ")[0].replace(" ", "_") + ".pdf",
            mime="application/pdf",
        )

    st.header("2. Optional")
    extra = st.text_input(
        "Owner or director names",
        help="Payments from these names count as the owner's own money, not sales. "
        "The account name on the statement is always included.",
    )
    st.divider()
    st.caption(f"[Source code and write-up]({REPO})")

# --------------------------------------------------------------------------------------- main

st.title("Statement Analyzer")
st.caption(
    "Reads a bank statement, proves every figure against the totals the bank printed, "
    "and turns the verified figures into a lending decision. No AI in the numbers."
)

if pdf is None:
    st.info("Upload a PDF in the sidebar, or pick one of the samples.")
    st.stop()

owners = tuple(n.strip() for n in extra.split(",") if n.strip())
with st.spinner("Reading and checking every row..."):
    r = analyse(pdf, owners)
ex, v, a, d = r.extracted, r.validation, r.analysis, r.decision

# Decision banner
offer = f" Suggested limit: **{naira(d.offer)}**." if d.offer > 0 else ""
message = f"**{d.outcome}.** {d.headline}{offer}"
if d.outcome == APPROVE:
    st.success(message, icon="✅")
elif d.outcome == DECLINE:
    st.error(message, icon="⛔")
elif d.outcome == NO_DECISION:
    st.error(message, icon="🚫")
else:
    st.warning(message, icon="👀")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Bank layout", ex.bank or "Unknown", ex.template_id or "no template", delta_color="off")
c2.metric("Transactions read", f"{len(ex.rows):,}", f"{ex.pages} pages", delta_color="off")
status_text = {PASSED: "Proved", FAILED: "Do not match"}.get(v.status, "Needs a look")
c3.metric("Figures vs bank's totals", status_text)
c4.metric("Average monthly sales", naira(a.avg_monthly_sales) if a else "-")

tab_proof, tab_rows, tab_cash, tab_rules, tab_how = st.tabs(
    ["Proof of figures", "Transactions", "Cash flow", "Decision rules", "How it works"]
)

with tab_proof:
    st.subheader("Are the figures right?")
    st.write(v.reason)
    if v.checks:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Check": c.name,
                        "Bank printed / expected": c.expected,
                        "Worked out from the rows": c.found,
                        "Result": "✅ matches" if c.ok else "❌ off",
                    }
                    for c in v.checks
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    if v.breaks:
        st.markdown("**Rows where the running balance stops adding up**")
        st.caption(
            "The previous balance plus this row's money in, minus its money out, "
            "should equal the balance the bank printed on this row."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Row": b.index + 1,
                        "Page": ex.rows[b.index].page,
                        "Date": ex.rows[b.index].date,
                        "Narration": ex.rows[b.index].narration,
                        "Money in (as printed)": float(ex.rows[b.index].credit),
                        "Balance should be": float(b.expected_balance),
                        "Balance printed": float(b.printed_balance),
                        "Difference": float(b.delta),
                    }
                    for b in v.breaks
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={
                k: money_col(k)
                for k in [
                    "Money in (as printed)",
                    "Balance should be",
                    "Balance printed",
                    "Difference",
                ]
            },
        )
        st.info(
            "A broken chain at a single row, with the totals off by the same amount, is "
            "what an edited PDF looks like: someone changed a figure but not the balance "
            "next to it.",
            icon="🔎",
        )
    for w in ex.warnings:
        st.warning(w)
    if ex.summary:
        with st.expander("What the bank printed in its summary"):
            st.json({k: str(v) for k, v in ex.summary.items()})

with tab_rows:
    if not a:
        st.info("No transactions were read.")
    else:
        cats = sorted({t.category for t in a.txns})
        pick = st.multiselect("Show categories", cats, default=cats)
        df = pd.DataFrame(
            [
                {
                    "Date": t.row.date,
                    "Narration": t.row.narration,
                    "Money in": float(t.row.credit) or None,
                    "Money out": float(t.row.debit) or None,
                    "Balance": float(t.row.balance),
                    "Counterparty": t.party or "",
                    "Category": t.category,
                    "Read by rule": t.grammar or "(none matched)",
                }
                for t in a.txns
                if t.category in pick
            ]
        )
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            height=520,
            column_config={k: money_col(k) for k in ["Money in", "Money out", "Balance"]},
        )
        st.caption(
            "Each counterparty is read by an ordered list of patterns. A wording no "
            "pattern reads stays 'unidentified' with its amount: it is never quietly "
            "counted as sales."
        )

with tab_cash:
    if a:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Average daily balance", naira(a.avg_daily_balance))
        k2.metric(
            "Largest customer's share of sales",
            f"{a.top_customer_share:.0%}",
            a.top_customer or "",
            delta_color="off",
        )
        k3.metric("Loan repayments per month", naira(a.avg_monthly_loan_repayments))
        k4.metric("Money in we could not read", f"{a.unidentified_share:.1%}")

        months = pd.DataFrame(
            [
                {
                    "Month": m.label,
                    "Sales": float(m.sales),
                    "Other money in": float(m.money_in - m.sales),
                    "Money out": float(m.money_out),
                    "Loan repayments": float(m.loan_repayments),
                }
                for m in a.months
            ]
        )
        st.markdown("**Money in per month: sales vs everything else**")
        st.bar_chart(months.set_index("Month")[["Sales", "Other money in"]], stack=True, sort=False)
        st.dataframe(
            months,
            hide_index=True,
            width="stretch",
            column_config={k: money_col(k) for k in months.columns if k != "Month"},
        )

        left, right = st.columns(2)
        with left:
            st.markdown("**Where the money went, by category**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Category": k, "Amount": float(v)}
                        for k, v in sorted(a.by_category.items(), key=lambda kv: -kv[1])
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config={"Amount": money_col("Amount")},
            )
        with right:
            st.markdown("**Biggest paying customers** (card payments excluded)")
            sales_total = sum(t.row.credit for t in a.txns if t.category == SALES)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Customer": n,
                            "Paid": float(amt),
                            "Share of sales": f"{amt / sales_total:.0%}",
                        }
                        for n, amt in a.top_customers
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config={"Paid": money_col("Paid")},
            )

with tab_rules:
    if not d.rules:
        st.info("No rules were applied: the figures have to be proved first.")
    else:
        effect = {"decline": "⛔ Decline", "refer": "👀 Refer"}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rule": x.name,
                        "This business": x.value,
                        "Policy": x.threshold,
                        "Result": "✅ Pass" if x.passed else effect[x.effect],
                        "Why it matters": x.why,
                    }
                    for x in d.rules
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            f"Suggested limit = {POLICY['offer_share_of_monthly_sales']:.0%} of average monthly "
            f"sales, minus repayments already owed to other lenders, capped at "
            f"{naira(POLICY['offer_cap'])} and rounded down. Any decline rule failing means "
            f"decline; any refer rule failing sends it to a person."
        )

with tab_how:
    st.markdown(
        f"""
**1. Read.** Every word on every page is read with its position. A small JSON template per
bank layout says where each column sits, as a fraction of the page width. The bank is
recognised from the statement's own header, never from transaction text (other banks' names
appear in narrations all the time).

**2. Prove.** A statement checks itself: each row's balance must equal the previous balance
plus money in minus money out, and the rows must add up to the totals the bank printed.
Misread one digit and it shows, at the exact row. A statement that doesn't reconcile gets
**no decision**, not a guess.

**3. Understand.** Ordered patterns read who each payment is from or to. Turnover is not
sales: the owner's own transfers, loans received and reversals are taken out first.

**4. Decide.** Plain policy rules, each showing the figure, the threshold and why it matters.

There is no AI model anywhere in the figures or the decision. Full write-up and source:
[{REPO}]({REPO}).
"""
    )
