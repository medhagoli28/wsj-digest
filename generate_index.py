#!/usr/bin/env python3
"""Build a GitHub Pages site from the daily digests.

Renders each digest-<date>.md into a styled HTML page (real headings, article
cards, section color accents, a jump-to-section strip) and writes an index.html
linking to them newest-first. Plain Python + inline CSS — no frameworks, no deps.

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

# Map a section heading to an accent color class.
SECTION_CLASSES = [("tech", "tech"), ("markets", "markets"), ("personal finance", "finance")]

CSS = """
  :root { color-scheme: light dark;
          --tech: #2563eb; --markets: #059669; --finance: #d97706;
          --card: #fafafa; --border: #ececec; --muted: #6b7280; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         max-width: 740px; margin: 0 auto; padding: 2.5rem 1.1rem 4rem;
         line-height: 1.65; color: #1a1a1a; background: #fff;
         -webkit-font-smoothing: antialiased; }
  h1 { font-size: 2rem; line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 .4rem; }
  .lead { color: var(--muted); margin: 0 0 1.4rem; font-size: .98rem; }
  h2 { font-size: 1.25rem; margin: 2.2rem 0 .9rem; padding-left: .6rem;
       border-left: 4px solid var(--muted); }
  h2.tech { border-color: var(--tech); } h2.markets { border-color: var(--markets); }
  h2.finance { border-color: var(--finance); }
  .article { margin: 0 0 .9rem; padding: 1rem 1.15rem; border: 1px solid var(--border);
             border-radius: 12px; background: var(--card); }
  .article strong { font-size: 1.06rem; }
  .article em { color: var(--muted); font-style: italic; }
  .sources, .sources a { color: var(--muted); font-size: .87rem; }
  a { color: var(--tech); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .jump { display: flex; flex-wrap: wrap; gap: .5rem; margin: 0 0 1.5rem;
          font-size: .9rem; }
  .jump a { padding: .25rem .7rem; border: 1px solid var(--border); border-radius: 999px;
            color: #1a1a1a; background: var(--card); }
  .back { display: inline-block; margin-bottom: 1.1rem; font-size: .9rem; color: var(--muted); }
  ul { list-style: none; padding: 0; }
  li { padding: .6rem 0; border-bottom: 1px solid var(--border); font-size: 1.12rem; }
  hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
  footer { margin-top: 2.5rem; color: #9aa0a6; font-size: .82rem; }
  @media (prefers-color-scheme: dark) {
    :root { --card: #161b22; --border: #24292f; --muted: #9198a1; }
    body { color: #e6e6e6; background: #0d1117; }
    .jump a { color: #e6e6e6; }
    a { color: #6ea8fe; } h2 a, .article strong { color: inherit; }
  }
"""


def find_digests():
    """Return (date, md_filename) pairs for every digest-<date>.md, newest first."""
    found = []
    for path in glob.glob("digest-*.md"):
        name = os.path.basename(path)
        m = FILENAME_RE.match(name)
        if m:
            found.append((datetime.date.fromisoformat(m.group(1)), name))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return found


def pretty_date(d):
    """Format a date like 'July 8, 2026' (no leading zero on the day)."""
    return f"{d:%B} {d.day}, {d.year}"


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _section_class(text):
    low = text.lower()
    for needle, cls in SECTION_CLASSES:
        if needle in low:
            return cls
    return ""


def _strip_emoji(text):
    """Drop a leading emoji so 'Tech' shows in the jump strip, not '💻 Tech'."""
    return re.sub(r"^[^\w]+", "", text).strip()


def _inline(text):
    """Convert inline Markdown in an already-HTML-escaped string to HTML."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)  # [t](url)
    text = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', text)           # <url>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)                    # **bold**
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)                 # *italic*
    return text


def md_to_html(md):
    """Convert digest Markdown to (html_fragment, [(section_id, label), ...])."""
    out, sections, in_list = [], [], False
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
            label = line[3:]
            sid = _slug(label)
            sections.append((sid, label))
            out.append(f'<h2 id="{sid}" class="{_section_class(label)}">{_inline(html.escape(label))}</h2>')
        elif line == "---":
            out.append("<hr>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(html.escape(line[2:]))}</li>")
        else:
            para = _inline(html.escape(line))
            para = para.replace("<em>Sources:", '<span class="sources"><em>Sources:')
            if 'class="sources"' in para:
                para += "</span>"
            cls = ' class="article"' if para.startswith("<strong>") else ""
            if para.startswith("<em>") and not cls:      # the italic intro line under the title
                cls = ' class="lead"'
            out.append(f"<p{cls}>{para}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out), sections


def _page(title, body):
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{html.escape(title)}</title>\n"
        f"  <style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def render_digest_page(md_text, date):
    """One digest -> a styled HTML page with a back-link and jump-to-section strip."""
    frag, sections = md_to_html(md_text)
    if sections:
        links = " ".join(
            f'<a href="#{sid}">{html.escape(_strip_emoji(label))}</a>' for sid, label in sections
        )
        # place the jump strip right after the <h1>
        frag = frag.replace("</h1>", f'</h1>\n<nav class="jump">{links}</nav>', 1)
    body = '<a class="back" href="index.html">← all digests</a>\n' + frag
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
        '  <p class="lead">Daily summaries — headlines from WSJ, depth researched from other outlets.</p>\n'
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
        with open(os.path.join(args.out, f"digest-{date.isoformat()}.html"), "w", encoding="utf-8") as f:
            f.write(render_digest_page(md_text, date))

    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(digests))

    print(f"[wrote {args.out}/index.html + {len(digests)} digest page(s)]")


if __name__ == "__main__":
    main()
