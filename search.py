#!/usr/bin/env python3
"""Search library for the WSJ digest archive.

Builds a small inverted index with TF-IDF ranking over the daily digests, so a
reader can search past summaries by keyword (ranked by relevance, not recency),
filter by date range and topic, and get a highlighted snippet.

Everything here is pure-Python stdlib and side-effect free — it's the reference
implementation that (a) builds the JSON index shipped to the browser and (b) is
mirrored by the client-side scorer in search.html. Keep the two in sync.

Design notes:
- No stopword list: TF-IDF already down-weights common words (high document
  frequency -> low IDF), so there's nothing to keep in sync between Python and JS.
- Dates are ISO strings ("YYYY-MM-DD"), which sort and compare lexicographically,
  so range filtering is a plain string comparison.
"""

from __future__ import annotations

import datetime
import glob
import html
import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Lowercase and split into terms of length >= 2 (drops single characters)."""
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def idf(n_docs: int, doc_freq: int) -> float:
    """Smoothed inverse document frequency — always positive, safe for tiny corpora."""
    return math.log((n_docs + 1) / (doc_freq + 1)) + 1.0


def markdown_to_text(md: str) -> str:
    """Reduce digest Markdown to plain readable text (for indexing + snippets)."""
    t = re.sub(r"`([^`]*)`", r"\1", md)                     # inline code
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)          # [label](url) -> label
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)     # headings
    t = re.sub(r"[*_>#]", "", t)                            # residual markdown punctuation
    return re.sub(r"\s+", " ", t).strip()


def build_index(docs: List[dict]) -> dict:
    """Build a JSON-serializable inverted index from documents.

    ``docs`` is a list of {"date": ISO str, "text": str, "topics": [str]}.
    Returns {"N", "df", "postings", "docs"} where postings maps term -> [[doc_id, tf]].
    """
    postings: Dict[str, List[List[int]]] = {}
    df: Dict[str, int] = {}
    meta: List[dict] = []
    for doc_id, doc in enumerate(docs):
        counts = Counter(tokenize(doc["text"]))
        for term, tf in counts.items():
            postings.setdefault(term, []).append([doc_id, tf])
            df[term] = df.get(term, 0) + 1
        meta.append({
            "date": doc["date"],
            "topics": sorted(doc.get("topics", [])),
            "text": doc["text"],
            "len": sum(counts.values()),
        })
    return {"N": len(docs), "df": df, "postings": postings, "docs": meta}


def parse_date(s: Optional[str]) -> Optional[datetime.date]:
    """Parse an ISO date. None/'' -> None; a malformed non-empty string raises ValueError."""
    if s is None or s == "":
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"malformed date: {s!r}") from exc


def make_snippet(text: str, q_terms, width: int = 240) -> str:
    """Return an HTML-safe snippet around the first query-term match, with <mark>s.

    With no query terms, returns the start of the text (browse mode). All literal
    text is HTML-escaped; only the <mark> tags are raw, so this is injection-safe.
    """
    terms = list(q_terms)
    if not terms:
        head = text[:width]
        return html.escape(head) + ("…" if len(text) > width else "")

    pat = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(terms)) + r")\b", re.I)
    m = pat.search(text)
    if not m:
        return html.escape(text[:width])

    start = max(0, m.start() - width // 3)
    end = min(len(text), start + width)
    frag = text[start:end]

    out, last = [], 0
    for mm in pat.finditer(frag):
        out.append(html.escape(frag[last:mm.start()]))
        out.append(f"<mark>{html.escape(mm.group(0))}</mark>")
        last = mm.end()
    out.append(html.escape(frag[last:]))
    return ("…" if start > 0 else "") + "".join(out) + ("…" if end < len(text) else "")


def search(index: dict, query: str, date_from: Optional[str] = None,
           date_to: Optional[str] = None, topics: Optional[List[str]] = None) -> List[dict]:
    """Rank digests for a query with optional date-range and topic filters.

    - Ranking: sum of tf*idf over query terms; ties broken by date (newest first).
    - Empty/whitespace query -> browse mode: every filter-passing digest, newest first.
    - Malformed date_from/date_to raises ValueError.
    - Topic filter matches any selected topic (union).
    Returns a list of {"date", "score", "topics", "snippet"}.
    """
    df, n_docs, postings, docs = index["df"], index["N"], index["postings"], index["docs"]
    d_from = parse_date(date_from)
    d_to = parse_date(date_to)
    topic_set = set(topics) if topics else None

    def passes(doc: dict) -> bool:
        if d_from and doc["date"] < d_from.isoformat():
            return False
        if d_to and doc["date"] > d_to.isoformat():
            return False
        if topic_set and not (set(doc["topics"]) & topic_set):
            return False
        return True

    q_terms = list(dict.fromkeys(tokenize(query)))  # unique, order-preserving
    if not q_terms:
        ranked = [(i, 0.0) for i in range(len(docs)) if passes(docs[i])]
        ranked.sort(key=lambda pair: docs[pair[0]]["date"], reverse=True)
    else:
        scores: Dict[int, float] = {}
        for term in q_terms:
            for doc_id, tf in postings.get(term, []):
                scores[doc_id] = scores.get(doc_id, 0.0) + tf * idf(n_docs, df.get(term, 0))
        ranked = [(i, s) for i, s in scores.items() if passes(docs[i])]
        ranked.sort(key=lambda pair: (pair[1], docs[pair[0]]["date"]), reverse=True)

    q_set = set(q_terms)
    return [{
        "date": docs[i]["date"],
        "score": round(s, 4),
        "topics": docs[i]["topics"],
        "snippet": make_snippet(docs[i]["text"], q_set),
    } for i, s in ranked]


def load_digests(root: str = ".") -> List[dict]:
    """Read every digest-<date>.md under ``root`` into index documents.

    Reuses the existing topic tagging from generate_index (lazy import so the core
    index/ranking functions and their tests stay decoupled from the site builder).
    """
    from generate_index import digest_topics

    docs = []
    for path in sorted(glob.glob(os.path.join(root, "digest-*.md"))):
        m = re.match(r"digest-(\d{4}-\d{2}-\d{2})\.md$", os.path.basename(path))
        if not m:
            continue
        md = open(path, encoding="utf-8").read()
        docs.append({
            "date": m.group(1),
            "text": markdown_to_text(md),
            "topics": sorted(digest_topics(md)),
        })
    return docs
