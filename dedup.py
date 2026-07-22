#!/usr/bin/env python3
"""Cross-day headline de-dup. No external services, just difflib.

Mode B pulls a fresh batch of headlines every day, but the same story keeps
showing up. So before researching one I compare it against what I already covered
in the last few days and skip the near-matches.

Store is a plain JSON file: headline text -> {date it was covered}.
"""

import difflib
import json
import os
from datetime import date, timedelta

STORE_PATH = "seen_headlines.json"


def load_store(path=STORE_PATH):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_store(store, path=STORE_PATH):
    with open(path, "w") as f:
        json.dump(store, f, indent=2)


def similarity(a, b):
    # difflib ratio in [0, 1], case-insensitive
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def prune_store(store, lookback_days=7):
    """Drop entries older than the lookback window.

    We only ever compare against the last `lookback_days`, so older stuff is dead
    weight and just bloats the file.
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    return {
        text: record
        for text, record in store.items()
        if date.fromisoformat(record["date"]) >= cutoff
    }


def is_duplicate(headline, store, threshold=0.85, lookback_days=7):
    """True if `headline` looks like something covered in the last N days.

    Empty store -> never a duplicate. Bails out on the first match above threshold.
    """
    if not store:
        return False

    cutoff = date.today() - timedelta(days=lookback_days)
    for text, record in store.items():
        if date.fromisoformat(record["date"]) < cutoff:
            continue  # too old, skip
        if similarity(headline, text) > threshold:
            return True
    return False
