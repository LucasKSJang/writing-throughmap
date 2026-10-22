"""Tests for build: runs and observations, the page data, saved versions and the commands."""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import tm_build
from tests import SCRIPTS_DIR
from tests.fixtures import (
    REVISION_CHANGES, STUB_TEMPLATE, STUB_TEMPLATE_PATH, built_sample, built_version, lanes_marked,
    n_paragraphs, para, quiet, revision, rewrite_draft, run_main, run_main_streams, sample_analysis,
    sample_source, sample_with_unthreaded_P3_and_own_missing_from_last_section, table_item,
    tmp_dir, tmp_path, two_builds, version_of, write_draft,
)
from tm_build import (
    BuildError, build, compute_observations, compute_runs, list_versions, next_version,
    render_html, terminal_summary,
)
from tm_compare import CompareError

DOT = "\N{MIDDLE DOT}"
ARROW = "\N{RIGHTWARDS ARROW}"
EN_DASH, EM_DASH = "\N{EN DASH}", "\N{EM DASH}"
ONE, TWO, THREE = "\N{CIRCLED DIGIT ONE}", "\N{CIRCLED DIGIT TWO}", "\N{CIRCLED DIGIT THREE}"
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


@contextlib.contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def read_text(path):
    return Path(path).read_text("utf-8")


def embedded_data(html):
    """Return the data a page embeds, read back from its data script element."""
    match = re.search(r'<script id="throughmap-data" type="application/json">(.*?)</script>',
                      html, re.DOTALL)
    if match is None:
        raise AssertionError("the page has no data script element")
    return json.loads(match.group(1))


def folder_of(draft):
    return os.path.dirname(draft)


def beside(draft, name):
    """Return the absolute path of ``name`` in the folder of the draft."""
    return os.path.abspath(os.path.join(folder_of(draft), name))


class BuildTests(unittest.TestCase):
    def test_compute_runs(self):
        # T1 sits between P4 and P5, so P4 and P5 are not consecutive items; P5 and P6 are.
        a = lanes_marked({"q1": ["P1", "P2", "P5", "P6"], "q2": ["P3"]})
        runs = compute_runs(a)
        self.assertEqual(runs["q1"], {"span": ["P1", "P6"], "solid": [["P1", "P2"], ["P5", "P6"]]})
        self.assertEqual(runs["q2"], {"span": ["P3", "P3"], "solid": []})
        self.assertNotIn("own", runs)                  # a lane without marks has no runs

    def test_quiet_thread_threshold_counts_paragraphs_only(self):
        a = n_paragraphs(24, marks={"q1": ["P1", "P10", "P16"]}, table_after="P5")
        self.assertEqual(quiet(compute_observations(a)),
                         [{"type": "quiet", "lane": "q1", "from": "P1", "to": "P10", "length": 8}])

    def test_unresolved_and_unthreaded(self):
        obs = compute_observations(sample_with_unthreaded_P3_and_own_missing_from_last_section())
        self.assertIn({"type": "unresolved", "lane": "own"}, obs)
        self.assertIn({"type": "unthreaded", "at": ["P3"]}, obs)
        self.assertNotIn({"type": "unthreaded", "at": ["P4"]}, obs)        # P4 is a transition

    def test_next_version(self):
        d = tmp_dir()
        self.assertEqual(next_version(d), 1)
        for n in (1, 2, 10):
            Path(d, f"v{n}.json").write_text("{}", "utf-8")
        self.assertEqual(next_version(d), 11)

    def test_render_html_escapes_script_close(self):
        html = render_html({"t": "</script><b>x</b>"}, STUB_TEMPLATE)
        self.assertIn("<\\/script><b>x<\\/b>", html)
        self.assertEqual(html.count("</script>"), STUB_TEMPLATE.count("</script>"))
        with self.assertRaises(ValueError):
            render_html({}, "<html></html>")

    def test_terminal_summary_format(self):
        lines = terminal_summary(built_sample(), "/x/index.html").splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], f"throughmap {DOT} Sample Essay (6 paragraphs, 3 threads)")
        self.assertTrue(lines[1].startswith("flow: ") and f" {ARROW} " in lines[1])
        self.assertTrue(lines[2].startswith(f"gaps: {ONE}"))
        self.assertEqual(lines[3], "open: /x/index.html")

    def test_build_writes_versions_without_overwriting(self):
        draft = write_draft(sample_source(), sample_analysis())
        r1 = build(draft, STUB_TEMPLATE_PATH)
        v1 = Path(r1["json_path"]).read_text("utf-8")
        r2 = build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual((r1["version"], r2["version"]), (1, 2))
        self.assertEqual(Path(r1["json_path"]).read_text("utf-8"), v1)
        data = json.loads(Path(r2["json_path"]).read_text("utf-8"))
        self.assertEqual(set(data) >= {"version", "generated_at", "computed"}, True)
        self.assertIn('"version": 2', Path(r2["html_path"]).read_text("utf-8"))

    def test_build_refuses_invalid_draft(self):
        a = sample_analysis()
        a["paragraphs"][1]["evidence"] = "nope"
        draft = write_draft(sample_source(), a)
        with self.assertRaises(BuildError) as raised:
            build(draft, STUB_TEMPLATE_PATH)
        self.assertFalse(Path(draft).with_name("v1.json").exists())
        # The message is the report that check gives, and nothing at all was written.
        self.assertIn("ERROR $.paragraphs[1].evidence", str(raised.exception))
        self.assertEqual(str(raised.exception).splitlines()[-1], "1 error, 0 warnings")
        self.assertEqual(sorted(os.listdir(folder_of(draft))), ["draft.json", "source.json"])

    def test_versions_listing(self):
        draft = write_draft(sample_source(), sample_analysis())
        build(draft, STUB_TEMPLATE_PATH)
        build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual([v["version"] for v in list_versions(str(Path(draft).parent))], [1, 2])


class RunsTests(unittest.TestCase):
    def test_a_run_is_every_consecutive_mark_and_the_span_covers_the_gaps(self):
        a = lanes_marked({"q1": ["P1", "P2", "P3", "P5", "P6"]})     # P4 and T1 lie between P3, P5
        self.assertEqual(compute_runs(a)["q1"],
                         {"span": ["P1", "P6"], "solid": [["P1", "P2", "P3"], ["P5", "P6"]]})

    def test_a_table_is_an_item_between_the_paragraphs_around_it(self):
        apart = lanes_marked({"q1": ["P4", "P5"]})
        self.assertEqual(compute_runs(apart)["q1"], {"span": ["P4", "P5"], "solid": []})
        joined = lanes_marked({"q1": ["P4", "T1", "P5"]})
        self.assertEqual(compute_runs(joined)["q1"],
                         {"span": ["P4", "P5"], "solid": [["P4", "T1", "P5"]]})

    def test_lanes_without_marks_are_left_out(self):
        self.assertEqual(list(compute_runs(lanes_marked({"q1": ["P1"]}))), ["q1"])
        self.assertEqual(compute_runs(lanes_marked({})), {})

    def test_lanes_follow_the_order_of_the_lane_list(self):
        self.assertEqual(list(compute_runs(sample_analysis())), ["q1", "q2", "own"])

    def test_the_sample_matches_the_runs_and_observations_worked_out_by_hand(self):
        sample = built_sample()
        self.assertEqual(compute_runs(sample), sample["computed"]["runs"])
        self.assertEqual(compute_observations(sample), sample["computed"]["observations"])


class QuietThreadTests(unittest.TestCase):
    def test_the_threshold_is_the_larger_of_6_and_a_quarter_of_the_paragraphs(self):
        # (paragraphs, paragraphs that rest between two marks, is it reported)
        cases = ((10, 5, False), (10, 6, True), (24, 5, False), (24, 6, True),
                 (25, 6, False), (25, 7, True), (40, 9, False), (40, 10, True))
        for paragraphs, resting, reported in cases:
            with self.subTest(paragraphs=paragraphs, resting=resting):
                end = f"P{resting + 2}"
                a = n_paragraphs(paragraphs, marks={"q1": ["P1", end]})
                expected = [{"type": "quiet", "lane": "q1", "from": "P1", "to": end,
                             "length": resting}]
                self.assertEqual(quiet(compute_observations(a)), expected if reported else [])

    def test_a_table_does_not_raise_the_threshold(self):
        # 24 paragraphs make the threshold 6. With T1 the draft holds 25 items, but a quarter of
        # 25 would be 7: only the paragraphs are counted, so the rest of 6 is still reported.
        a = n_paragraphs(24, marks={"q1": ["P1", "P8"]}, table_after="P20")
        self.assertEqual(quiet(compute_observations(a)),
                         [{"type": "quiet", "lane": "q1", "from": "P1", "to": "P8", "length": 6}])

    def test_the_stretches_before_the_first_mark_and_after_the_last_do_not_count(self):
        a = n_paragraphs(24, marks={"q1": ["P10", "P11"]})
        self.assertEqual(quiet(compute_observations(a)), [])

    def test_each_rest_between_two_marks_is_its_own_entry(self):
        a = n_paragraphs(24, marks={"q1": ["P1", "P9", "P10", "P20"], "q2": ["P2", "P12"]})
        self.assertEqual(quiet(compute_observations(a)), [
            {"type": "quiet", "lane": "q1", "from": "P1", "to": "P9", "length": 7},
            {"type": "quiet", "lane": "q1", "from": "P10", "to": "P20", "length": 9},
            {"type": "quiet", "lane": "q2", "from": "P2", "to": "P12", "length": 9},
        ])

    def test_a_marked_table_is_a_mark_that_ends_the_rest(self):
        resting = n_paragraphs(24, marks={"q1": ["P1", "P10"]}, table_after="P5")
        self.assertEqual(len(quiet(compute_observations(resting))), 1)
        marked = n_paragraphs(24, marks={"q1": ["P1", "T1", "P10"]}, table_after="P5")
        self.assertEqual(quiet(compute_observations(marked)), [])


class UnresolvedAndUnthreadedTests(unittest.TestCase):
    def test_the_sample_with_two_observations_has_exactly_those(self):
        obs = compute_observations(sample_with_unthreaded_P3_and_own_missing_from_last_section())
        self.assertEqual(obs, [{"type": "unresolved", "lane": "own"},
                               {"type": "unthreaded", "at": ["P3"]}])

    def test_a_table_is_never_unthreaded(self):
        a = sample_analysis()
        table_item(a)["lanes"] = {}
        self.assertEqual(compute_observations(a), [])

    def test_only_marks_on_paragraphs_count_in_the_last_section(self):
        # q2 is also marked on T1, and T1 says it is in the last section: the table is not relied on
        a = lanes_marked({"q1": ["P1", "P6"], "q2": ["P2", "T1"], "own": ["P1"]})
        table_item(a)["section"] = "S3"
        unresolved = [o for o in compute_observations(a) if o["type"] == "unresolved"]
        self.assertEqual(unresolved, [{"type": "unresolved", "lane": "q2"},
                                      {"type": "unresolved", "lane": "own"}])

    def test_a_lane_without_any_mark_is_not_called_unresolved(self):
        obs = compute_observations(lanes_marked({"q1": ["P1", "P6"]}))
        self.assertEqual([o for o in obs if o["type"] != "unthreaded"], [])

    def test_a_draft_of_one_section_has_no_unresolved_lane(self):
        a = n_paragraphs(8, marks={"q1": ["P1"], "q2": ["P2"]})
        self.assertEqual([o for o in compute_observations(a) if o["type"] == "unresolved"], [])

    def test_observations_come_in_the_order_quiet_unresolved_unthreaded(self):
        a = n_paragraphs(12, marks={"q1": ["P1", "P9"], "q2": ["P2"]})
        for item in a["paragraphs"][6:]:                  # P7 to P12 make a second section
            item["section"] = "S2"
        first = a["sections"][0]
        a["sections"] = [dict(first, last="P6"), dict(first, id="S2", first="P7", last="P12")]
        self.assertEqual(compute_observations(a), [
            {"type": "quiet", "lane": "q1", "from": "P1", "to": "P9", "length": 7},
            {"type": "unresolved", "lane": "q2"},
            *({"type": "unthreaded", "at": [f"P{n}"]} for n in (3, 4, 5, 6, 7, 8, 10, 11, 12)),
        ])


class RenderHtmlTests(unittest.TestCase):
    def test_the_placeholder_must_occur_exactly_once(self):
        placeholder = tm_build.PLACEHOLDER
        for template in ("<html></html>", f"<p>{placeholder}</p><p>{placeholder}</p>"):
            with self.subTest(template=template), self.assertRaisesRegex(ValueError, placeholder):
                render_html({}, template)

    def test_the_data_reads_back_unchanged_from_the_page(self):
        tricky = ["</script>", "<!-- <script> -->", "<!--<script>x</script>-->", "--><script>",
                  "a\\</b", "\\", "</", "<\\/", "<!-", "<!-- ", "&amp; <b>bold</b> & <i>x</i>",
                  "\\1 \\g<0>", tm_build.PLACEHOLDER, "\N{LINE SEPARATOR}",
                  f"한글 {EM_DASH} text"]
        data = {"items": tricky, "</script>": 1, "<!--": 2}
        html = render_html(data, STUB_TEMPLATE)
        self.assertEqual(embedded_data(html), data)
        self.assertEqual(html.count("</script>"), 1)             # the one that closes the data

    def test_an_html_comment_opener_cannot_swallow_the_closing_tag(self):
        # After an unclosed "<!--" and a "<script", a browser takes the next "</script>" for the end
        # of a nested script: the data element stays open and swallows the page that follows it
        # (seen in Chrome and Edge).
        html = render_html({"t": "<!--<script>"}, STUB_TEMPLATE)
        self.assertNotIn("<!--", html)
        self.assertEqual(embedded_data(html), {"t": "<!--<script>"})

    def test_text_stays_text_and_is_not_ascii_escaped(self):
        html = render_html({"t": f"한글 {EM_DASH} text"}, STUB_TEMPLATE)
        self.assertIn(f"한글 {EM_DASH} text", html)
        self.assertNotIn("\\u", html)

    def test_the_data_replaces_the_placeholder_in_the_template(self):
        html = render_html({"a": 1}, STUB_TEMPLATE)
        self.assertEqual(html, STUB_TEMPLATE.replace(tm_build.PLACEHOLDER, '{"a": 1}'))


class TerminalSummaryTests(unittest.TestCase):
    def setUp(self):
        self.data = built_sample()
        self.data["gaps"] = [{"at": ["P3"], "note": "First gap.", "direction": "Do this."},
                             {"at": ["P4"], "note": "Second gap.", "direction": "Do that."}]
        self.data["computed"]["observations"] = [
            {"type": "quiet", "lane": "q1", "from": "P1", "to": "P9", "length": 7},
            {"type": "unresolved", "lane": "own"},
            {"type": "unthreaded", "at": ["P3"]},
        ]

    def gaps_line(self):
        return terminal_summary(self.data, "/x/index.html").splitlines()[2]

    def test_a_changes_line_goes_before_the_open_line(self):
        lines = terminal_summary(built_sample(), "/x/index.html",
                                 changes="changes from v1: none").splitlines()
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[2].startswith("gaps: "))
        self.assertEqual(lines[3], "changes from v1: none")
        self.assertEqual(lines[4], "open: /x/index.html")

    def test_the_flow_names_each_section_and_the_questions_it_answers(self):
        flow = terminal_summary(built_sample(), "/x/index.html").splitlines()[1]
        self.assertEqual(flow, f"flow: Opening (Q1) {ARROW} Middle (Q1, Q2) {ARROW} End (Q2)")
        data = built_sample()
        data["sections"][0]["answers"] = []
        data["sections"][1]["title"] = "A much longer heading"        # the short name is shown
        flow = terminal_summary(data, "/x/index.html").splitlines()[1]
        self.assertEqual(flow, f"flow: Opening {ARROW} Middle (Q1, Q2) {ARROW} End (Q2)")

    def test_the_gap_notes_come_first_and_three_notes_are_the_most(self):
        self.assertEqual(self.gaps_line(), f"gaps: {ONE} First gap. {TWO} Second gap. {THREE} "
                                           f"Pace rests for 7 paragraphs (P1{EN_DASH}P9)")

    def test_observations_follow_in_english_with_the_label_of_their_lane(self):
        self.data["gaps"] = []
        self.assertEqual(
            self.gaps_line(),
            f"gaps: {ONE} Pace rests for 7 paragraphs (P1{EN_DASH}P9) "
            f"{TWO} Rest time does not return in the last section {THREE} P3 is on no thread")

    def test_an_observation_of_an_unknown_lane_falls_back_to_its_id(self):
        self.data["gaps"] = []
        self.data["computed"]["observations"] = [{"type": "unresolved", "lane": "zzz"}]
        self.assertEqual(self.gaps_line(), f"gaps: {ONE} zzz does not return in the last section")

    def test_no_notes_say_none(self):
        self.data["gaps"], self.data["computed"]["observations"] = [], []
        self.assertEqual(self.gaps_line(), "gaps: none")

    def test_one_gap_is_one_note(self):
        self.data["computed"]["observations"] = []
        self.data["gaps"] = self.data["gaps"][:1]
        self.assertEqual(self.gaps_line(), f"gaps: {ONE} First gap.")

    def test_the_counts_are_singular_for_one(self):
        data = built_sample()
        data["paragraphs"] = [item for item in data["paragraphs"] if item["id"] == "P1"]
        data["lanes"] = data["lanes"][:1]
        first = terminal_summary(data, "/x/index.html").splitlines()[0]
        self.assertEqual(first, f"throughmap {DOT} Sample Essay (1 paragraph, 1 thread)")

    def test_a_line_break_in_a_title_or_a_note_does_not_add_lines(self):
        self.data["essay"]["title"] = "Sample\n  Essay"
        self.data["gaps"][0]["note"] = "First\ngap.\n"
        lines = terminal_summary(self.data, "/x/index.html").splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], f"throughmap {DOT} Sample Essay (6 paragraphs, 3 threads)")
        self.assertTrue(lines[2].startswith(f"gaps: {ONE} First gap. {TWO}"), lines[2])


class BuildFilesTests(unittest.TestCase):
    def setUp(self):
        self.source, self.analysis = sample_source(), sample_analysis()

    def built(self, template=STUB_TEMPLATE_PATH):
        draft = write_draft(self.source, self.analysis)
        return draft, build(draft, template)

    def test_it_returns_the_version_the_absolute_paths_and_the_summary(self):
        draft, result = self.built()
        self.assertEqual(set(result), {"version", "json_path", "html_path", "summary"})
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["json_path"], beside(draft, "v1.json"))
        self.assertEqual(result["html_path"], beside(draft, "index.html"))
        lines = result["summary"].splitlines()
        self.assertEqual(lines[0], f"throughmap {DOT} Sample Essay (6 paragraphs, 3 threads)")
        self.assertEqual(lines[-1], "open: " + result["html_path"])        # absolute: it is clicked

    def test_the_version_file_is_the_analysis_plus_version_time_and_computed(self):
        draft, result = self.built()
        text = read_text(result["json_path"])
        data = json.loads(text)
        expected = built_sample()
        expected["generated_at"] = data["generated_at"]
        self.assertEqual(data, expected)
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(json.loads(read_text(draft)), self.analysis)      # draft.json is unchanged

    def test_observations_are_computed_into_the_version_and_the_summary(self):
        self.analysis = sample_with_unthreaded_P3_and_own_missing_from_last_section()
        _, result = self.built()
        computed = json.loads(read_text(result["json_path"]))["computed"]
        self.assertEqual(computed["runs"], {
            "q1": {"span": ["P1", "P6"], "solid": []},
            "q2": {"span": ["P2", "P6"], "solid": [["P5", "P6"]]},
            "own": {"span": ["P2", "T1"], "solid": []},
        })
        self.assertEqual(computed["observations"], [{"type": "unresolved", "lane": "own"},
                                                    {"type": "unthreaded", "at": ["P3"]}])
        self.assertEqual(
            result["summary"].splitlines()[2],
            f"gaps: {ONE} {self.analysis['gaps'][0]['note']} "
            f"{TWO} Rest time does not return in the last section {THREE} P3 is on no thread")

    def test_generated_at_is_the_utc_time_in_iso_8601_to_the_second(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        _, result = self.built()
        after = datetime.now(timezone.utc)
        stamp = json.loads(read_text(result["json_path"]))["generated_at"]
        self.assertRegex(stamp, f"^{STAMP.pattern}$")
        moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertTrue(before <= moment <= after, (before, moment, after))

    def test_non_ascii_text_is_written_as_it_is(self):
        self.analysis["thesis"] = "반죽은 오래 쉴수록 부드러워진다."
        _, result = self.built()
        for path in (result["json_path"], result["html_path"]):
            with self.subTest(path=os.path.basename(path)):
                text = read_text(path)
                self.assertIn("반죽은 오래 쉴수록", text)
                self.assertIn(EM_DASH, text)                    # the em dash of P3
                self.assertNotIn("\\u", text)

    def test_the_page_is_the_template_with_the_data_of_this_version(self):
        _, result = self.built()
        data = json.loads(read_text(result["json_path"]))
        self.assertEqual(read_text(result["html_path"]), render_html(data, STUB_TEMPLATE))
        self.assertEqual(embedded_data(read_text(result["html_path"])), data)

    def test_the_page_follows_the_latest_version_and_the_older_ones_stay(self):
        draft, first = self.built()
        self.analysis["thesis"] = "A changed thesis."
        Path(draft).write_text(json.dumps(self.analysis), "utf-8")      # the next analysis
        second = build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual(embedded_data(read_text(second["html_path"]))["version"], 2)
        self.assertEqual(embedded_data(read_text(second["html_path"]))["thesis"],
                         "A changed thesis.")
        self.assertEqual(json.loads(read_text(second["json_path"]))["thesis"], "A changed thesis.")
        self.assertNotEqual(json.loads(read_text(first["json_path"]))["thesis"],
                            "A changed thesis.")

    def test_markup_in_the_text_is_kept_in_the_data_and_cannot_close_the_script(self):
        text = " Tags like </script><b>bold</b> & <!--<script>x</script> stay text."
        self.source["paragraphs"][1]["text"] += text
        self.analysis["paragraphs"][1]["text"] += text
        _, result = self.built()
        data = json.loads(read_text(result["json_path"]))
        self.assertTrue(data["paragraphs"][1]["text"].endswith(text))
        self.assertIn("</script><b>bold</b>", read_text(result["json_path"]))
        html = read_text(result["html_path"])
        self.assertNotIn("<!--", html)
        self.assertEqual(html.count("</script>"), 1)
        self.assertEqual(embedded_data(html), data)

    def test_the_draft_and_the_source_are_not_changed(self):
        draft = write_draft(self.source, self.analysis)
        before = {name: Path(folder_of(draft), name).read_bytes()
                  for name in ("draft.json", "source.json")}
        build(draft, STUB_TEMPLATE_PATH)
        build(draft, STUB_TEMPLATE_PATH)
        after = {name: Path(folder_of(draft), name).read_bytes() for name in before}
        self.assertEqual(after, before)

    def test_warnings_do_not_stop_the_build(self):
        self.analysis["paragraphs"][0]["label"] = "x" * 29
        _, result = self.built()
        self.assertEqual(result["version"], 1)

    def test_a_draft_with_a_byte_order_mark_builds(self):
        draft = write_draft(self.source, self.analysis)
        Path(draft).write_bytes(BOM.encode("utf-8") + Path(draft).read_bytes())
        self.assertEqual(build(draft, STUB_TEMPLATE_PATH)["version"], 1)

    def test_a_relative_path_to_the_draft_works_and_the_paths_come_back_absolute(self):
        draft = write_draft(self.source, self.analysis)
        with working_directory(folder_of(draft)):
            result = build("draft.json", STUB_TEMPLATE_PATH)
        for key in ("json_path", "html_path"):
            self.assertTrue(os.path.isabs(result[key]), result)
        self.assertTrue(os.path.samefile(result["html_path"], beside(draft, "index.html")))
        self.assertEqual(result["summary"].splitlines()[-1], "open: " + result["html_path"])

    def test_a_spaced_korean_folder_works(self):
        draft = write_draft(self.source, self.analysis)
        folder = tmp_dir("B and F", "한글 폴더", "글 초안.throughmap")
        for name in ("source.json", "draft.json"):
            shutil.copy(os.path.join(folder_of(draft), name), folder)
        moved = os.path.join(folder, "draft.json")
        result = build(moved, STUB_TEMPLATE_PATH)
        self.assertEqual(result["html_path"], beside(moved, "index.html"))
        self.assertEqual(embedded_data(read_text(result["html_path"]))["version"], 1)

    def test_an_existing_version_is_never_overwritten(self):
        # Two builds that both claim version 1 (say, run at once): the later one fails and changes
        # nothing, the page included, although its analysis differs.
        draft, first = self.built()
        kept = (read_text(first["json_path"]), read_text(first["html_path"]))
        self.analysis["thesis"] = "A changed thesis."
        Path(draft).write_text(json.dumps(self.analysis), "utf-8")
        with mock.patch.object(tm_build, "next_version", return_value=1):
            with self.assertRaises(FileExistsError):
                build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual((read_text(first["json_path"]), read_text(first["html_path"])), kept)

    def test_nothing_is_written_when_the_template_cannot_be_used(self):
        draft = write_draft(self.source, self.analysis)
        no_placeholder = tmp_path("template.html")
        Path(no_placeholder).write_text("<html></html>", "utf-8")
        for template in (no_placeholder, tmp_path("missing.html")):
            with self.subTest(template=os.path.basename(template)):
                with self.assertRaises((ValueError, OSError)):
                    build(draft, template)
                self.assertEqual(sorted(os.listdir(folder_of(draft))),
                                 ["draft.json", "source.json"])

    def test_nothing_is_written_when_the_text_cannot_be_encoded(self):
        # JSON may spell a lone surrogate as an escape, but no file can hold it as UTF-8.
        draft = write_draft(self.source, self.analysis)
        self.analysis["thesis"] = "a lone surrogate: " + chr(0xD800)
        Path(draft).write_text(json.dumps(self.analysis), "utf-8")      # ASCII: an escape
        with self.assertRaises(ValueError):
            build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual(sorted(os.listdir(folder_of(draft))), ["draft.json", "source.json"])

    def test_missing_files_are_value_errors_that_name_the_file(self):
        draft = write_draft(self.source, self.analysis)
        with self.assertRaisesRegex(ValueError, "gone"):
            build(os.path.join(folder_of(draft), "gone", "draft.json"), STUB_TEMPLATE_PATH)
        os.remove(os.path.join(folder_of(draft), "source.json"))
        with self.assertRaisesRegex(ValueError, "extract"):
            build(draft, STUB_TEMPLATE_PATH)

    def test_without_a_template_argument_it_uses_the_one_in_the_skill(self):
        default = Path(tm_build.DEFAULT_TEMPLATE)
        self.assertEqual(default.resolve(),
                         (SCRIPTS_DIR.parent / "assets" / "template.html").resolve())
        self.assertEqual(default.read_text("utf-8").count(tm_build.PLACEHOLDER), 1)
        draft = write_draft(self.source, self.analysis)
        result = build(draft)
        data = embedded_data(read_text(result["html_path"]))
        self.assertEqual(data, json.loads(read_text(result["json_path"])))


class OtherFilesTests(unittest.TestCase):
    """After a build, the summary names any file in <out> that is not the map's own.

    An agent's helper script (assemble.py, say) left in <out> is the case in point. Build only
    names such files: it deletes nothing.
    """

    def setUp(self):
        self.draft = write_draft(sample_source(), sample_analysis())
        self.folder = os.path.dirname(beside(self.draft, "index.html"))   # absolute, as build has it

    def put(self, *parts):
        path = os.path.join(self.folder, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text("print('helper')\n", "utf-8")
        return path

    def test_a_stray_file_is_named_in_a_last_line_and_kept(self):
        helper = self.put("assemble.py")
        code, out, err = run_main_streams(["build", self.draft])
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 5, out)
        self.assertEqual(lines[3], "open: " + beside(self.draft, "index.html"))
        self.assertEqual(lines[4], f"also in {self.folder}: assemble.py "
                                   "(remove it if you created it)")
        self.assertTrue(os.path.isfile(helper))                       # named, never deleted

    def test_several_stray_files_share_the_line_in_name_order(self):
        for name in ("notes.txt", "v1.json.bak", "assemble.py"):
            self.put(name)
        summary = build(self.draft, STUB_TEMPLATE_PATH)["summary"]
        self.assertEqual(summary.splitlines()[4:], [
            f"also in {self.folder}: assemble.py, notes.txt, v1.json.bak "
            "(remove any you created)"])

    def test_a_clean_folder_prints_no_such_line(self):
        # The second build finds v1.json and index.html, which are the map's own, and compares.
        first = build(self.draft, STUB_TEMPLATE_PATH)["summary"].splitlines()
        second = build(self.draft, STUB_TEMPLATE_PATH)["summary"].splitlines()
        self.assertEqual((len(first), len(second)), (4, 5), (first, second))
        self.assertEqual(second[3], "changes from v1: none")
        for lines in (first, second):
            self.assertFalse([line for line in lines if line.startswith("also in")], lines)

    def test_subfolders_and_the_maps_own_files_are_never_named(self):
        # source.json, draft.json, the draft under any other name, every vN.json and index.html
        # belong to the map; a folder is not a file, whatever it holds.
        self.put("helpers", "assemble.py")
        os.makedirs(os.path.join(self.folder, "empty"))
        build(self.draft, STUB_TEMPLATE_PATH)
        renamed = os.path.join(self.folder, "draft-2.json")
        shutil.copyfile(self.draft, renamed)
        result = build(renamed, STUB_TEMPLATE_PATH)
        self.assertEqual(result["version"], 2)
        self.assertFalse([line for line in result["summary"].splitlines()
                          if line.startswith("also in")], result["summary"])

    def test_files_the_system_leaves_are_never_named(self):
        # Finder and Explorer write these into a folder they show; no agent wrote them.
        for name in (".DS_Store", "Thumbs.db", "desktop.ini"):
            self.put(name)
        self.assertEqual(len(build(self.draft, STUB_TEMPLATE_PATH)["summary"].splitlines()), 4)
        self.put("assemble.py")
        summary = build(self.draft, STUB_TEMPLATE_PATH)["summary"]
        self.assertEqual([line for line in summary.splitlines() if line.startswith("also in")], [
            f"also in {self.folder}: assemble.py (remove it if you created it)"])

    def test_a_failed_build_names_nothing(self):
        self.put("assemble.py")
        analysis = sample_analysis()
        analysis["paragraphs"][1]["evidence"] = "nope"
        Path(self.draft).write_text(json.dumps(analysis), "utf-8")
        code, out = run_main(["build", self.draft])
        self.assertEqual(code, 1)
        self.assertNotIn("also in", out)


class VersionTests(unittest.TestCase):
    def test_next_version_counts_only_files_named_for_a_version(self):
        d = tmp_dir()
        for name in ("draft.json", "source.json", "index.html", "v2.json.bak", "v3.txt", "v.json",
                     "vx.json", "v09.json", "v0.json", "xv9.json", "v1234567890.json"):
            Path(d, name).write_text("{}", "utf-8")
        Path(d, "v2.json").write_text("{}", "utf-8")
        self.assertEqual(next_version(d), 3)

    def test_versions_are_listed_in_numeric_order_with_date_and_paragraph_count(self):
        d = tmp_dir()
        paragraphs = [{"kind": "paragraph"}, {"kind": "table"}, {"kind": "paragraph"}]
        Path(d, "v10.json").write_text(json.dumps(
            {"generated_at": "2026-10-17T12:00:00Z", "paragraphs": paragraphs}), "utf-8")
        Path(d, "v2.json").write_text(json.dumps(
            {"generated_at": "2026-10-16T08:30:00Z", "paragraphs": paragraphs[:1]}), "utf-8")
        self.assertEqual(list_versions(d), [
            {"version": 2, "generated_at": "2026-10-16T08:30:00Z", "paragraphs": 1},
            {"version": 10, "generated_at": "2026-10-17T12:00:00Z", "paragraphs": 2},
        ])

    def test_a_file_that_is_not_a_version_is_listed_without_details(self):
        d = tmp_dir()
        contents = {1: "{}", 2: "{not json", 3: "[1, 2]", 4: '{"paragraphs": 3}'}
        for number, content in contents.items():
            Path(d, f"v{number}.json").write_text(content, "utf-8")
        self.assertEqual(list_versions(d), [
            {"version": number, "generated_at": None, "paragraphs": 0} for number in (1, 2, 3, 4)])

    def test_no_versions_is_an_empty_list(self):
        self.assertEqual(list_versions(tmp_dir()), [])


class BuildCommandTests(unittest.TestCase):
    def setUp(self):
        self.source, self.analysis = sample_source(), sample_analysis()

    def test_it_prints_the_summary_and_exits_0(self):
        draft = write_draft(self.source, self.analysis)
        code, out, err = run_main_streams(["build", draft])
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 4, out)
        self.assertEqual(lines[0], f"throughmap {DOT} Sample Essay (6 paragraphs, 3 threads)")
        self.assertEqual(lines[3], "open: " + beside(draft, "index.html"))
        self.assertTrue(os.path.isfile(beside(draft, "v1.json")))
        self.assertTrue(os.path.isfile(beside(draft, "index.html")))

    def test_each_run_saves_the_next_version(self):
        draft = write_draft(self.source, self.analysis)
        for _ in range(3):
            self.assertEqual(run_main(["build", draft])[0], 0)
        self.assertEqual(sorted(os.listdir(folder_of(draft))), [
            "draft.json", "index.html", "source.json", "v1.json", "v2.json", "v3.json"])

    def test_errors_print_the_report_exit_1_and_write_nothing(self):
        self.analysis["paragraphs"][1]["evidence"] = "nope"
        draft = write_draft(self.source, self.analysis)
        code, out, err = run_main_streams(["build", draft])
        self.assertEqual((code, err), (1, ""))
        self.assertTrue(out.startswith("ERROR $.paragraphs[1].evidence: "), out)
        self.assertEqual(out.splitlines()[-1], "1 error, 0 warnings")
        self.assertEqual(sorted(os.listdir(folder_of(draft))), ["draft.json", "source.json"])

    def test_a_draft_that_is_not_json_is_a_report_and_exit_1(self):
        draft = write_draft(self.source, self.analysis)
        Path(draft).write_text("{not json", "utf-8")
        code, out, err = run_main_streams(["build", draft])
        self.assertEqual((code, err), (1, ""))
        self.assertTrue(out.startswith("ERROR $: "), out)
        self.assertEqual(sorted(os.listdir(folder_of(draft))), ["draft.json", "source.json"])

    def test_warnings_alone_still_build(self):
        self.analysis["paragraphs"][0]["label"] = "x" * 29
        code, out = run_main(["build", write_draft(self.source, self.analysis)])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("throughmap "), out)

    def test_a_missing_draft_is_a_usage_error(self):
        code, out, err = run_main_streams(["build", os.path.join(tmp_dir(), "draft.json")])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error:"), err)

    def test_a_missing_source_json_says_to_run_extract(self):
        folder = tmp_dir("lonely.throughmap")
        draft = os.path.join(folder, "draft.json")
        Path(draft).write_text(json.dumps(self.analysis), "utf-8")
        code, out, err = run_main_streams(["build", draft])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("extract", err)
        self.assertEqual(os.listdir(folder), ["draft.json"])

    def test_usage_errors_exit_2(self):
        for argv in (["build"], ["build", "a.json", "b.json"], ["build", "--no-such-option"]):
            with self.subTest(argv):
                code, out, err = run_main_streams(argv)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith(("usage:", "error:")), err)

    def test_help_names_both_commands_and_the_draft(self):
        code, out = run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("build", out)
        self.assertIn("versions", out)
        self.assertIn("draft", run_main(["build", "--help"])[1].lower())


class VersionsCommandTests(unittest.TestCase):
    def test_it_lists_a_line_per_version(self):
        draft = write_draft(sample_source(), sample_analysis())
        for _ in range(2):
            run_main(["build", draft])
        code, out, err = run_main_streams(["versions", folder_of(draft)])
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 2, out)
        for number, line in enumerate(lines, 1):
            self.assertRegex(line, f"^v{number}  {STAMP.pattern}  6 paragraphs$")

    def test_a_version_without_details_and_the_order_of_the_numbers(self):
        folder = tmp_dir("x.throughmap")
        paragraphs = [{"kind": "paragraph"}] * 29
        for number in (10, 2):
            Path(folder, f"v{number}.json").write_text(json.dumps(
                {"generated_at": "2026-10-17T12:00:00Z", "paragraphs": paragraphs}), "utf-8")
        Path(folder, "v1.json").write_text("{}", "utf-8")
        code, out = run_main(["versions", folder])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["v1  -  0 paragraphs",
                                            "v2  2026-10-17T12:00:00Z  29 paragraphs",
                                            "v10  2026-10-17T12:00:00Z  29 paragraphs"])

    def test_one_paragraph_is_singular(self):
        folder = tmp_dir("x.throughmap")
        version = {"generated_at": "2026-10-17T12:00:00Z", "paragraphs": [{"kind": "paragraph"}]}
        Path(folder, "v1.json").write_text(json.dumps(version), "utf-8")
        self.assertEqual(run_main(["versions", folder]),
                         (0, "v1  2026-10-17T12:00:00Z  1 paragraph\n"))

    def test_a_folder_without_versions_says_so(self):
        self.assertEqual(run_main(["versions", tmp_dir("x.throughmap")]), (0, "no versions yet\n"))

    def test_a_folder_that_does_not_exist_is_a_usage_error(self):
        code, out, err = run_main_streams(["versions", os.path.join(tmp_dir(), "nothing")])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error:"), err)
        self.assertIn("is not a folder", err)

    def test_usage_errors_exit_2(self):
        for argv in (["versions"], ["versions", "a", "b"]):
            with self.subTest(argv):
                code, out, err = run_main_streams(argv)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith(("usage:", "error:")), err)


class CompareBuildTests(unittest.TestCase):
    def test_a_first_build_has_no_comparison(self):
        result = build(write_draft(*revision()[0]), STUB_TEMPLATE_PATH)
        self.assertNotIn("compare", json.loads(read_text(result["json_path"])))
        self.assertEqual(len(result["summary"].splitlines()), 4)

    def test_the_second_build_compares_with_the_first(self):
        result = two_builds(*revision())
        data = json.loads(read_text(result["json_path"]))
        first = json.loads(read_text(beside(result["json_path"], "v1.json")))
        self.assertEqual(set(data["compare"]), {
            "against", "before", "versions", "pairs", "splits", "merges", "added", "removed",
            "marks", "lanes", "quiet_closed", "quiet_opened", "gaps_closed"})
        self.assertEqual((data["compare"]["against"], data["compare"]["before"]), (1, first))
        self.assertEqual([v["version"] for v in data["compare"]["versions"]], [1, 2])
        self.assertEqual(data["compare"]["versions"][1]["generated_at"], data["generated_at"])

    def test_the_summary_says_what_changed_before_the_open_line(self):
        lines = two_builds(*revision())["summary"].splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[3], REVISION_CHANGES)
        self.assertTrue(lines[4].startswith("open: "))

    def test_a_third_build_compares_with_the_second_and_holds_no_nested_copy(self):
        draft = beside(two_builds(*revision())["json_path"], "draft.json")
        third = build(draft, STUB_TEMPLATE_PATH)
        data = json.loads(read_text(third["json_path"]))
        self.assertEqual(data["compare"]["against"], 2)
        self.assertNotIn("compare", data["compare"]["before"])
        self.assertIn("changes from v2: none", third["summary"].splitlines())

    def test_compare_with_names_an_earlier_version(self):
        draft = beside(two_builds(*revision())["json_path"], "draft.json")
        self.assertIn(REVISION_CHANGES, build(draft, STUB_TEMPLATE_PATH, compare_with=1)["summary"])

    def test_a_version_that_is_not_saved_is_an_error_and_nothing_is_written(self):
        folder = os.path.dirname(two_builds(*revision())["json_path"])
        files = sorted(os.listdir(folder))
        with self.assertRaisesRegex(CompareError, r"^no saved version v5 in .*; the saved versions are v1, v2$"):
            build(os.path.join(folder, "draft.json"), STUB_TEMPLATE_PATH, compare_with=5)
        self.assertEqual(sorted(os.listdir(folder)), files)
        with self.assertRaisesRegex(CompareError, "it holds no saved version yet$"):
            build(write_draft(*revision()[0]), STUB_TEMPLATE_PATH, compare_with=1)

    def test_an_unreadable_latest_version_builds_without_a_comparison(self):     # Review Focus 5
        draft = write_draft(*revision()[0])
        Path(build(draft, STUB_TEMPLATE_PATH)["json_path"]).write_text("{not json", "utf-8")
        result = build(draft, STUB_TEMPLATE_PATH)
        self.assertNotIn("compare", json.loads(read_text(result["json_path"])))
        self.assertEqual(result["summary"].splitlines()[3],
                         "changes from v1: not compared (v1.json cannot be read: it is not valid JSON)")

    def test_compare_names_a_usable_version_while_the_latest_is_not(self):
        # The Troubleshooting row for "not compared" sends the agent here: the latest saved version
        # cannot be read, and --compare names an earlier one that can.
        draft = beside(two_builds(*revision())["json_path"], "draft.json")
        Path(beside(draft, "v2.json")).write_text("{not json", "utf-8")
        code, out, err = run_main_streams(["build", draft, "--compare", "v1"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn(REVISION_CHANGES, out.splitlines())                      # "changes from v1: ..."
        data = json.loads(read_text(beside(draft, "v3.json")))
        self.assertEqual((data["compare"]["against"], data["compare"]["before"]["version"]), (1, 1))
        self.assertEqual(read_text(beside(draft, "v2.json")), "{not json")      # left as it was

    def test_an_unreadable_named_version_is_an_error(self):                       # Review Focus 5
        draft = write_draft(*revision()[0])
        first = build(draft, STUB_TEMPLATE_PATH)
        page = read_text(first["html_path"])
        Path(first["json_path"]).write_text("{not json", "utf-8")
        with self.assertRaisesRegex(CompareError, r"^v1\.json cannot be read: it is not valid JSON$"):
            build(draft, STUB_TEMPLATE_PATH, compare_with=1)
        self.assertFalse(os.path.exists(beside(draft, "v2.json")))
        self.assertEqual(read_text(first["html_path"]), page)

    def test_unrelated_versions_say_added_and_removed(self):                      # Review Focus 4
        first = version_of([para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)], {"q1": [1]})
        second = version_of([para(20, 21, 22), para(23, 24, 25), para(26, 27, 28)], {"q1": [1]})
        self.assertEqual(two_builds(first, second)["summary"].splitlines()[3],
                         f"changes from v1: 3 added (P1, P2, P3) {DOT} 3 removed (v1 P1, v1 P2, v1 P3)")

    def test_a_compare_left_in_the_draft_is_dropped(self):
        source, analysis = revision()[0]
        analysis["compare"] = {"against": 9}
        result = build(write_draft(source, analysis), STUB_TEMPLATE_PATH)
        self.assertNotIn("compare", json.loads(read_text(result["json_path"])))

    def test_earlier_versions_are_not_changed(self):
        first, second = revision()
        draft = write_draft(*first)
        saved = Path(build(draft, STUB_TEMPLATE_PATH)["json_path"]).read_bytes()
        rewrite_draft(draft, *second)
        build(draft, STUB_TEMPLATE_PATH)
        self.assertEqual(Path(beside(draft, "v1.json")).read_bytes(), saved)

    def test_the_earlier_computed_fields_are_worked_out_again(self):
        # A saved version with a stale or hand-edited computed cannot skew the comparison.
        first, second = revision()
        draft = write_draft(*first)
        saved = Path(build(draft, STUB_TEMPLATE_PATH)["json_path"])
        data = json.loads(read_text(saved))
        data["computed"] = {"runs": {}, "observations": []}
        saved.write_text(json.dumps(data), "utf-8")
        rewrite_draft(draft, *second)
        compare = json.loads(read_text(build(draft, STUB_TEMPLATE_PATH)["json_path"]))["compare"]
        self.assertEqual(compare["before"]["computed"], built_version(first[1], 1)["computed"])
        self.assertEqual(len(compare["quiet_closed"]), 1)


class CompareCommandTests(unittest.TestCase):
    def setUp(self):
        self.draft = beside(two_builds(*revision())["json_path"], "draft.json")

    def test_compare_takes_v_k_or_k(self):
        for value in ("v1", "1"):
            code, out = run_main(["build", self.draft, "--compare", value])
            self.assertEqual(code, 0)
            self.assertIn(REVISION_CHANGES, out.splitlines())

    def test_a_malformed_compare_value_is_a_usage_error(self):
        code, out, err = run_main_streams(["build", self.draft, "--compare", "x"])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("usage:"), err)

    def test_a_compare_that_names_no_saved_version_exits_1(self):
        code, out, err = run_main_streams(["build", self.draft, "--compare", "v9"])
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: no saved version v9"), err)

    def test_help_names_the_compare_option(self):
        self.assertIn("--compare", run_main(["build", "--help"])[1])

    def test_a_capital_v_is_taken_too(self):
        code, out = run_main(["build", self.draft, "--compare", "V1"])
        self.assertEqual(code, 0)
        self.assertIn(REVISION_CHANGES, out.splitlines())

    def test_a_value_that_is_no_version_number_is_a_usage_error_and_writes_nothing(self):
        files = sorted(os.listdir(folder_of(self.draft)))
        for value in ("", "v", "0", "v0", "01", "v01", "1.5", "-1", "v 1", " 1", "v1234567890"):
            with self.subTest(value=value):
                code, out, err = run_main_streams(["build", self.draft, "--compare", value])
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("usage:"), err)
        self.assertEqual(sorted(os.listdir(folder_of(self.draft))), files)


class BuildScriptTests(unittest.TestCase):
    """Run the real script on pipes: the summary holds non-ASCII text on a cp949 console."""

    SCRIPT = SCRIPTS_DIR / "throughmap.py"

    def run_script(self, *args):
        env = {key: value for key, value in os.environ.items()
               if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        return subprocess.run([sys.executable, str(self.SCRIPT), *args], capture_output=True,
                              env=env, timeout=120, stdin=subprocess.DEVNULL)

    def test_the_summary_is_utf8(self):
        analysis = sample_analysis()
        analysis["gaps"][0]["note"] = f"P3 {EN_DASH} 한글 노트"
        draft = write_draft(sample_source(), analysis)
        done = self.run_script("build", draft)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.decode("utf-8").splitlines()
        self.assertEqual(lines[0], f"throughmap {DOT} Sample Essay (6 paragraphs, 3 threads)")
        self.assertEqual(lines[2], f"gaps: {ONE} P3 {EN_DASH} 한글 노트")
        self.assertEqual(done.stderr, b"")

    def test_versions_prints_on_a_pipe(self):
        draft = write_draft(sample_source(), sample_analysis())
        self.assertEqual(self.run_script("build", draft).returncode, 0)
        done = self.run_script("versions", folder_of(draft))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout.decode("utf-8"), f"^v1  {STAMP.pattern}  6 paragraphs\r?\n$")


if __name__ == "__main__":
    unittest.main()
