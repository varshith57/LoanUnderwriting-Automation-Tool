# Design decisions and findings

Each of these came from studying real statements, and each changed the design.

## Templates over word coordinates, not generic table extraction

Generic PDF table detection failed on most banks: one fragmented every row into its own table,
one merged many rows into a single cell, and one produced no tables at all. Reading words with
their coordinates and applying a small per-bank template was faster, exact, and easy to test.

## Page-relative column boundaries

One bank sizes each page's width to its content, so widths vary by file. Column boundaries are
stored as fractions of the page, not absolute points.

## Detect the bank from the summary block only

Transaction narrations often name other banks ("TRANSFER TO … <other bank>"). Detection reads
only the statement's own header and summary, so a statement is never claimed by the wrong template.
Detectors are also checked for collisions: a phrase like "opening bal" appears in many banks'
statements and cannot identify any one of them.

## Split multi-account statements into separate ledgers

One wallet provider ships two complete statements in one PDF, a main account and a savings
pocket, each with its own totals. Treating them as one would nearly double apparent turnover,
which is a serious error for a lending decision.

## Quantise spreadsheet money on read

Excel exports store money as floats (`525.619999999999` for `525.62`). Values are rounded to
the kobo as they are read, and all arithmetic afterwards is `Decimal`.

## Do not map figures that mean something else

One bank prints a "balance" column that is the live balance when the statement was printed, not
the period's closing balance. Mapping it would make every statement from that bank fail. It is
deliberately left unmapped, and that is documented in the template.

## Three states for counterparties, never merged

A wording either names a party, names nobody by design (`no_party`: fees, VAT, own money), or
could not be read (`unidentified`). Merging the last two would hide how much money the engine
does not understand. Unidentified money is shown with its amount.

## "Misread" is the most expensive error

If a pattern reads the borrower's own name out of a payment, that payment is treated as a
self-transfer and dropped from sales. These rows are shown first in the queue, with the amount
dropped, because they move the decision the most.

## Honest residuals

Files that do not fully reconcile are reported with the exact difference and the rows that cause
it, for example a bank that prints fee refunds without the fee, or rows stamped out of order. The
tool never smooths a gap to make a file pass.

## AI only where its mistakes are caught

The LLM drafts templates and patterns offline. Every upload must compile, pass a safety check,
and read its own examples through the real engine, and the batch is all-or-nothing. A wrong
template leaves a file `failed` with its delta; it can never produce a quietly wrong figure.
