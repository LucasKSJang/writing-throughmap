"""Tests for the comparison on the page: the "what changed" panel and the before/after view, opened
in headless Chrome or Edge.

A test builds two versions of one draft with the real template, opens the page that the second build
writes and reads the DOM its script leaves behind. As in test_page.py, the script's own string table
is part of that DOM, so what a page shows is read from the element that must show it, or from
rendered(), the DOM without its scripts and styles.

The tests that need a browser skip when there is none: set THROUGHMAP_BROWSER.
"""

import json
import re
from html import unescape
from pathlib import Path

from tests.browser import dump_dom
from tests.fixtures import (
    GAP_AT_P8_NOTE, TEMPLATE_PATH, built_sample, page, para, revision, sample_analysis,
    sections_of, source_of, two_builds, version_of, write_page_directly,
)
from tests.test_page import (
    API, NO_ERRORS, BrowserTestCase, between, chosen, click, rendered, start_tags, with_script,
    write_html,
)
from tests.test_poster import WRITE_POSTER_SVG

# Shows what linksOf makes of the page's comparison, in a <pre> that a test can read.
SHOW_LINKS = (
    'document.body.appendChild(Object.assign(document.createElement("pre"), {id: "t-links", '
    "textContent: JSON.stringify(window.throughmap.linksOf(window.throughmap.data.compare))}));"
)


def change_lines(dom):
    return re.findall(r'<div class="tm-change" data-change="([^"]+)">(.*?)</div>', rendered(dom))


def links(dom):
    return sorted(re.findall(r'<g class="tm-link(?: is-sel)?" data-old="([^"]+)" data-new="([^"]+)" '
                             r'data-kind="([^"]+)"', dom))


def badges(dom):
    return sorted(re.findall(r'<text class="tm-badge" data-badge="([^"]+)" data-item="([^"]+)" '
                             r'data-side="([^"]+)"', dom))


def forty_then_thirty():
    """Build a draft of 40 paragraphs and then its first 30; return the page of the second build."""
    texts = sections_of({"One": 40})[0][1]
    return two_builds(version_of(texts, {"q1": [1]}), version_of(texts[:30], {"q1": [1]}),
                      template_path=str(TEMPLATE_PATH))["html_path"]


# Where the two columns of cards stand, in a <pre> that a test can read.
PLACES = """
const out = document.createElement("pre"); out.id = "t-out";
const a = document.getElementById("tm-flow-before").getBoundingClientRect();
const b = document.getElementById("tm-flow-now").getBoundingClientRect();
out.textContent = JSON.stringify({side: Math.abs(a.top - b.top) < 1 && a.right <= b.left,
                                  stacked: a.bottom <= b.top + 1});
document.body.appendChild(out);
"""


def saved_version(html):
    """Return the v2.json that sits beside the page ``html`` (the second build of revision())."""
    return json.loads(Path(html).with_name("v2.json").read_text("utf-8"))


class ChangesPanelTests(BrowserTestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = two_builds(*revision(), template_path=str(TEMPLATE_PATH))["html_path"]

    def test_the_panel_lists_every_kind_of_change(self):
        dom = dump_dom(self.html)
        self.assertRegex(dom, NO_ERRORS)
        self.assertRegex(rendered(dom), 'id="tm-changes-title"[^>]*>What changed since v1<')
        self.assertEqual(change_lines(dom), [
            ("edited", "Edited: P7"), ("added", "New: P8"), ("removed", "Removed: v1 P8"),
            ("split", "Split: v1 P2 → P2, P3"), ("merged", "Merged: v1 P5, v1 P6 → P5"),
            ("moved", "Moved: v1 P3 → P7"), ("marks", "P4: − Own"), ("marks", "P6 (v1 P7): + Q1"),
            ("marks", "P7 (v1 P3): + Q1 · − Pace"), ("thread-added", "New thread: Cost"),
            ("thread-removed", "Dropped thread: Gone"),
            ("quiet-closed", "Q1 no longer rests from v1 P1 to v1 P8"),
            ("quiet-opened", "Pace now rests for 6 paragraphs (P1–P8)"),
            ("gap", GAP_AT_P8_NOTE + " (v1 P8)")])
        self.assertEqual(re.findall(r'<h3 class="tm-subhead">(.*?)</h3>', between(dom, 'id="tm-changes"', "</section>")),
                         ["Paragraphs", "Threads", "Quiet threads", "Gaps that no longer apply"])

    def test_the_versions_line_lists_every_saved_version(self):
        self.assertRegex(rendered(dump_dom(self.html)),
                         r'id="tm-versions"[^>]*>Saved versions: v1 \(\d{4}-\d\d-\d\d, 8 paragraphs, '
                         r'compared\) · v2 \(\d{4}-\d\d-\d\d, 8 paragraphs, this map\)\. To compare with '
                         r'another one, ask your agent\.<')

    def test_a_version_that_cannot_be_read_shows_only_its_number(self):
        data = saved_version(self.html)
        data["compare"]["versions"][0] = {"version": 1, "generated_at": None, "paragraphs": 0}
        data["compare"]["versions"].insert(1, {"version": 3, "generated_at": None, "paragraphs": 0})
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertRegex(rendered(dom),
                         r'id="tm-versions"[^>]*>Saved versions: v1 \(compared\) · v3 · v2 '
                         r'\(\d{4}-\d\d-\d\d, 8 paragraphs, this map\)\. To compare with another '
                         r'one, ask your agent\.<')

    def test_the_panel_speaks_korean(self):
        dom = dump_dom(two_builds(*revision(ui_language="ko"), template_path=str(TEMPLATE_PATH))["html_path"])
        self.assertRegex(rendered(dom), 'id="tm-changes-title"[^>]*>v1 이후 바뀐 점<')
        for line in (("split", "나뉜 문단: v1 P2 → P2, P3"),
                     ("quiet-closed", "Q1 실이 v1 P1~v1 P8에서 더는 쉬지 않아요"),
                     ("quiet-opened", "Pace 실이 이제 P1부터 P8까지 6개 문단 동안 쉬어요")):
            self.assertIn(line, change_lines(dom))
        self.assertRegex(rendered(dom),
                         r'id="tm-versions"[^>]*>저장된 버전: v1 \(\d{4}-\d\d-\d\d, 문단 8개, 비교 대상\) · '
                         r'v2 \(\d{4}-\d\d-\d\d, 문단 8개, 지금 지도\)\. 다른 버전과 비교하려면 에이전트에게 '
                         r'말해 주세요\.<')

    def test_every_line_heading_and_detail_of_the_panel_is_in_korean(self):
        html = two_builds(*revision(ui_language="ko"), template_path=str(TEMPLATE_PATH))["html_path"]
        dom = dump_dom(html)
        self.assertEqual(change_lines(dom), [
            ("edited", "고친 문단: P7"), ("added", "새 문단: P8"), ("removed", "빠진 문단: v1 P8"),
            ("split", "나뉜 문단: v1 P2 → P2, P3"), ("merged", "합친 문단: v1 P5, v1 P6 → P5"),
            ("moved", "옮긴 문단: v1 P3 → P7"), ("marks", "P4: − Own"), ("marks", "P6 (v1 P7): + Q1"),
            ("marks", "P7 (v1 P3): + Q1 · − Pace"), ("thread-added", "새 실: Cost"),
            ("thread-removed", "빠진 실: Gone"),
            ("quiet-closed", "Q1 실이 v1 P1~v1 P8에서 더는 쉬지 않아요"),
            ("quiet-opened", "Pace 실이 이제 P1부터 P8까지 6개 문단 동안 쉬어요"),
            ("gap", GAP_AT_P8_NOTE + " (v1 P8)")])
        self.assertEqual(re.findall(r'<h3 class="tm-subhead">(.*?)</h3>', between(dom, 'id="tm-changes"', "</section>")),
                         ["문단", "실", "쉬는 실", "더는 해당하지 않는 손볼 곳"])
        detail = lambda item: re.search(r'<div class="tm-detail-before">(.*?)</div>',
                                        dump_dom(html, hash=f"select={item}")).group(1)
        self.assertEqual(detail("P1"), "이전: v1 P1, 100% 일치")
        self.assertRegex(detail("P7"), r"^이전: v1 P3, \d\d% 일치 · 옮김$")
        self.assertEqual(detail("P3"), "이전: v1 P2에서 나뉨 (P2, P3)")
        self.assertEqual(detail("P5"), "이전: v1 P5, v1 P6, 하나로 합침")
        self.assertEqual(detail("P8"), "v1 이후 새 문단")
        first = revision(ui_language="ko")[0]
        same = dump_dom(two_builds(first, first, template_path=str(TEMPLATE_PATH))["html_path"])
        self.assertEqual(change_lines(same), [("none", "문단, 실, 손볼 곳 모두 그대로예요.")])

    def test_a_thread_is_named_by_the_version_it_belongs_to(self):
        data = saved_version(self.html)
        data["lanes"][1]["label"], data["lanes"][2]["label"] = "Own later", "Pace later"
        earlier = data["compare"]["before"]["lanes"]
        earlier[0]["question"], earlier[1]["label"], earlier[2]["label"] = "Q9", "Own then", "Pace then"
        lines = change_lines(dump_dom(write_page_directly(data)))
        for line in (("marks", "P4: − Own then"),                       # lost: named by the earlier version
                     ("marks", "P6 (v1 P7): + Q1"),                     # gained: named by this one
                     ("marks", "P7 (v1 P3): + Q1 · − Pace then"),
                     ("quiet-closed", "Q9 no longer rests from v1 P1 to v1 P8"),
                     ("quiet-opened", "Pace later now rests for 6 paragraphs (P1–P8)")):
            self.assertIn(line, lines)

    def test_a_table_of_the_earlier_version_keeps_the_prefix_of_the_language(self):
        first, second = sample_analysis("ko"), sample_analysis("ko")
        second["paragraphs"] = [item for item in second["paragraphs"] if item["id"] != "T1"]
        html = two_builds((source_of(first), first), (source_of(second), second),
                          template_path=str(TEMPLATE_PATH))["html_path"]
        self.assertEqual(change_lines(dump_dom(html)), [("removed", "빠진 문단: v1 표1")])

    def test_nothing_changed_says_so(self):
        first = revision()[0]
        dom = dump_dom(two_builds(first, first, template_path=str(TEMPLATE_PATH))["html_path"])
        self.assertEqual(change_lines(dom), [("none", "Nothing changed in the paragraphs, threads or gaps.")])

    def test_the_detail_box_says_where_a_paragraph_came_from(self):
        detail = lambda item: re.search(r'<div class="tm-detail-before">(.*?)</div>',
                                        dump_dom(self.html, hash=f"select={item}")).group(1)
        self.assertEqual(detail("P1"), "Before: v1 P1, 100% match")
        self.assertRegex(detail("P7"), r"^Before: v1 P3, \d\d% match · moved$")
        self.assertEqual(detail("P3"), "Before: v1 P2, split into P2, P3")
        self.assertEqual(detail("P5"), "Before: v1 P5, v1 P6, merged into this one")
        self.assertEqual(detail("P8"), "New since v1")

    def test_an_edited_pair_never_reads_100_percent(self):
        # One word of a long paragraph changes: the pair is edited, yet its ratio rounds to 1.0.
        # Beside "Edited" the page says 99%, in the detail box and on the hover text of the line;
        # the paragraph that did not change still says 100%.
        long = para(*range(1, 25))
        wording = {   # the detail box, the hover text of the line and the panel's line, per language
            "en": ("Before: v1 {id}, {pct}% match", "<title>v1 {id} → {id} · {pct}% match</title>",
                   ("edited", "Edited: P1")),
            "ko": ("이전: v1 {id}, {pct}% 일치", "<title>v1 {id} → {id} · {pct}% 일치</title>",
                   ("edited", "고친 문단: P1"))}
        for language, (detail_text, title_text, edited_line) in wording.items():
            with self.subTest(language):
                first = version_of([long, para(25, 26, 27)], {"q1": [1]}, ui_language=language)
                second = version_of([long.replace("patience", "care"), para(25, 26, 27)],
                                    {"q1": [1]}, ui_language=language)
                html = two_builds(first, second, template_path=str(TEMPLATE_PATH))["html_path"]
                self.assertEqual(saved_version(html)["compare"]["pairs"], [      # the premise
                    {"old": "P1", "new": "P1", "ratio": 1.0, "edited": True, "moved": False},
                    {"old": "P2", "new": "P2", "ratio": 1.0, "edited": False, "moved": False}])
                for item, pct, wrong in (("P1", 99, 100), ("P2", 100, 99)):
                    dom = dump_dom(html, hash=f"select={item}")
                    shown = re.search(r'<div class="tm-detail-before">(.*?)</div>', dom).group(1)
                    self.assertEqual(shown, detail_text.format(id=item, pct=pct))
                    self.assertIn(title_text.format(id=item, pct=pct), dom)
                    self.assertNotIn(title_text.format(id=item, pct=wrong), dom)
                self.assertIn(edited_line, change_lines(dom))

    def test_links_run_in_the_order_of_the_new_items_and_then_of_the_old_ones(self):
        data = saved_version(self.html)
        pairs = data["compare"]["pairs"]
        ratio = next(pair["ratio"] for pair in pairs if pair["new"] == "P7")
        pairs.append({"old": "P99", "new": "P8", "ratio": 0.9, "edited": False, "moved": False})
        html = Path(write_page_directly(data)).read_text("utf-8")
        exposed = html.replace("window.throughmap = api;", "api.linksOf = linksOf; window.throughmap = api;")
        self.assertNotEqual(exposed, html)
        dom = dump_dom(with_script(write_html(exposed), SHOW_LINKS))
        self.assertRegex(dom, NO_ERRORS)
        links = json.loads(unescape(re.search(r'<pre id="t-links">(.*?)</pre>', dom, re.S).group(1)))
        link = lambda old, new, kind, ratio=None, edited=False: {
            "old": old, "new": new, "kind": kind, "ratio": ratio, "edited": edited}
        # P7 comes from v1 P3 but stands after P6, which comes from v1 P7; P99 is on no map.
        # Only the pair of v1 P3 is edited, and a split or a merge carries no edit of its own.
        self.assertEqual(links, [
            link("P1", "P1", "pair", 1), link("P2", "P2", "split"), link("P2", "P3", "split"),
            link("P4", "P4", "pair", 1), link("P5", "P5", "merge"), link("P6", "P5", "merge"),
            link("P7", "P6", "pair", 1), link("P3", "P7", "pair", ratio, True)])

    def test_a_page_without_a_comparison_hides_the_panel(self):
        dom = dump_dom(page(sample_analysis()))
        self.assertIn('<section class="tm-panel" id="tm-changes" hidden="">', dom)
        # The class of the detail line is in the page's own script too: look at what it shows.
        self.assertNotIn("tm-detail-before", rendered(dump_dom(page(sample_analysis()), hash="select=P2")))

    def test_a_broken_comparison_leaves_the_plain_map(self):
        data = built_sample()
        data["compare"] = {"against": 1, "before": "not a map"}
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertIn('id="tm-changes" hidden=""', dom)

    def test_an_earlier_version_with_its_fields_missing_still_renders(self):
        data = saved_version(self.html)
        compare = data["compare"]
        compare["before"] = {}                      # nothing of the earlier version is left
        compare["pairs"] = [None, 5, {"old": "P1"}]
        compare["marks"] = ["x", {"new": "P4", "gained": "q1"}]
        compare["lanes"] = "none"
        compare["versions"] = "none"
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertNotIn('id="tm-changes" hidden=""', dom)
        self.assertEqual(change_lines(dom), [        # the earlier lane q1 is named by its id
            ("added", "New: P8"), ("removed", "Removed: v1 P8"),
            ("split", "Split: v1 P2 → P2, P3"), ("merged", "Merged: v1 P5, v1 P6 → P5"),
            ("quiet-closed", "q1 no longer rests from v1 P1 to v1 P8"),
            ("quiet-opened", "Pace now rests for 6 paragraphs (P1–P8)"),
            ("gap", GAP_AT_P8_NOTE + " (v1 P8)")])
        self.assertRegex(dom, r'id="tm-versions"[^>]*hidden=""')

    def test_markup_in_the_earlier_version_stays_text(self):
        markup = '<img src="x" onerror="document.body.remove()">'
        data = json.loads(Path(self.html).with_name("v2.json").read_text("utf-8"))
        data["compare"]["before"]["lanes"][3]["label"] = "Gone " + markup        # the lane gone
        data["compare"]["gaps_closed"][0]["note"] = "Note " + markup
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertNotIn("img", start_tags(dom))
        self.assertIn("Dropped thread: Gone &lt;img", dom)
        self.assertIn("Note &lt;img", dom)


class BeforeAfterTests(BrowserTestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = two_builds(*revision(), template_path=str(TEMPLATE_PATH))["html_path"]

    def test_links_join_each_paragraph_to_its_match(self):
        self.assertEqual(links(dump_dom(self.html)), sorted([
            ("P1", "P1", "pair"), ("P2", "P2", "split"), ("P2", "P3", "split"), ("P4", "P4", "pair"),
            ("P5", "P5", "merge"), ("P6", "P5", "merge"), ("P7", "P6", "pair"), ("P3", "P7", "pair")]))

    def test_badges_mark_what_is_new_removed_split_and_merged(self):
        self.assertEqual(badges(dump_dom(self.html)), sorted([
            ("added", "P8", "now"), ("removed", "P8", "before"), ("split", "P2", "before"),
            ("merged", "P5", "now")]))

    def test_a_link_says_how_closely_its_paragraphs_match(self):
        dom = dump_dom(self.html)
        self.assertIn("<title>v1 P1 → P1 · 100% match</title>", dom)
        self.assertRegex(dom, r"<title>v1 P3 → P7 · \d\d% match</title>")
        self.assertIn("<title>v1 P2 → P3 · split</title>", dom)

    def test_both_maps_share_one_column_width(self):
        texts = sections_of({"One": 40})[0][1]
        html = two_builds(version_of(texts, {"q1": [1]}), version_of(texts[:30], {"q1": [1]}),
                          template_path=str(TEMPLATE_PATH))["html_path"]
        width = lambda dom, svg: re.search(rf'<svg\b[^>]*\bid="{svg}"[^>]*\bwidth="([^"]*)"', dom).group(1)
        wide, narrow = dump_dom(html), dump_dom(html, width=600)
        self.assertEqual((width(wide, "tm-map-before"), width(wide, "tm-map")), ("1080", "840"))   # 24 px
        self.assertEqual((width(narrow, "tm-map-before"), width(narrow, "tm-map")), ("680", "540")) # 14 px

    def test_selecting_a_paragraph_lights_where_it_came_from(self):
        lit = lambda dom: re.findall(r'class="tm-col is-sel" data-item="([^"]+)"',
                                     between(dom, 'id="tm-map-before"', "</svg>"))
        self.assertEqual(lit(dump_dom(self.html, hash="select=P5")), ["P5", "P6"])
        self.assertIn('<g class="tm-link is-sel" data-old="P2" data-new="P3"',
                      dump_dom(self.html, hash="select=P3"))

    def test_clicking_an_earlier_column_selects_its_match(self):
        picked = lambda item: chosen(dump_dom(with_script(
            self.html, click(f'#tm-map-before .tm-col[data-item="{item}"]'))))["detail"]
        self.assertEqual((picked("P3"), picked("P8")), ("P7", None))              # v1 P8 was removed

    def test_isolating_a_thread_dims_it_in_both_maps(self):
        dom = dump_dom(self.html, hash="lane=q1")
        dimmed = lambda svg: re.findall(r'class="tm-lane is-dim" data-lane="([^"]+)"',
                                        between(dom, f'id="{svg}"', "</svg>"))
        self.assertEqual((dimmed("tm-map-before"), dimmed("tm-map")),
                         (["own", "pace", "gone"], ["own", "pace", "cost"]))

    def test_the_cards_sit_side_by_side_on_a_wide_window_and_stack_on_a_narrow_one(self):
        def place(width):
            dom = dump_dom(with_script(self.html, PLACES), width=width)
            return json.loads(unescape(re.search(r'<pre id="t-out">(.*?)</pre>', dom, re.S).group(1))), dom
        wide, dom = place(1240)
        self.assertTrue(wide["side"], wide)
        self.assertTrue(place(700)[0]["stacked"])
        self.assertEqual((dom.count('class="tm-card is-before"'), dom.count('class="tm-role-before"')), (1, 8))

    def test_the_poster_is_the_same_with_or_without_a_comparison(self):
        data = json.loads(Path(self.html).with_name("v2.json").read_text("utf-8"))
        plain = {key: value for key, value in data.items() if key != "compare"}
        poster = lambda d: re.search(r'<pre id="t8-svg">(.*?)</pre>',
                                     dump_dom(with_script(write_page_directly(d), WRITE_POSTER_SVG)), re.S).group(1)
        self.assertEqual(poster(data), poster(plain))

    def test_a_comparison_that_matched_nothing_renders(self):                     # Review Focus 4
        first = version_of([para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)], {"q1": [1]})
        second = version_of([para(20, 21, 22), para(23, 24, 25), para(26, 27, 28)], {"q1": [1]})
        dom = dump_dom(two_builds(first, second, template_path=str(TEMPLATE_PATH))["html_path"])
        self.assertRegex(dom, NO_ERRORS)
        self.assertEqual(links(dom), [])
        self.assertEqual([b[0] for b in badges(dom)], ["added"] * 3 + ["removed"] * 3)

    def test_a_page_without_a_comparison_shows_one_map_and_one_column(self):
        dom = dump_dom(page(sample_analysis()))
        for element in ("tm-flow-before", "tm-map-before", "tm-links", "tm-compare-legend"):
            self.assertRegex(dom, rf'id="{element}"[^>]*hidden=""')

    # Beyond the plan's tests: what its contract says and its tests leave unchecked.

    def test_the_heads_the_legend_and_the_hover_texts_say_what_they_are(self):
        dom = rendered(dump_dom(self.html))
        for element in ("tm-flow-before-head", "tm-map-before-head"):
            self.assertRegex(dom, f'id="{element}"[^>]*>Before · v1<')
        for element in ("tm-flow-now-head", "tm-map-now-head"):
            self.assertRegex(dom, f'id="{element}"[^>]*>Now · v2<')
        legend = ("Thin lines join each paragraph to its match; hover over one to see how close it is"
                  " · + new · \N{MINUS SIGN} removed · \N{DIVISION SIGN} split · \N{UNION} merged")
        self.assertRegex(dom, f'id="tm-compare-legend"[^>]*>{re.escape(legend)}<')
        self.assertIn("<title>v1 P6 → P5 · merged</title>", dom)
        shown = re.findall(r'data-badge="(\w+)"[^>]*><title>(.*?)</title>(.)</text>', dom)
        self.assertEqual(sorted(shown), sorted([
            ("added", "P8 · new", "+"), ("removed", "v1 P8 · removed", "\N{MINUS SIGN}"),
            ("split", "v1 P2 · split", "\N{DIVISION SIGN}"), ("merged", "P5 · merged", "\N{UNION}")]))

    def test_the_view_speaks_korean(self):
        html = two_builds(*revision(ui_language="ko"), template_path=str(TEMPLATE_PATH))["html_path"]
        dom = rendered(dump_dom(html))
        legend = ("가는 선은 서로 맞는 문단을 이어요. 선에 마우스를 올리면 얼마나 같은지 보여요 · + 새 문단"
                  " · \N{MINUS SIGN} 빠진 문단 · \N{DIVISION SIGN} 나뉜 문단 · \N{UNION} 합친 문단")
        for element, text in (("tm-flow-before-head", "이전 · v1"), ("tm-map-before-head", "이전 · v1"),
                              ("tm-flow-now-head", "지금 · v2"), ("tm-map-now-head", "지금 · v2"),
                              ("tm-compare-legend", legend)):
            self.assertRegex(dom, f'id="{element}"[^>]*>{re.escape(text)}<')
        for title in ("v1 P1 → P1 · 100% 일치", "v1 P2 → P3 · 나뉜 문단", "v1 P6 → P5 · 합친 문단",
                      "v1 P4 · 주장 · Part 4"):
            self.assertIn(f"<title>{title}</title>", dom)
        self.assertRegex(dom, r"<title>v1 P3 → P7 · \d\d% 일치</title>")
        self.assertEqual(sorted(re.findall(r'<text class="tm-badge"[^>]*><title>(.*?)</title>', dom)),
                         ["P5 · 합친 문단", "P8 · 새 문단", "v1 P2 · 나뉜 문단", "v1 P8 · 빠진 문단"])

    def test_the_strip_is_drawn_to_the_measures_of_the_contract(self):
        dom = dump_dom(self.html)
        strip = between(dom, 'id="tm-links"', "</svg>")
        self.assertRegex(dom, r'<svg id="tm-links" class="tm-svg" aria-hidden="true" width="408" '
                              r'height="36" viewBox="0 0 408 36"')                      # 120 + 8 × 36
        self.assertIn('<line x1="210" y1="10" x2="354" y2="26"></line>', strip)   # v1 P3 to P7, centre to centre
        self.assertEqual(strip.count("<line x1="), 8)                  # a line 1 px wide for each pair...
        self.assertEqual(strip.count('<line class="tm-hit"'), 8)        # ...and a wide invisible one over it
        place = lambda kind: re.search(rf'data-badge="{kind}"[^>]*? x="(\d+)" y="(\d+)"', strip).groups()
        self.assertEqual([place(kind) for kind in ("added", "merged", "removed", "split")],
                         [("390", "31"), ("282", "31"), ("390", "5"), ("174", "5")])

    def test_the_earlier_map_is_for_looking_at(self):
        dom = dump_dom(self.html)
        before, now = between(dom, 'id="tm-map-before"', "</svg>"), between(dom, 'id="tm-map"', "</svg>")
        self.assertEqual(re.findall(r'<g class="tm-lname"([^>]*)>', before),      # no role, tabindex or aria-pressed
                         [f' data-lane="{lane}"' for lane in ("q1", "own", "pace", "gone")])
        self.assertEqual(re.findall(r'<g class="tm-lname" data-lane="([^"]+)" role="button" tabindex="0" '
                                    r'aria-pressed="false">', now), ["q1", "own", "pace", "cost"])
        self.assertEqual(len(re.findall(r'<rect class="tm-col" data-item="P\d"[^>]*><title>', before)), 8)
        self.assertIn("<title>v1 P4 · Claim · Part 4</title>", before)
        self.assertEqual(len(re.findall(r'<rect class="tm-col"[^>]*></rect>', now)), 8)   # this map's say nothing

    def test_clicking_an_earlier_column_selects_the_first_paragraph_it_became(self):
        def after(item, before_script=""):
            script = before_script + click(f'#tm-map-before .tm-col[data-item="{item}"]')
            return chosen(dump_dom(with_script(self.html, script)))["detail"]
        # v1 P2 was split into P2 and P3, and v1 P6 was merged into P5.
        self.assertEqual([after(item) for item in ("P1", "P2", "P6", "P7")], ["P1", "P2", "P5", "P6"])
        self.assertIsNone(after("P8", API + 'select("P3");'))         # one that was removed clears the choice

    def test_an_earlier_version_without_its_names_or_runs_still_draws_its_map(self):
        data = saved_version(self.html)
        runs = lambda d: re.findall(r'<line class="tm-(?:run|span)"[^>]*>', between(
            dump_dom(write_page_directly(d)), 'id="tm-map-before"', "</svg>"))
        drawn = runs(data)
        del data["compare"]["before"]["computed"]                  # the page works the runs out itself
        self.assertEqual(runs(data), drawn)
        self.assertTrue(drawn)
        earlier = data["compare"]["before"]
        del earlier["essay"]
        for entry in earlier["sections"]:
            del entry["short"]
        for entry in earlier["lanes"]:
            del entry["label"]
        for entry in earlier["paragraphs"]:
            del entry["label"], entry["role"], entry["lanes"]
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        before = between(dom, 'id="tm-map-before"', "</svg>")
        self.assertEqual(len(re.findall(r'<rect class="tm-col"', before)), 8)
        self.assertEqual(re.findall(r'<tspan class="tm-lname-name">(.*?)</tspan>', before),
                         ["Q1", "own", "pace", "gone"])          # a thread with no label goes by its id
        self.assertIn("<title>v1 P1</title>", before)             # a column with no role or label
        self.assertIn('<span class="tm-short">S1</span>', dom)   # a section with no short name

    def test_markup_in_the_earlier_version_stays_text_in_its_cards_and_map(self):
        markup = '<img src="x" onerror="document.body.remove()">'
        data = saved_version(self.html)
        earlier = data["compare"]["before"]
        earlier["sections"][0]["short"] = "Short " + markup
        earlier["sections"][0]["conclusion"] = "Conclusion " + markup
        earlier["paragraphs"][3]["label"] = "Label " + markup
        earlier["lanes"][1]["label"] = "Lane " + markup
        dom = dump_dom(write_page_directly(data))
        self.assertRegex(dom, NO_ERRORS)
        self.assertNotIn("img", start_tags(dom))
        for text in ("Short", "Conclusion", "Lane"):
            self.assertIn(f"{text} &lt;img", rendered(dom))
        self.assertIn("<title>v1 P4 · Claim · Label &lt;img", dom)       # the hover text of a column

    def test_both_maps_and_the_strip_are_drawn_again_together_when_the_window_resizes(self):
        squeezed = with_script(forty_then_thirty(), 'document.querySelector("main").style.maxWidth = "632px";'
                                                    'window.dispatchEvent(new Event("resize"));')
        dom = dump_dom(squeezed)
        width = lambda svg: re.search(rf'<svg\b[^>]*\bid="{svg}"[^>]*\bwidth="([^"]*)"', dom).group(1)
        self.assertEqual([width(svg) for svg in ("tm-map-before", "tm-links", "tm-map")], ["680", "680", "540"])
        self.assertEqual((len(links(dom)), dom.count('class="tm-badge"')), (30, 10))     # drawn anew, not added to
        # In print each map keeps its part of the strip's width, so that the columns still line up.
        share = lambda svg: re.search(rf'<svg\b[^>]*\bid="{svg}"[^>]*\bstyle="--share: ([\d.]+);"', dom).group(1)
        self.assertEqual((share("tm-map-before"), share("tm-map")), ("1", "0.794"))       # 540 / 680
