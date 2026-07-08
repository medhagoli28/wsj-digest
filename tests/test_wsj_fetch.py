"""Unit tests for wsj_fetch.py — pure functions only, no network calls.

Run with:  python3 -m pytest
"""

import datetime
from pathlib import Path

import dedup
from wsj_fetch import clean, parse_items, split_summary_and_sources

# A small Google-News-style RSS payload captured as a fixture.
FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()


# --- clean() -----------------------------------------------------------------

def test_clean_strips_html_and_decodes_entities():
    assert clean("&lt;b&gt;Caf&#233;&lt;/b&gt;  x") == "Café x"
    assert clean("<p>hi</p>\n\n  there") == "hi there"
    assert clean("") == ""          # empty input
    assert clean(None) == ""        # None input


# --- parse_items() -----------------------------------------------------------

def test_parse_items_strips_the_wsj_suffix():
    items = parse_items(FIXTURE, is_gnews=True, section="Tech", limit=10)
    assert items[0]["title"] == "Apple to Spend $30 Billion on U.S.-Made Chips From Broadcom"
    assert items[0]["section"] == "Tech"
    assert items[0]["link"].startswith("https://news.google.com/")


def test_parse_items_skips_empty_titles_and_decodes_entities():
    titles = [it["title"] for it in parse_items(FIXTURE, is_gnews=True, section="Tech", limit=10)]
    assert "" not in titles                                  # the empty <item> is dropped
    assert titles == [
        "Apple to Spend $30 Billion on U.S.-Made Chips From Broadcom",
        "Microsoft Is Cutting More Than 3,000 Jobs in Xbox Division",
        "Café Culture Meets AI & Robotics",                  # &#233; and &amp; decoded
    ]


def test_parse_items_respects_the_limit():
    assert len(parse_items(FIXTURE, is_gnews=True, section="Tech", limit=2)) == 2


# --- split_summary_and_sources() (Mode B helper) -----------------------------

def test_split_summary_and_sources_parses_and_drops_wsj():
    text = (
        "Apple committed over $30B to Broadcom for U.S. chips.\n"
        "SOURCES: https://www.cnbc.com/x, https://www.wsj.com/y, https://reuters.com/z"
    )
    summary, sources = split_summary_and_sources(text)
    assert summary == "Apple committed over $30B to Broadcom for U.S. chips."
    assert sources == ["https://www.cnbc.com/x", "https://reuters.com/z"]  # wsj.com dropped


# --- dedup.is_duplicate() ----------------------------------------------------
# Similarity uses difflib, so these run fully offline and deterministically —
# no monkeypatching, no API. The store maps headline text -> {date}.

def _today():
    return datetime.date.today().isoformat()


def test_is_duplicate_true_when_above_threshold():
    # Same story, trivially reworded ("U.S." -> "US") -> difflib ratio well above 0.85.
    store = {"Apple to Spend $30 Billion on U.S.-Made Chips From Broadcom": {"date": _today()}}
    assert dedup.is_duplicate("Apple to Spend $30 Billion on US-Made Chips From Broadcom", store) is True


def test_is_duplicate_false_when_below_threshold():
    store = {"Fed holds interest rates steady": {"date": _today()}}
    assert dedup.is_duplicate("Apple announces a new iPhone lineup", store) is False


def test_is_duplicate_false_when_store_empty():
    assert dedup.is_duplicate("Anything at all", {}) is False


def test_prune_store_drops_entries_older_than_lookback():
    old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    recent = datetime.date.today().isoformat()
    store = {
        "old story": {"date": old},
        "recent story": {"date": recent},
    }
    pruned = dedup.prune_store(store)
    assert "recent story" in pruned
    assert "old story" not in pruned
