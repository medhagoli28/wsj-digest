#!/usr/bin/env python3
"""Build the static search layer for the published site.

Reads every digest-<date>.md, builds the TF-IDF index (search.py), and writes:
  - <out>/search-index.json   the prebuilt index the browser searches client-side
  - <out>/search.html         the search page (copied from the repo root)

Run after generate_index.py so it writes into the same ./public directory that
gets deployed to GitHub Pages. Dependency-light: Python stdlib only.

Usage:
  python3 build_search_index.py            # -> ./public/{search-index.json,search.html}
  python3 build_search_index.py --out DIR --root DIR
"""

import argparse
import json
import os
import shutil

import search


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="public", help="output directory (default: public)")
    ap.add_argument("--root", default=".", help="where the digest-*.md files live")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    index = search.build_index(search.load_digests(args.root))

    # Expose the full topic label list (order preserved) for the filter UI.
    from generate_index import TOPIC_RULES
    index["topics"] = [label for label, _ in TOPIC_RULES]

    with open(os.path.join(args.out, "search-index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    shutil.copyfile(os.path.join(args.root, "search.html"), os.path.join(args.out, "search.html"))

    total = os.path.getsize(os.path.join(args.out, "search-index.json"))
    print(f"[search] indexed {index['N']} digests -> {args.out}/search-index.json "
          f"({total // 1024} KB) + search.html")


if __name__ == "__main__":
    main()
