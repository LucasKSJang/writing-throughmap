"""Tests for the poster: the #poster mode, window.throughmap.posterSVG() and exportPNG().

The poster is one svg element, id tm-poster, that the page draws from its data: the header, the
section cards, the thread map, the recurring examples and a footer line. The page's DOM also
holds the analysis as JSON and the template's script with its string table, so a string found
anywhere in the DOM proves nothing (ruling R34). Every check on what the poster shows reads the
text drawn inside the poster's own svg element, and a negative control shows that those checks
fail when no poster is drawn, while the same strings are still found in the DOM.

The tests that need a browser skip when there is none: set THROUGHMAP_BROWSER.
"""

import base64
import json
import re
import struct
import unittest
import xml.etree.ElementTree as ElementTree
import zlib
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from tests.browser import dump_dom, find_browser, screenshot
from tests.fixtures import (
    TEMPLATE_PATH, built_sample, forty_paragraphs, page, sample_analysis, tmp_path, total_marks,
    write_page_directly,
)
from tests.test_page import NO_ERRORS, rendered, start_tags, with_script
from tm_text import slugify

SVG_NS = "http://www.w3.org/2000/svg"
WIDTH, PAD = 1200, 48
POSTER_FONT = ('-apple-system, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", '
               '"Noto Sans KR", sans-serif')
# The poster's colours (brief): background, text, secondary, borders, card fill, teal, purple.
PALETTE = ("#ffffff", "#1f1f1e", "#5f5e5a", "#d3d1c7", "#f7f6f2", "#1d9e75", "#7f77dd")
NEUTRAL_HUE = "#8a887f"              # the page's dot for a question that no thread follows
WHITE = (255, 255, 255)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Markup, an ampersand and quotes, as a draft can hold them.
MARKUP = '</script><b>bold</b> & "quoted"'


# --- Reading the poster out of a DOM dump --------------------------------------------------------


class _Node:
    """An element inside the poster, as the DOM dump has it: tag, attributes and children."""

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []               # _Node elements and str character data, in order

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def elements(self):
        """Yield this element and every element inside it, in document order."""
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.elements()

    def find_all(self, tag, cls=None):
        """Return the elements named ``tag`` in this one, with the class ``cls`` if it is given."""
        return [node for node in self.elements()
                if node.tag == tag and (cls is None or cls in node.classes())]

    def lines(self):
        """Return what this element draws as text: one string per text element, in order."""
        return [_characters(node) for node in self.find_all("text")]

    def drawn(self):
        """Return the text this element draws, its text elements joined by spaces."""
        return " ".join(self.lines())


def _characters(node):
    """Return the character data inside ``node``, leaving out title and style elements."""
    return "".join(child if isinstance(child, str) else
                   "" if child.tag in ("title", "style") else _characters(child)
                   for child in node.children)


class _PosterParser(HTMLParser):
    """Build the tree of the first svg element whose id is tm-poster in a serialized DOM."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.poster = None
        self.open = []                   # the elements open inside the poster, the poster first

    def handle_starttag(self, tag, attrs):
        if self.open:
            node = _Node(tag, attrs)
            self.open[-1].children.append(node)
            self.open.append(node)
        elif self.poster is None and tag == "svg" and ("id", "tm-poster") in attrs:
            self.poster = _Node(tag, attrs)
            self.open.append(self.poster)

    def handle_endtag(self, tag):
        if self.open:
            self.open.pop()

    def handle_data(self, data):
        if self.open:
            self.open[-1].children.append(data)


def poster_in(dom):
    """Return the poster's tree from a DOM dump, or None when the DOM holds no poster."""
    parser = _PosterParser()
    parser.feed(dom)
    parser.close()
    return parser.poster


def poster_problems(poster, analysis):
    """Return what the poster fails to draw of ``analysis``; an empty list when it draws it all.

    Each check reads only the text drawn inside the poster's svg element (R34): the title, the
    short name that opens each section's card, one dot per lane mark, and a chip per recurring
    example that opens with its name.
    """
    if poster is None:
        return ["no poster"]
    problems = []
    title = " ".join(node.drawn() for node in poster.find_all("text", "tm-p-title"))
    if title != analysis["essay"]["title"]:
        problems.append("title")
    cards = {node.attrs.get("data-section"): node for node in poster.find_all("g", "tm-p-card")}
    for section in analysis["sections"]:
        card = cards.get(section["id"])
        if card is None or not card.drawn().startswith(section["short"]):
            problems.append(f"section {section['id']}")
    if len(poster.find_all("circle", "tm-mark")) != total_marks(analysis):
        problems.append("marks")
    chips = [node.drawn() for node in poster.find_all("g", "tm-p-case")]
    for case in analysis["cases"]:
        if not any(chip.startswith(case["name"]) for chip in chips):
            problems.append(f"case {case['name']}")
    return problems


def every_problem(analysis):
    """Return the problems poster_problems finds in a poster that draws nothing of ``analysis``."""
    return (["title"] + [f"section {section['id']}" for section in analysis["sections"]]
            + ["marks"] + [f"case {case['name']}" for case in analysis["cases"]])


def drawn_texts(svg):
    """Return the text of each text element in a parsed svg (ElementTree), in document order."""
    def characters(element):
        inside = "".join(characters(child) + (child.tail or "") for child in element
                         if child.tag not in (f"{{{SVG_NS}}}title", f"{{{SVG_NS}}}style"))
        return (element.text or "") + inside
    return [characters(element) for element in svg.iter(f"{{{SVG_NS}}}text")]


# --- PNG files -------------------------------------------------------------------------------------


def png_size(data):
    """Return (width, height) from the header of a PNG."""
    return struct.unpack(">II", data[16:24])


def png_rows(data, count):
    """Return the top ``count`` rows of an 8-bit RGB or RGBA PNG, each a list of (r, g, b)."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG")
    position, header, compressed = 8, None, []
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.append(body)
        position += 12 + length
    width, _, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in (2, 6) or interlace:
        raise ValueError(f"unexpected PNG format: depth {depth}, colour type {colour}")
    channels = 3 if colour == 2 else 4
    stride = width * channels
    raw = zlib.decompressobj().decompress(b"".join(compressed), (stride + 1) * count)
    rows, previous = [], bytearray(stride)
    for number in range(count):
        line = raw[number * (stride + 1):(number + 1) * (stride + 1)]
        kind, row = line[0], bytearray(line[1:])
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                row[i] = (row[i] + left) & 255
            elif kind == 2:
                row[i] = (row[i] + up) & 255
            elif kind == 3:
                row[i] = (row[i] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min((abs(guess - left), 0, left), (abs(guess - up), 1, up),
                           (abs(guess - corner), 2, corner))
                row[i] = (row[i] + near[2]) & 255
        rows.append([tuple(row[x:x + 3]) for x in range(0, stride, channels)])
        previous = row
    return rows


# --- Scripts the tests run on the page, on load (with_script) -------------------------------------

# Write the result of a test script as JSON into <pre id="t8-out">.
WRITE = """
function t8write(result) {
  const out = document.createElement("pre");
  out.id = "t8-out";
  out.textContent = JSON.stringify(result);
  document.body.appendChild(out);
}
"""

# What exportPNG hands the browser, recorded without letting it download anything: the blob
# URLs made and revoked, and the link it clicks. Once the export is done, the PNG is read back:
# its bytes in base64, and its teal, purple and text-coloured pixels counted after the browser
# decodes it again. posterSVG() comes along, to compare the sizes.
EXPORT_HOOK = WRITE + """
const t8blobs = new Map();
const t8seen = {created: [], revoked: []};
let t8clicked = null;
const t8create = URL.createObjectURL.bind(URL);
const t8revoke = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = function (blob) {
  const url = t8create(blob);
  t8blobs.set(url, blob);
  t8seen.created.push(blob.type);
  return url;
};
URL.revokeObjectURL = function (url) {
  t8seen.revoked.push(t8blobs.has(url) ? t8blobs.get(url).type : "unknown");
  t8revoke(url);
};
HTMLAnchorElement.prototype.click = function () {
  t8clicked = {name: this.download, blob: t8blobs.get(this.href) || null};
};
function t8inspect(png) {
  const base64 = new Promise(function (resolve) {
    const reader = new FileReader();
    reader.onload = function () { resolve(reader.result.split(",")[1]); };
    reader.readAsDataURL(png);
  });
  // An image from the PNG's own data URL: createImageBitmap never settles in a headless browser
  // that runs on virtual time.
  return base64.then(function (data) {
    return new Promise(function (resolve, reject) {
      const image = new Image();
      image.onload = function () { resolve({data: data, image: image}); };
      image.onerror = function () { reject(new Error("the PNG does not decode")); };
      image.src = "data:image/png;base64," + data;
    });
  }).then(function (loaded) {
    const image = loaded.image;
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const counts = {teal: 0, purple: 0, ink: 0, black: 0};
    for (let i = 0; i < pixels.length; i += 4) {
      const rgb = (pixels[i] << 16) | (pixels[i + 1] << 8) | pixels[i + 2];
      if (rgb === 0x1D9E75) counts.teal += 1;
      else if (rgb === 0x7F77DD) counts.purple += 1;
      else if (rgb === 0x1F1F1E) counts.ink += 1;
      else if (rgb === 0) counts.black += 1;
    }
    return {base64: loaded.data, counts: counts};
  });
}
function t8finish(running) {
  Promise.resolve(running).then(function (value) {
    const result = {seen: t8seen, value: value === undefined ? "undefined" : String(value),
                    svg: window.throughmap.posterSVG()};
    if (!t8clicked || !t8clicked.blob) return t8write(Object.assign(result, {clicked: t8clicked}));
    return t8inspect(t8clicked.blob).then(function (png) {
      t8write(Object.assign(result, {name: t8clicked.name, type: t8clicked.blob.type,
                                     png: png.base64, counts: png.counts}));
    });
  }).catch(function (error) { t8write({error: String(error && error.stack || error)}); });
}
"""
EXPORT_BY_API = EXPORT_HOOK + "t8finish(window.throughmap.exportPNG());"
# The Save PNG button: exportPNG is watched, so the test knows when the export the button started
# is done, and whether the button was disabled while it ran.
EXPORT_BY_BUTTON = EXPORT_HOOK + """
const t8real = window.throughmap.exportPNG;
window.throughmap.exportPNG = function () {
  t8seen.disabledWhileRunning = document.getElementById("tm-png").disabled;
  const running = t8real.apply(this, arguments);
  t8finish(running);
  return running;
};
document.getElementById("tm-png").click();
"""

# The names of the downloads for each [source, title] in __PAIRS__, set one after the other on
# the page's own data. The canvas is not encoded: only the name counts here.
NAMES_HOOK = WRITE + """
const t8names = [];
HTMLAnchorElement.prototype.click = function () { t8names.push(this.download); };
HTMLCanvasElement.prototype.toBlob = function (callback) {
  callback(new Blob(["png"], {type: "image/png"}));
};
const t8essay = window.throughmap.data.essay;
__PAIRS__.reduce(function (chain, pair) {
  return chain.then(function () {
    t8essay.source = pair[0];
    t8essay.title = pair[1];
    return window.throughmap.exportPNG();
  });
}, Promise.resolve()).then(function () { t8write(t8names); }).catch(function (error) {
  t8write({error: String(error && error.stack || error)});
});
"""

WRITE_POSTER_SVG = """
const out = document.createElement("pre");
out.id = "t8-svg";
out.textContent = window.throughmap.posterSVG();
document.body.appendChild(out);
"""

# Run in #poster mode: the text elements of the poster that stick out of its content box (inside
# the 48 px padding), out of the card they belong to, or into the card's question chips. Then a
# probe, a text far too long for a card, is put into the first card to show that the check finds
# such a text.
OVERFLOW_CHECK = WRITE + """
function t8outside(inner, outer) {
  return inner.left < outer.left - 0.5 || inner.right > outer.right + 0.5
    || inner.top < outer.top - 0.5 || inner.bottom > outer.bottom + 0.5;
}
function t8overlap(one, other) {
  return one.left < other.right - 0.5 && other.left < one.right - 0.5
    && one.top < other.bottom - 0.5 && other.top < one.bottom - 0.5;
}
function t8overflows() {
  const poster = document.getElementById("tm-poster");
  const edge = poster.getBoundingClientRect();
  const content = {left: edge.left + 48, right: edge.right - 48, top: edge.top + 48,
                   bottom: edge.bottom - 48};
  const found = [];
  poster.querySelectorAll("text").forEach(function (text) {
    if (t8outside(text.getBoundingClientRect(), content)) found.push("poster: " + text.textContent);
  });
  poster.querySelectorAll(".tm-p-card").forEach(function (card) {
    const box = card.querySelector(".tm-p-cardbg").getBoundingClientRect();
    const chips = Array.from(card.querySelectorAll(".tm-p-answer"));
    card.querySelectorAll("text").forEach(function (text) {
      const place = text.getBoundingClientRect();
      if (t8outside(place, box)) {
        found.push(card.getAttribute("data-section") + ": " + text.textContent);
      }
      chips.forEach(function (chip) {
        if (!chip.contains(text) && t8overlap(place, chip.getBoundingClientRect())) {
          found.push(card.getAttribute("data-section") + " chip: " + text.textContent);
        }
      });
    });
  });
  return found;
}
const t8before = t8overflows();
const t8card = document.querySelector("#tm-poster .tm-p-card");
const t8box = t8card.querySelector(".tm-p-cardbg");
const t8probe = document.createElementNS("http://www.w3.org/2000/svg", "text");
t8probe.setAttribute("x", t8box.getAttribute("x"));
t8probe.setAttribute("y", Number(t8box.getAttribute("y")) + 20);
t8probe.setAttribute("class", "tm-p-concl");
t8probe.textContent = "probe ".repeat(300).trim();
t8card.appendChild(t8probe);
const t8after = t8overflows();
t8probe.remove();
t8write({before: t8before, after: t8after});
"""


def long_texts():
    """Return the Korean sample with texts that must wrap: a title and a thesis of two lines or
    more, a long question, a long heading, a Korean conclusion of several lines, a conclusion
    that is one unbroken run of 180 characters and a long English one."""
    a = sample_analysis(ui_language="ko")
    a["essay"]["title"] = ("마을 텃밭이 물을 더 주지 않아도 한여름 더위를 견디는가: 짚 덮개와 흙의 "
                           "관계를 처음부터 다시 읽어 보기")
    a["thesis"] = ("봄에 밭을 짚으로 덮어 두면 흙이 덜 마르고 잡초도 줄어서, mulch를 깔아 둔 밭은 "
                   "여름 내내 물을 덜 주어도 한여름을 견디고 이웃들은 저녁마다 무거운 물통을 나르는 "
                   "수고를 덜어 그 시간을 김매기와 수확에 쓸 수 있다는 것이 이 글의 논지다")
    a["questions"][0]["text"] = ("mulch를 까는 수고가 한 해 동안 물을 덜 주는 이득보다 정말 큰가, "
                                 "그리고 짚을 구하기 어려운 해에는 어떤 덮개가 그 자리를 대신할 수 "
                                 "있는가?")
    # Long enough to run into the question chips at the top right, were no room kept for them.
    a["sections"][1]["title"] = ("A Much Longer Heading That Goes On Well Past The Short Name "
                                 "Of The Section It Names, And Then Keeps Going For A While, "
                                 "Long Enough To Reach The Question Chips")
    a["sections"][0]["conclusion"] = (
        "짚을 덮은 밭은 맨흙 밭보다 흙이 천천히 마르고 잡초가 적게 올라온다는 것이 이 섹션의 결론이고, "
        "그래서 물 주는 횟수를 줄여도 상추와 고추가 잘 자라며 이웃들이 저녁마다 무거운 물통을 나르는 "
        "수고도 크게 덜게 된다는 점을 앞의 두 문단이 함께 보여 준다")
    a["sections"][1]["conclusion"] = "https://example.com/" + "x" * 160
    a["sections"][2]["conclusion"] = (
        "The straw on the beds keeps the soil cool and damp through the hottest weeks of the "
        "summer, so the neighbours water less often, pull fewer weeds and still pick more beans "
        "and peppers than they did in the years when the beds were left bare to the sun.")
    return a


class PosterTestCase(unittest.TestCase):
    def setUp(self):
        if find_browser() is None:
            self.skipTest("no Chrome or Edge found: set THROUGHMAP_BROWSER to a browser")

    def run_script(self, html, script, hash=""):
        """Run ``script`` on load on a copy of ``html``; return the JSON it wrote, and the DOM."""
        dom = dump_dom(with_script(html, script), hash=hash)
        found = re.search(r'<pre id="t8-out">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(found, "the script wrote no result")
        result = json.loads(unescape(found.group(1)))
        if isinstance(result, dict) and "error" in result:
            self.fail(result["error"])
        return result, dom


class PosterTests(PosterTestCase):
    """The poster tests of the plan, with their checks read inside the poster (R34)."""

    def test_poster_mode_renders_svg(self):
        a = sample_analysis(ui_language="ko")
        dom = dump_dom(page(a), hash="poster")
        poster = poster_in(dom)
        self.assertIsNotNone(poster)
        self.assertRegex(dom, r'<svg[^>]*id="tm-poster"[^>]*width="1200"')
        self.assertEqual(poster.attrs["width"], "1200")
        self.assertEqual(poster_problems(poster, a), [])
        self.assertRegex(dom, NO_ERRORS)

    def test_poster_screenshot_png(self):
        png = tmp_path("p.png")
        screenshot(page(sample_analysis()), png, hash="poster", width=1200, height=1800)
        data = Path(png).read_bytes()
        self.assertTrue(data.startswith(PNG_SIGNATURE))
        self.assertGreater(len(data), 20_000)
        self.assertEqual(png_size(data), (2400, 3600))

    def test_the_poster_checks_fail_when_no_poster_is_drawn(self):
        # Negative control for R34. Without #poster, the DOM still holds every string the checks
        # look for, in the data and on the page, but the checks read the poster and so fail.
        a = sample_analysis(ui_language="ko")
        html = page(a)
        plain = dump_dom(html)
        strings = [a["essay"]["title"], a["cases"][0]["name"]]
        strings += [section["short"] for section in a["sections"]]
        for text in strings:
            self.assertIn(text, plain)
        self.assertEqual(plain.count('class="tm-mark'), total_marks(a))
        self.assertIsNone(poster_in(plain))
        self.assertEqual(poster_problems(poster_in(plain), a), ["no poster"])
        # A poster element that draws nothing fails every check, one by one.
        emptied = dump_dom(with_script(html, 'document.getElementById("tm-poster")'
                                             '.replaceChildren();'), hash="poster")
        self.assertIn(a["essay"]["title"], emptied)                        # still in the data
        self.assertEqual(poster_problems(poster_in(emptied), a), every_problem(a))


class PosterContentTests(PosterTestCase):
    """What the poster draws, read inside its svg element."""

    def test_poster_mode_shows_only_the_poster(self):
        a = sample_analysis()
        dom = dump_dom(page(a), hash="poster")
        body = rendered(dom).split("<body>", 1)[1].split("</body>", 1)[0]
        self.assertRegex(body, r'^\s*<pre id="tm-errors" hidden=""></pre>\s*<svg id="tm-poster"')
        self.assertTrue(body.rstrip().endswith("</svg>"))
        self.assertNotIn("<main", body)
        self.assertEqual(body.count('class="tm-card"'), 0)
        self.assertEqual(len(poster_in(dom).find_all("g", "tm-p-card")), 3)

    def test_the_poster_and_the_page_around_it_are_white_in_dark_mode(self):
        html = page(sample_analysis())
        png = tmp_path("dark.png")
        # 1,300 px: the page shows on both sides of the 1,200 px poster.
        screenshot(html, png, hash="poster", width=1300, height=600, scale=1,
                   color_scheme="dark")
        rows = png_rows(Path(png).read_bytes(), 4)
        self.assertEqual({pixel for row in rows for pixel in row}, {WHITE})
        # Negative control: the page itself is dark in the same browser.
        screenshot(html, png, width=1300, height=600, scale=1, color_scheme="dark")
        self.assertNotEqual(png_rows(Path(png).read_bytes(), 1)[0][0], WHITE)

    def test_the_poster_speaks_the_ui_language(self):
        words = sample_analysis()["essay"]["word_count"]
        expected = {
            "en": ([f"sample.md · 6 paragraphs · {words} words · analysis v1", "Thesis",
                    "Questions", "Section flow", "P3 Claim", "T1 Synthesis",
                    "↓ Does the rest slow the bakery?", "Thread map", "Recurring examples",
                    "throughmap · Data file: x.throughmap/v1.json"],
                   "Large dot = main point", "click a thread name"),
            "ko": ([f"sample.md · 문단 6개 · {words}단어 · 분석 v1", "논지", "질문", "섹션 흐름",
                    "P3 주장", "표1 종합", "↓ Does the rest slow the bakery?", "연결 지도", "다시 나오는 사례",
                    "throughmap · 분석 기록: x.throughmap/v1.json"],
                   "큰 점 = 중심 논지", "왼쪽 이름을 누르면"),
        }
        for language, (lines, legend, clicking) in expected.items():
            with self.subTest(language=language):
                poster = poster_in(dump_dom(page(sample_analysis(ui_language=language)),
                                            hash="poster"))
                drawn = poster.lines()
                for line in lines:
                    self.assertIn(line, drawn)
                self.assertIn(legend, poster.drawn())
                self.assertNotIn(clicking, poster.drawn())             # a poster has no clicks

    def test_the_cards_carry_the_inferred_tag_and_the_quote_warning(self):
        a = built_sample()
        a["sections"][1]["inferred"] = True
        a["paragraphs"][1]["evidence"] = "nope"               # P2's quote is not in P2
        for language, tag in (("en", "inferred"), ("ko", "추정")):
            with self.subTest(language=language):
                a["ui_language"] = language
                poster = poster_in(dump_dom(write_page_directly(a), hash="poster"))
                tagged = [card.attrs["data-section"] for card in poster.find_all("g", "tm-p-card")
                          if [_characters(node) for node in card.find_all("text", "tm-p-tag")]
                          == [tag]]
                self.assertEqual(tagged, ["S2"])
                warned = [node.attrs["data-item"] for node in poster.find_all("g", "tm-p-role")
                          if "!" in node.lines()]
                self.assertEqual(warned, ["P2"])

    def test_the_poster_map_is_drawn_at_the_fixed_content_width(self):
        # The map has 1,104 px (1,200 minus twice 48) whatever the window: 120 + 40 x 24.6 for
        # forty paragraphs, 120 + 7 x 36 for the sample.
        for analysis, width in ((forty_paragraphs(), "1104"), (sample_analysis(), "372")):
            with self.subTest(width=width):
                poster = poster_in(dump_dom(page(analysis), hash="poster", width=700))
                maps = poster.find_all("svg", "tm-p-map")
                self.assertEqual(len(maps), 1)
                self.assertEqual((maps[0].attrs["x"], maps[0].attrs["width"]), ("48", width))
                self.assertEqual(poster_problems(poster, analysis), [])

    def test_the_text_wraps_inside_the_poster_and_its_cards(self):
        a = long_texts()
        html = page(a)
        result, dom = self.run_script(html, OVERFLOW_CHECK, hash="poster")
        self.assertEqual(result["before"], [])
        # The probe sticks out of the poster's content box and its card, and runs over the chip.
        self.assertEqual([entry.split(": ", 1)[0] for entry in result["after"]],
                         ["poster", "S1", "S1 chip"])
        self.assertTrue(all(entry.split(": ", 1)[1].startswith("probe")
                            for entry in result["after"]), result["after"])
        poster = poster_in(dom)
        self.assertEqual(poster_problems(poster, a), [])
        self.assertGreaterEqual(len(poster.find_all("text", "tm-p-title")), 2)
        self.assertGreaterEqual(len(poster.find_all("text", "tm-p-thesis")), 2)
        cards = {node.attrs["data-section"]: node for node in poster.find_all("g", "tm-p-card")}
        for section in a["sections"]:
            lines = [_characters(node) for node in cards[section["id"]].find_all("text",
                                                                                  "tm-p-concl")]
            self.assertGreaterEqual(len(lines), 2, section["id"])
            self.assertEqual("".join(lines).replace(" ", ""),
                             section["conclusion"].replace(" ", ""))   # every word is drawn

    def test_poster_svg_is_standalone_markup_with_its_text_escaped(self):
        a = sample_analysis()
        a["essay"]["title"] = "Title " + MARKUP + chr(1)      # chr(1) is not allowed in XML
        a["thesis"] = "Thesis " + MARKUP
        a["questions"][0]["text"] = "Question " + MARKUP
        a["sections"][0]["title"] = "Heading " + MARKUP
        a["sections"][0]["conclusion"] = "Conclusion " + MARKUP
        a["sections"][0]["baton"] = "Baton " + MARKUP
        a["cases"][0]["name"] = "Case " + MARKUP
        lane = 'o"wn&<x>'                                     # ids reach attributes
        a["lanes"][2]["id"] = lane
        for item in a["paragraphs"]:
            if "own" in item["lanes"]:
                item["lanes"][lane] = item["lanes"].pop("own")
        html = write_page_directly(a)
        dom = dump_dom(with_script(html, WRITE_POSTER_SVG))
        self.assertRegex(dom, NO_ERRORS)
        markup = unescape(re.search(r'<pre id="t8-svg">(.*?)</pre>', dom, re.S).group(1))
        self.assertTrue(markup.startswith("<svg"))
        # &, <, > and " are escaped in text and in attribute values alike.
        escaped = ("&lt;/script&gt;&lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot;")
        self.assertIn(">Title " + escaped + "<", markup)
        self.assertIn('data-lane="o&quot;wn&amp;&lt;x&gt;"', markup)
        self.assertNotIn(chr(1), markup)
        svg = ElementTree.fromstring(markup)                  # well-formed, standalone XML
        self.assertEqual(svg.tag, f"{{{SVG_NS}}}svg")
        self.assertEqual((svg.get("id"), svg.get("width")), ("tm-poster", "1200"))
        self.assertNotIn("foreignobject", markup.lower())
        drawn = " ".join(drawn_texts(svg))
        for text in ("Title " + MARKUP, "Thesis " + MARKUP, "Question " + MARKUP,
                     "Heading " + MARKUP, "Conclusion " + MARKUP, "Baton " + MARKUP,
                     "Case " + MARKUP):
            self.assertIn(text, drawn)
        self.assertEqual(len([node for node in svg.iter(f"{{{SVG_NS}}}circle")
                              if node.get("data-lane") == lane]), 4)      # P2, P4, T1, P6
        # The same poster in #poster mode: the markup stays text there too.
        shown = dump_dom(html, hash="poster")
        self.assertRegex(shown, NO_ERRORS)
        self.assertNotIn("b", start_tags(shown))
        self.assertIn("Title " + MARKUP, poster_in(shown).drawn())

    def test_poster_svg_paints_its_own_light_palette(self):
        dom = dump_dom(with_script(page(sample_analysis()), WRITE_POSTER_SVG),
                       color_scheme="dark")
        markup = unescape(re.search(r'<pre id="t8-svg">(.*?)</pre>', dom, re.S).group(1))
        svg = ElementTree.fromstring(markup)
        height = svg.get("height")
        self.assertEqual(svg.get("viewBox"), f"0 0 1200 {height}")
        background = next(svg.iter(f"{{{SVG_NS}}}rect"))     # the first shape painted
        self.assertEqual((background.get("width"), background.get("height"),
                          background.get("fill")), ("1200", height, "#ffffff"))
        colours = set(re.findall(r"#[0-9a-f]{6}\b", markup.lower()))
        self.assertLessEqual(colours, set(PALETTE) | {NEUTRAL_HUE})
        self.assertLessEqual(set(PALETTE), colours)
        style = "".join(node.text or "" for node in svg.iter(f"{{{SVG_NS}}}style"))
        self.assertIn(f"font-family: {POSTER_FONT}", style)
        self.assertNotIn("var(--", markup)
        self.assertNotIn("prefers-color-scheme", markup)

    def test_the_poster_comes_and_goes_with_the_hash(self):
        a = sample_analysis()
        html = page(a)
        entered = dump_dom(with_script(html, 'location.hash = "poster";'))
        self.assertEqual(poster_problems(poster_in(entered), a), [])
        self.assertNotIn("<main", rendered(entered))
        left = dump_dom(with_script(html, 'location.hash = "select=P2";'), hash="poster")
        self.assertIsNone(poster_in(left))
        shown = rendered(left)
        self.assertIn('<main class="tm-page">', shown)
        self.assertEqual(shown.count('class="tm-mark'), total_marks(a))
        self.assertRegex(shown, r'<div class="tm-detail" id="tm-detail" data-item="P2">')


class ExportTests(PosterTestCase):
    """exportPNG(): the poster painted on a canvas at 2x and handed to the browser to save."""

    def test_export_png_saves_the_poster_at_twice_its_size(self):
        result, dom = self.run_script(page(sample_analysis(ui_language="ko")), EXPORT_BY_API)
        self.assertRegex(dom, NO_ERRORS)
        self.assertEqual(result["value"], "undefined")         # Promise<void>
        self.assertEqual(result["name"], "sample-throughmap.png")
        self.assertEqual(result["type"], "image/png")
        png = base64.b64decode(result["png"])
        self.assertTrue(png.startswith(PNG_SIGNATURE))
        svg = ElementTree.fromstring(result["svg"])
        self.assertEqual(png_size(png), (2 * 1200, 2 * int(svg.get("height"))))
        self.assertEqual(png_rows(png, 1)[0][:20], [WHITE] * 20)
        counts = result["counts"]                             # the map's dots and the text
        self.assertGreater(counts["teal"], 500)
        self.assertGreater(counts["purple"], 500)
        self.assertGreater(counts["ink"], 2000)
        # Nothing in the palette is black: a black pixel is a shape left without its fill, as
        # happens when the poster's style sheet does not reach the image.
        self.assertEqual(counts["black"], 0)
        # The poster went to the canvas through a blob URL, which is revoked once it is drawn.
        self.assertEqual(result["seen"]["created"][:2], ["image/svg+xml", "image/png"])
        self.assertIn("image/svg+xml", result["seen"]["revoked"])

    def test_the_save_png_button_exports_the_poster(self):
        html = page(sample_analysis())
        before = dump_dom(html)
        self.assertRegex(before, r'<button type="button" class="tm-button" id="tm-png">Save PNG<')
        result, dom = self.run_script(html, EXPORT_BY_BUTTON)
        self.assertEqual(result["name"], "sample-throughmap.png")
        self.assertTrue(base64.b64decode(result["png"]).startswith(PNG_SIGNATURE))
        self.assertTrue(result["seen"]["disabledWhileRunning"])
        self.assertRegex(dom, r'<button type="button" class="tm-button" id="tm-png">Save PNG<')
        self.assertRegex(dom, r'<div class="tm-note" id="tm-note" aria-live="polite"></div>')
        self.assertRegex(dom, NO_ERRORS)

    def test_the_png_is_named_after_the_source_or_else_the_title(self):
        named = [("sample.md", "Sample Essay", "sample"),
                 ("drafts/notes.v2.docx", "x", "notes.v2"),
                 ("C:\\Users\\me\\글 모음\\한글 글.docx", "x", "한글 글"),
                 ("README", "x", "README")]
        titles = ["Cheap Pipes, Rich Taps!", "나의 소원", "?!", "", "Rails_and_Edges: " + "가나다" * 30,
                  "Ünïcödé — Café №5"]
        pairs = [[source, title] for source, title, _ in named] + [["", t] for t in titles]
        expected = ([stem + "-throughmap.png" for _, _, stem in named]
                    + [slugify(title) + "-throughmap.png" for title in titles])
        self.assertIn("essay-throughmap.png", expected)                     # "?!" and ""
        script = NAMES_HOOK.replace("__PAIRS__", json.dumps(pairs))
        names, _ = self.run_script(write_page_directly(sample_analysis()), script)
        self.assertEqual(names, expected)


class TemplateFileTests(unittest.TestCase):
    """What can be read from the template file itself, without a browser."""

    def test_the_poster_is_pure_svg_in_system_fonts(self):
        template = TEMPLATE_PATH.read_text("utf-8")
        self.assertNotIn("foreignObject", template)
        self.assertNotIn("@font-face", template)
        self.assertIn(POSTER_FONT, template)

    def test_the_template_stays_under_the_plugin_file_limit(self):
        self.assertLess(TEMPLATE_PATH.stat().st_size, 256 * 1024)


if __name__ == "__main__":
    unittest.main()
