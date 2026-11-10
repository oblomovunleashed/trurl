#!/usr/bin/env python3
"""Render a Sunday edition from public-facing, already verified pick metadata."""
import argparse
from datetime import date
from html import escape
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unicodedata import combining, east_asian_width
from urllib.parse import urlsplit
from xml.etree import ElementTree


CATEGORIES = {
    "book": "Book",
    "film": "Film",
    "podcast": "Podcast",
    "youtube_video": "YouTube video",
    "lecture": "Lecture",
    "scientific_paper": "Paper",
}
WIDTH = 768
INSET = 44
COPY_X = 211
COPY_WIDTH = WIDTH - COPY_X - INSET
INK = "#090909"
MUTED = "#6B6B6B"
BLUE = "#2355C6"
RULE = "#E6E6E6"


def public_text(pick, field, required=False):
    value = pick.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"{field} is required")
    if any(ord(character) < 32 or ord(character) in {0xFFFE, 0xFFFF} for character in value):
        raise ValueError(f"{field} contains an unsupported character")
    return value


def load_edition(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("The edition must be an object")
    date_text = raw.get("edition_date")
    if not isinstance(date_text, str):
        raise ValueError("edition_date must be a Sunday in YYYY-MM-DD format")
    edition_date = date.fromisoformat(date_text)
    if edition_date.isoformat() != date_text or edition_date.weekday() != 6:
        raise ValueError("edition_date must be a Sunday in YYYY-MM-DD format")

    categories = raw.get("categories")
    if not isinstance(categories, list) or not categories or not all(
        isinstance(category, str) and category in CATEGORIES for category in categories
    ) or len(categories) != len(set(categories)):
        raise ValueError("categories must list distinct supported formats")
    picks = raw.get("picks")
    if not isinstance(picks, list):
        raise ValueError("picks must be a list")

    by_category = {}
    urls = set()
    for pick in picks:
        if not isinstance(pick, dict):
            raise ValueError("Each pick must be an object")
        medium = public_text(pick, "medium", required=True)
        if medium not in categories or medium in by_category:
            raise ValueError(f"Expected at most one pick for each chosen category: {medium}")
        url = public_text(pick, "canonical_url", required=True)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or re.search(r'[\s<>\\"]', url):
            raise ValueError(f"Expected a public HTTPS work link for {medium}")
        if url in urls:
            raise ValueError("Each category must have a distinct work link")
        urls.add(url)
        by_category[medium] = {
            "canonical_url": url,
            "title": public_text(pick, "title", required=True),
            "creator": public_text(pick, "creator", required=True),
            "description": public_text(pick, "description"),
            "detail": public_text(pick, "detail"),
        }
    return edition_date, [(CATEGORIES[category], by_category.get(category)) for category in categories]


def markdown_text(value):
    return re.sub(r'([\\\x60*_[\]<>!&])', r'\\\1', value)


def issue_markdown(date_label, slots):
    lines = [
        "# Sunday edition", "", date_label, "",
        "![The Trurl Sunday edition. The full selection and links follow below.](sunday-edition.svg)", "",
    ]
    for label, pick in slots:
        lines.extend([f"## {label}", ""])
        if pick is None:
            lines.extend(["No verified pick this week.", ""])
            continue
        title = markdown_text(pick["title"])
        creator = markdown_text(pick["creator"])
        lines.extend([f"**[{title}](<{pick['canonical_url']}>)** · {creator}", ""])
        for field in ("detail", "description"):
            if pick[field]:
                lines.extend([markdown_text(pick[field]), ""])
    return "\n".join(lines)


def character_width(character):
    if combining(character):
        return 0
    if east_asian_width(character) in {"W", "F"} or character in "MWmw@%":
        return 1.1
    if character in " ilI.,:;’'!|":
        return 0.38
    return 0.78 if character.isupper() else 0.65


def wrapped_lines(value, size):
    limit = COPY_WIDTH / size
    line = ""
    width = 0
    for word in value.split():
        word_width = sum(map(character_width, word))
        if line and width + character_width(" ") + word_width > limit:
            yield line
            line, width = "", 0
        if line:
            line += " "
            width += character_width(" ")
        for character in word:
            advance = character_width(character)
            if width + advance > limit:
                yield line
                line, width = "", 0
            line += character
            width += advance
    if line:
        yield line


def svg_text(x, y, value, size, color=INK, attributes=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}"{attributes}>{escape(value)}</text>'


def rule(y):
    return f'<path d="M{INSET} {y}H{WIDTH - INSET}" fill="none" stroke="{RULE}" stroke-width="1.5"/>'


def svg_wordmark():
    path = Path(__file__).resolve().parents[1] / "assets" / "trurl-wordmark.svg"
    paths = ElementTree.parse(path).getroot().iter("{http://www.w3.org/2000/svg}path")
    contours = "".join(f'<path d="{escape(item.attrib["d"], quote=True)}"/>' for item in paths)
    return f'<g transform="translate({INSET} 35) scale(0.132)" fill="{INK}">{contours}</g>'


def issue_svg(date_label, slots):
    bold = ' font-weight="700"'
    overline = bold + ' letter-spacing="1.6"'
    serif = ' font-family="Georgia, Times New Roman, serif"'
    rows = [
        svg_wordmark(),
        svg_text(WIDTH - INSET, 60, date_label.upper(), 15, BLUE, overline + ' text-anchor="end"'),
        rule(96),
        svg_text(INSET - 3, 183, "Sunday edition", 68, attributes=serif + ' letter-spacing="-2"'),
        svg_text(INSET, 223, "One pick per category", 22, MUTED),
    ]
    y = 255
    for label, pick in slots:
        rows.append(rule(y))
        rows.append(svg_text(INSET, y + 39, label.upper(), 15, BLUE, overline))
        cursor = y + 42
        if pick is None:
            rows.append(svg_text(COPY_X, cursor, "No verified pick this week", 22, MUTED))
            y = cursor + 31
            continue
        fields = (
            (pick["title"], 29, 33, INK, serif),
            (pick["creator"], 19, 25, INK, bold),
            (pick["detail"], 16, 22, BLUE, ""),
            (pick["description"], 19, 25, MUTED, ""),
        )
        for value, size, line_height, color, attributes in fields:
            for line in wrapped_lines(value, size):
                rows.append(svg_text(COPY_X, cursor, line, size, color, attributes))
                cursor += line_height
        y = cursor + 9
    rows.append(rule(y))
    height = y + 34
    body = "\n    ".join(rows)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Trurl Sunday edition, {escape(date_label)}</title>
  <desc id="desc">One pick per category. See the accompanying issue text for the selection and direct links.</desc>
  <rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2}" fill="#FFFFFF" stroke="{RULE}" stroke-width="2"/>
  <g font-family="Arial, Helvetica, sans-serif">
    {body}
  </g>
</svg>
'''


def render_edition(source, destination):
    edition_date, slots = load_edition(source)
    label = f"Sunday, {edition_date.day} {edition_date:%B %Y}"
    svg = issue_svg(label, slots)
    markdown = issue_markdown(label, slots)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Choose a new output directory for this edition")
    with TemporaryDirectory(prefix=".trurl-edition-", dir=destination.parent) as temp:
        staging = Path(temp) / "edition"
        staging.mkdir()
        (staging / "sunday-edition.svg").write_text(svg, encoding="utf-8")
        (staging / "sunday-edition.md").write_text(markdown, encoding="utf-8")
        staging.rename(destination)
    return {
        "directory": str(destination),
        "picks": sum(pick is not None for _, pick in slots),
        "shortfalls": [category for category, pick in slots if pick is None],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="render a verified Sunday issue as SVG and Markdown")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = render_edition(args.input, args.output_dir)
    except (ValueError, OSError) as error:
        parser.exit(2, f"trurl sunday: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
