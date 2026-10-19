"""Tests for the rules of the checker (tm_check).

The files, the command line and whole drafts are tested in test_check_command.
"""

import copy
import json
import unittest

from tests.fixtures import (
    SAMPLE_P1, SAMPLE_TABLE_CAPTION, SAMPLE_TABLE_TEXT, STRAIGHT_VERSION_OF_P3_SENTENCE,
    THIRTEEN_WORDS_FROM_P5, run_main, sample_analysis, sample_source, table_item, with_lanes,
    with_paragraphs, with_questions, without_marks, write_draft,
)
from tm_check import LIMITS, ROLES, check, format_report
from tm_text import normalize, word_count

NBSP = "\N{NO-BREAK SPACE}"
EM_DASH = "\N{EM DASH}"
LEFT_QUOTE, RIGHT_QUOTE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
LEFT_SINGLE, RIGHT_SINGLE = "\N{LEFT SINGLE QUOTATION MARK}", "\N{RIGHT SINGLE QUOTATION MARK}"
ITEM_FIELDS = ("id", "kind", "section", "text", "role", "label", "evidence", "lanes")


def item_of(analysis, item_id):
    """The item of ``analysis`` with this id, itself and not a copy."""
    return next(item for item in analysis["paragraphs"] if item["id"] == item_id)


def figure_item(text="Figure 1: Fees by chain"):
    """An item for the figure F1 in section S1, quoting its whole caption."""
    return {"id": "F1", "kind": "figure", "section": "S1", "text": text, "role": "evidence",
            "label": "Fees by chain", "evidence": text, "lanes": {}}


def table_entry(after="P3"):
    return {"id": "T1", "caption": "Table 1: Fees", "after": after, "text": "a | b"}


def small_table_item():
    """An item for table_entry(), in section S1."""
    return {"id": "T1", "kind": "table", "section": "S1", "text": "Table 1: Fees\na | b",
            "role": "evidence", "label": "Fees table", "evidence": "Table 1: Fees", "lanes": {}}


def with_figure(source, analysis, index=2, after="P2"):
    """Add the figure F1 to ``source`` (after ``after``) and to ``analysis`` at ``index``."""
    source["figures"] = [{"id": "F1", "caption": "Figure 1: Fees by chain", "after": after}]
    analysis["paragraphs"].insert(index, figure_item())


class CheckBase(unittest.TestCase):
    def setUp(self):
        self.src, self.a = sample_source(), sample_analysis()

    def errs(self, a, src=None):
        return [e["path"] for e in check(a, src or self.src)["errors"]]

    def warns(self, a, src=None):
        return [w["path"] for w in check(a, src or self.src)["warnings"]]

    def messages(self, a, path, src=None):
        """The messages of the errors at ``path``."""
        return [e["message"] for e in check(a, src or self.src)["errors"] if e["path"] == path]


class CheckTests(CheckBase):
    def test_clean_analysis_passes(self):
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_misquote_is_error(self):
        self.a["paragraphs"][1]["evidence"] = "not in the text"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[1].evidence"])

    def test_lane_quote_must_be_verbatim(self):
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "made up"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1.quote"])

    def test_quote_normalization_accepts_style_differences(self):   # Review Focus 2
        self.a["paragraphs"][2]["evidence"] = STRAIGHT_VERSION_OF_P3_SENTENCE  # straight quotes, hyphen, plain space
        self.assertEqual(self.errs(self.a), [])

    def test_text_must_match_source(self):
        self.a["paragraphs"][2]["text"] += " extra"
        self.assertIn("$.paragraphs[2].text", self.errs(self.a))

    def test_counts(self):
        self.assertIn("$.lanes", self.errs(with_lanes(self.a, 7)))
        self.assertIn("$.questions", self.errs(with_questions(self.a, 0)))
        self.assertIn("$.paragraphs", self.errs(*with_paragraphs(41)))       # (analysis, source) pair
        self.assertIn("$.lanes[2]", self.errs(without_marks(self.a, "own")))

    def test_enums(self):
        self.a["paragraphs"][0]["role"] = "argument"
        self.a["paragraphs"][0]["lanes"]["q1"]["weight"] = "heavy"
        self.assertEqual(set(self.errs(self.a)), {"$.paragraphs[0].role", "$.paragraphs[0].lanes.q1.weight"})

    def test_sections_cover_in_order(self):
        self.a["sections"][1]["first"] = "P2"          # overlaps the first section
        self.assertIn("$.sections[1]", self.errs(self.a))

    def test_cases_and_references(self):
        self.a["cases"][0]["at"] = ["P2"]
        self.a["gaps"][0]["at"] = ["P99"]
        self.assertEqual(set(self.errs(self.a)), {"$.cases[0].at", "$.gaps[0].at"})

    def test_direction_rules(self):
        self.a["gaps"][0]["direction"] = "One. Two. Three."
        self.assertEqual(self.errs(self.a), ["$.gaps[0].direction"])
        self.a["gaps"][0]["direction"] = 'Write "' + " ".join(["new"] * 13) + '" in P3.'
        self.assertEqual(self.errs(self.a), ["$.gaps[0].direction"])
        self.a["gaps"][0]["direction"] = 'Reuse "' + THIRTEEN_WORDS_FROM_P5 + '" in P3.'
        self.assertEqual(self.errs(self.a), [])
        self.a["gaps"][0]["direction"] = "P16의 '밭을 돌아가며 맡을 수 있다'를 기준 3과 한 문장으로 잇기"
        self.assertEqual(self.errs(self.a), [])

    def test_length_warnings_are_not_errors(self):
        self.a["paragraphs"][0]["label"] = "x" * 29
        self.a["thesis"] = "t" * 161
        r = check(self.a, self.src)
        self.assertEqual(r["errors"], [])
        self.assertEqual({w["path"] for w in r["warnings"]}, {"$.paragraphs[0].label", "$.thesis"})

    def test_table_must_match_source(self):
        table_item(self.a)["text"] = "changed"
        self.assertIn("$.paragraphs[4].text", self.errs(self.a))     # T1 sits at index 4

    def test_cli_exit_codes(self):
        d = write_draft(self.src, self.a)
        self.assertEqual(run_main(["check", d])[0], 0)
        self.a["paragraphs"][1]["evidence"] = "nope"
        code, out = run_main(["check", write_draft(self.src, self.a)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR $.paragraphs[1].evidence", out)


class FixtureTests(unittest.TestCase):
    """The sample data is what the checker tests and the build tests rely on."""

    def test_sample_source_has_the_planned_shape(self):
        src = sample_source()
        self.assertEqual(src["essay"]["title"], "Sample Essay")
        self.assertEqual([p["id"] for p in src["paragraphs"]], [f"P{n}" for n in range(1, 7)])
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P2"},
                                           {"title": "Middle", "first": "P3", "last": "P4"},
                                           {"title": "End", "first": "P5", "last": "P6"}])
        self.assertEqual([(t["id"], t["after"]) for t in src["tables"]], [("T1", "P4")])
        self.assertEqual((src["figures"], src["excluded"]), ([], []))

    def test_p3_holds_the_typography_a_checker_must_tolerate(self):
        p3 = sample_source()["paragraphs"][2]["text"]
        for char in ("\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}",
                     "\N{EM DASH}", NBSP):
            self.assertIn(char, p3)
        self.assertNotIn(STRAIGHT_VERSION_OF_P3_SENTENCE, p3)
        self.assertEqual(normalize(p3), STRAIGHT_VERSION_OF_P3_SENTENCE)

    def test_thirteen_words_come_from_p5(self):
        p5 = sample_source()["paragraphs"][4]["text"]
        self.assertEqual(word_count(THIRTEEN_WORDS_FROM_P5), 13)
        self.assertIn(THIRTEEN_WORDS_FROM_P5, p5)

    def test_sample_analysis_has_the_planned_content(self):
        a = sample_analysis()
        self.assertEqual([item["id"] for item in a["paragraphs"]],
                         ["P1", "P2", "P3", "P4", "T1", "P5", "P6"])
        self.assertEqual(item_of(a, "P3")["role"], "claim")
        self.assertEqual(
            (a["paragraphs"][4]["id"], a["paragraphs"][4]["role"]), ("T1", "synthesis"))
        self.assertEqual([s["short"] for s in a["sections"]], ["Opening", "Middle", "End"])
        self.assertEqual([q["id"] for q in a["questions"]], ["Q1", "Q2"])
        self.assertEqual([(lane["id"], lane["kind"], lane["question"]) for lane in a["lanes"]],
                         [("q1", "question", "Q1"), ("q2", "question", "Q2"),
                          ("own", "concept", "Q2")])
        for lane in a["lanes"]:
            self.assertTrue(any(lane["id"] in item["lanes"] for item in a["paragraphs"]), lane)
        self.assertEqual(a["cases"][0]["name"], "Acme")
        self.assertEqual(a["cases"][0]["at"], ["P2", "P5"])
        self.assertEqual(len(a["gaps"]), 1)
        self.assertEqual((a["gaps"][0]["at"], a["gaps"][0]["direction"]),
                         (["P3"], "Connect P3 to the rest-time thread."))

    def test_the_table_item_is_the_caption_and_the_rows_joined_by_a_newline(self):
        self.assertEqual(table_item(sample_analysis())["text"],
                         SAMPLE_TABLE_CAPTION + "\n" + SAMPLE_TABLE_TEXT)

    def test_ui_language_is_a_parameter_and_every_call_is_new(self):
        self.assertEqual(sample_analysis()["ui_language"], "en")
        first = sample_analysis("ko")
        self.assertEqual(first["ui_language"], "ko")
        first["paragraphs"][0]["label"] = "changed"
        first["lanes"].clear()
        self.assertEqual(sample_analysis()["paragraphs"][0]["label"], "Every loaf rests long")
        self.assertEqual(len(sample_analysis()["lanes"]), 3)
        self.assertIsNot(sample_source(), sample_source())

    def test_the_variants_have_the_requested_size(self):
        a = sample_analysis()
        for count in (0, 1, 3, 6, 7):
            self.assertEqual(len(with_lanes(a, count)["lanes"]), count)
        for count in (0, 1, 2, 4, 5):
            self.assertEqual(len(with_questions(a, count)["questions"]), count)
        for count in (4, 5, 40, 41):
            analysis, source = with_paragraphs(count)
            self.assertEqual(len(analysis["paragraphs"]), count)
            self.assertEqual(len(source["paragraphs"]), count)
        self.assertEqual(len(a["lanes"]), 3)                       # the originals are untouched
        self.assertEqual(len(a["questions"]), 2)
        self.assertNotIn("own", [lane for item in without_marks(a, "own")["paragraphs"]
                                 for lane in item["lanes"]])
        self.assertIn("own", item_of(a, "P2")["lanes"])


class StructureTests(CheckBase):
    def test_the_analysis_must_be_an_object(self):
        for value in ([], "text", 3, None):
            with self.subTest(value=value):
                result = check(value, self.src)
                self.assertEqual([e["path"] for e in result["errors"]], ["$"])
                self.assertEqual(result["warnings"], [])

    def test_schema_must_be_throughmap_1(self):
        self.a["schema"] = "throughmap/2"
        self.assertEqual(self.errs(self.a), ["$.schema"])
        self.assertIn('found "throughmap/2"', self.messages(self.a, "$.schema")[0])
        self.a["schema"] = "throughmap/1 " + "x" * 500
        self.assertLess(len(self.messages(self.a, "$.schema")[0]), 100)
        del self.a["schema"]
        self.assertEqual(self.errs(self.a), ["$.schema"])

    def test_every_top_level_field_is_required(self):
        for key in ("schema", "essay", "ui_language", "thesis", "questions", "lanes", "sections",
                    "paragraphs", "cases", "gaps"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a[key]
                self.assertIn("$." + key, self.errs(a))

    def test_a_missing_field_says_it_is_missing(self):
        del self.a["thesis"]
        del self.a["paragraphs"][0]["evidence"]
        del self.a["paragraphs"][0]["lanes"]["q1"]["weight"]
        for path in ("$.thesis", "$.paragraphs[0].evidence", "$.paragraphs[0].lanes.q1.weight"):
            self.assertIn("missing", self.messages(self.a, path)[0])

    def test_a_value_of_the_wrong_type_says_which_type_it_found(self):
        for value, name in ((None, "null"), (True, "boolean"), (3, "number"), ([], "list"),
                            ({}, "object")):
            with self.subTest(name=name):
                self.a["thesis"] = value
                self.assertIn(name, self.messages(self.a, "$.thesis")[0])

    def test_a_missing_or_misshapen_list_is_the_only_error(self):
        # What refers to the list (a lane's question, an item's section) is not reported on top.
        for key in ("questions", "lanes", "sections", "paragraphs", "cases", "gaps"):
            for broken in ("missing", {}, "text", None):
                with self.subTest(key=key, broken=broken):
                    a = copy.deepcopy(self.a)
                    if broken == "missing":
                        del a[key]
                    else:
                        a[key] = broken
                    self.assertEqual(self.errs(a), ["$." + key])

    def test_an_empty_list_is_the_only_error_where_it_may_not_be_empty(self):
        for key in ("questions", "lanes", "sections"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                a[key] = []
                self.assertEqual(self.errs(a), ["$." + key])
        self.assertIn("list", self.messages({**self.a, "gaps": {}}, "$.gaps")[0])

    def test_cases_and_gaps_may_be_empty(self):
        self.a["cases"], self.a["gaps"] = [], []
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_ui_strings_is_optional_and_must_be_an_object(self):
        self.a["ui_strings"] = {"p": "Absatz"}
        self.assertEqual(self.errs(self.a), [])
        self.a["ui_strings"] = ["Absatz"]
        self.assertEqual(self.errs(self.a), ["$.ui_strings"])

    def test_essay_facts_are_not_compared_with_the_source(self):
        self.a["essay"].update(title="Another title", source="other.docx", source_kind="docx",
                               word_count=5)
        self.assertEqual(self.errs(self.a), [])

    def test_extra_keys_are_ignored(self):
        self.a.update(version=3, generated_at="2026-10-17T00:00:00Z", computed={})
        self.a["essay"]["subtitle"] = "x"
        self.assertEqual(self.errs(self.a), [])

    def test_essay_fields(self):
        for key in ("title", "source", "source_kind", "language", "word_count"):
            with self.subTest(missing=key):
                a = copy.deepcopy(self.a)
                del a["essay"][key]
                self.assertEqual(self.errs(a), ["$.essay." + key])
        for key in ("title", "source", "language"):
            with self.subTest(empty=key):
                a = copy.deepcopy(self.a)
                a["essay"][key] = ""
                self.assertEqual(self.errs(a), ["$.essay." + key])
        self.a["essay"] = []
        self.assertEqual(self.errs(self.a), ["$.essay"])

    def test_source_kind_is_one_of_six(self):
        for kind in ("docx", "md", "txt", "pdf", "paste", "gdoc"):
            with self.subTest(kind=kind):
                self.a["essay"]["source_kind"] = kind
                self.assertEqual(self.errs(self.a), [])
        self.a["essay"]["source_kind"] = "doc"
        self.assertEqual(self.errs(self.a), ["$.essay.source_kind"])

    def test_word_count_is_a_whole_number(self):
        for value in (0, 2035):
            self.a["essay"]["word_count"] = value
            self.assertEqual(self.errs(self.a), [])
        for value in ("122", True, -1, 1.5, None):
            with self.subTest(value=value):
                self.a["essay"]["word_count"] = value
                self.assertEqual(self.errs(self.a), ["$.essay.word_count"])

    def test_ui_language_and_thesis_are_text(self):
        for key in ("ui_language", "thesis"):
            for value in ("", "  ", None, 3):
                with self.subTest(key=key, value=value):
                    a = copy.deepcopy(self.a)
                    a[key] = value
                    self.assertEqual(self.errs(a), ["$." + key])

    def test_nothing_is_changed_by_checking(self):
        before = copy.deepcopy((self.a, self.src))
        self.a["paragraphs"][1]["evidence"] = "not in the text"
        before[0]["paragraphs"][1]["evidence"] = "not in the text"
        check(self.a, self.src)
        self.assertEqual((self.a, self.src), before)

    def test_a_source_read_from_json_is_as_good_as_the_assembled_one(self):
        plain = json.loads(json.dumps(self.src))
        r = check(self.a, plain)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))


class ItemTests(CheckBase):
    def test_the_item_fields_are_required(self):
        for key in ITEM_FIELDS:
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a["paragraphs"][0][key]
                self.assertIn(f"$.paragraphs[0].{key}", self.errs(a))

    def test_an_item_must_be_an_object(self):
        self.a["paragraphs"][3] = "P4"
        self.assertIn("$.paragraphs[3]", self.errs(self.a))

    def test_an_id_that_source_json_lacks_is_an_error(self):
        self.a["paragraphs"][3]["id"] = "P9"
        self.assertEqual(set(self.errs(self.a)), {"$.paragraphs[3].id", "$.paragraphs"})
        self.assertIn("P9", self.messages(self.a, "$.paragraphs[3].id")[0])

    def test_an_item_without_a_string_id_is_an_error(self):
        for value in (None, 4, ["P4"]):
            with self.subTest(value=value):
                a = copy.deepcopy(self.a)
                a["paragraphs"][3]["id"] = value
                self.assertIn("$.paragraphs[3].id", self.errs(a))

    def test_every_paragraph_of_the_source_must_be_listed(self):
        del self.a["paragraphs"][2]
        self.assertEqual(self.errs(self.a), ["$.paragraphs"])
        self.assertIn("P3", self.messages(self.a, "$.paragraphs")[0])

    def test_several_missing_paragraphs_are_one_error(self):
        self.a["paragraphs"] = [self.a["paragraphs"][0], self.a["paragraphs"][-1]]
        result = check(self.a, self.src)
        self.assertEqual([e["path"] for e in result["errors"]], ["$.paragraphs"])
        for item_id in ("P2", "P3", "P4", "P5"):
            self.assertIn(item_id, result["errors"][0]["message"])

    def test_a_long_list_of_missing_paragraphs_is_counted_not_listed(self):
        analysis, source = with_paragraphs(10)
        del analysis["paragraphs"][:8]
        message = self.messages(analysis, "$.paragraphs", source)[0]
        self.assertIn("P1, P2, P3, P4, P5, P6 and 2 more", message)

    def test_a_duplicate_item_is_an_error(self):
        self.a["paragraphs"].insert(2, copy.deepcopy(self.a["paragraphs"][1]))
        self.assertEqual(self.errs(self.a), ["$.paragraphs[2].id"])

    def test_a_duplicate_is_reported_once_wherever_it_stands(self):
        self.a["paragraphs"].append(copy.deepcopy(self.a["paragraphs"][0]))
        self.assertEqual(self.errs(self.a), ["$.paragraphs[7].id"])

    def test_paragraphs_must_follow_the_draft(self):
        paragraphs = self.a["paragraphs"]
        paragraphs[1], paragraphs[2] = paragraphs[2], paragraphs[1]
        self.assertEqual(self.errs(self.a), ["$.paragraphs[2].id"])

    def test_tables_and_figures_are_optional(self):
        del self.a["paragraphs"][4]
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_a_table_must_follow_the_paragraph_it_comes_after(self):
        self.a["paragraphs"].append(self.a["paragraphs"].pop(4))
        self.assertEqual(self.errs(self.a), ["$.paragraphs[6]"])
        self.assertIn("P4", self.messages(self.a, "$.paragraphs[6]")[0])

    def test_a_table_that_follows_no_paragraph_comes_first(self):
        self.a["paragraphs"].insert(0, self.a["paragraphs"].pop(4))
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0]"])
        self.src["tables"][0]["after"] = None
        self.assertEqual(self.errs(self.a), [])
        self.a["paragraphs"].append(self.a["paragraphs"].pop(0))
        self.assertEqual(self.errs(self.a), ["$.paragraphs[6]"])

    def test_a_table_the_source_lacks_is_an_error(self):
        table_item(self.a)["id"] = "T2"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].id"])

    def test_a_figure_is_checked_like_a_table(self):
        with_figure(self.src, self.a)
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))
        item_of(self.a, "F1")["text"] = "Figure 1: Fees by owner"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[2].text"])
        item_of(self.a, "F1")["text"] = "Figure 1: Fees by chain"
        self.a["paragraphs"].insert(4, self.a["paragraphs"].pop(2))        # after P3, not P2
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4]"])
        self.a["paragraphs"].insert(2, self.a["paragraphs"].pop(4))
        item_of(self.a, "F1")["id"] = "F2"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[2].id"])

    def test_a_figure_before_the_first_paragraph(self):
        with_figure(self.src, self.a, index=0, after=None)
        self.assertEqual(self.errs(self.a), [])

    def test_the_kind_must_be_known_and_agree_with_the_id(self):
        self.a["paragraphs"][0]["kind"] = "table"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].kind"])
        self.a["paragraphs"][0]["kind"] = "chart"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].kind"])
        self.a["paragraphs"][0]["kind"] = "paragraph"
        table_item(self.a)["kind"] = "paragraph"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].kind"])

    def test_the_section_must_exist(self):
        self.a["paragraphs"][0]["section"] = "S9"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].section"])
        message = self.messages(self.a, "$.paragraphs[0].section")[0]
        self.assertIn("unknown section", message)
        self.assertIn("S9", message)

    def test_a_paragraph_belongs_to_the_section_that_covers_it(self):
        self.a["paragraphs"][0]["section"] = "S2"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].section"])
        message = self.messages(self.a, "$.paragraphs[0].section")[0]
        self.assertIn("S1", message)

    def test_a_table_may_belong_to_either_neighbouring_section(self):
        table_item(self.a)["section"] = "S3"
        self.assertEqual(self.errs(self.a), [])

    def test_section_membership_is_not_judged_when_the_sections_are_wrong(self):
        self.a["sections"][1]["first"] = "P2"
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])

    def test_style_differences_in_text_are_accepted(self):
        self.a["paragraphs"][2]["text"] = STRAIGHT_VERSION_OF_P3_SENTENCE
        self.assertEqual(self.errs(self.a), [])
        self.a["paragraphs"][0]["text"] = "  " + SAMPLE_P1.replace(" ", "  ", 2) + "\n"
        self.assertEqual(self.errs(self.a), [])

    def test_a_changed_word_in_text_is_an_error_that_says_where(self):
        self.a["paragraphs"][0]["text"] = SAMPLE_P1.replace("every loaf", "each loaf")
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].text"])
        message = self.messages(self.a, "$.paragraphs[0].text")[0]
        self.assertIn("P1", message)
        self.assertIn("each loaf", message)
        self.assertIn("every loaf", message)
        self.assertIn("at character 50", message)
        self.assertIn('source.json has "...every street, and every loaf', message)

    def test_an_invisible_character_in_the_draft_does_not_break_a_quote(self):
        zero_width = "\N{ZERO WIDTH SPACE}"
        text = SAMPLE_P1.replace("long rest", "long " + zero_width + "rest")
        self.src["paragraphs"][0]["text"] = text
        self.a["paragraphs"][0]["text"] = text               # as the source has it, character in
        self.assertEqual(self.errs(self.a), [])              # the evidence and the q1 quote span it
        self.a["paragraphs"][0]["text"] = SAMPLE_P1          # or typed without the character
        self.assertEqual(self.errs(self.a), [])
        self.src["paragraphs"][0]["text"] = SAMPLE_P1        # and a quote may hold one that the
        self.a["paragraphs"][0]["evidence"] = (              # draft lacks
            "every loaf needs a long " + zero_width + "rest")
        self.assertEqual(self.errs(self.a), [])

    def test_a_character_that_does_not_show_is_spelled_out(self):
        private_use = chr(0xE000)               # not a format character, so it stays in the text
        self.src["paragraphs"][0]["text"] = SAMPLE_P1.replace("bakeries", "ba" + private_use + "keries")
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].text"])
        self.assertIn("ba\\" + "ue000keries", self.messages(self.a, "$.paragraphs[0].text")[0])

    def test_text_is_case_sensitive(self):
        self.a["paragraphs"][0]["text"] = SAMPLE_P1.replace("Small", "small")
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].text"])

    def test_text_cut_short_or_extended_is_an_error(self):
        self.a["paragraphs"][0]["text"] = SAMPLE_P1[:-20]
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].text"])
        self.assertIn(f"at character {len(SAMPLE_P1) - 19}",
                      self.messages(self.a, "$.paragraphs[0].text")[0])
        self.a["paragraphs"][0]["text"] = ""
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].text"])
        self.assertIn("differs from P1", self.messages(self.a, "$.paragraphs[0].text")[0])

    def test_quotes_are_checked_against_the_draft_not_against_the_text_field(self):
        self.a["paragraphs"][0]["text"] = "Something else entirely."
        self.a["paragraphs"][0]["evidence"] = "Something else"
        self.assertEqual(set(self.errs(self.a)),
                         {"$.paragraphs[0].text", "$.paragraphs[0].evidence"})

    def test_a_table_item_is_the_caption_and_the_rows_joined_by_a_newline(self):
        table_item(self.a)["text"] = SAMPLE_TABLE_TEXT
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].text"])
        table_item(self.a)["text"] = SAMPLE_TABLE_CAPTION
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].text"])
        table_item(self.a)["text"] = SAMPLE_TABLE_TEXT + "\n" + SAMPLE_TABLE_CAPTION
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].text"])

    def test_a_caption_only_table_is_its_caption(self):
        self.src["tables"][0]["text"] = ""
        table_item(self.a)["text"] = SAMPLE_TABLE_CAPTION
        table_item(self.a)["lanes"]["own"]["quote"] = "rise and crumb"
        self.assertEqual(self.errs(self.a), [])

    def test_a_table_without_a_caption_is_its_rows(self):
        self.src["tables"][0]["caption"] = ""
        table_item(self.a)["text"] = SAMPLE_TABLE_TEXT
        table_item(self.a)["evidence"] = "Quick | One hour | No"
        self.assertEqual(self.errs(self.a), [])

    def test_table_quotes_must_come_from_the_table_item(self):
        table_item(self.a)["evidence"] = "Acme runs one such bakery"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[4].evidence"])
        table_item(self.a)["evidence"] = "Quick | One hour | No"
        table_item(self.a)["lanes"]["own"]["quote"] = "Slow | Overnight | Yes"
        self.assertEqual(self.errs(self.a), [])


class QuoteTests(CheckBase):
    def test_a_quote_may_differ_in_whitespace(self):
        self.a["paragraphs"][0]["evidence"] = "every  loaf\nneeds a long" + NBSP + "rest"
        self.assertEqual(self.errs(self.a), [])

    def test_a_quote_may_differ_in_quotes_dashes_and_spaces(self):
        quote = 'rest a "curly" delay-yet bakers knead the dough only once'
        self.a["paragraphs"][2]["lanes"]["q1"]["quote"] = quote
        self.assertEqual(self.errs(self.a), [])
        curly = f"rest a {LEFT_QUOTE}curly{RIGHT_QUOTE} delay{EM_DASH}yet"
        self.a["paragraphs"][2]["lanes"]["q1"]["quote"] = curly
        self.assertEqual(self.errs(self.a), [])

    def test_quotes_are_case_sensitive(self):
        self.a["paragraphs"][0]["evidence"] = "Every loaf needs a long rest before the oven"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])
        self.a["paragraphs"][0]["evidence"] = "every loaf needs a long rest before the oven"
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "EVERY LOAF"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1.quote"])

    def test_a_quote_must_be_in_its_own_item(self):
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "keeps most of the dough"   # P2's words
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1.quote"])
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "every loaf"
        self.a["paragraphs"][0]["evidence"] = "Acme runs one such bakery"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])

    def test_a_quote_may_not_span_two_paragraphs(self):
        self.a["paragraphs"][0]["evidence"] = "before the oven. Acme runs"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])

    def test_the_message_names_the_paragraph_and_the_quote(self):
        self.a["paragraphs"][1]["evidence"] = "not in the text"
        message = self.messages(self.a, "$.paragraphs[1].evidence")[0]
        self.assertIn("P2", message)
        self.assertIn("not in the text", message)

    def test_a_long_quote_is_shortened_in_the_message(self):
        self.a["paragraphs"][1]["evidence"] = "word " * 100
        message = self.messages(self.a, "$.paragraphs[1].evidence")[0]
        self.assertLess(len(message), 200)

    def test_a_message_stays_on_one_line(self):
        self.a["paragraphs"][1]["evidence"] = "line one\nline  two\n\nline three"
        message = self.messages(self.a, "$.paragraphs[1].evidence")[0]
        self.assertIn('"line one line two line three"', message)

    def test_an_empty_or_missing_quote_is_one_error(self):
        for value in ("", "   ", NBSP):
            with self.subTest(value=value):
                self.a["paragraphs"][0]["evidence"] = value
                self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = value
                self.assertEqual(set(self.errs(self.a)),
                                 {"$.paragraphs[0].evidence", "$.paragraphs[0].lanes.q1.quote"})
        del self.a["paragraphs"][0]["evidence"]
        del self.a["paragraphs"][0]["lanes"]["q1"]["quote"]
        self.assertEqual(self.errs(self.a),
                         ["$.paragraphs[0].evidence", "$.paragraphs[0].lanes.q1.quote"])

    def test_a_quote_must_be_a_string(self):
        for value in (None, 7, ["every loaf"]):
            with self.subTest(value=value):
                self.a["paragraphs"][0]["evidence"] = value
                self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])

    def test_html_in_the_draft_is_just_text(self):                    # Review Focus 4
        text = "Use <b>bold</b> and </script> with care & never trust \"input\" or 'it'."
        self.src["paragraphs"][0]["text"] = self.a["paragraphs"][0]["text"] = text
        self.a["paragraphs"][0]["evidence"] = "</script> with care & never"
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "<b>bold</b>"
        self.assertEqual(self.errs(self.a), [])
        self.a["paragraphs"][0]["evidence"] = "&lt;b&gt;bold"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])

    def test_korean_text_is_checked_the_same_way(self):
        korean = "정원은 집과 집 사이에서 채소를 기르고 모든 텃밭은 물을 필요로 한다."
        self.src["paragraphs"][0]["text"] = korean
        self.a["paragraphs"][0]["text"] = korean
        self.a["paragraphs"][0]["evidence"] = "모든 텃밭은 물을 필요로 한다"
        self.a["paragraphs"][0]["lanes"]["q1"]["quote"] = "집 사이에서"
        self.assertEqual(self.errs(self.a), [])
        self.a["paragraphs"][0]["evidence"] = "모든 텃밭은 물을 필요로 하지 않는다"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].evidence"])


class EnumTests(CheckBase):
    def test_all_twelve_roles_are_accepted(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.a["paragraphs"][0]["role"] = role
                self.assertEqual(self.errs(self.a), [])

    def test_an_unknown_role_is_an_error_that_lists_the_roles(self):
        for value in ("argument", "Claim", "CLAIM", " claim", "", None, 3):
            with self.subTest(value=value):
                self.a["paragraphs"][0]["role"] = value
                self.assertEqual(self.errs(self.a), ["$.paragraphs[0].role"])
        self.a["paragraphs"][0]["role"] = "argument"
        message = self.messages(self.a, "$.paragraphs[0].role")[0]
        for role in ROLES:
            self.assertIn(role, message)
        self.assertIn("argument", message)

    def test_weights(self):
        for weight in ("major", "minor"):
            self.a["paragraphs"][0]["lanes"]["q1"]["weight"] = weight
            self.assertEqual(self.errs(self.a), [])
        for weight in ("heavy", "Major", "", None, 1):
            with self.subTest(weight=weight):
                self.a["paragraphs"][0]["lanes"]["q1"]["weight"] = weight
                self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1.weight"])
        del self.a["paragraphs"][0]["lanes"]["q1"]["weight"]
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1.weight"])

    def test_lane_kinds(self):
        for kind in ("question", "concept"):
            self.a["lanes"][2]["kind"] = kind
            self.assertEqual(self.errs(self.a), [])
        for kind in ("thread", "Question", "", None):
            with self.subTest(kind=kind):
                self.a["lanes"][2]["kind"] = kind
                self.assertEqual(self.errs(self.a), ["$.lanes[2].kind"])

    def test_item_kinds(self):
        self.a["paragraphs"][0]["kind"] = None
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].kind"])


class CountTests(CheckBase):
    def test_one_to_six_lanes(self):
        for count in (1, 3, 6):
            with self.subTest(count=count):
                r = check(with_lanes(self.a, count), self.src)
                self.assertEqual((r["errors"], r["warnings"]), ([], []))
        self.assertEqual(self.errs(with_lanes(self.a, 7)), ["$.lanes"])
        self.assertEqual(self.errs(with_lanes(self.a, 0)), ["$.lanes"])
        self.assertIn("7", self.messages(with_lanes(self.a, 7), "$.lanes")[0])

    def test_one_to_four_questions(self):
        for count in (1, 4):
            with self.subTest(count=count):
                a = with_questions(self.a, count)
                if count == 1:                       # the lanes and sections still name Q2
                    a["lanes"][1]["question"] = a["lanes"][2]["question"] = "Q1"
                    a["sections"][1]["answers"] = a["sections"][2]["answers"] = ["Q1"]
                self.assertEqual(self.errs(a), [])
        self.assertEqual(self.errs(with_questions(self.a, 5)), ["$.questions"])
        self.assertEqual(self.errs(with_questions(self.a, 0)), ["$.questions"])
        self.assertIn("5", self.messages(with_questions(self.a, 5), "$.questions")[0])

    def test_forty_paragraphs_are_enough_and_forty_one_are_not(self):
        analysis, source = with_paragraphs(40)
        r = check(analysis, source)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))
        r = check(*with_paragraphs(41))
        self.assertEqual([e["path"] for e in r["errors"]], ["$.paragraphs"])
        self.assertEqual(r["warnings"], [])
        self.assertIn("41", r["errors"][0]["message"])
        self.assertIn("40", r["errors"][0]["message"])

    def test_the_remedy_for_over_forty_fits_the_draft(self):
        # With section headings, one section can be mapped. Without them, extract --section
        # exits 1, so check gives extract's own advice instead.
        analysis, source = with_paragraphs(41)
        (error,) = check(analysis, source)["errors"]
        self.assertTrue(error["message"].endswith("map one section, with extract --section"),
                        error["message"])
        source["sections"] = []
        analysis["sections"][0].update(title="", inferred=True)
        (error,) = check(analysis, source)["errors"]
        self.assertEqual(error["path"], "$.paragraphs")
        self.assertTrue(error["message"].endswith(
            "and the draft has no section headings: add headings or split the draft"),
            error["message"])
        self.assertNotIn("--section", error["message"])

    def test_tables_and_figures_do_not_count_toward_forty(self):
        analysis, source = with_paragraphs(40)
        source["tables"] = [table_entry()]
        source["figures"] = [{"id": "F1", "caption": "Figure 1: Fees", "after": "P3"}]
        analysis["paragraphs"][3:3] = [small_table_item(), figure_item("Figure 1: Fees")]
        self.assertEqual(len(analysis["paragraphs"]), 42)
        r = check(analysis, source)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_fewer_than_five_paragraphs_is_a_warning(self):
        r = check(*with_paragraphs(4))
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["path"] for w in r["warnings"]], ["$.paragraphs"])
        self.assertIn("4", r["warnings"][0]["message"])
        r = check(*with_paragraphs(5))
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_a_table_does_not_make_up_the_five_paragraphs(self):
        analysis, source = with_paragraphs(4)
        source["tables"] = [table_entry()]
        analysis["paragraphs"].insert(3, small_table_item())
        r = check(analysis, source)
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["path"] for w in r["warnings"]], ["$.paragraphs"])

    def test_no_question_lane_is_a_warning(self):
        self.a["lanes"][0]["kind"] = self.a["lanes"][1]["kind"] = "concept"
        r = check(self.a, self.src)
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["path"] for w in r["warnings"]], ["$.lanes"])

    def test_no_lanes_at_all_is_an_error_and_not_also_a_warning(self):
        r = check(with_lanes(self.a, 0), self.src)
        self.assertEqual(r["warnings"], [])


class LaneTests(CheckBase):
    def test_a_lane_needs_an_id_a_kind_and_a_label(self):
        for key in ("id", "kind", "label"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a["lanes"][2][key]
                self.assertIn(f"$.lanes[2].{key}", self.errs(a))
        self.a["lanes"][2]["label"] = " "
        self.assertEqual(self.errs(self.a), ["$.lanes[2].label"])

    def test_lane_ids_are_unique(self):
        self.a["lanes"].append(copy.deepcopy(self.a["lanes"][0]))
        self.assertEqual(self.errs(self.a), ["$.lanes[3].id"])

    def test_a_message_about_an_id_with_a_line_break_stays_on_one_line(self):
        for _ in range(2):
            self.a["lanes"].append({**self.a["lanes"][0], "id": "two\nlines"})
        errors = check(self.a, self.src)["errors"]
        self.assertEqual([e["path"] for e in errors], ["$.lanes[3]", "$.lanes[4].id"])
        for error in errors:
            self.assertIn('"two lines"', error["message"])

    def test_a_question_lane_needs_a_question(self):
        del self.a["lanes"][0]["question"]
        self.assertEqual(self.errs(self.a), ["$.lanes[0].question"])
        for value in (None, ""):
            self.a["lanes"][0]["question"] = value
            self.assertEqual(self.errs(self.a), ["$.lanes[0].question"])

    def test_a_concept_lane_may_do_without_a_question(self):
        for change in (lambda lane: lane.pop("question"), lambda lane: lane.update(question=None),
                       lambda lane: lane.update(question="")):
            a = copy.deepcopy(self.a)
            change(a["lanes"][2])
            self.assertEqual(self.errs(a), [])

    def test_a_lane_question_must_exist(self):
        self.a["lanes"][0]["question"] = "Q9"
        self.assertEqual(self.errs(self.a), ["$.lanes[0].question"])
        self.assertIn("Q9", self.messages(self.a, "$.lanes[0].question")[0])
        self.a["lanes"][0]["question"] = "Q1"
        self.a["lanes"][2]["question"] = "q2"                 # a lane id, and not a question id
        self.assertEqual(self.errs(self.a), ["$.lanes[2].question"])
        self.a["lanes"][2]["question"] = 2
        self.assertEqual(self.errs(self.a), ["$.lanes[2].question"])

    def test_sub_is_optional_text(self):
        del self.a["lanes"][0]["sub"]
        self.assertEqual(self.errs(self.a), [])
        for value in (None, ""):
            self.a["lanes"][0]["sub"] = value
            self.assertEqual(self.errs(self.a), [])
        self.a["lanes"][0]["sub"] = 4
        self.assertEqual(self.errs(self.a), ["$.lanes[0].sub"])

    def test_a_lane_without_marks_is_an_error(self):
        self.assertEqual(self.errs(without_marks(self.a, "q2")), ["$.lanes[1]"])
        self.assertIn("q2", self.messages(without_marks(self.a, "q2"), "$.lanes[1]")[0])

    def test_one_mark_is_enough_whatever_its_weight(self):
        a = without_marks(self.a, "own")
        a["paragraphs"][3]["lanes"]["own"] = {"weight": "minor", "quote": "how long each loaf rests"}
        self.assertEqual(self.errs(a), [])

    def test_a_malformed_mark_still_counts_as_a_mark(self):
        a = without_marks(self.a, "own")
        a["paragraphs"][3]["lanes"]["own"] = "yes"
        self.assertEqual(self.errs(a), ["$.paragraphs[3].lanes.own"])

    def test_a_mark_names_a_lane_that_exists(self):
        self.a["paragraphs"][0]["lanes"]["zz"] = {"weight": "minor", "quote": "every loaf"}
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.zz"])
        self.assertIn("zz", self.messages(self.a, "$.paragraphs[0].lanes.zz")[0])

    def test_a_mark_is_an_object_and_lanes_is_an_object(self):
        self.a["paragraphs"][0]["lanes"]["q1"] = "major"
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes.q1"])
        self.a["paragraphs"][0]["lanes"] = []
        self.assertEqual(self.errs(self.a), ["$.paragraphs[0].lanes"])

    def test_a_lane_id_with_odd_characters_still_gives_an_exact_path(self):
        a = copy.deepcopy(self.a)
        a["lanes"][2]["id"] = "own thread"
        for item in a["paragraphs"]:
            if "own" in item["lanes"]:
                item["lanes"]["own thread"] = item["lanes"].pop("own")
        self.assertEqual(self.errs(a), [])
        a["paragraphs"][3]["lanes"]["own thread"]["weight"] = "heavy"
        self.assertEqual(self.errs(a), ['$.paragraphs[3].lanes["own thread"].weight'])
        a["lanes"][2]["id"] = "own-thread"
        for item in a["paragraphs"]:
            if "own thread" in item["lanes"]:
                item["lanes"]["own-thread"] = item["lanes"].pop("own thread")
        self.assertEqual(self.errs(a), ["$.paragraphs[3].lanes.own-thread.weight"])

    def test_questions_need_unique_ids(self):
        self.a["questions"][1]["id"] = "Q1"
        self.assertIn("$.questions[1].id", self.errs(self.a))

    def test_an_entry_without_an_id_does_not_set_off_errors_where_it_is_named(self):
        for key, index, path in (("questions", 1, "$.questions[1].id"),
                                 ("lanes", 2, "$.lanes[2].id"),
                                 ("sections", 0, "$.sections[0].id")):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a[key][index]["id"]
                self.assertEqual(self.errs(a), [path])

    def test_questions_need_text_and_an_id(self):
        self.a["questions"][0]["text"] = ""
        self.assertEqual(self.errs(self.a), ["$.questions[0].text"])
        self.a["questions"][0]["text"] = "Does a long rest slow the bakery down?"
        del self.a["questions"][0]["id"]
        self.assertIn("$.questions[0].id", self.errs(self.a))
        self.a["questions"][0] = "Q1"
        self.assertIn("$.questions[0]", self.errs(self.a))


class SectionTests(CheckBase):
    def test_a_section_needs_its_fields(self):
        for key in ("id", "short", "title", "inferred", "first", "last", "conclusion", "answers"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a["sections"][0][key]
                self.assertIn(f"$.sections[0].{key}", self.errs(a))

    def test_the_untitled_lead_section_may_have_an_empty_title(self):
        self.assertEqual(self.a["sections"][0]["title"], "")
        self.assertEqual(self.errs(self.a), [])
        self.a["sections"][0]["title"] = None
        self.assertEqual(self.errs(self.a), ["$.sections[0].title"])

    def test_short_and_conclusion_may_not_be_empty(self):
        self.a["sections"][1]["short"] = ""
        self.a["sections"][1]["conclusion"] = " "
        self.assertEqual(set(self.errs(self.a)),
                         {"$.sections[1].short", "$.sections[1].conclusion"})

    def test_inferred_is_true_or_false(self):
        for value in ("false", 0, None, "yes"):
            with self.subTest(value=value):
                self.a["sections"][0]["inferred"] = value
                self.assertEqual(self.errs(self.a), ["$.sections[0].inferred"])
        self.a["sections"][0]["inferred"] = True
        self.assertEqual(self.errs(self.a), [])

    def test_sections_without_ids_do_not_set_off_errors_in_the_items(self):
        for section in self.a["sections"]:
            del section["id"]
        self.assertEqual(self.errs(self.a),
                         ["$.sections[0].id", "$.sections[1].id", "$.sections[2].id"])

    def test_section_ids_are_unique(self):
        self.a["sections"][1]["id"] = "S1"
        self.assertIn("$.sections[1].id", self.errs(self.a))

    def test_sections_that_leave_a_paragraph_uncovered(self):
        self.a["sections"][1]["first"] = "P4"                  # S2 now starts after P3
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])
        self.assertIn("P3", self.messages(self.a, "$.sections[1]")[0])

    def test_the_first_section_starts_at_the_first_paragraph(self):
        self.a["sections"][0]["first"] = "P2"
        self.assertEqual(self.errs(self.a), ["$.sections[0]"])
        self.assertIn("P1", self.messages(self.a, "$.sections[0]")[0])

    def test_the_last_section_ends_at_the_last_paragraph(self):
        self.a["sections"][2]["last"] = "P5"
        self.assertEqual(self.errs(self.a), ["$.sections[2]"])
        message = self.messages(self.a, "$.sections[2]")[0]
        self.assertIn("stop at P5", message)
        self.assertIn("goes on to P6", message)

    def test_overlapping_sections(self):
        self.a["sections"][1]["first"] = "P2"
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])
        self.assertIn("P2", self.messages(self.a, "$.sections[1]")[0])

    def test_sections_out_of_order(self):
        sections = self.a["sections"]
        sections[1], sections[2] = sections[2], sections[1]
        sections[1]["baton"], sections[2]["baton"] = sections[2]["baton"], sections[1]["baton"]
        # S3 now comes before S2: the first leaves P3 uncovered, the second begins where S3 has
        # already been. Nothing else is wrong: P5 and P6 are covered, and so is the draft's end.
        self.assertEqual(self.errs(self.a), ["$.sections[1]", "$.sections[2]"])
        self.assertIn("leaves P3 uncovered", self.messages(self.a, "$.sections[1]")[0])
        self.assertIn("already reaches P6", self.messages(self.a, "$.sections[2]")[0])

    def test_the_first_two_sections_swapped(self):
        sections = self.a["sections"]
        sections[0], sections[1] = sections[1], sections[0]
        self.assertEqual(self.errs(self.a), ["$.sections[0]", "$.sections[1]"])

    def test_a_section_inside_another_is_the_only_error(self):
        self.a["sections"][0]["last"] = "P4"            # S1 now runs from P1 to P4 ...
        self.a["sections"][1]["first"] = "P2"           # ... and S2 sits inside it
        self.a["sections"][1]["last"] = "P3"
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])
        self.assertIn("already reaches P4", self.messages(self.a, "$.sections[1]")[0])

    def test_first_may_not_come_after_last(self):
        self.a["sections"][1]["first"], self.a["sections"][1]["last"] = "P4", "P3"
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])

    def test_first_and_last_must_be_paragraph_ids_of_the_source(self):
        for key, value in (("first", "P99"), ("last", "T1"), ("first", None), ("last", 3)):
            with self.subTest(key=key, value=value):
                a = copy.deepcopy(self.a)
                a["sections"][0][key] = value
                self.assertEqual(self.errs(a), [f"$.sections[0].{key}"])

    def test_a_single_section_may_cover_everything(self):
        analysis, source = with_paragraphs(6)
        self.assertEqual(self.errs(analysis, source), [])

    def test_there_must_be_a_section(self):
        self.a["sections"] = []
        self.assertEqual(self.errs(self.a), ["$.sections"])

    def test_an_entry_that_is_not_an_object_is_the_only_error(self):
        # The sections around it are still read for what they are: the last one needs no baton.
        for key, index, path in (("sections", 1, "$.sections[1]"), ("lanes", 1, "$.lanes[1]"),
                                 ("questions", 1, "$.questions[1]")):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                a[key][index] = "text"
                self.assertEqual(self.errs(a), [path])

    def test_every_section_but_the_last_hands_on_a_baton(self):
        for value in ("", "  ", None, 3):
            with self.subTest(value=value):
                self.a["sections"][0]["baton"] = value
                self.assertEqual(self.errs(self.a), ["$.sections[0].baton"])
        del self.a["sections"][1]["baton"]
        self.assertIn("$.sections[1].baton", self.errs(self.a))

    def test_the_last_section_needs_no_baton(self):
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))
        del self.a["sections"][2]["baton"]
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))
        self.a["sections"][2]["baton"] = None
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))
        self.a["sections"][2]["baton"] = "   "
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_a_baton_on_the_last_section_is_a_warning(self):
        self.a["sections"][2]["baton"] = "What comes next?"
        r = check(self.a, self.src)
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["path"] for w in r["warnings"]], ["$.sections[2].baton"])

    def test_the_last_batons_type_is_still_checked(self):
        self.a["sections"][2]["baton"] = 4
        self.assertEqual(self.errs(self.a), ["$.sections[2].baton"])

    def test_the_only_section_is_the_last_one(self):
        analysis, source = with_paragraphs(6)
        analysis["sections"][0]["baton"] = "Next?"
        self.assertEqual(self.errs(analysis, source), [])
        self.assertEqual(self.warns(analysis, source), ["$.sections[0].baton"])

    def test_answers_name_existing_questions(self):
        self.a["sections"][0]["answers"] = ["Q9"]
        self.assertEqual(self.errs(self.a), ["$.sections[0].answers"])
        self.assertIn("Q9", self.messages(self.a, "$.sections[0].answers")[0])
        self.a["sections"][0]["answers"] = ["Q1", "q2"]
        self.assertEqual(self.errs(self.a), ["$.sections[0].answers"])
        self.a["sections"][0]["answers"] = "Q1"
        self.assertEqual(self.errs(self.a), ["$.sections[0].answers"])
        self.a["sections"][0]["answers"] = [1]
        self.assertEqual(self.errs(self.a), ["$.sections[0].answers"])

    def test_a_section_may_answer_no_question(self):
        self.a["sections"][0]["answers"] = []
        self.assertEqual(self.errs(self.a), [])

    def test_sections_of_a_draft_without_headings_should_be_inferred(self):
        self.src["sections"] = []
        r = check(self.a, self.src)
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["path"] for w in r["warnings"]],
                         ["$.sections[0].inferred", "$.sections[1].inferred",
                          "$.sections[2].inferred"])
        for section in self.a["sections"]:
            section["inferred"] = True
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_inferred_sections_of_a_draft_with_headings_are_fine(self):
        self.a["sections"][1]["inferred"] = True
        r = check(self.a, self.src)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_inferred_sections_still_have_to_cover_the_draft(self):
        self.src["sections"] = []
        for section in self.a["sections"]:
            section["inferred"] = True
        self.a["sections"][1]["first"] = "P2"
        self.assertEqual(self.errs(self.a), ["$.sections[1]"])


class ReferenceTests(CheckBase):
    def test_a_case_appears_in_at_least_two_places(self):
        self.a["cases"][0]["at"] = ["P2"]
        self.assertEqual(self.errs(self.a), ["$.cases[0].at"])
        self.a["cases"][0]["at"] = []
        self.assertEqual(self.errs(self.a), ["$.cases[0].at"])
        self.a["cases"][0]["at"] = ["P2", "P2"]
        self.assertEqual(self.errs(self.a), ["$.cases[0].at"])
        for at in (["P2", "P5"], ["P2", "P5", "P6"], ["P2", "T1"]):
            self.a["cases"][0]["at"] = at
            self.assertEqual(self.errs(self.a), [])

    def test_a_reference_to_an_unknown_id_is_one_error(self):
        self.a["cases"][0]["at"] = ["P2", "P99"]
        self.assertEqual(self.errs(self.a), ["$.cases[0].at"])
        self.assertIn("P99", self.messages(self.a, "$.cases[0].at")[0])
        self.a["gaps"][0]["at"] = ["P3", "T9", "x"]
        self.assertEqual(self.errs(self.a), ["$.cases[0].at", "$.gaps[0].at"])

    def test_references_must_be_a_list_of_strings(self):
        for value in ("P2", None, [3, "P5"], [["P2"], "P5"]):
            with self.subTest(value=value):
                a = copy.deepcopy(self.a)
                a["cases"][0]["at"] = value
                self.assertEqual(self.errs(a), ["$.cases[0].at"])
        del self.a["cases"][0]["at"]
        self.assertEqual(self.errs(self.a), ["$.cases[0].at"])

    def test_a_reference_to_a_table_needs_the_table_in_the_analysis(self):
        self.a["gaps"][0]["at"] = ["T1"]
        self.assertEqual(self.errs(self.a), [])
        del self.a["paragraphs"][4]
        self.assertEqual(self.errs(self.a), ["$.gaps[0].at"])

    def test_a_paragraph_missing_from_the_list_is_reported_once(self):
        self.a["gaps"][0]["at"] = ["P3"]
        del self.a["paragraphs"][2]
        self.assertEqual(self.errs(self.a), ["$.paragraphs"])

    def test_a_case_needs_a_name_and_a_note(self):
        for key in ("name", "note"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                a["cases"][0][key] = ""
                self.assertEqual(self.errs(a), [f"$.cases[0].{key}"])
                del a["cases"][0][key]
                self.assertEqual(self.errs(a), [f"$.cases[0].{key}"])
        self.a["cases"][0] = ["Acme", "P2", "P5"]
        self.assertEqual(self.errs(self.a), ["$.cases[0]"])

    def test_a_gap_needs_at_note_and_direction(self):
        for key in ("at", "note", "direction"):
            with self.subTest(key=key):
                a = copy.deepcopy(self.a)
                del a["gaps"][0][key]
                self.assertEqual(self.errs(a), [f"$.gaps[0].{key}"])
        self.a["gaps"][0]["note"] = " "
        self.assertEqual(self.errs(self.a), ["$.gaps[0].note"])
        self.a["gaps"][0] = "Connect P3."
        self.assertEqual(self.errs(self.a), ["$.gaps[0]"])

    def test_a_gap_may_name_no_place(self):
        self.a["gaps"][0]["at"] = []
        self.assertEqual(self.errs(self.a), [])

    def test_the_second_entry_is_reported_with_its_own_index(self):
        self.a["cases"].append({"name": "Beta", "at": ["P1"], "note": "x"})
        self.a["gaps"].append(copy.deepcopy(self.a["gaps"][0]))
        self.a["gaps"][1]["at"] = ["P98"]
        self.assertEqual(self.errs(self.a), ["$.cases[1].at", "$.gaps[1].at"])


class DirectionTests(CheckBase):
    def set_direction(self, text):
        self.a["gaps"][0]["direction"] = text
        return self.errs(self.a)

    def test_two_sentences_are_the_most(self):
        self.assertEqual(self.set_direction("Link P3 to Q1. Then cut P5."), [])
        self.assertEqual(self.set_direction("Link P3 to Q1. Then cut P5. Then stop."),
                         ["$.gaps[0].direction"])
        self.assertIn("3", self.messages(self.a, "$.gaps[0].direction")[0])

    def test_a_stop_that_does_not_end_a_sentence_does_not_count(self):
        self.assertEqual(self.set_direction("Link P3 to Q1, e.g. the rails claim, i.e. P5, etc."),
                         [])
        quote = "the rails claim. And more. And more."
        self.assertEqual(self.set_direction(f'Add "{quote}" to P3.'), [])

    def test_twelve_new_words_in_a_quote_are_allowed_and_thirteen_are_not(self):
        self.assertEqual(self.set_direction('Write "' + " ".join(["new"] * 12) + '" in P3.'), [])
        self.assertEqual(self.set_direction('Write "' + " ".join(["new"] * 13) + '" in P3.'),
                         ["$.gaps[0].direction"])
        self.assertIn("13", self.messages(self.a, "$.gaps[0].direction")[0])

    def test_every_quote_style_is_covered(self):
        words = " ".join(["new"] * 13)
        for text in (f"Write '{words}' in P3.", f"Write {LEFT_QUOTE}{words}{RIGHT_QUOTE} in P3.",
                     f"Write {LEFT_SINGLE}{words}{RIGHT_SINGLE} in P3."):
            with self.subTest(text=text):
                self.assertEqual(self.set_direction(text), ["$.gaps[0].direction"])

    def test_a_long_quote_from_the_draft_is_allowed(self):
        self.assertEqual(self.set_direction('Reuse "' + THIRTEEN_WORDS_FROM_P5 + '" in P3.'), [])

    def test_a_long_quote_from_the_draft_may_differ_in_style(self):
        quote = "knead the dough only once, and the starter keeps working when shifts change."
        self.assertEqual(word_count(quote), 13)
        self.assertEqual(self.set_direction(f'Reuse "{quote}" in P5.'), [])
        self.assertEqual(self.set_direction(f'Reuse "{quote.replace("only once", "only  once")}" '
                                            "in P5."), [])

    def test_a_long_quote_may_span_an_invisible_character_of_the_draft(self):
        p5 = self.src["paragraphs"][4]
        p5["text"] = p5["text"].replace("the slow", "the \N{ZERO WIDTH SPACE}slow")
        self.assertIn("\N{ZERO WIDTH SPACE}", p5["text"])
        self.assertEqual(self.set_direction('Reuse "' + THIRTEEN_WORDS_FROM_P5 + '" in P3.'), [])

    def test_a_long_quote_from_a_table_or_a_figure_is_allowed(self):
        rows = " ".join(SAMPLE_TABLE_TEXT.split("\n"))
        self.assertGreater(word_count(rows), 12)
        self.assertEqual(self.set_direction(f'Compare "{rows}" with P4.'), [])
        figure = "Figure 1: Fees paid on every message across the largest protocols in 2025"
        self.src["figures"] = [{"id": "F1", "caption": figure, "after": "P2"}]
        self.assertGreater(word_count(figure), 12)
        self.assertEqual(self.set_direction(f'Cite "{figure}" in P3.'), [])
        self.assertEqual(self.set_direction(f'Cite "{figure}s" in P3.'), ["$.gaps[0].direction"])

    def test_a_long_quote_must_come_from_one_paragraph(self):
        quote = "a long rest before the oven. Acme runs one such bakery and keeps"
        self.assertEqual(word_count(quote), 13)
        self.assertEqual(self.set_direction(f'Join "{quote}" in P3.'), ["$.gaps[0].direction"])

    def test_a_long_quote_is_judged_case_sensitively(self):
        quote = THIRTEEN_WORDS_FROM_P5.replace("Acme", "acme")
        self.assertEqual(self.set_direction(f'Reuse "{quote}" in P3.'), ["$.gaps[0].direction"])

    def test_each_long_quote_that_is_not_in_the_draft_is_an_error(self):
        words = " ".join(["new"] * 13)
        self.assertEqual(self.set_direction(f'Swap "{words}" for "{words} again" in P3.'),
                         ["$.gaps[0].direction", "$.gaps[0].direction"])

    def test_short_quotes_may_be_anything(self):
        self.assertEqual(self.set_direction('Say "this is not in the draft" in P3.'), [])

    def test_korean_directions(self):
        self.assertEqual(self.set_direction("P16의 '밭을 돌아가며 맡을 수 있다'를 기준 3과 한 문장으로 잇기"),
                         [])
        words = " ".join(["새"] * 13)
        self.assertEqual(self.set_direction(f"P3의 '{words}'를 기준 3과 잇기"),
                         ["$.gaps[0].direction"])
        self.assertEqual(self.set_direction("첫 문장이다. 둘째 문장이다. 셋째 문장이다."),
                         ["$.gaps[0].direction"])

    def test_a_direction_is_a_non_empty_string(self):
        for value in ("", " ", None, 5, ["Connect P3."]):
            with self.subTest(value=value):
                self.assertEqual(self.set_direction(value), ["$.gaps[0].direction"])

    def test_directions_are_judged_against_the_source_not_the_analysis(self):
        item_of(self.a, "P5")["text"] = "Different words entirely, with a long tail " * 3
        paths = self.set_direction(f'Reuse "{THIRTEEN_WORDS_FROM_P5}" in P3.')
        self.assertEqual(paths, ["$.paragraphs[5].text"])


class WarningTests(CheckBase):
    def over(self, path, setter, limit, fill="x"):
        """A value of ``limit`` characters raises no warning, one more raises exactly one."""
        for length, expected in ((limit, []), (limit + 1, [path])):
            with self.subTest(path=path, length=length):
                a = copy.deepcopy(self.a)
                setter(a, fill * length)
                r = check(a, self.src)
                self.assertEqual(r["errors"], [])
                self.assertEqual([w["path"] for w in r["warnings"]], expected)

    def test_label(self):
        self.over("$.paragraphs[0].label", lambda a, v: a["paragraphs"][0].update(label=v), 28)

    def test_conclusion(self):
        self.over("$.sections[0].conclusion",
                  lambda a, v: a["sections"][0].update(conclusion=v), 90)

    def test_baton(self):
        self.over("$.sections[1].baton", lambda a, v: a["sections"][1].update(baton=v), 40)

    def test_short(self):
        self.over("$.sections[2].short", lambda a, v: a["sections"][2].update(short=v), 12)

    def test_thesis(self):
        self.over("$.thesis", lambda a, v: a.update(thesis=v), 160)

    def test_lengths_count_characters_not_bytes(self):
        self.over("$.paragraphs[0].label", lambda a, v: a["paragraphs"][0].update(label=v), 28,
                  fill="가")

    def test_a_table_label_is_limited_too(self):
        table_item(self.a)["label"] = "x" * 29
        self.assertEqual(self.warns(self.a), ["$.paragraphs[4].label"])

    def test_the_warning_says_the_size_and_the_limit(self):
        self.a["thesis"] = "t" * 161
        message = check(self.a, self.src)["warnings"][0]["message"]
        self.assertIn("161", message)
        self.assertIn("160", message)

    def test_a_long_baton_on_the_last_section_warns_once(self):
        self.a["sections"][2]["baton"] = "b" * 50
        self.assertEqual(self.warns(self.a), ["$.sections[2].baton"])

    def test_warnings_never_become_errors_and_errors_never_warnings(self):
        self.a["thesis"] = "t" * 200
        self.a["paragraphs"][1]["evidence"] = "nope"
        r = check(self.a, self.src)
        self.assertEqual([e["path"] for e in r["errors"]], ["$.paragraphs[1].evidence"])
        self.assertEqual([w["path"] for w in r["warnings"]], ["$.thesis"])


class RobustnessTests(CheckBase):
    """The checker reads what an agent wrote, so it must report any shape and never raise."""

    WRONG_VALUES = (None, True, 0, -1, 1.5, "", " ", "x", "two\nlines", [], {}, [None], {"a": 1},
                    ["P1"], ["two\nlines"])
    # Required fields that hold a string, as paths: each one has a check of its own.
    REQUIRED_STRINGS = (
        ("schema",), ("ui_language",), ("thesis",), ("essay", "title"), ("essay", "source"),
        ("essay", "source_kind"), ("essay", "language"), ("questions", 0, "id"),
        ("questions", 0, "text"), ("lanes", 0, "id"), ("lanes", 0, "kind"), ("lanes", 0, "label"),
        ("sections", 0, "id"), ("sections", 0, "short"), ("sections", 0, "conclusion"),
        ("sections", 0, "first"), ("sections", 0, "last"), ("sections", 0, "baton"),
        ("paragraphs", 0, "id"), ("paragraphs", 0, "kind"), ("paragraphs", 0, "section"),
        ("paragraphs", 0, "text"), ("paragraphs", 0, "role"), ("paragraphs", 0, "label"),
        ("paragraphs", 0, "evidence"), ("paragraphs", 0, "lanes", "q1", "weight"),
        ("paragraphs", 0, "lanes", "q1", "quote"), ("paragraphs", 4, "text"),
        ("cases", 0, "name"), ("cases", 0, "note"), ("gaps", 0, "note"), ("gaps", 0, "direction"),
    )

    @staticmethod
    def json_path(steps):
        text = "$"
        for step in steps:
            text += f"[{step}]" if isinstance(step, int) else f".{step}"
        return text

    @staticmethod
    def every_path(value, steps=()):
        yield steps
        if isinstance(value, dict):
            for key, child in value.items():
                yield from RobustnessTests.every_path(child, steps + (key,))
        elif isinstance(value, list):
            for number, child in enumerate(value):
                yield from RobustnessTests.every_path(child, steps + (number,))

    @staticmethod
    def changed(analysis, steps, value=None, remove=False):
        result = copy.deepcopy(analysis)
        if not steps:
            return value
        parent = result
        for step in steps[:-1]:
            parent = parent[step]
        if remove:
            del parent[steps[-1]]
        else:
            parent[steps[-1]] = value
        return result

    def assert_well_formed(self, result):
        self.assertEqual(set(result), {"errors", "warnings"})
        for entry in result["errors"] + result["warnings"]:
            self.assertEqual(set(entry), {"path", "message"})
            self.assertTrue(entry["path"].startswith("$"), entry)
            self.assertTrue(entry["message"].strip(), entry)
            self.assertNotIn("\n", entry["message"])
            self.assertNotIn("\n", entry["path"])

    def test_no_wrongly_shaped_value_makes_the_checker_raise(self):
        for steps in self.every_path(self.a):
            for value in self.WRONG_VALUES:
                self.assert_well_formed(check(self.changed(self.a, steps, value), self.src))
            if steps:
                self.assert_well_formed(check(self.changed(self.a, steps, remove=True), self.src))

    def test_a_wrong_type_in_a_required_text_field_is_reported_at_that_field(self):
        for steps in self.REQUIRED_STRINGS:
            for value in (None, 3, True, [], {}):
                with self.subTest(path=self.json_path(steps), value=value):
                    errors = self.errs(self.changed(self.a, steps, value))
                    self.assertIn(self.json_path(steps), errors)

    def test_a_missing_required_field_is_reported_at_that_field(self):
        for steps in self.REQUIRED_STRINGS:
            with self.subTest(path=self.json_path(steps)):
                errors = self.errs(self.changed(self.a, steps, remove=True))
                self.assertIn(self.json_path(steps), errors)

    def test_the_source_may_be_empty_or_odd(self):
        for source in (None, [], "source", {}, {"paragraphs": []},
                       {"paragraphs": None, "tables": None}):
            with self.subTest(source=source):
                self.assert_well_formed(check(self.a, source))
        self.assertTrue(check(self.a, {})["errors"])

    def test_an_empty_analysis_object_lists_every_missing_field(self):
        result = check({}, self.src)
        self.assertEqual([e["path"] for e in result["errors"]],
                         ["$.schema", "$.essay", "$.ui_language", "$.thesis", "$.questions",
                          "$.lanes", "$.sections", "$.paragraphs", "$.cases", "$.gaps"])


class ReportTests(unittest.TestCase):
    def test_a_clean_result_is_ok(self):
        self.assertEqual(format_report({"errors": [], "warnings": []}), "OK")

    def test_errors_then_warnings_then_the_counts(self):
        report = format_report({
            "errors": [{"path": "$.a", "message": "first"},
                       {"path": "$.b[1]", "message": "second"}],
            "warnings": [{"path": "$.c", "message": "third"}]})
        self.assertEqual(report.splitlines(), [
            "ERROR $.a: first", "ERROR $.b[1]: second", "WARN $.c: third",
            "2 errors, 1 warning"])

    def test_one_error_and_no_warnings(self):
        report = format_report({"errors": [{"path": "$", "message": "m"}], "warnings": []})
        self.assertEqual(report.splitlines()[-1], "1 error, 0 warnings")

    def test_warnings_alone_still_count(self):
        report = format_report({"errors": [], "warnings": [{"path": "$.t", "message": "long"}] * 2})
        self.assertEqual(report.splitlines(), ["WARN $.t: long", "WARN $.t: long",
                                               "0 errors, 2 warnings"])

    def test_a_real_result(self):
        a, src = sample_analysis(), sample_source()
        a["paragraphs"][1]["evidence"] = "nope"
        a["thesis"] = "t" * 161
        lines = format_report(check(a, src)).splitlines()
        self.assertTrue(lines[0].startswith("ERROR $.paragraphs[1].evidence: "))
        self.assertTrue(lines[1].startswith("WARN $.thesis: "))
        self.assertEqual(lines[2], "1 error, 1 warning")
        self.assertEqual(len(lines), 3)


class LimitsTests(unittest.TestCase):
    def test_the_twelve_roles_in_order(self):
        self.assertEqual(ROLES, ("problem", "thesis", "context", "claim", "evidence", "example",
                                 "counter", "implication", "framework", "transition", "synthesis",
                                 "conclusion"))

    def test_the_limits(self):
        self.assertEqual(LIMITS, {
            "paragraphs": 40, "lanes": 6, "questions": 4, "label": 28, "conclusion": 90,
            "baton": 40, "short": 12, "thesis": 160, "direction_sentences": 2,
            "unquoted_words": 12, "min_paragraphs": 5})


if __name__ == "__main__":
    unittest.main()
