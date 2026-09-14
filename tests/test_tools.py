"""The deterministic tools the agents call.

Every one of these is ordinary Python over local files -- no model, no
network. They are exercised here by calling them directly.
"""

from __future__ import annotations

import pytest

from lapse import clocks
from lapse.corpus import reference_index
from lapse.tools import (
    compute_window_expiry,
    list_clock_types,
    list_reference_documents,
    lookup_clock_type,
    read_reference_document,
    search_reference_documents,
)

TODAY = "2026-09-14"


# --------------------------------------------------------------------------
# compute_window_expiry
# --------------------------------------------------------------------------


def test_compute_window_expiry_reports_a_live_calendar_window():
    out = compute_window_expiry("2026-03-29", 180, False, TODAY)
    assert "2026-09-25" in out
    assert "LIVE" in out
    assert "LAPSED" not in out
    assert "11 days remaining" in out
    assert "calendar" in out


def test_compute_window_expiry_reports_a_live_business_window():
    out = compute_window_expiry("2026-09-08", 10, True, TODAY)
    assert "2026-09-22" in out
    assert "LIVE" in out
    assert "8 days remaining" in out
    assert "business" in out


def test_compute_window_expiry_reports_a_lapsed_window():
    out = compute_window_expiry("2026-08-01", 30, False, TODAY)
    assert "2026-08-31" in out
    assert "LAPSED" in out
    assert "LIVE" not in out
    assert "14 days ago" in out


def test_compute_window_expiry_is_live_on_the_expiry_date_itself():
    out = compute_window_expiry("2026-09-04", 10, False, TODAY)
    assert "2026-09-14" in out
    assert "LIVE" in out
    assert "0 days remaining" in out


def test_compute_window_expiry_business_and_calendar_disagree():
    cal = compute_window_expiry("2026-09-04", 10, False, TODAY)
    biz = compute_window_expiry("2026-09-04", 10, True, TODAY)
    assert cal != biz


# --------------------------------------------------------------------------
# clock registry tools
# --------------------------------------------------------------------------


def test_list_clock_types_returns_the_catalogue():
    assert list_clock_types() == clocks.catalogue()


def test_lookup_clock_type_describes_a_statutory_clock():
    out = lookup_clock_type("insurance_internal_appeal")
    assert "180" in out
    assert "calendar days" in out
    assert "ERISA" in out


def test_lookup_clock_type_refuses_to_invent_a_window_for_instrument_defined_clocks():
    out = lookup_clock_type("price_protection")
    assert "INSTRUMENT-DEFINED" in out


def test_lookup_clock_type_with_a_bad_key_returns_the_valid_key_list():
    out = lookup_clock_type("definitely_not_a_clock")
    assert "No clock type 'definitely_not_a_clock'" in out
    for key in clocks.REGISTRY:
        assert key in out


def test_lookup_clock_type_with_a_bad_key_does_not_raise():
    # The contract is "return a message", not "raise" -- a raising tool would
    # surface to the model as an error rather than as guidance.
    assert isinstance(lookup_clock_type(""), str)


# --------------------------------------------------------------------------
# reference documents
# --------------------------------------------------------------------------


def test_reference_corpus_is_present():
    assert reference_index(), "reference corpus is empty; tool tests below are vacuous"


def test_list_reference_documents_names_every_document_on_file():
    out = list_reference_documents()
    for doc_id in reference_index():
        assert doc_id in out


def test_read_reference_document_returns_the_full_text():
    doc_id = "keystone_certificate_of_coverage.md"
    out = read_reference_document(doc_id)
    assert out == reference_index()[doc_id].text


def test_read_reference_document_with_a_bad_id_does_not_raise():
    out = read_reference_document("not_a_real_document.md")
    assert "No such document" in out
    for doc_id in reference_index():
        assert doc_id in out


def test_search_finds_investigational_in_the_keystone_certificate():
    out = search_reference_documents("investigational")
    assert "keystone_certificate_of_coverage.md" in out
    assert "investigational" in out.lower()


def test_search_is_case_insensitive():
    assert search_reference_documents("INVESTIGATIONAL") == search_reference_documents(
        "investigational"
    )


def test_search_returns_one_excerpt_per_document():
    out = search_reference_documents("the")
    doc_ids = [d for d in reference_index() if f"--- {d} ---" in out]
    for doc_id in doc_ids:
        assert out.count(f"--- {doc_id} ---") == 1


def test_search_reports_a_miss_rather_than_raising():
    out = search_reference_documents("zzzz_no_such_phrase_zzzz")
    assert out.startswith("No reference document contains")


def test_search_rejects_an_empty_query():
    assert search_reference_documents("   ") == "Empty query."


@pytest.mark.parametrize(
    "tool_fn,args",
    [
        (lookup_clock_type, ("bogus",)),
        (read_reference_document, ("bogus",)),
        (search_reference_documents, ("bogus_nonsense_term",)),
    ],
)
def test_tools_degrade_to_a_message_not_an_exception(tool_fn, args):
    assert isinstance(tool_fn(*args), str)
