"""Markdown -> styled HTML -> PDF export.

No new dependencies. The Markdown converter handles exactly the constructs
`report.py` emits (headings, tables, blockquotes, lists, emphasis, code spans,
rules) rather than pulling in a general parser.

PDF rendering shells out to headless Edge or Chrome, both of which ship on
Windows and render Korean, Indonesian, and emoji with system fonts — something
a pure-Python PDF library would need font registration and CJK handling to do.
If no browser is found, the styled HTML is still written and can be printed to
PDF from any browser with Ctrl+P.
"""

from __future__ import annotations

import html as html_lib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# Browsers that support --print-to-pdf, in preference order.
BROWSER_CANDIDATES: Sequence[str] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
BROWSER_ON_PATH: Sequence[str] = ("msedge", "chrome", "chromium", "google-chrome", "chromium-browser")

CSS = """
@page {
  size: A4;
  margin: 16mm 14mm 18mm 14mm;
}

:root {
  --ink: #1a1d21;
  --muted: #5c6470;
  --line: #d8dde3;
  --accent: #c2410c;
  --accent-soft: #fff5ed;
  --band: #f4f6f8;
  --pos: #15803d;
  --neg: #b91c1c;
}

* { box-sizing: border-box; }

body {
  font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo",
               "Noto Sans KR", system-ui, -apple-system, sans-serif;
  font-size: 10pt;
  line-height: 1.55;
  color: var(--ink);
  margin: 0;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

h1 {
  font-size: 21pt;
  line-height: 1.2;
  margin: 0 0 4pt;
  letter-spacing: -0.4pt;
  color: var(--ink);
}

h1 + p { color: var(--muted); margin-top: 0; }

h2 {
  font-size: 14pt;
  margin: 0 0 10pt;
  padding: 7pt 0 6pt;
  border-top: 2.5pt solid var(--accent);
  border-bottom: 0.5pt solid var(--line);
  break-before: page;
  break-after: avoid;
  letter-spacing: -0.2pt;
}
h2:first-of-type { break-before: auto; }

h3 {
  font-size: 11.5pt;
  margin: 14pt 0 5pt;
  color: var(--accent);
  break-after: avoid;
}

p { margin: 0 0 7pt; orphans: 2; widows: 2; }

strong { font-weight: 650; }

code {
  font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
  font-size: 8.8pt;
  background: var(--band);
  padding: 0.5pt 3pt;
  border-radius: 2pt;
  white-space: pre;          /* keeps the topic-bar alignment intact */
}

blockquote {
  margin: 7pt 0;
  padding: 6pt 10pt;
  background: var(--accent-soft);
  border-left: 2.5pt solid var(--accent);
  color: #52321f;
  font-size: 9.2pt;
  break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }

table {
  width: 100%;
  border-collapse: collapse;
  margin: 7pt 0 11pt;
  font-size: 9pt;
  break-inside: auto;
}

th, td {
  border: 0.5pt solid var(--line);
  padding: 4.5pt 7pt;
  text-align: left;
  vertical-align: top;
}

th {
  background: var(--band);
  font-weight: 650;
  font-size: 8.8pt;
  letter-spacing: 0.2pt;
}

tr { break-inside: avoid; }
thead { display: table-header-group; }   /* repeat headers across pages */

/* The recommendation tables use an empty header row - hide it. */
table.headless thead { display: none; }
table.headless td:first-child {
  background: var(--band);
  font-weight: 600;
  width: 30%;
}

ul { margin: 0 0 9pt; padding-left: 15pt; }
li { margin-bottom: 5pt; break-inside: avoid; }

hr {
  border: none;
  border-top: 0.5pt solid var(--line);
  margin: 14pt 0;
}

.meta {
  color: var(--muted);
  font-size: 9pt;
}

.footer {
  margin-top: 16pt;
  padding-top: 7pt;
  border-top: 0.5pt solid var(--line);
  color: var(--muted);
  font-size: 8pt;
}
"""

# ---------------------------------------------------------------- inline

_INLINE_HTML_ALLOWED = ("br/", "br")


def _escape_keep_breaks(text: str) -> str:
    """Escape HTML, then restore the <br/> tags report.py emits deliberately."""
    escaped = html_lib.escape(text, quote=False)
    for tag in _INLINE_HTML_ALLOWED:
        escaped = escaped.replace(f"&lt;{tag}&gt;", "<br/>")
    return escaped


def _inline(text: str) -> str:
    out = _escape_keep_breaks(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


# ----------------------------------------------------------------- block


def _is_table_divider(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(re.fullmatch(r"\|(?:\s*:?-{2,}:?\s*\|)+", stripped))


def _split_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _alignments(divider: str) -> List[str]:
    result = []
    for cell in _split_row(divider):
        if cell.endswith(":") and cell.startswith(":"):
            result.append("center")
        elif cell.endswith(":"):
            result.append("right")
        else:
            result.append("left")
    return result


def markdown_to_html(markdown_text: str, *, title: str = "Report") -> str:
    lines = markdown_text.split("\n")
    body: List[str] = []
    index = 0
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # --- table -------------------------------------------------------
        if stripped.startswith("|") and index + 1 < len(lines) and _is_table_divider(lines[index + 1]):
            close_list()
            headers = _split_row(stripped)
            aligns = _alignments(lines[index + 1])
            index += 2

            rows: List[List[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1

            headless = all(not h for h in headers)
            body.append(f'<table class="{"headless" if headless else ""}">')
            body.append("<thead><tr>")
            for position, header in enumerate(headers):
                align = aligns[position] if position < len(aligns) else "left"
                body.append(f'<th style="text-align:{align}">{_inline(header)}</th>')
            body.append("</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>")
                for position, cell in enumerate(row):
                    align = aligns[position] if position < len(aligns) else "left"
                    body.append(f'<td style="text-align:{align}">{_inline(cell)}</td>')
                body.append("</tr>")
            body.append("</tbody></table>")
            continue

        # --- headings ----------------------------------------------------
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            body.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        # --- horizontal rule ---------------------------------------------
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            close_list()
            body.append("<hr/>")
            index += 1
            continue

        # --- blockquote (consecutive lines merge into one) ----------------
        if stripped.startswith(">"):
            close_list()
            quote: List[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            body.append(f"<blockquote><p>{_inline(' '.join(quote))}</p></blockquote>")
            continue

        # --- list item ----------------------------------------------------
        item = re.match(r"^[-*+]\s+(.*)$", stripped)
        if item:
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(item.group(1))}</li>")
            index += 1
            continue

        # --- blank / paragraph --------------------------------------------
        if not stripped:
            close_list()
            index += 1
            continue

        close_list()
        paragraph: List[str] = []
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(#{1,6}\s|[-*+]\s|>|\||-{3,}$)", lines[index].strip()
        ):
            paragraph.append(lines[index].strip())
            index += 1
        # A trailing double-space in Markdown means a hard line break.
        body.append("<p>" + _inline("\n".join(paragraph)).replace("\n", "<br/>") + "</p>")

    close_list()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{html_lib.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
{chr(10).join(body)}
<div class="footer">
  Generated by the Zorvex SNS listening system &middot; I'M IN BUSAN Impact Hackathon 2026
</div>
</body>
</html>"""


# ------------------------------------------------------------------- pdf


def find_browser() -> Optional[str]:
    """Locate a Chromium-family browser that can print to PDF."""
    override = os.environ.get("PDF_BROWSER")
    if override and Path(override).exists():
        return override
    for candidate in BROWSER_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in BROWSER_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html_path: Path, pdf_path: Path, *, timeout: int = 120) -> bool:
    """Render `html_path` to `pdf_path` with headless Chromium. False if unavailable."""
    browser = find_browser()
    if not browser:
        return False

    # Chromium needs absolute paths: a file:// URI and an absolute output path.
    html_path = html_path.resolve()
    pdf_path = pdf_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    base_args = [
        browser,
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]

    # `--headless=new` is required by recent builds; classic `--headless`
    # still works on older ones, so try both before giving up.
    for headless_flag in ("--headless=new", "--headless"):
        args = [base_args[0], headless_flag, *base_args[1:]]
        try:
            subprocess.run(
                args,
                timeout=timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            return True
    return False


def export_pdf(
    markdown_path: Path,
    pdf_path: Optional[Path] = None,
    *,
    title: Optional[str] = None,
    keep_html: bool = True,
) -> dict:
    """Convert a Markdown report to HTML and (if possible) PDF.

    Returns {"html": Path, "pdf": Path | None}. The HTML is always written, so
    a missing browser degrades to "open this and press Ctrl+P" rather than
    failing the run.
    """
    markdown_path = Path(markdown_path).resolve()
    if not markdown_path.exists():
        raise FileNotFoundError(f"No such report: {markdown_path}")

    text = markdown_path.read_text(encoding="utf-8")
    heading = next((l.lstrip("# ").strip() for l in text.split("\n") if l.startswith("# ")), None)
    html = markdown_to_html(text, title=title or heading or markdown_path.stem)

    html_path = markdown_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    target = Path(pdf_path) if pdf_path else markdown_path.with_suffix(".pdf")
    produced = html_to_pdf(html_path, target)

    if not keep_html and produced:
        html_path.unlink(missing_ok=True)

    return {"html": html_path if (keep_html or not produced) else None,
            "pdf": target if produced else None}
