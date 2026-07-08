#!/usr/bin/env python3
"""Build a GitHub Pages site from the daily digests.

Renders each digest-<date>.md into a styled HTML page (real headings, readable
type, clickable sources) and writes an index.html linking to them newest-first.
Plain Python + inline CSS — no frameworks, no dependencies.

Usage:
  python3 generate_index.py            # output into ./public
  python3 generate_index.py --out DIR  # choose the output directory
"""

import argparse
import datetime
import glob
import html
import os
import re

FILENAME_RE = re.compile(r"^digest-(\d{4}-\d{2}-\d{2})\.md$")

# Shared inline CSS for both the index and each digest page.
CSS = """
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         max-width: 720px; margin: 2.5rem auto; padding: 0 1.1rem; line-height: 1.6;
         color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 .3rem; }
  h2 { font-size: 1.3rem; margin: 2rem 0 .6rem; padding-bottom: .3rem;
       border-bottom: 1px solid #eee; }
  p { margin: 0 0 1rem; }
  p em:first-child { color: #666; }              /* the intro line under the title */
  a { color: #0645ad; text-decoration: none; }
  a:hover { text-decoration: underline; }
  ul { list-style: none; padding: 0; }
  li { padding: .55rem 0; border-bottom: 1px solid #eee; font-size: 1.1rem; }
  .back { display: inline-block; margin-bottom: 1rem; font-size: .9rem; }
  .sources, .sources a { color: #888; font-size: .9rem; }   /* the *Sources: ...* line */
  hr { border: none; border-top: 1px solid #eee; margin: 2rem 0; }
  footer { margin-top: 2.5rem; color: #999; font-size: .85rem; }
  @media (prefers-color-scheme: dark) {
    body { color: #e6e6e6; background: #0d1117; }
    h2, li, hr { border-color: #222; }
    a { color: #6ea8fe; }
  }
"""


def find_digests():
    """Return (date, md_filename) pairs for every digest-<date>.md, newest first."""
    found = []
    for path in glob.glob("digest-*.md"):
        name = os.path.basename(path)
        match = FILENAME_RE.match(name)
        if match:
            found.append((datetime.date.fromisoformat(match.group(1)), name))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return found


def pretty_date(d):
    """Format a date like 'July 8, 2026' (no leading zero on the day)."""
    return f"{d:%B} {d.day}, {d.year}"


def _inline(text):
    """Convert inline Markdown in an already-HTML-escaped string to HTML."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)  # [t](url)
    text = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', text)           # <url>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)                    # **bold**
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)                 # *italic*
    return text


def md_to_html(md):
    """Convert our digest Markdown to an HTML fragment (headings, lists, paragraphs)."""
    out, in_list = [], False
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            if in_list:
                out.append("</ul>"); in_list = False
            continue
        if in_list and not line.startswith("- "):
            out.append("</ul>"); in_list = False

        if line.startswith("# "):
            out.append(f"<h1>{_inline(html.escape(line[2:]))}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(html.escape(line[3:]))}</h2>")
        elif line == "---":
            out.append("<hr>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(html.escape(line[2:]))}</li>")
        else:
            para = _inline(html.escape(line))
            # style the trailing "*Sources: ...*" so it reads as a caption
            para = para.replace("<em>Sources:", '<span class="sources"><em>Sources:')
            if 'class="sources"' in para:
                para += "</span>"
            out.append(f"<p>{para}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _page(title, body):
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{html.escape(title)}</title>\n"
        f"  <style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def render_digest_page(md_text, date):
    """One digest -> a full styled HTML page with a back-link to the index."""
    body = '<a class="back" href="index.html">← all digests</a>\n' + md_to_html(md_text)
    return _page(f"WSJ Digest — {pretty_date(date)}", body)


def render_index(digests):
    """The index -> links to each digest's HTML page, newest first."""
    if digests:
        rows = "\n".join(
            f'      <li><a href="digest-{d.isoformat()}.html">{html.escape(pretty_date(d))}</a></li>'
            for d, _ in digests
        )
    else:
        rows = "      <li>No digests yet.</li>"
    body = (
        "  <h1>WSJ Deep Digest</h1>\n"
        '  <p><em>Daily summaries — headlines from WSJ, depth researched from other outlets.</em></p>\n'
        f"  <ul>\n{rows}\n  </ul>\n"
        "  <footer>Generated automatically. No paywalled WSJ text is reproduced.</footer>"
    )
    return _page("WSJ Deep Digest", body)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="public", help="output directory (default: public)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    digests = find_digests()

    for date, name in digests:
        md_text = open(name, encoding="utf-8").read()
        out_path = os.path.join(args.out, f"digest-{date.isoformat()}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(render_digest_page(md_text, date))

    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(digests))

    print(f"[wrote {args.out}/index.html + {len(digests)} digest page(s)]")


if __name__ == "__main__":
    main()
