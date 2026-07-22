#!/usr/bin/env python3
"""Search library for the digest archive.

Small inverted index with TF-IDF ranking over the daily digests. Lets a reader
search past summaries by keyword (ranked by relevance, not date), filter by date
range and topic, and get a highlighted snippet back.

All stdlib, no side effects. This is the reference impl: it (a) builds the JSON
index that ships to the browser and (b) is mirrored by the JS scorer in
search.html. If you touch the scoring here, touch it there too.

A couple of notes to future-me:
- No stopword list on purpose. TF-IDF already tanks common words (high doc
  frequency -> low IDF), so there's nothing extra to keep in sync with the JS.
- Dates are ISO strings, which sort/compare lexicographically, so range filtering
  is just string comparison.
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
    # lowercase, keep terms of length >= 2 (single chars are noise)
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def idf(n_docs: int, doc_freq: int) -> float:
    # smoothed idf so it stays positive even on a tiny corpus
    return math.log((n_docs + 1) / (doc_freq + 1)) + 1.0


def markdown_to_text(md: str) -> str:
    """Flatten digest markdown to plain text for indexing + snippets."""
    t = re.sub(r"`([^`]*)`", r"\1", md)                     # inline code
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)          # [label](url) -> label
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)     # headings
    t = re.sub(r"[*_>#]", "", t)                            # leftover md punctuation
    return re.sub(r"\s+", " ", t).strip()


def build_index(docs: List[dict]) -> dict:
    """Build a JSON-serializable inverted index.

    docs = list of {"date": ISO str, "text": str, "topics": [str]}.
    Returns {"N", "df", "postings", "docs"}; postings maps term -> [[doc_id, tf]].
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
    # None/'' -> None; a bad non-empty string raises ValueError
    if s is None or s == "":
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"malformed date: {s!r}") from exc


def make_snippet(text: str, q_terms, width: int = 240) -> str:
    """HTML-safe snippet around the first matched term, with <mark>s.

    No query terms -> just the start of the text (browse mode). Everything gets
    escaped except the <mark> tags, so this is safe to drop straight into the DOM.
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
    """Rank digests for a query, with optional date-range + topic filters.

    Score = sum of tf*idf over the query terms, ties broken by date (newest first).
    Empty query = browse mode (every doc that passes the filters, newest first).
    Bad date_from/date_to raises ValueError. Topic filter is a union (match any).
    Returns [{"date", "score", "topics", "snippet"}].
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

    q_terms = list(dict.fromkeys(tokenize(query)))  # dedup, keep order
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
    """Read every digest-<date>.md under `root` into index docs.

    Reuses the topic tagging from generate_index (lazy import so the core
    index/ranking code and its tests don't drag in the site builder).
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
