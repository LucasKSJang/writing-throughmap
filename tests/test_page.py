"""Tests for the page renderer, assets/template.html, opened in headless Chrome or Edge.

A test builds a page, opens it with tests/browser.py and reads the DOM that the page's script
leaves behind. The tests that need a browser skip when there is none: set THROUGHMAP_BROWSER.

The page's own script holds its whole string table, so a string found anywhere in the DOM proves
nothing: a test looks for a string in the element that must show it, or in rendered(), the DOM
without its scripts and styles.
"""

import json
import re
import struct
import unicodedata
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.browser import dump_dom, find_browser, screenshot
from tests.fixtures import (
    EVIDENCE_OF_P2, TEMPLATE_PATH, analysis_with_text, built_sample, forty_paragraphs,
    lanes_marked, n_paragraphs, page, sample_analysis, sample_source,
    sample_with_unthreaded_P3_and_own_missing_from_last_section, source_of, tmp_path,
    total_marks, write_page_directly,
)
from tm_build import PLACEHOLDER, compute_runs
from tm_text import _TYPOGRAPHY_TO_PLAIN, contains_verbatim

NO_ERRORS = r'<pre id="tm-errors" hidden="">\s*</pre>'
EN_DASH = "\N{EN DASH}"
DATA_ELEMENT = f'<script id="throughmap-data" type="application/json">{PLACEHOLDER}</script>'
# What a page without readable data says, in the language of the browser.
NO_DATA = (
    "No readable analysis in this page: its data is missing or broken. Ask for the page to be "
    "built again.",
    "이 파일에서 읽을 수 있는 분석을 찾지 못했어요. 데이터가 없거나 깨졌어요. 페이지를 다시 만들어 "
    "달라고 해 주세요.",
)


def svg_width(dom):
    """Return the width attribute of the map's svg element."""
    tag = re.search(r'<svg\b[^>]*\bid="tm-map"[^>]*>', dom).group()
    return re.search(r'\bwidth="([^"]*)"', tag).group(1)


def detail_box(dom):
    """Return the markup from the detail box's id up to the paragraph list that follows it."""
    return dom.split('id="tm-detail"', 1)[1].split('id="tm-list"', 1)[0]


def between(dom, start, end):
    """Return the markup after ``start`` and before the next ``end``."""
    return dom.split(start, 1)[1].split(end, 1)[0]


def write_html(html):
    """Write ``html`` to a new index.html; return its path."""
    path = tmp_path("index.html")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)
    return path


def with_script(html_path, script):
    """Copy a page with ``script`` run on load, once the page has drawn itself; return the copy."""
    html = Path(html_path).read_text("utf-8")
    run = f'<script>window.addEventListener("load", function () {{ {script} }});</script>'
    return write_html(html.replace("</body>", run + "</body>"))


# Actions for with_script(): real events on the page's elements, as a pointer or a key sends them.
def event_on(selector, event):
    return (f"document.querySelector({json.dumps(selector)})"
            f'.dispatchEvent(new MouseEvent("{event}", {{bubbles: true}}));')


def click(selector):
    return event_on(selector, "click")


def hover(selector):
    return event_on(selector, "mouseover")


LEAVE_MAP = 'document.getElementById("tm-map").dispatchEvent(new MouseEvent("mouseleave"));'
PRESS_ESCAPE = ('document.dispatchEvent(new KeyboardEvent("keydown", '
                '{key: "Escape", bubbles: true}));')
API = "window.throughmap."


def chosen(dom):
    """Return what the page shows as chosen, read from its DOM.

    ``detail`` is the item in the detail box (None when it shows none); ``roles``, ``columns``
    and ``names`` are the pressed role chips, the lit map columns and the pressed thread names;
    ``dimmed`` are the faded lanes; ``cases`` counts the pressed case chips.
    """
    detail = re.search(r'<div class="tm-detail[^"]*" id="tm-detail"(?: data-item="([^"]*)")?', dom)
    return {
        "detail": detail.group(1),
        "roles": re.findall(r'<button class="tm-role" data-item="([^"]+)"[^>]*'
                            r'aria-pressed="true"', dom),
        "columns": re.findall(r'class="tm-col is-sel" data-item="([^"]+)"', dom),
        "names": re.findall(r'<g class="tm-lname" data-lane="([^"]+)"[^>]*aria-pressed="true"',
                            dom),
        "dimmed": re.findall(r'class="tm-lane is-dim" data-lane="([^"]+)"', dom),
        "cases": len(re.findall(r'<button class="tm-case"[^>]*aria-pressed="true"', dom)),
    }


NOTHING_CHOSEN = {"detail": None, "roles": [], "columns": [], "names": [], "dimmed": [],
                  "cases": 0}


def rendered(dom):
    """Return the DOM without its script and style elements: what the page itself shows."""
    return re.sub(r"<(script|style)\b.*?</\1>", "", dom, flags=re.S)


def showing_everything(ui_language):
    """Return built data whose page shows every string: all 12 roles, a table and a figure, an
    inferred section, a gap with a direction, the three kinds of observation, a failing quote."""
    data = forty_paragraphs()
    data["ui_language"] = ui_language
    data["paragraphs"].insert(3, {
        "id": "T1", "kind": "table", "section": "S1", "text": "Table 1: Sizes.\nA | B",
        "role": "evidence", "label": "Sizes", "evidence": "Table 1: Sizes.", "lanes": {}})
    data["paragraphs"].insert(6, {
        "id": "F1", "kind": "figure", "section": "S1", "text": "Figure 1: The flow.",
        "role": "example", "label": "The flow", "evidence": "Figure 1: The flow.", "lanes": {}})
    data["sections"][0]["inferred"] = True
    data["paragraphs"][1]["evidence"] = "nope"
    data["gaps"] = [{"at": ["P3"], "note": "P3 never names the owner.",
                     "direction": "Connect P3 to the rest-time thread."}]
    data.update(version=1, generated_at="2026-10-17T12:00:00Z", computed={
        "runs": compute_runs(data),
        "observations": [{"type": "quiet", "lane": "q1", "from": "P1", "to": "T1", "length": 7},
                         {"type": "unresolved", "lane": "own"},
                         {"type": "unthreaded", "at": ["F1"]}]})
    return data


ROLE_NAMES = {
    "en": ("Problem", "Thesis", "Context", "Claim", "Evidence", "Example", "Counterpoint",
           "Implication", "Framework", "Transition", "Synthesis", "Conclusion"),
    "ko": ("문제 제기", "논지", "배경", "주장", "근거", "사례", "반론·균형", "함의", "틀", "전환", "종합",
           "결론"),
}
# The text of the page's fixed elements, by element id, from the string table of the plan.
PANEL_TEXT = {
    "en": {
        "tm-thesis-label": "Thesis",
        "tm-questions-label": "Questions",
        "tm-flow-title": "Section flow",
        "tm-flow-hint": "One line per section, then its paragraphs' roles in order. Click a role "
                        "to find it on the map.",
        "tm-map-title": "Thread map",
        "tm-map-legend": "Large dot = main point · small dot = brief mention · solid line = "
                         "consecutive paragraphs · dashed line = the thread rests · click a "
                         "thread name to isolate it",
        "tm-detail": "Hover or click a paragraph, a dot or a role to see its summary and "
                     "evidence.",
        "tm-cases-title": "Recurring examples",
        "tm-cases-hint": "Click to highlight where each appears.",
        "tm-png": "Save PNG",
        "tm-print": "Print",
        "tm-gaps-summary": 'Gaps (4)<span class="tm-toggle-hint"> · click to expand</span>',
    },
    "ko": {
        "tm-thesis-label": "논지",
        "tm-questions-label": "질문",
        "tm-flow-title": "섹션 흐름",
        "tm-flow-hint": "섹션마다 결론 한 줄과 문단 역할 순서 · 역할에 마우스를 올리면 요약, 누르면 "
                        "아래 지도에서 그 문단이 강조돼요",
        "tm-map-title": "연결 지도",
        "tm-map-legend": "큰 점 = 중심 논지 · 작은 점 = 짧은 언급 · 실선 = 연달아 다룸 · 점선 = "
                         "쉬었다 다시 나옴 · 왼쪽 이름을 누르면 그 실만 남아요",
        "tm-detail": "문단 번호, 점, 또는 위 카드의 역할을 누르면 요약과 근거 문장이 여기 보여요",
        "tm-cases-title": "다시 나오는 사례",
        "tm-cases-hint": "누르면 지도에서 그 문단들이 강조돼요",
        "tm-png": "PNG로 저장",
        "tm-print": "인쇄",
        "tm-gaps-summary": '손볼 곳 4개<span class="tm-toggle-hint"> · 눌러서 펼치기</span>',
    },
}
# How the fixed elements whose text goes on with counts and paths begin.
PANEL_START = {
    "en": {"tm-list-summary": "All paragraphs · ",
           "tm-footer": "Opens without an internet connection · "},
    "ko": {"tm-list-summary": "문단 목록 전체 펼치기 · ",
           "tm-footer": "인터넷 연결 없이 열리는 파일 · "},
}
# The other strings that showing_everything() puts on the page, each as an element's whole text.
SHOWN = {
    "en": (
        ">Seen by counting<", ">Direction: Connect P3 to the rest-time thread.<",
        ">Q1 · main point ·<", ">Q1 · brief mention ·<", ">Quote not found in the paragraph<",
        ">inferred<", f">Q1 rests for 7 paragraphs (P1{EN_DASH}T1)<",
        ">Rest time does not return in the last section<", ">F1 is on no thread<",
        ">T1 Evidence<", ">F1 Example<",
    ),
    "ko": (
        ">계산으로 보이는 것<", ">방향: Connect P3 to the rest-time thread.<", ">Q1 · 큰 점 ·<",
        ">Q1 · 작은 점 ·<", ">원문에서 찾지 못한 인용<", ">추정<",
        ">Q1 실이 P1부터 표1까지 7개 문단 동안 쉬어요<",
        ">Rest time 실이 마지막 섹션에 다시 나오지 않아요<", ">어느 실에도 걸리지 않은 문단: 그림1<",
        ">표1 근거<", ">그림1 사례<",
    ),
}
THREADS_LABEL = {"en": "Threads: ", "ko": "실: "}


class _StartTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def start_tags(dom):
    """Return the names of the elements in ``dom``, as an HTML parser reads it."""
    parser = _StartTags()
    parser.feed(dom)
    return parser.tags


def quote_pairs():
    """Return (text, quote) pairs that try every rule of tm_text.normalize, one rule per pair."""
    whitespace = [chr(code) for code in range(0x10000) if re.fullmatch(r"\s", chr(code))]
    format_characters = [chr(code) for code in range(0x110000)
                         if unicodedata.category(chr(code)) == "Cf"]
    pairs = []
    for code, plain in _TYPOGRAPHY_TO_PLAIN.items():
        pairs += [(f"a{chr(code)}b", f"a{plain}b"), (f"a{plain}b", f"a{chr(code)}b")]
    for space in whitespace:
        pairs += [(f"x{space}y", "x y"), ("x y", f"x{space}y"), (f"x{space} {space}y", "x y")]
    pairs += [(f"ab{char}cd", "abcd") for char in format_characters]
    pairs += [
        ("Rail fees", "rail fees"),                                  # case counts
        ("Rail fees", "Rail fee"),
        ("Rail fees", "Rail  fees"),
        ("Rail fees", "Rail fees stay"),
        ("Rail fees", ""),
        ("Rail fees", "\N{ZERO WIDTH SPACE} \N{SOFT HYPHEN}"),       # nothing left to find
        ("Cafe\N{COMBINING ACUTE ACCENT} prices", "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
        ("Caf\N{LATIN SMALL LETTER E WITH ACUTE} prices", "Cafe\N{COMBINING ACUTE ACCENT}"),
        # The format characters go first, so that NFC then joins the "e" and its accent.
        ("Cafe\N{ZERO WIDTH SPACE}\N{COMBINING ACUTE ACCENT} prices",
         "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
        ("Caf\N{LATIN SMALL LETTER E WITH ACUTE} prices",
         "Cafe\N{ZERO WIDTH SPACE}\N{COMBINING ACUTE ACCENT}"),
        ("x\N{HANGUL FILLER}y", "x y"),                              # a letter, not a space
        ("  lead and trail  ", " lead and trail "),
        ("a\N{GRINNING FACE}b", "a\N{GRINNING FACE}b"),
        ("tax\N{SOFT HYPHEN}ation", "taxation"),
    ]
    return pairs


class BrowserTestCase(unittest.TestCase):
    def setUp(self):
        if find_browser() is None:
            self.skipTest("no Chrome or Edge found: set THROUGHMAP_BROWSER to a browser")


class PageTests(BrowserTestCase):
    """The page tests of the plan."""

    def test_page_renders_all_panels_en(self):
        dom = dump_dom(page(sample_analysis()))
        self.assertRegex(dom, r'<pre id="tm-errors" hidden="">\s*</pre>')
        self.assertEqual(dom.count('class="tm-card"'), 3)
        self.assertEqual(dom.count('class="tm-role"'), 7)                 # 6 paragraphs + T1
        self.assertEqual(dom.count('class="tm-mark'), total_marks(sample_analysis()))
        self.assertIn(">P3 Claim<", dom)
        self.assertIn("Thread map", dom)

    def test_page_korean_strings(self):
        dom = dump_dom(page(sample_analysis(ui_language="ko")))
        self.assertIn("연결 지도", dom)
        self.assertIn(">P3 주장<", dom)
        self.assertIn(">표1 ", dom)

    def test_page_unknown_language_falls_back_to_english(self):
        a = sample_analysis(ui_language="ja")
        self.assertIn("Thread map", dump_dom(page(a)))
        a["ui_strings"] = {"map": "スレッド"}
        self.assertIn("スレッド", dump_dom(page(a)))

    def test_page_flags_unverified_quote(self):
        a = built_sample(); a["paragraphs"][1]["evidence"] = "nope"       # bypasses check
        html = write_page_directly(a)                                  # render_html + real template
        self.assertEqual(dump_dom(html).count('class="tm-warn"'), 1)

    def test_page_escapes_html_in_text(self):                              # Review Focus 4
        a = analysis_with_text("P2", "Tags like </script><b>bold</b> & <i>x</i> stay text.")
        dom = dump_dom(page(a))
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", dom)
        self.assertNotIn("<b>bold</b>", dom)
        self.assertRegex(dom, r'<pre id="tm-errors" hidden="">\s*</pre>')

    def test_page_single_mark_lane(self):
        a = lanes_marked({"q1": ["P1", "P2"], "q2": ["P3"], "own": ["P4"]})
        self.assertRegex(dump_dom(page(a)), r'<pre id="tm-errors" hidden="">\s*</pre>')

    def test_page_map_columns_clamp_and_scroll(self):
        dom = dump_dom(page(forty_paragraphs()), width=600)
        self.assertIn('width="680"', dom)                                    # 120 + 40 × 14

    def test_page_truncates_narrow_band_labels(self):
        a = forty_paragraphs(first_section_size=1); a["sections"][0]["short"] = "Introduction"
        dom = dump_dom(page(a))                       # a 1-column band is at most 36 px wide
        self.assertRegex(dom, r'class="tm-band"[^>]*>.*…')
        self.assertIn("<title>Introduction</title>", dom)

    def test_page_deep_links(self):
        html = page(sample_analysis())
        self.assertIn(EVIDENCE_OF_P2, dump_dom(html, hash="select=P2"))
        self.assertEqual(dump_dom(html, hash="lane=q1").count("tm-lane is-dim"), 2)

    def test_template_has_no_external_requests(self):
        t = TEMPLATE_PATH.read_text("utf-8")
        for bad in ("<script src", "<link ", "@import", "url(http", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(bad, t)


class PageBehaviourTests(BrowserTestCase):
    """More of what the page must do, beyond the plan's tests."""

    def test_selecting_an_item_fills_the_detail_box(self):
        html = page(sample_analysis())
        self.assertNotIn(EVIDENCE_OF_P2, detail_box(dump_dom(html)))
        selected = detail_box(dump_dom(html, hash="select=P2"))
        self.assertIn('data-item="P2"', selected.split(">", 1)[0])
        self.assertIn(EVIDENCE_OF_P2, selected)
        self.assertIn("Acme keeps dough overnight", selected)                       # the label

    def test_isolating_a_lane_fades_the_other_lanes_and_paragraphs(self):
        html = page(sample_analysis())
        dom = dump_dom(html, hash="lane=q1")
        self.assertEqual(dom.count('class="tm-lane"'), 1)
        self.assertEqual(dom.count("tm-num is-faint"), 4)                  # all but P1, P3, P6
        self.assertEqual(dump_dom(html, hash="lane=nothing").count("tm-lane is-dim"), 0)

    def test_the_map_is_as_wide_as_its_columns(self):
        self.assertEqual(svg_width(dump_dom(page(sample_analysis()))), "372")      # 120 + 7 × 36
        self.assertEqual(svg_width(dump_dom(page(forty_paragraphs()))), "1080")    # 120 + 40 × 24

    def test_the_quote_check_normalizes_exactly_as_python_does(self):
        pairs = quote_pairs()
        data = built_sample()
        data["paragraphs"] = [
            {"id": f"P{n}", "kind": "paragraph", "section": "S1", "text": text, "role": "claim",
             "label": f"Pair {n}", "evidence": quote, "lanes": {}}
            for n, (text, quote) in enumerate(pairs, 1)]
        data["sections"] = [dict(data["sections"][0], first="P1", last=f"P{len(pairs)}")]
        data["cases"], data["gaps"] = [], []
        data["computed"] = {"runs": {}, "observations": []}
        expected = [f"P{n}" for n, (text, quote) in enumerate(pairs, 1)
                    if not contains_verbatim(text, quote)]
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertEqual(re.findall(r'class="tm-warn" data-item="([^"]+)"', dom), expected)
        self.assertEqual(len(expected), 5)                                  # the pairs that fail

    def test_a_failing_lane_quote_is_flagged_once_per_item(self):
        a = built_sample()
        a["paragraphs"][6]["lanes"]["q1"]["quote"] = "not in P6"
        a["paragraphs"][6]["lanes"]["own"]["quote"] = "nor this"
        html = write_page_directly(a)
        dom = dump_dom(html)
        self.assertEqual(re.findall(r'class="tm-warn" data-item="([^"]+)"', dom), ["P6"])
        self.assertEqual(dom.count(">Quote not found in the paragraph<"), 2)       # list rows
        detail = detail_box(dump_dom(html, hash="select=P6"))
        self.assertIn("Quote not found in the paragraph", detail)
        self.assertIn("Q1 “not in P6”", detail)
        self.assertIn("Rest time “nor this”", detail)

    def test_observations_are_written_in_the_ui_language(self):
        data = built_sample()
        data["computed"]["observations"] = [
            {"type": "quiet", "lane": "q1", "from": "P1", "to": "T1", "length": 7},
            {"type": "unresolved", "lane": "own"},
            {"type": "unthreaded", "at": ["P3"]},
        ]
        en = dump_dom(write_page_directly(data))
        self.assertEqual(en.count('class="tm-obs"'), 3)
        self.assertIn(f"Q1 rests for 7 paragraphs (P1{EN_DASH}T1)", en)
        self.assertIn("Rest time does not return in the last section", en)
        self.assertIn("P3 is on no thread", en)
        self.assertEqual(en.count('class="tm-gap"'), 1)
        data["ui_language"] = "ko"
        ko = dump_dom(write_page_directly(data))
        self.assertIn("Q1 실이 P1부터 표1까지 7개 문단 동안 쉬어요", ko)
        self.assertIn("Rest time 실이 마지막 섹션에 다시 나오지 않아요", ko)
        self.assertIn(">어느 실에도 걸리지 않은 문단: P3<", ko)

    def test_a_page_without_computed_fields_works_them_out_itself(self):
        # An agent without Python embeds the analysis as it is: no version, no computed. The
        # page must then find the runs and observations that build would have found.
        analyses = (
            sample_with_unthreaded_P3_and_own_missing_from_last_section(),
            # q1 rests 5 paragraphs (not quiet: the least is 6), q2 rests 9 (quiet); T1 is no
            # paragraph, so it neither rests nor counts.
            n_paragraphs(12, marks={"q1": ["P1", "P7", "P8"], "q2": ["P2", "P12"]},
                         table_after="P5"),
            forty_paragraphs(),
        )
        drawn = (r'<div class="tm-obs">(.*?)</div>', r'<line class="tm-(?:run|span)"[^>]*>',
                 r'<circle class="tm-mark"[^>]*>')
        for number, analysis in enumerate(analyses):
            with self.subTest(analysis=number):
                direct = dump_dom(write_page_directly(analysis))
                built = dump_dom(page(analysis))
                self.assertRegex(direct, NO_ERRORS)
                for pattern in drawn:
                    self.assertEqual(re.findall(pattern, direct), re.findall(pattern, built))
                self.assertIn('class="tm-obs"', built)
                self.assertIn('class="tm-run"', built)
        sample = dump_dom(write_page_directly(analyses[0]))
        self.assertIn("Rest time does not return in the last section", sample)
        self.assertIn("P3 is on no thread", sample)

    def test_a_page_whose_data_cannot_be_read_says_so(self):
        # Filled in by hand, the data has only "</" escaped (spec 5.4). A comment opener and a
        # "<script" in the draft then make the data element run on to the end of the file.
        analysis = analysis_with_text("P2", "In HTML, <!-- a <script> b opens a comment.")
        template = TEMPLATE_PATH.read_text("utf-8")
        by_hand = json.dumps(analysis, ensure_ascii=False).replace("</", "<\\/")
        pages = {"run on": template.replace(PLACEHOLDER, by_hand),
                 "never filled in": template,
                 "no data element": template.replace(DATA_ELEMENT, "")}
        for name, html in pages.items():
            with self.subTest(name):
                dom = dump_dom(write_html(html))
                box = re.search(r'<pre id="tm-errors"( hidden="")?>(.*?)</pre>', dom, re.S)
                self.assertIsNone(box.group(1))                             # the box shows
                self.assertTrue(any(message in box.group(2) for message in NO_DATA), box.group(2))
                self.assertIn('<main class="tm-page" hidden="">', dom)
                self.assertEqual(dom.count('class="tm-card"'), 0)
        built = dump_dom(page(analysis))                      # build escapes the opener as well
        self.assertRegex(built, NO_ERRORS)
        self.assertEqual(built.count('class="tm-card"'), 3)

    def test_an_inferred_section_carries_a_tag(self):
        a = sample_analysis()
        a["sections"][1]["inferred"] = True
        en = dump_dom(page(a))
        self.assertEqual(en.count('class="tm-inferred"'), 1)
        self.assertIn(">inferred<", between(en, 'data-section="S2"', 'data-section="S3"'))
        a["ui_language"] = "ko"
        self.assertIn(">추정<", dump_dom(page(a)))

    def test_markup_in_any_text_stays_text(self):
        markup = '<img src="x" onerror="document.body.remove()">'
        data = built_sample()
        data["essay"]["title"] = "Title " + markup
        data["thesis"] = "Thesis " + markup
        data["questions"][0]["text"] = "Question " + markup
        data["lanes"][2]["label"] = "Lane " + markup
        data["sections"][0]["conclusion"] = "Conclusion " + markup
        data["sections"][0]["baton"] = "Baton " + markup
        data["paragraphs"][0]["label"] = "Label " + markup
        data["cases"][0]["name"] = "Case " + markup
        data["gaps"][0]["note"] = "Gap " + markup
        data["gaps"][0]["direction"] = "Direction " + markup
        data["ui_strings"] = {"map": "Map " + markup}
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertNotIn("img", start_tags(dom))
        for text in ("Title", "Thesis", "Question", "Lane", "Conclusion", "Baton", "Label", "Case",
                     "Gap", "Direction", "Map"):
            self.assertIn(f"{text} &lt;img", dom)

    def test_every_string_is_shown_in_the_ui_language(self):
        for language in ("en", "ko"):
            with self.subTest(language=language):
                html = write_page_directly(showing_everything(language))
                shown = rendered(dump_dom(html))
                for element, text in PANEL_TEXT[language].items():
                    self.assertRegex(shown, f'id="{element}"[^>]*>{re.escape(text)}<')
                for element, start in PANEL_START[language].items():
                    self.assertRegex(shown, f'id="{element}"[^>]*>{re.escape(start)}')
                for text in SHOWN[language]:
                    self.assertIn(text, shown)
                for number, name in enumerate((ROLE_NAMES[language] * 4)[:40], 1):
                    self.assertIn(f">P{number} {name}<", shown)             # roles in turn
                selected = rendered(dump_dom(html, hash="select=P1"))
                self.assertIn(THREADS_LABEL[language], detail_box(selected))

    def test_another_language_falls_back_to_english_key_by_key(self):
        data = showing_everything("ja")
        data["ui_strings"] = {"map": "スレッド", "role.claim": "主張"}
        shown = rendered(dump_dom(write_page_directly(data)))
        self.assertRegex(shown, 'id="tm-map-title"[^>]*>スレッド<')
        self.assertNotIn("Thread map", shown)
        self.assertIn(">P4 主張<", shown)                                   # P4 is a claim
        self.assertRegex(shown, 'id="tm-flow-title"[^>]*>Section flow<')
        self.assertIn(">P5 Evidence<", shown)

    def test_the_map_is_drawn_again_when_the_window_resizes(self):
        squeezed = with_script(page(forty_paragraphs()),
                               'document.querySelector("main").style.maxWidth = "632px";'
                               'window.dispatchEvent(new Event("resize"));')
        self.assertEqual(svg_width(dump_dom(squeezed)), "680")     # 600 px: 40 columns of 14

    def test_printing_opens_the_list_and_the_gaps_then_restores_them(self):
        html = page(sample_analysis())
        printing = dump_dom(with_script(html, 'window.dispatchEvent(new Event("beforeprint"));'))
        self.assertRegex(printing, r'<details[^>]*id="tm-list"[^>]*open=""')
        self.assertRegex(printing, r'<details[^>]*id="tm-gaps"[^>]*open=""')
        printed = dump_dom(with_script(html, 'document.getElementById("tm-gaps").open = true;'
                                             'window.dispatchEvent(new Event("beforeprint"));'
                                             'window.dispatchEvent(new Event("afterprint"));'))
        self.assertNotRegex(printed, r'<details[^>]*id="tm-list"[^>]*open=""')    # was closed
        self.assertRegex(printed, r'<details[^>]*id="tm-gaps"[^>]*open=""')       # was open

    def test_screenshot_saves_a_png_of_the_page(self):
        png = tmp_path("page.png")
        screenshot(page(sample_analysis()), png, width=800, height=600, scale=1)
        data = Path(png).read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", data[16:24]), (800, 600))


class InteractionTests(BrowserTestCase):
    """What clicks, the pointer, keys and window.throughmap do, as the DOM shows it after."""

    def setUp(self):
        super().setUp()
        self.html = page(sample_analysis())

    def after(self, script):
        """Return what the sample page shows as chosen once ``script`` has run on it."""
        return chosen(dump_dom(with_script(self.html, script)))

    def assertChosen(self, script, **expected):
        """Check what is chosen after ``script``: the keys given, the others being unchosen."""
        self.assertEqual(self.after(script), {**NOTHING_CHOSEN, **expected})

    def test_a_thread_name_isolates_its_thread_and_a_second_click_restores_all(self):
        name = '.tm-lname[data-lane="q1"]'
        self.assertChosen(click(name), names=["q1"], dimmed=["q2", "own"])
        self.assertChosen(click(name) * 2)

    def test_enter_on_a_thread_name_isolates_it(self):
        self.assertChosen('document.querySelector(\'.tm-lname[data-lane="q2"]\').dispatchEvent('
                          'new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));',
                          names=["q2"], dimmed=["q1", "own"])

    def test_a_case_lights_its_places_and_ends_an_isolation(self):
        self.assertChosen(API + 'isolateLane("q1");' + click(".tm-case"),
                          columns=["P2", "P5"], cases=1)
        self.assertChosen(click(".tm-case") * 2)
        dom = dump_dom(with_script(self.html, click(".tm-case")))
        self.assertIn("Acme returns as the running example", detail_box(dom))

    def test_the_api_selects_items_and_isolates_lanes(self):
        both = API + 'select("P3");' + API + 'isolateLane("own");'
        self.assertChosen(both, detail="P3", roles=["P3"], columns=["P3"], names=["own"],
                          dimmed=["q1", "q2"])
        self.assertChosen(both + API + "select(null);" + API + "isolateLane(null);")
        self.assertChosen(API + 'select("P99");' + API + 'isolateLane("nothing");')
        shown = dump_dom(with_script(self.html, 'document.getElementById("tm-note").textContent = '
                                                + API + "data.thesis;"))
        self.assertRegex(shown, 'id="tm-note"[^>]*>How long the dough rests, not how fast it rises')

    def test_hovering_previews_an_item_and_leaving_the_map_restores_the_pinned_one(self):
        pin_and_hover = API + 'select("P3");' + hover('.tm-col[data-item="P5"]')
        self.assertChosen(pin_and_hover, detail="P5", roles=["P3"], columns=["P5"])
        self.assertChosen(pin_and_hover + LEAVE_MAP, detail="P3", roles=["P3"], columns=["P3"])
        # With nothing pinned, the item last hovered stays in the detail box.
        self.assertChosen(hover('.tm-col[data-item="P5"]') + LEAVE_MAP, detail="P5",
                          columns=["P5"])

    def test_a_role_pins_its_item_and_a_second_click_unpins_it(self):
        role = '.tm-role[data-item="P3"]'
        self.assertChosen(click(role), detail="P3", roles=["P3"], columns=["P3"])
        self.assertChosen(click(role) * 2)

    def test_a_column_or_a_dot_pins_its_item(self):
        self.assertChosen(click('.tm-col[data-item="T1"]'), detail="T1", roles=["T1"],
                          columns=["T1"])
        self.assertChosen(click('.tm-mark[data-item="P6"][data-lane="own"]'), detail="P6",
                          roles=["P6"], columns=["P6"])

    def test_escape_clears_the_choice_and_the_isolation(self):
        self.assertChosen(API + 'select("P3");' + API + 'isolateLane("q1");' + PRESS_ESCAPE)
        self.assertChosen(click(".tm-case") + PRESS_ESCAPE)

    def test_a_new_hash_applies_without_reloading(self):
        self.assertChosen('location.hash = "lane=q2&select=P5";', detail="P5", roles=["P5"],
                          columns=["P5"], names=["q2"], dimmed=["q1", "own"])


class TemplateFileTests(unittest.TestCase):
    """What can be read from the template file itself, without a browser."""

    def setUp(self):
        self.template = TEMPLATE_PATH.read_text("utf-8")

    def test_the_placeholder_occurs_once_inside_the_data_element(self):
        self.assertEqual(self.template.count(PLACEHOLDER), 1)
        self.assertIn(DATA_ELEMENT, self.template)

    def test_the_renderer_comes_before_the_data_it_waits_for(self):
        # A data element that runs on to the end of the file cannot swallow a renderer before it.
        renderer = self.template.index('document.addEventListener("DOMContentLoaded"')
        self.assertLess(renderer, self.template.index(DATA_ELEMENT))
        self.assertNotIn("<!--", self.template)

    def test_the_page_reads_its_data_with_json_parse_only(self):
        self.assertIn('JSON.parse(document.getElementById("throughmap-data").textContent)',
                      self.template)

    def test_no_text_is_ever_parsed_as_markup(self):
        for api in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser",
                    "createContextualFragment", "eval(", "new Function"):
            self.assertNotIn(api, self.template)

    def test_the_template_stays_small(self):
        # A plugin file may have 256 KiB; the renderer keeps well under it, with room for more.
        self.assertLess(TEMPLATE_PATH.stat().st_size, 128 * 1024)

    def test_the_template_has_lf_line_endings(self):
        self.assertNotIn(b"\r", TEMPLATE_PATH.read_bytes())

    def test_source_of_the_sample_analysis_is_the_sample_source(self):
        self.assertEqual(source_of(sample_analysis()), sample_source())


if __name__ == "__main__":
    unittest.main()
