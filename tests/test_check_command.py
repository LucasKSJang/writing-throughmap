"""Tests for reading the files, the check command and whole drafts through the checker."""

import contextlib
import copy
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests import SCRIPTS_DIR
from tests.fixtures import (
    LONG1, LONG2, LONG3, LONG4, STYLES_EN, TABLE, B, P, make_docx, run_main, run_main_streams,
    sample_analysis, sample_source, tmp_dir, write_draft,
)
from tm_check import check, check_files, format_report, read_json
from tm_source import assemble_source

BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
EM_DASH = "\N{EM DASH}"
LEFT_QUOTE, RIGHT_QUOTE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"


@contextlib.contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CheckFilesTests(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.dirname(write_draft(sample_source(), sample_analysis()))
        self.draft = os.path.join(self.folder, "draft.json")
        self.source = os.path.join(self.folder, "source.json")

    def test_it_reads_both_files(self):
        result = check_files(self.draft, self.source)
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_invalid_json_in_the_draft_is_a_check_error(self):
        Path(self.draft).write_text('{"schema": "throughmap/1",', "utf-8")
        result = check_files(self.draft, self.source)
        self.assertEqual([e["path"] for e in result["errors"]], ["$"])
        self.assertIn("not valid JSON", result["errors"][0]["message"])
        self.assertNotIn("\n", result["errors"][0]["message"])

    def test_a_draft_that_is_not_utf8_is_a_check_error(self):
        Path(self.draft).write_bytes('{"thesis": "한글"}'.encode("cp949"))
        result = check_files(self.draft, self.source)
        self.assertEqual([e["path"] for e in result["errors"]], ["$"])
        self.assertIn("UTF-8", result["errors"][0]["message"])

    def test_a_draft_that_starts_with_a_byte_order_mark_is_read(self):
        draft = Path(self.draft)
        draft.write_bytes(BOM.encode("utf-8") + draft.read_bytes())
        result = check_files(self.draft, self.source)
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_read_json_takes_utf8_with_or_without_a_byte_order_mark(self):
        path = os.path.join(self.folder, "plain.json")
        for prefix in ("", BOM):
            with self.subTest(prefix=prefix):
                Path(path).write_bytes((prefix + '{"한글": 1}').encode("utf-8"))
                self.assertEqual(read_json(path), {"한글": 1})
        Path(path).write_text("{", "utf-8")
        with self.assertRaises(ValueError):
            read_json(path)
        with self.assertRaises(OSError):
            read_json(os.path.join(self.folder, "nothing.json"))

    def test_a_missing_source_says_to_run_extract(self):
        with self.assertRaisesRegex(ValueError, "extract"):
            check_files(self.draft, os.path.join(self.folder, "nothing.json"))

    def test_a_missing_draft_is_a_value_error_that_names_it(self):
        with self.assertRaisesRegex(ValueError, "gone"):
            check_files(os.path.join(self.folder, "gone", "draft.json"), self.source)

    def test_a_source_that_is_not_a_source_file_is_a_value_error(self):
        for content in ("[1, 2", "[1, 2]", "{}", '{"paragraphs": 3}'):
            with self.subTest(content=content):
                Path(self.source).write_text(content, "utf-8")
                with self.assertRaisesRegex(ValueError, "source.json"):
                    check_files(self.draft, self.source)


class CheckCommandTests(unittest.TestCase):
    def setUp(self):
        self.src, self.a = sample_source(), sample_analysis()

    def test_a_clean_draft_prints_ok_and_exits_0(self):
        code, out = run_main(["check", write_draft(self.src, self.a)])
        self.assertEqual((code, out), (0, "OK\n"))

    def test_errors_exit_1_and_are_listed_with_their_paths(self):
        self.a["paragraphs"][1]["evidence"] = "nope"
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "made up"
        code, out, err = run_main_streams(["check", write_draft(self.src, self.a)])
        self.assertEqual((code, err), (1, ""))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("ERROR $.paragraphs[0].lanes.q1.quote: "), lines)
        self.assertTrue(lines[1].startswith("ERROR $.paragraphs[1].evidence: "), lines)
        self.assertEqual(lines[-1], "2 errors, 0 warnings")

    def test_warnings_alone_exit_0(self):
        self.a["paragraphs"][0]["label"] = "x" * 29
        code, out = run_main(["check", write_draft(self.src, self.a)])
        self.assertEqual(code, 0)
        self.assertTrue(out.splitlines()[0].startswith("WARN $.paragraphs[0].label: "), out)
        self.assertEqual(out.splitlines()[-1], "0 errors, 1 warning")

    def test_source_json_is_read_from_the_drafts_folder(self):
        draft = write_draft(self.src, self.a)
        other = write_draft(self.src, self.a)
        longer = copy.deepcopy(self.src)
        longer["paragraphs"][0]["text"] += " More."
        Path(os.path.dirname(other), "source.json").write_text(json.dumps(longer), "utf-8")
        self.assertEqual(run_main(["check", draft])[0], 0)
        code, out = run_main(["check", other])
        self.assertEqual(code, 1)
        self.assertIn("ERROR $.paragraphs[0].text", out)

    def test_a_relative_path_works(self):
        draft = write_draft(self.src, self.a)
        with working_directory(os.path.dirname(draft)):
            self.assertEqual(run_main(["check", "draft.json"]), (0, "OK\n"))

    def test_a_spaced_korean_path_works(self):
        draft = write_draft(self.src, self.a)
        folder = tmp_dir("B and F", "한글 폴더", "글 초안.throughmap")
        for name in ("source.json", "draft.json"):
            shutil.copy(os.path.join(os.path.dirname(draft), name), folder)
        self.assertEqual(run_main(["check", os.path.join(folder, "draft.json")]), (0, "OK\n"))

    def test_invalid_json_is_an_error_report_and_exit_1(self):
        draft = write_draft(self.src, self.a)
        Path(draft).write_text("{not json", "utf-8")
        code, out, err = run_main_streams(["check", draft])
        self.assertEqual((code, err), (1, ""))
        self.assertTrue(out.startswith("ERROR $: "), out)
        self.assertIn("not valid JSON", out)
        self.assertEqual(out.splitlines()[-1], "1 error, 0 warnings")

    def test_a_json_list_is_an_error_report(self):
        draft = write_draft(self.src, self.a)
        Path(draft).write_text("[]", "utf-8")
        code, out = run_main(["check", draft])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("ERROR $: "), out)

    def test_a_missing_draft_is_a_usage_error(self):
        code, out, err = run_main_streams(["check", os.path.join(tmp_dir(), "draft.json")])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error:"), err)

    def test_a_missing_source_json_says_to_run_extract(self):
        folder = tmp_dir("lonely.throughmap")
        draft = os.path.join(folder, "draft.json")
        Path(draft).write_text(json.dumps(self.a), "utf-8")
        code, out, err = run_main_streams(["check", draft])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("source.json", err)
        self.assertIn("extract", err)

    def test_usage_errors_exit_2(self):
        for argv in (["check"], ["check", "a.json", "b.json"], ["check", "--no-such-option"]):
            with self.subTest(argv):
                code, out, err = run_main_streams(argv)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith(("usage:", "error:")), err)

    def test_help_exits_0_and_names_the_arguments(self):
        for argv in (["check", "--help"], ["--help"]):
            with self.subTest(argv):
                code, out = run_main(argv)
                self.assertEqual(code, 0)
                self.assertIn("check", out)
        self.assertIn("draft", run_main(["check", "--help"])[1].lower())


def analysis_of(source):
    """Write the shortest valid analysis of any source: one section, one thread, all claims.

    A table is its caption and rows joined by a newline and a figure its caption, each item
    right after the paragraph it follows.
    """
    after = {}
    for table in source["tables"]:
        text = "\n".join(part for part in (table["caption"], table["text"]) if part)
        after.setdefault(table["after"], []).append(("table", table["id"], text))
    for figure in source["figures"]:
        after.setdefault(figure["after"], []).append(("figure", figure["id"], figure["caption"]))
    entries = list(after.get(None, []))
    for paragraph in source["paragraphs"]:
        entries.append(("paragraph", paragraph["id"], paragraph["text"]))
        entries.extend(after.get(paragraph["id"], []))
    ids = [paragraph["id"] for paragraph in source["paragraphs"]]
    first_words = " ".join(source["paragraphs"][0]["text"].split()[:3])
    return {
        "schema": "throughmap/1",
        "essay": {"title": source["essay"]["title"], "source": source["essay"]["source"],
                  "source_kind": source["essay"]["source_kind"], "language": "en",
                  "word_count": source["essay"]["word_count"]},
        "ui_language": "en", "thesis": "A thesis.",
        "questions": [{"id": "Q1", "text": "Why?"}],
        "lanes": [{"id": "q1", "kind": "question", "label": "Why", "question": "Q1"}],
        "sections": [{"id": "S1", "short": "All", "title": "", "inferred": True,
                      "first": ids[0], "last": ids[-1], "conclusion": "Everything.", "baton": "",
                      "answers": ["Q1"]}],
        "paragraphs": [
            {"id": item_id, "kind": kind, "section": "S1", "text": text, "role": "claim",
             "label": item_id, "evidence": text.split("\n")[0],
             "lanes": ({"q1": {"weight": "major", "quote": first_words}}
                       if item_id == ids[0] else {})}
            for kind, item_id, text in entries],
        "cases": [], "gaps": [],
    }


KOREAN_PARAGRAPHS = (
    "작은 빵집들은 골목마다 빵을 굽고 모든 반죽은 오븐에 들어가기 전에 오래 쉬어야 한다.",
    "반죽을 천천히 부풀리기 때문에 빵이 늦게 나오지만 제빵사는 그 시간을 거의 아깝게 여기지 않는다.",
    "그러나 빵을 빨리 구우면 아침에 더 많이 팔 수 있고 손님은 줄을 덜 서게 될 것이다.",
    "오래 쉰 반죽은 기포가 고르게 자라서 속이 부드럽고 이틀이 지나도 쉽게 마르지 않는다.",
    "결국 맛을 정하는 것은 굽는 속도보다 반죽이 오븐 앞에서 쉬는 시간의 길이이다.",
)


def korean_pair():
    """A Korean draft with three headed sections and a complete Korean analysis of it."""
    blocks = [B("heading", "도입", 1), B("para", KOREAN_PARAGRAPHS[0]),
              B("para", KOREAN_PARAGRAPHS[1]), B("heading", "본론", 1),
              B("para", KOREAN_PARAGRAPHS[2]), B("para", KOREAN_PARAGRAPHS[3]),
              B("heading", "결론", 1), B("para", KOREAN_PARAGRAPHS[4])]
    source = assemble_source(blocks, title_hint="느린 빵", source_name="느린 빵.md",
                             source_kind="md")
    analysis = analysis_of(source)
    analysis["essay"]["language"] = analysis["ui_language"] = "ko"
    analysis["thesis"] = "반죽이 오래 쉴수록 빵이 부드러워지므로 굽는 속도보다 휴지 시간이 중요하다."
    analysis["questions"] = [{"id": "Q1", "text": "빵을 빨리 구우면 무엇을 잃는가?"}]
    analysis["lanes"] = [{"id": "q1", "kind": "question", "label": "굽는 속도", "question": "Q1"}]
    spans = (("도입", "P1", "P2", "빨리 구우면 어떻게 되는가?"),
             ("본론", "P3", "P4", "부드러움은 어디서 오는가?"), ("결론", "P5", "P5", ""))
    analysis["sections"] = [
        {"id": f"S{n}", "short": title, "title": title, "inferred": False, "first": first,
         "last": last, "conclusion": f"{title}의 결론이다.", "baton": baton, "answers": ["Q1"]}
        for n, (title, first, last, baton) in enumerate(spans, 1)]
    evidence = ("모든 반죽은 오븐에 들어가기 전에 오래 쉬어야 한다",
                "제빵사는 그 시간을 거의 아깝게 여기지 않는다",
                "빵을 빨리 구우면 아침에 더 많이 팔 수 있고", "이틀이 지나도 쉽게 마르지 않는다",
                "반죽이 오븐 앞에서 쉬는 시간의 길이이다")
    section_ids = ("S1", "S1", "S2", "S2", "S3")
    for item, section_id, quote in zip(analysis["paragraphs"], section_ids, evidence):
        item["section"] = section_id
        item["evidence"] = quote
        item["label"] = f"{item['id']}의 요지"
        item["lanes"] = {"q1": {"weight": "major", "quote": quote}}
    analysis["gaps"] = [{
        "at": ["P3"], "note": "P3는 휴지 시간 이야기와 이어지지 않는다.",
        "direction": "P4의 '이틀이 지나도 쉽게 마르지 않는다'를 P3과 한 문장으로 잇기"}]
    return analysis, source


class KoreanDraftTests(unittest.TestCase):
    def test_a_complete_korean_analysis_passes(self):
        analysis, source = korean_pair()
        result = check(analysis, source)
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_a_korean_misquote_is_found(self):
        analysis, source = korean_pair()
        analysis["paragraphs"][1]["evidence"] = "제빵사는 그 시간을 거의 아깝게 여긴다"
        self.assertEqual([e["path"] for e in check(analysis, source)["errors"]],
                         ["$.paragraphs[1].evidence"])

    def test_the_report_names_the_korean_quote(self):
        analysis, source = korean_pair()
        analysis["paragraphs"][1]["evidence"] = "제빵사는 그 시간을 거의 아깝게 여긴다"
        report = format_report(check(analysis, source))
        self.assertIn("제빵사는 그 시간을 거의 아깝게 여긴다", report.splitlines()[0])

    def test_a_zero_width_space_in_a_korean_paragraph_is_not_a_difference(self):
        analysis, source = korean_pair()
        paragraph = source["paragraphs"][1]
        pasted = paragraph["text"].replace("시간을 거의", "시간을 \N{ZERO WIDTH SPACE}거의")
        self.assertNotEqual(pasted, paragraph["text"])
        paragraph["text"] = pasted              # the evidence "...그 시간을 거의..." spans it
        result = check(analysis, source)
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_labels_are_counted_in_characters(self):
        analysis, source = korean_pair()
        analysis["paragraphs"][0]["label"] = "가" * 28
        self.assertEqual(check(analysis, source)["warnings"], [])
        analysis["paragraphs"][0]["label"] = "가" * 29
        self.assertEqual([w["path"] for w in check(analysis, source)["warnings"]],
                         ["$.paragraphs[0].label"])


class RealExtractionTests(unittest.TestCase):
    """The checker accepts what extract writes: tables and figures as the readers produce them."""

    def extract(self, body):
        folder = tmp_dir("essays")
        path = os.path.join(folder, "essay.docx")
        make_docx(path, body, STYLES_EN)
        self.assertEqual(run_main(["extract", path])[0], 0)
        out = os.path.join(folder, "essay.throughmap")
        with open(os.path.join(out, "source.json"), encoding="utf-8") as handle:
            return out, json.load(handle)

    def test_an_analysis_with_a_table_and_a_figure_from_a_word_file(self):
        out, source = self.extract(
            P("Opening", "Heading1") + P(LONG1) + P(LONG2) + P("Table 1: Rest times by loaf.")
            + TABLE([["Loaf", "Rest"], ["Quick", "Hour"], ["Slow", "Night"]])
            + P(LONG3) + P("Figure 1: Fees by chain") + P(LONG4) + P(LONG1))
        self.assertEqual([(t["id"], t["after"]) for t in source["tables"]], [("T1", "P2")])
        self.assertEqual([(f["id"], f["after"]) for f in source["figures"]], [("F1", "P3")])
        analysis = analysis_of(source)
        self.assertEqual([item["id"] for item in analysis["paragraphs"]],
                         ["P1", "P2", "T1", "P3", "F1", "P4", "P5"])
        draft = os.path.join(out, "draft.json")
        with open(draft, "w", encoding="utf-8") as handle:
            json.dump(analysis, handle)
        self.assertEqual(run_main(["check", draft]), (0, "OK\n"))
        table = next(item for item in analysis["paragraphs"] if item["id"] == "T1")
        self.assertEqual(table["text"].splitlines()[1:], ["Loaf | Rest", "Quick | Hour",
                                                           "Slow | Night"])
        table["lanes"] = {"q1": {"weight": "minor", "quote": "Quick | Hour"}}
        self.assertEqual(check(analysis, source)["errors"], [])
        table["lanes"]["q1"]["quote"] = "Quick | Night"
        self.assertEqual([e["path"] for e in check(analysis, source)["errors"]],
                         ["$.paragraphs[2].lanes.q1.quote"])


class CheckScriptTests(unittest.TestCase):
    """Run the real script on pipes: the report holds non-ASCII text on a cp949 console."""

    SCRIPT = SCRIPTS_DIR / "throughmap.py"

    def test_the_report_is_utf8(self):
        src, a = sample_source(), sample_analysis()
        a["paragraphs"][1]["evidence"] = "한글 인용" + EM_DASH + LEFT_QUOTE + "x" + RIGHT_QUOTE
        draft = write_draft(src, a)
        env = {key: value for key, value in os.environ.items()
               if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        done = subprocess.run([sys.executable, str(self.SCRIPT), "check", draft],
                              capture_output=True, env=env, timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 1, done.stderr)
        out = done.stdout.decode("utf-8")
        self.assertIn("ERROR $.paragraphs[1].evidence", out)
        self.assertIn("한글 인용", out)
        self.assertEqual(done.stderr, b"")


if __name__ == "__main__":
    unittest.main()
