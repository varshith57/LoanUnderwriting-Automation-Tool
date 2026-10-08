"""The page itself, driven headlessly: every sample renders, with the right banner, no errors."""

import pytest
from streamlit.testing.v1 import AppTest

from underwriter.synthetic import SAMPLES

EXPECTED = ["Approve", "Refer to an underwriter", "Decline", "No decision"]


def page(choice: str | None = None) -> AppTest:
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    if choice is not None:
        at.sidebar.radio[0].set_value(choice).run()
    return at


@pytest.mark.parametrize(("name", "outcome"), zip(SAMPLES, EXPECTED, strict=True))
def test_each_sample_renders_its_decision(name, outcome):
    at = page(name)
    assert not at.exception
    banners = [*at.success, *at.warning, *at.error]
    assert any(f"**{outcome}.**" in b.value for b in banners)


def test_upload_mode_waits_for_a_file_instead_of_failing():
    at = page("Upload a PDF")
    assert not at.exception
    assert any("Upload a PDF" in i.value for i in at.info)


def test_owner_names_box_reruns_without_errors():
    at = page()
    at.sidebar.text_input[0].set_value("Ngozi Obi").run()
    assert not at.exception
