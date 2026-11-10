"""Build static Atlas illustrations from interests approved for publication.

No personal model is read. These labels and tentative connections are the
reviewed, selected illustration content, rather than an exported profile.
"""
from pathlib import Path
from xml.sax.saxutils import escape
import json
import re

OUT = Path(__file__).resolve().parent
INK, MUTED, RULE, BLUE, RED = '#090909', '#6B6B6B', '#E6E6E6', '#2355C6', '#C53A32'
wordmark = (OUT.parents[1] / 'skills/trurl/assets/trurl-wordmark.svg').read_text()
logo = re.search(r'(<g fill=.*?</g>)', wordmark, re.S).group(1)


def text(x, y, value, size=16, fill=INK, weight=400, extra=''):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" {extra}>{escape(value)}</text>'


def line(x1, y1, x2, y2, color=RULE, width=1, extra=''):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" {extra}/>'


def rect(x, y, width, height, stroke=RULE, fill='white', rx=0):
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>'


def label(x, y, value, fill=MUTED, extra=''):
    return text(x, y, value.upper(), 10, fill, 550, f'letter-spacing="1.25" {extra}')


def begin(title, description, height):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>',
        f'<rect width="1200" height="{height}" fill="white"/><g font-family="Arial, Helvetica, sans-serif">',
        f'<g transform="translate(48 32) scale(.13)">{logo}</g>',
        label(1152, 53, 'Illustrated view · selected real interests', extra='text-anchor="end"'),
    ]


def finish(parts, name):
    (OUT / name).write_text('\n'.join(parts + ['</g></svg>']) + '\n')


def card(x, y, width, heading, lines, kind='topic', height=61):
    color = RED if kind == 'hypothesis' else INK if kind == 'work' else RULE
    parts = [rect(x, y, width, height, color, '#FAFAFA' if kind == 'work' else 'white', 3),
             label(x + 14, y + 20, heading, RED if kind == 'hypothesis' else MUTED)]
    parts += [text(x + 14, y + 44 + index * 21, value, 15, RED if kind == 'hypothesis' else INK, 500)
              for index, value in enumerate(lines)]
    return parts


# Genre is the only sourced path here. The two enjoyed works stay hypotheses.
s = begin('A real discovery, with its evidence in view',
          'Illustrated Atlas Connections view using shared real interests. Science fiction has a solid sourced genre connection to A Memory Called Empire. Mad Men and Red Rising connect through a dashed, unconfirmed hypothesis about power, status and persuasion.', 900)
s += [text(48, 119, 'Where your interests meet', 38, weight=500),
      text(48, 151, 'Choose a work. Follow the connections. Inspect what supports each one.', 17, MUTED),
      line(48, 180, 1152, 180), text(48, 207, 'Connections', 13, BLUE, 550),
      text(158, 207, 'Interests', 13, MUTED), text(245, 207, 'Activity', 13, MUTED),
      rect(48, 236, 1104, 567), line(312, 236, 312, 803),
      text(68, 270, 'Explore a work', 17, weight=550), rect(68, 292, 224, 39, '#A0A0A0', rx=3),
      text(80, 316, 'Find a work or interest', 12, MUTED)]
for y, title_lines, meta, active in [
    (353, ['A Memory Called Empire'], '1 sourced path · 1 hypothesis', True),
    (444, ['The Art of Gandhara'], 'Recommended', False),
    (535, ['Exploring Chinese Teas', 'and Tea Wares'], 'Recommended', False),
]:
    if active:
        s += [rect(59, y - 7, 244, 75, stroke='none', fill='#FAFAFA'), line(59, y - 7, 59, y + 68, BLUE, 2)]
    s += [text(77, y + 15 + index * 19, value, 14, weight=500) for index, value in enumerate(title_lines)]
    s += [text(77, y + 39 + (len(title_lines) - 1) * 19, meta, 11, MUTED)]
s += [text(338, 271, 'A Memory Called Empire', 26, weight=500),
      text(338, 299, 'Arkady Martine · book', 13, MUTED),
      text(338, 325, 'RECOMMENDED', 10, BLUE, 550, 'letter-spacing="1"'),
      label(338, 366, 'Your interests'), label(565, 366, 'Recorded connections'), label(905, 366, 'A discovery'),
      line(512, 420, 865, 442, INK, 1.5), text(680, 410, 'Genre: science fiction', 11, MUTED, extra='text-anchor="middle"'),
      line(512, 520, 565, 558, RED, 1.5, 'stroke-dasharray="5 5"'),
      line(512, 610, 565, 592, RED, 1.5, 'stroke-dasharray="5 5"'),
      line(830, 575, 865, 490, RED, 1.5, 'stroke-dasharray="5 5"')]
s += card(338, 390, 174, 'Stated interest', ['Science fiction'])
s += card(338, 490, 174, 'Enjoyed work', ['Mad Men'])
s += card(338, 580, 174, 'Enjoyed work', ['Red Rising'])
s += card(565, 535, 265, 'Tentative taste hypothesis', ['Power, status', 'and persuasion'], 'hypothesis', 82)
s += card(865, 411, 259, 'Work', ['A Memory Called', 'Empire'], 'work', 94)
s += [line(338, 677, 1124, 677), label(338, 705, 'Inspect the source'),
      text(338, 734, 'Pan Macmillan identifies a space opera about an ambassador navigating imperial intrigue.', 13, MUTED),
      text(338, 760, 'The proposed link to Mad Men and Red Rising remains a hypothesis to test.', 13, RED),
      line(48, 839, 83, 839, INK, 1.5), text(93, 843, 'Sourced content relationship', 12, MUTED),
      line(352, 839, 387, 839, RED, 1.5, 'stroke-dasharray="5 5"'), text(397, 843, 'Unconfirmed taste hypothesis', 12, RED),
      text(1152, 843, 'Personal fit stays open to feedback.', 12, MUTED, extra='text-anchor="end"')]
finish(s, 'atlas-connections-example.svg')

# A selected subset: no activity totals, feedback or private model metadata.
s = begin('An atlas of real curiosity',
          'Illustrated Atlas interest view of eight selected real interests and two tentative possibilities, shared with permission. Black circles are stated interests and red diamonds are hypotheses. Positions do not encode preference strength.', 840)
s += [text(48, 119, 'An atlas of your curiosity', 38, weight=500),
      text(48, 151, 'A selection of real interests, with possibilities still taking shape.', 17, MUTED),
      line(48, 180, 1152, 180), rect(48, 226, 1104, 536), line(726, 226, 726, 762),
      label(68, 256, 'Interest map'), label(706, 256, 'By evidence', extra='text-anchor="end"')]
cx, cy = 385, 510
s += [f'<ellipse cx="{cx}" cy="{cy}" rx="284" ry="202" fill="none" stroke="{RULE}"/>',
      f'<ellipse cx="{cx}" cy="{cy}" rx="210" ry="143" fill="none" stroke="{RULE}"/>',
      line(81, cy, 689, cy), line(cx, 280, cx, 720),
      f'<circle cx="{cx}" cy="{cy}" r="49" fill="white" stroke="{RULE}"/>',
      text(cx, cy + 3, '10', 27, weight=500, extra='text-anchor="middle"'),
      text(cx, cy + 24, 'IN VIEW', 9, MUTED, extra='text-anchor="middle" letter-spacing="1"')]
for x, y, lines in [
    (385, 367, [(329, 350, 'Human learning')]),
    (534, 409, [(492, 390, 'Artificial intelligence')]),
    (595, 510, [(606, 515, 'History')]),
    (534, 611, [(479, 638, 'Retro video games')]),
    (385, 653, [(319, 679, 'Papua New Guinea'), (316, 697, 'first-contact histories')]),
    (236, 611, [(176, 638, 'Advertising')]),
    (175, 510, [(100, 535, 'Chinese gongfu cha')]),
    (236, 409, [(171, 390, 'Stanisław Lem')]),
]:
    s += [f'<circle cx="{x}" cy="{y}" r="6" fill="{INK}"/>']
    s += [text(tx, ty, value, 12) for tx, ty, value in lines]
for x, y, lines in [
    (385, 308, [(292, 289, 'How different minds learn')]),
    (624, 640, [(554, 675, 'First contact and'), (563, 693, 'understanding')]),
]:
    s += [f'<path d="M{x} {y-8}l8 8-8 8-8-8Z" fill="white" stroke="{RED}" stroke-width="1.7"/>']
    s += [text(tx, ty, value, 12, RED) for tx, ty, value in lines]
s += [label(750, 256, 'Inspect a possibility', RED),
      text(750, 299, 'First contact and', 25, weight=500), text(750, 330, 'understanding', 25, weight=500),
      text(750, 365, 'POSSIBLE INTEREST · EXPLORING', 10, RED, 550, 'letter-spacing="1"'),
      line(750, 390, 1128, 390), text(750, 430, 'From your interests in', 13, weight=550),
      text(750, 457, 'Stanisław Lem', 13, MUTED),
      text(750, 481, 'First-contact histories in Papua New Guinea', 13, MUTED)]
for y, value in [
    (531, 'Lem’s fiction and first-contact histories'),
    (555, 'in Papua New Guinea offer a possible route'),
    (579, 'into the limits of understanding unfamiliar'),
    (603, 'perspectives. That connection remains'),
    (627, 'a hypothesis to explore.'),
    (675, 'Why either interest appeals is still open.'),
]:
    s += [text(750, y, value, 13, MUTED)]
s += [line(750, 705, 1128, 705), text(750, 735, 'Feedback can strengthen, narrow or reject it.', 12, MUTED),
      '<circle cx="55" cy="797" r="5" fill="#090909"/>', text(69, 801, 'Stated interest', 12, MUTED),
      f'<path d="M238 791l6 6-6 6-6-6Z" fill="white" stroke="{RED}" stroke-width="1.5"/>',
      text(252, 801, 'Possibility · exploring', 12, MUTED),
      text(1152, 801, 'Position does not measure preference strength.', 11, MUTED, extra='text-anchor="end"')]
finish(s, 'atlas-interests-example.svg')

manifest = {
    'notice': 'Public promotional illustrations using selected real interests shared with permission. Hypotheses remain tentative. These are static illustrated views, not screenshots; no raw profile, feedback, identity or provenance records are included.',
    'assets': [
        {'path': 'curiosity-paths.png', 'type': 'generated_editorial_illustration',
         'alt': 'Open books send paths across a spare black-and-white atlas landscape toward a small blue doorway.',
         'caption': 'A few curiosities. An unexpected direction.',
         'method': 'Built-in image_gen; prompt saved in hero-prompt.txt.'},
        {'path': 'atlas-connections-example.svg', 'type': 'static_native_svg_product_illustration',
         'alt': 'A Memory Called Empire connects to science fiction through a solid genre path; Mad Men and Red Rising connect through a separate dashed hypothesis about power, status and persuasion.',
         'caption': 'Illustrated Atlas Connections view · selected real interests, shared with permission.',
         'content_source': 'https://www.panmacmillan.com/authors/arkady-martine/a-memory-called-empire/9781529001594'},
        {'path': 'atlas-interests-example.svg', 'type': 'static_native_svg_product_illustration',
         'alt': 'Eight selected real interests include Lem, AI, learning, history, gongfu tea, advertising, retro games and Papua New Guinea first-contact histories; two red possibilities remain tentative.',
         'caption': 'Illustrated Atlas interest view · selected real interests, shared with permission.'},
    ],
}
(OUT / 'assets.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
