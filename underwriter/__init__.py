"""Statement in, verified figures and a credit decision out.

extract   PDF -> rows, using a per-bank layout template over word coordinates
validate  prove the rows against the totals the bank printed
analysis  who paid whom, what counts as sales, monthly cash flow
decision  policy rules -> approve / refer / decline, with reasons
synthetic invented statements for the demo and the tests
"""

from dataclasses import dataclass

from .analysis import Analysis, analyse
from .decision import Decision, decide
from .extract import Extracted, extract
from .validate import Validation, validate


@dataclass
class Result:
    extracted: Extracted
    validation: Validation
    analysis: Analysis | None
    decision: Decision


def run(pdf: bytes, extra_owner_names: list[str] | None = None) -> Result:
    """The whole pipeline for one statement."""
    extracted = extract(pdf)
    validation = validate(extracted)
    analysis = None
    if extracted.rows:
        owners = [extracted.summary.get("account_name", "")] + (extra_owner_names or [])
        analysis = analyse(extracted.rows, [o for o in owners if o])
    return Result(extracted, validation, analysis, decide(validation, analysis))
