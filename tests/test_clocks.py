"""The clock registry and its safety invariant.

The dangerous failure mode this file guards is a plausible-but-wrong default
window on a clock whose length is actually set by the governing instrument.
"""

from __future__ import annotations

import pytest

from lapse import clocks

# Clocks whose window is set by the document in front of you, never by statute.
# These MUST NOT carry a default window.
INSTRUMENT_DEFINED_KEYS = [
    "contract_scope_objection",
    "product_recall_free_remedy",
    "price_protection",
    "mail_in_rebate",
]

# Clocks whose window is fixed by law and the same for everyone.
STATUTORY_KEYS = [
    "insurance_internal_appeal",
    "habitability_repair_notice",
    "card_chargeback",
]


def test_registry_is_not_empty():
    assert clocks.REGISTRY


@pytest.mark.parametrize("key", sorted(clocks.REGISTRY))
def test_every_entry_key_matches_its_dict_key(key):
    assert clocks.REGISTRY[key].key == key


@pytest.mark.parametrize("key", INSTRUMENT_DEFINED_KEYS)
def test_instrument_defined_clocks_have_no_default_window(key):
    """Safety invariant. A default here would be a confident wrong deadline."""
    ct = clocks.lookup(key)
    assert ct is not None, f"{key} disappeared from the registry"
    assert ct.default_window is None


@pytest.mark.parametrize("key", STATUTORY_KEYS)
def test_statutory_clocks_carry_a_concrete_positive_window(key):
    ct = clocks.lookup(key)
    assert ct is not None
    assert isinstance(ct.default_window, int)
    assert ct.default_window > 0


def test_known_statutory_window_values():
    assert clocks.REGISTRY["insurance_internal_appeal"].default_window == 180
    assert clocks.REGISTRY["habitability_repair_notice"].default_window == 14
    assert clocks.REGISTRY["card_chargeback"].default_window == 60


def test_every_entry_cites_an_authority():
    for key, ct in clocks.REGISTRY.items():
        assert ct.authority.strip(), f"{key} cites no authority"


def test_lookup_returns_the_entry_for_a_known_key():
    ct = clocks.lookup("insurance_internal_appeal")
    assert ct is not None
    assert ct.key == "insurance_internal_appeal"


def test_lookup_returns_none_for_an_unknown_key():
    assert clocks.lookup("no_such_clock") is None
    assert clocks.lookup("") is None


def test_catalogue_lists_every_key():
    text = clocks.catalogue()
    for key in clocks.REGISTRY:
        assert key in text


@pytest.mark.parametrize("key", INSTRUMENT_DEFINED_KEYS)
def test_catalogue_marks_instrument_defined_entries(key):
    text = clocks.catalogue()
    block = text.split(f"- {key}:", 1)[1].split("\n- ", 1)[0]
    assert "INSTRUMENT-DEFINED" in block


@pytest.mark.parametrize("key", STATUTORY_KEYS)
def test_catalogue_gives_a_concrete_day_count_for_statutory_entries(key):
    text = clocks.catalogue()
    block = text.split(f"- {key}:", 1)[1].split("\n- ", 1)[0]
    window = clocks.REGISTRY[key].default_window
    assert f"{window} " in block
    assert "days" in block
    assert "INSTRUMENT-DEFINED" not in block
