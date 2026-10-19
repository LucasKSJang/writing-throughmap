import contextlib
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import SCRIPTS_DIR
from tests.fixtures import (
    B, FIVE, FIVE_TWO_SECTIONS, FORTY_FIVE, LONG1, LONG2, LONG3, LONG4, P, STYLES_EN, T1, T2, T3,
    T4, T4_AFTER, T4_BEFORE, T5, TABLE, make_corrupt_docx, make_docx, run_main, run_main_streams,
    sections_of, tmp_dir, write_md,
)
from tm_source import (
    CorrectionError, apply_corrections, assemble_source, extract_path, resolve_out_dir,
    select_section,
)
from tm_text import word_count

DOT = "\N{MIDDLE DOT}"
EN_DASH = "\N{EN DASH}"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
KOREAN = ("작은 빵집들은 골목마다 빵을 굽고 모든 반죽은 오븐에 들어가기 전에 오래 쉰다 "
          "그래서 아침마다 부드러운 빵이 나온다.")


def assemble(blocks, hint="hint", name="x.md", kind="md"):
    return assemble_source(blocks, title_hint=hint, source_name=name, source_kind=kind)


def hand_made(*texts):
    """A source written out by hand, so a paragraph can hold odd whitespace."""
    return {
        "schema": "throughmap-source/1",
        "essay": {"title": "t", "source": "t.md", "source_kind": "md",
                  "word_count": 0, "paragraph_count": len(texts)},
        "paragraphs": [{"id": f"P{n}", "text": text} for n, text in enumerate(texts, 1)],
        "tables": [], "figures": [],
        "sections": [{"title": "", "first": "P1", "last": f"P{len(texts)}"}],
        "excluded": [],
    }


def read_both(markdown, word_body):
    """Extract one draft from a Markdown file and from a .docx; yield (file name, source)."""
    folder = tmp_dir()
    paths = (os.path.join(folder, "draft.md"), os.path.join(folder, "draft.docx"))
    with open(paths[0], "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    make_docx(paths[1], word_body, STYLES_EN)
    for path in paths:
        yield os.path.basename(path), extract_path(path, title_hint="the hint")


@contextlib.contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ExtractTests(unittest.TestCase):
    def test_title_byline_lead_section_and_sections(self):
        src = assemble_source([B("title", "Free Rails"), B("para", "By Lucas Jang"),
                               B("para", LONG1), B("para", LONG2),
                               B("heading", "A Switch", 1), B("para", LONG3), B("para", LONG4)],
                              title_hint="x", source_name="x.docx", source_kind="docx")
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual(src["excluded"], [{"kind": "byline", "text": "By Lucas Jang"}])
        self.assertEqual([p["id"] for p in src["paragraphs"]], ["P1", "P2", "P3", "P4"])
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P2"},
                                           {"title": "A Switch", "first": "P3", "last": "P4"}])

    def test_captions_tables_figures_references_and_closing(self):
        src = assemble_source([B("para", LONG1), B("para", "Figure 1: Fees"), B("para", LONG2),
                               B("para", "Table 1: Owners."), B("table", "a | b"),
                               B("para", "그림 2: 수수료"), B("para", LONG3), B("para", "PUBLIUS."),
                               B("heading", "References", 1), B("para", "Aave (2026) ...")],
                              title_hint="t", source_name="t.md", source_kind="md")
        self.assertEqual(src["figures"], [{"id": "F1", "caption": "Figure 1: Fees", "after": "P1"},
                                          {"id": "F2", "caption": "그림 2: 수수료", "after": "P2"}])
        self.assertEqual(src["tables"], [{"id": "T1", "caption": "Table 1: Owners.", "after": "P2", "text": "a | b"}])
        self.assertEqual(len(src["paragraphs"]), 3)
        self.assertEqual([e["kind"] for e in src["excluded"]], ["closing", "references"])

    def test_counts(self):
        src = assemble_source([B("para", LONG1), B("para", LONG2)], title_hint="t",
                              source_name="t.txt", source_kind="txt")
        self.assertEqual(src["essay"]["paragraph_count"], 2)
        self.assertEqual(src["essay"]["word_count"], word_count(LONG1) + word_count(LONG2))

    def test_apply_corrections_join_split_drop(self):
        out = apply_corrections(FIVE, joins=[("P2", "P3")], splits=[("P4", "However,")], drops=["P5"])
        self.assertEqual([p["text"] for p in out["paragraphs"]],
                         [T1, T2 + " " + T3, T4_BEFORE, "However," + T4_AFTER])
        self.assertEqual(out["excluded"][-1], {"kind": "dropped", "text": T5})

    def test_correction_errors(self):
        with self.assertRaisesRegex(CorrectionError, "not adjacent"):
            apply_corrections(FIVE, joins=[("P1", "P3")])
        with self.assertRaisesRegex(CorrectionError, "not found"):
            apply_corrections(FIVE, splits=[("P1", "zzz")])
        with self.assertRaisesRegex(CorrectionError, "different sections"):
            apply_corrections(FIVE_TWO_SECTIONS, joins=[("P2", "P3")])

    def test_select_section_keeps_ids(self):
        sel = select_section(FORTY_FIVE, "Two")
        self.assertEqual(sel["paragraphs"][0]["id"], "P16")
        self.assertEqual(sel["essay"]["selected_section"], "Two")
        self.assertEqual(select_section(FORTY_FIVE, "2")["paragraphs"][0]["id"], "P16")
        with self.assertRaises(CorrectionError):
            select_section(FORTY_FIVE, "Nope")

    def test_resolve_out_dir(self):
        base = os.path.join(tempfile.gettempdir(), "B and F")
        self.assertEqual(resolve_out_dir(os.path.join(base, "글.docx"), None, None, "/cwd"),
                         os.path.join(base, "글.throughmap"))
        self.assertEqual(resolve_out_dir(None, "Free Rails", None, "/cwd"), os.path.join("/cwd", "free-rails.throughmap"))
        self.assertEqual(resolve_out_dir("a.md", None, "/o", "/cwd"), "/o")
        with self.assertRaisesRegex(ValueError, "--name"):
            resolve_out_dir(None, None, None, "/cwd")

    def test_cli_extract_in_spaced_korean_path(self):          # Review Focus 1
        d = tmp_dir("B and F", "한글 폴더"); path = os.path.join(d, "글 초안.docx")
        make_docx(path, P("Intro", "Heading1") + P(LONG1) + P(LONG2), STYLES_EN)
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        src = json.loads(Path(d, "글 초안.throughmap", "source.json").read_text("utf-8"))
        self.assertEqual(len(src["paragraphs"]), 2)
        self.assertIn("paragraphs: 2", out)

    def test_cli_extract_over_limit_lists_sections(self):        # Review Focus 5
        path = write_md(tmp_dir(), "long.md", sections={"One": 15, "Two": 15, "Three": 15})
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertIn("over 40 paragraphs", out)
        self.assertIn("2. Two P16–P30, 15 paragraphs", out)
        code, out = run_main(["extract", path, "--section", "Two"])
        src = json.loads(Path(path).with_suffix(".throughmap").joinpath("source.json").read_text("utf-8"))
        self.assertEqual([p["id"] for p in src["paragraphs"]][:2], ["P16", "P17"])

    def test_cli_stdin_requires_name(self):
        code, _ = run_main(["extract", "-"], stdin="Some text.")
        self.assertEqual(code, 2)


class TitleTests(unittest.TestCase):
    def test_a_title_block_is_the_title_and_leaves_the_text(self):
        src = assemble([B("title", "Free Rails"), B("para", LONG1)])
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1])
        self.assertEqual(src["excluded"], [])
        self.assertTrue(src.title_from_block)

    def test_a_second_title_block_is_not_lost(self):
        src = assemble([B("title", "Free Rails"), B("title", "A second title line"), B("para", LONG1)])
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual(src["excluded"], [{"kind": "front", "text": "A second title line"}])

    def test_a_level_one_heading_is_the_title_when_deeper_headings_exist(self):
        src = assemble([B("heading", "Free Rails", 1), B("heading", "One", 2), B("para", LONG1),
                        B("heading", "Two", 2), B("para", LONG2)])
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual(src["sections"], [{"title": "One", "first": "P1", "last": "P1"},
                                           {"title": "Two", "first": "P2", "last": "P2"}])
        self.assertEqual(src["excluded"], [])
        self.assertTrue(src.title_from_block)

    def read_both(self, markdown, word_body):
        return read_both(markdown, word_body)

    def test_a_lone_heading_that_opens_the_draft_is_the_title(self):
        # A memo whose one heading is its "# title" was mapped as a single section holding every
        # paragraph, with no flow to show. As the title, the heading leaves a draft without
        # headings, whose sections the agent infers.
        drafts = self.read_both("# Free Rails\n\n" + LONG1 + "\n\n" + LONG2 + "\n",
                                P("Free Rails", "Heading1") + P(LONG1) + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "Free Rails")
                self.assertTrue(src.title_from_block)
                self.assertEqual(src["sections"], [])
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual(src["excluded"], [])

    def test_a_lone_heading_of_any_level_that_opens_the_draft_is_the_title(self):
        src = assemble([B("heading", "Free Rails", 2), B("para", LONG1), B("para", LONG2)])
        self.assertEqual((src["essay"]["title"], src["sections"]), ("Free Rails", []))
        self.assertTrue(src.title_from_block)

    def test_a_lone_heading_after_the_first_paragraph_still_makes_two_sections(self):
        drafts = self.read_both(LONG1 + "\n\n# Part\n\n" + LONG2 + "\n",
                                P(LONG1) + P("Part", "Heading1") + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "the hint")
                self.assertFalse(src.title_from_block)
                self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P1"},
                                                   {"title": "Part", "first": "P2", "last": "P2"}])

    def test_a_plain_title_line_over_level_one_sections_with_a_deeper_heading(self):
        # A common student .docx: a Normal-style title line, then Heading 1 sections and one
        # Heading 2. "Introduction" has body under it and another level-1 heading follows, so
        # it is a section, not the title (R67); the title line is a front line, as before.
        drafts = self.read_both(
            "\n\n".join(["Free Rails Essay", "# Introduction", LONG1, "# Analysis", LONG2,
                         "## Data", LONG3]) + "\n",
            P("Free Rails Essay") + P("Introduction", "Heading1") + P(LONG1)
            + P("Analysis", "Heading1") + P(LONG2) + P("Data", "Heading2") + P(LONG3))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "the hint")
                self.assertFalse(src.title_from_block)
                self.assertEqual(src["sections"],
                                 [{"title": "Introduction", "first": "P1", "last": "P1"},
                                  {"title": "Analysis", "first": "P2", "last": "P3"}])
                self.assertEqual(src["excluded"], [{"kind": "front", "text": "Free Rails Essay"},
                                                   {"kind": "subheading", "text": "Data"}])

    def test_the_one_level_one_heading_over_deeper_ones_is_still_the_title(self):
        drafts = self.read_both("\n\n".join(["# Title", "## A", LONG1, "## B", LONG2]) + "\n",
                                P("Title", "Heading1") + P("A", "Heading2") + P(LONG1)
                                + P("B", "Heading2") + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "Title")
                self.assertTrue(src.title_from_block)
                self.assertEqual([s["title"] for s in src["sections"]], ["A", "B"])
        # A level-1 heading with nothing under it is the title too, whatever follows it.
        src = assemble([B("heading", "Title", 1), B("heading", "One", 1), B("para", LONG1),
                        B("heading", "Detail", 2), B("para", LONG2), B("heading", "Two", 1),
                        B("para", LONG3)])
        self.assertEqual((src["essay"]["title"], [s["title"] for s in src["sections"]]),
                         ("Title", ["One", "Two"]))

    def test_a_first_heading_with_nothing_under_it_is_the_title(self):
        # "# My Essay" over "# Introduction" and "# Body" was an empty section, dropped, so the
        # page showed the file name (R63). A front line such as a byline may stand above it.
        for lines, excluded in (((), []),
                                (("By Sam Rivera",), [{"kind": "byline", "text": "By Sam Rivera"}])):
            drafts = self.read_both(
                "\n\n".join([*lines, "# My Essay", "# Introduction", LONG1, "# Body", LONG2]) + "\n",
                "".join(map(P, lines)) + P("My Essay", "Heading1") + P("Introduction", "Heading1")
                + P(LONG1) + P("Body", "Heading1") + P(LONG2))
            for name, src in drafts:
                with self.subTest(name, front=lines):
                    self.assertEqual(src["essay"]["title"], "My Essay")
                    self.assertTrue(src.title_from_block)
                    self.assertEqual(src["sections"],
                                     [{"title": "Introduction", "first": "P1", "last": "P1"},
                                      {"title": "Body", "first": "P2", "last": "P2"}])
                    self.assertEqual(src["excluded"], excluded)

    def test_a_first_heading_with_body_under_it_stays_a_section(self):
        drafts = self.read_both("# Introduction\n\n" + LONG1 + "\n\n# Body\n\n" + LONG2 + "\n",
                                P("Introduction", "Heading1") + P(LONG1) + P("Body", "Heading1")
                                + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "the hint")
                self.assertFalse(src.title_from_block)
                self.assertEqual([s["title"] for s in src["sections"]], ["Introduction", "Body"])
        # A deeper heading does not end what is under a heading: the body under "### Detail" is
        # under "## Part" too, so "## Part" stays a section.
        src = assemble([B("heading", "Part", 2), B("heading", "Detail", 3), B("para", LONG1),
                        B("heading", "Next", 2), B("para", LONG2)])
        self.assertEqual((src["essay"]["title"], [s["title"] for s in src["sections"]]),
                         ("hint", ["Part", "Next"]))

    def test_a_heading_that_opens_the_draft_stays_a_section_when_another_follows(self):
        src = assemble([B("heading", "Free Rails", 1), B("para", LONG1), B("heading", "More", 1),
                        B("para", LONG2)])
        self.assertEqual(src["essay"]["title"], "hint")
        self.assertFalse(src.title_from_block)
        self.assertEqual(src["sections"], [{"title": "Free Rails", "first": "P1", "last": "P1"},
                                           {"title": "More", "first": "P2", "last": "P2"}])

    REFERENCES = ("Aave (2026) Fee switch proposal.", "Circle (2025) Rails and edges.")
    REFERENCES_ENTRY = {"kind": "references", "text": "\n".join(("References", *REFERENCES))}

    def with_references(self, markdown, word_body, level=1):
        """read_both() for the draft followed by a References heading of ``level`` and entries."""
        markdown += (f"\n\n{'#' * level} References\n\n"
                     + "\n\n".join("- " + entry for entry in self.REFERENCES) + "\n")
        word_body += P("References", f"Heading{level}") + "".join(map(P, self.REFERENCES))
        return self.read_both(markdown, word_body)

    def test_a_lone_heading_over_the_references_is_still_the_title(self):
        # "# Title", the essay, then "# References" is the commonest shape of a university essay.
        # The references are set aside, so their heading does not count against the title.
        for level in (1, 2):
            drafts = self.with_references("# Free Rails\n\n" + LONG1 + "\n\n" + LONG2,
                                          P("Free Rails", "Heading1") + P(LONG1) + P(LONG2), level)
            for name, src in drafts:
                with self.subTest(name, level=level):
                    self.assertEqual(src["essay"]["title"], "Free Rails")
                    self.assertTrue(src.title_from_block)
                    self.assertEqual(src["sections"], [])
                    self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                    self.assertEqual(src["excluded"], [self.REFERENCES_ENTRY])

    def test_a_title_paragraph_over_a_references_heading_leaves_no_sections(self):
        path = os.path.join(tmp_dir(), "draft.docx")
        make_docx(path, P("Free Rails", "Title") + P(LONG1) + P(LONG2) + P("References", "Heading1")
                  + "".join(map(P, self.REFERENCES)), STYLES_EN)
        src = extract_path(path)
        self.assertEqual((src["essay"]["title"], src["sections"]), ("Free Rails", []))
        self.assertEqual(src["excluded"], [self.REFERENCES_ENTRY])

    def test_a_two_section_draft_that_ends_in_references_keeps_its_sections(self):
        # At either level the references heading goes with the references: a "## References" is
        # no deeper heading that would make "# One" the title.
        for level in (1, 2):
            drafts = self.with_references("# One\n\n" + LONG1 + "\n\n# Two\n\n" + LONG2,
                                          P("One", "Heading1") + P(LONG1) + P("Two", "Heading1")
                                          + P(LONG2), level)
            for name, src in drafts:
                with self.subTest(name, level=level):
                    self.assertEqual(src["essay"]["title"], "the hint")
                    self.assertFalse(src.title_from_block)
                    self.assertEqual(src["sections"],
                                     [{"title": "One", "first": "P1", "last": "P1"},
                                      {"title": "Two", "first": "P2", "last": "P2"}])
                    self.assertEqual(src["excluded"], [self.REFERENCES_ENTRY])

    def test_a_heading_after_a_references_line_is_body_again(self):
        # A one-line "References" paragraph opens the references just as a heading does. With no
        # section heading above it, the next heading ends them (R62), so the appendix is mapped:
        # body text is never lost. "Free Rails" then has body under it and another level-1
        # heading after it, so it is a section, as in a draft with no references at all.
        src = assemble([B("heading", "Free Rails", 1), B("para", LONG1), B("para", LONG2),
                        B("para", "References"), B("heading", "Appendix", 1),
                        B("para", "A note on the sources.")])
        self.assertEqual(src["essay"]["title"], "hint")
        self.assertEqual(src["sections"], [
            {"title": "Free Rails", "first": "P1", "last": "P2"},
            {"title": "Appendix", "first": "P3", "last": "P3"}])
        self.assertEqual(src["excluded"], [{"kind": "references", "text": "References"}])

    def test_a_notes_or_sources_heading_over_body_text_is_the_title(self):
        # The references open only where the body has started, at the first paragraph of 12
        # words or more; above it, such a heading is a lone heading like any other, and the body
        # under it is kept.
        for word in ("Notes", "Sources"):
            drafts = self.read_both(f"# {word}\n\n{LONG1}\n\n{LONG2}\n",
                                    P(word, "Heading1") + P(LONG1) + P(LONG2))
            for name, src in drafts:
                with self.subTest(name, heading=word):
                    self.assertEqual(src["essay"]["title"], word)
                    self.assertTrue(src.title_from_block)
                    self.assertEqual(src["sections"], [])
                    self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                    self.assertEqual(src["excluded"], [])

    def test_a_one_line_notes_paragraph_first_is_front_matter(self):
        drafts = self.read_both(f"Notes\n\n{LONG1}\n\n{LONG2}\n", P("Notes") + P(LONG1) + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual(src["excluded"], [{"kind": "front", "text": "Notes"}])
                self.assertEqual((src["essay"]["title"], src["sections"]), ("the hint", []))

    def assert_lone_title_under(self, lines, heading, excluded):
        """The lines are front matter over the draft's one heading, which is still its title."""
        drafts = self.read_both("\n\n".join([*lines, "# " + heading, LONG1, LONG2]) + "\n",
                                "".join(map(P, lines)) + P(heading, "Heading1") + P(LONG1)
                                + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], heading)
                self.assertTrue(src.title_from_block)
                self.assertEqual(src["sections"], [])
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual(src["excluded"], excluded)

    def test_to_and_from_lines_over_a_lone_heading_leave_it_the_title(self):
        self.assert_lone_title_under(("To: Team", "From: Ops"), "Subject line",
                                     [{"kind": "front", "text": "To: Team"},
                                      {"kind": "front", "text": "From: Ops"}])

    def test_a_byline_over_a_lone_heading_leaves_it_the_title(self):
        self.assert_lone_title_under(("By Sam Rivera",), "Free Rails",
                                     [{"kind": "byline", "text": "By Sam Rivera"}])

    def test_front_lines_over_a_title_with_sections_keep_both(self):
        # Front lines do not count against "# Title" over "##" sections either: the draft keeps
        # its title and its sections.
        cases = ((("By Sam Rivera",), [{"kind": "byline", "text": "By Sam Rivera"}]),
                 (("To: Team", "From: Ops"), [{"kind": "front", "text": "To: Team"},
                                              {"kind": "front", "text": "From: Ops"}]))
        for lines, excluded in cases:
            drafts = self.read_both(
                "\n\n".join([*lines, "# Free Rails", "## A", LONG1, "## B", LONG2]) + "\n",
                "".join(map(P, lines)) + P("Free Rails", "Heading1") + P("A", "Heading2")
                + P(LONG1) + P("B", "Heading2") + P(LONG2))
            for name, src in drafts:
                with self.subTest(name, front=lines[0]):
                    self.assertEqual(src["essay"]["title"], "Free Rails")
                    self.assertTrue(src.title_from_block)
                    self.assertEqual(src["sections"],
                                     [{"title": "A", "first": "P1", "last": "P1"},
                                      {"title": "B", "first": "P2", "last": "P2"}])
                    self.assertEqual(src["excluded"], excluded)

    def test_a_level_one_heading_after_a_paragraph_is_not_the_title(self):
        src = assemble([B("para", LONG1), B("heading", "Part", 1), B("heading", "Deeper", 2),
                        B("para", LONG2)])
        self.assertEqual(src["essay"]["title"], "hint")
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P1"},
                                           {"title": "Part", "first": "P2", "last": "P2"}])
        self.assertEqual(src["excluded"], [{"kind": "subheading", "text": "Deeper"}])

    def test_the_hint_is_the_title_when_the_text_has_none(self):
        src = assemble([B("para", LONG1)], hint="essay-name")
        self.assertEqual(src["essay"]["title"], "essay-name")
        self.assertFalse(src.title_from_block)


class ReferencesTests(unittest.TestCase):
    ENTRIES = [B("para", "Aave (2026) The fee switch."), B("para", "Curve (2025) Pools.")]
    TITLES = ("References", "REFERENCES:", "Bibliography", "Works Cited", "Sources", "Notes:",
              "참고문헌", "참고 문헌", "참고자료")

    def test_everything_from_a_references_heading_or_line_on_is_cut(self):
        for as_heading in (True, False):
            for title in self.TITLES:
                with self.subTest(title=title, heading=as_heading):
                    marker = B("heading", title, 1) if as_heading else B("para", title)
                    src = assemble([B("para", LONG1), B("para", LONG2), marker, *self.ENTRIES])
                    self.assertEqual(len(src["paragraphs"]), 2)
                    text = "\n".join([title, "Aave (2026) The fee switch.", "Curve (2025) Pools."])
                    self.assertEqual(src["excluded"], [{"kind": "references", "text": text}])

    def test_other_headings_do_not_cut(self):
        for title in ("Notes on the method", "References and further reading", "Sources of fees"):
            with self.subTest(title):
                src = assemble([B("para", LONG1), B("heading", title, 1), B("para", LONG2)])
                self.assertEqual(len(src["paragraphs"]), 2)
                self.assertEqual(src["excluded"], [])

    def test_the_first_match_starts_the_cut_and_the_text_is_cut_to_500_characters(self):
        blocks = [B("para", LONG1), B("heading", "Notes", 1), B("para", LONG2),
                  B("heading", "References", 1)] + [B("para", "x" * 100)] * 6
        src = assemble(blocks)
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1])
        (entry,) = src["excluded"]
        self.assertEqual(entry["kind"], "references")
        self.assertEqual(len(entry["text"]), 500)
        self.assertTrue(entry["text"].startswith("Notes\n" + LONG2 + "\nReferences\n"))

    NOTES = ("A first note on the data.", "A second note on the sources.")

    def test_a_notes_section_in_mid_draft_ends_at_the_next_heading_of_its_level(self):
        # The references run to the next heading of the same or a higher level (R62), so the
        # body after a mid-draft "## Notes" is kept: before, it was cut with exit 0.
        drafts = read_both(
            "\n\n".join(["# Policy Memo", "## Background", LONG1, "## Notes", *self.NOTES,
                         "### More notes", "A third note.", "## Recommendation", LONG2, LONG3]),
            P("Policy Memo", "Heading1") + P("Background", "Heading2") + P(LONG1)
            + P("Notes", "Heading2") + "".join(map(P, self.NOTES))
            + '<w:p><w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:r><w:t>More notes</w:t></w:r></w:p>'
            + P("A third note.") + P("Recommendation", "Heading2") + P(LONG2) + P(LONG3))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "Policy Memo")
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3])
                self.assertEqual(src["sections"],
                                 [{"title": "Background", "first": "P1", "last": "P1"},
                                  {"title": "Recommendation", "first": "P2", "last": "P3"}])
                self.assertEqual(src["excluded"], [{"kind": "references", "text": "\n".join(
                    ["Notes", *self.NOTES, "More notes", "A third note."])}])

    def test_references_at_the_end_still_run_to_the_end(self):
        drafts = read_both("\n\n".join(["# Policy Memo", "## Background", LONG1,
                                        "## Recommendation", LONG2, "## References", *self.NOTES]),
                           P("Policy Memo", "Heading1") + P("Background", "Heading2") + P(LONG1)
                           + P("Recommendation", "Heading2") + P(LONG2)
                           + P("References", "Heading2") + "".join(map(P, self.NOTES)))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual([s["title"] for s in src["sections"]],
                                 ["Background", "Recommendation"])
                self.assertEqual(src["excluded"], [
                    {"kind": "references", "text": "\n".join(["References", *self.NOTES])}])

    def test_an_appendix_after_the_references_is_mapped(self):
        # Body text is never lost: an appendix after the references is body again, and the user
        # can --drop it.
        drafts = read_both("\n\n".join(["# Policy Memo", "## Background", LONG1, "## References",
                                        *self.NOTES, "## Appendix A", LONG2]),
                           P("Policy Memo", "Heading1") + P("Background", "Heading2") + P(LONG1)
                           + P("References", "Heading2") + "".join(map(P, self.NOTES))
                           + P("Appendix A", "Heading2") + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual(src["essay"]["title"], "Policy Memo")
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual(src["sections"],
                                 [{"title": "Background", "first": "P1", "last": "P1"},
                                  {"title": "Appendix A", "first": "P2", "last": "P2"}])
                self.assertEqual(src["excluded"], [
                    {"kind": "references", "text": "\n".join(["References", *self.NOTES])}])

    def test_a_references_line_runs_to_the_next_heading_at_the_section_level(self):
        # A one-line "References" paragraph has no level of its own, so the draft's section level
        # ends it: here "##", so the "###" inside the references stays in them.
        src = assemble([B("title", "Free Rails"), B("heading", "A", 2), B("para", LONG1),
                        B("heading", "B", 2), B("para", LONG2), B("para", "References"),
                        B("para", "Aave (2026) The fee switch."), B("heading", "Books", 3),
                        B("para", "Curve (2025) Pools."), B("heading", "Appendix", 2),
                        B("para", LONG3)])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3])
        self.assertEqual([s["title"] for s in src["sections"]], ["A", "B", "Appendix"])
        self.assertEqual(src["excluded"], [{"kind": "references", "text": "\n".join(
            ["References", "Aave (2026) The fee switch.", "Books", "Curve (2025) Pools."])}])

    def test_references_runs_apart_are_listed_apart(self):
        src = assemble([B("heading", "One", 1), B("para", LONG1), B("heading", "Notes", 1),
                        B("para", "n1"), B("heading", "Two", 1), B("para", LONG2),
                        B("heading", "Sources", 1), B("para", "s1")])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
        self.assertEqual(src["excluded"], [{"kind": "references", "text": "Notes\nn1"},
                                           {"kind": "references", "text": "Sources\ns1"}])
        # The heading after a run is body again, so it counts for the title: "One" has body under
        # it and another level-1 heading follows, so it is a section, not the title.
        self.assertEqual(src["essay"]["title"], "hint")
        self.assertEqual(src["sections"], [{"title": "One", "first": "P1", "last": "P1"},
                                           {"title": "Two", "first": "P2", "last": "P2"}])

    def test_entries_are_not_mistaken_for_closing_lines(self):
        src = assemble([B("para", LONG1), B("heading", "References", 1), B("para", "Aave 2026."),
                        B("para", "Curve.")])
        self.assertEqual([e["kind"] for e in src["excluded"]], ["references"])


class FrontMatterAndClosingTests(unittest.TestCase):
    def test_lines_before_the_first_long_paragraph_are_set_aside(self):
        src = assemble([B("para", "Draft for review"), B("para", "By Lucas Jang"),
                        B("para", "Version 2"), B("para", LONG1), B("para", LONG2)])
        self.assertEqual(src["excluded"], [{"kind": "front", "text": "Draft for review"},
                                           {"kind": "byline", "text": "By Lucas Jang"},
                                           {"kind": "front", "text": "Version 2"}])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])

    def test_which_lines_are_bylines(self):
        cases = {"By Lucas": "byline", "by Lucas": "byline", "글: 장승현": "byline",
                 "작성 장승현": "byline", "작성자: 장승현": "byline",
                 "Bytes of fees": "front", "BY LUCAS": "front", "Written by Lucas": "front"}
        for text, kind in cases.items():
            with self.subTest(text):
                src = assemble([B("para", text), B("para", LONG1)])
                self.assertEqual(src["excluded"], [{"kind": kind, "text": text}])

    def test_only_the_first_byline_is_a_byline(self):
        src = assemble([B("para", "By Lucas"), B("para", "By Someone Else"), B("para", LONG1)])
        self.assertEqual([e["kind"] for e in src["excluded"]], ["byline", "front"])

    def test_nothing_is_set_aside_without_a_long_paragraph(self):
        src = assemble([B("para", "By Lucas Jang"), B("para", "Short one."), B("para", "PUBLIUS.")])
        self.assertEqual(len(src["paragraphs"]), 3)
        self.assertEqual(src["excluded"], [])

    def test_a_long_paragraph_has_twelve_words(self):
        twelve, eleven = " ".join(["word"] * 12), " ".join(["word"] * 11)
        src = assemble([B("para", "By Lucas"), B("para", twelve)])
        self.assertEqual(src["excluded"], [{"kind": "byline", "text": "By Lucas"}])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [twelve])
        src = assemble([B("para", "By Lucas"), B("para", eleven), B("para", LONG1)])
        self.assertEqual([e["kind"] for e in src["excluded"]], ["byline", "front"])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1])

    def test_keep_short_keeps_a_four_word_opening_paragraph_as_p1(self):
        blocks = [B("para", "Four words right here"), B("para", LONG1)]
        kept = assemble_source(blocks, title_hint="t", source_name="t.md", source_kind="md",
                               keep_short=True)
        self.assertEqual(kept["paragraphs"][0], {"id": "P1", "text": "Four words right here"})
        self.assertEqual(kept["excluded"], [])
        self.assertEqual(assemble(blocks)["paragraphs"][0]["text"], LONG1)  # the default

    def test_keep_short_keeps_a_byline_and_a_sign_off_as_paragraphs(self):
        blocks = [B("para", "By Lucas Jang"), B("para", LONG1), B("para", "PUBLIUS.")]
        kept = assemble_source(blocks, title_hint="t", source_name="t.md", source_kind="md",
                               keep_short=True)
        self.assertEqual([p["text"] for p in kept["paragraphs"]], ["By Lucas Jang", LONG1, "PUBLIUS."])
        self.assertEqual(kept["excluded"], [])

    def test_keep_short_still_finds_the_title_and_cuts_the_references(self):
        src = assemble_source([B("title", "Free Rails"), B("para", "By Lucas"), B("para", LONG1),
                               B("heading", "References", 1), B("para", "Aave 2026.")],
                              title_hint="t", source_name="t.md", source_kind="md", keep_short=True)
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual([p["text"] for p in src["paragraphs"]], ["By Lucas", LONG1])
        self.assertEqual([e["kind"] for e in src["excluded"]], ["references"])

    def test_short_lines_after_the_last_long_paragraph_are_closing(self):
        src = assemble([B("para", LONG1), B("para", LONG2), B("para", "Thanks for reading."),
                        B("para", "PUBLIUS.")])
        self.assertEqual(src["excluded"], [{"kind": "closing", "text": "Thanks for reading."},
                                           {"kind": "closing", "text": "PUBLIUS."}])
        self.assertEqual(len(src["paragraphs"]), 2)

    def test_closing_means_one_to_four_words_after_the_last_long_paragraph(self):
        src = assemble([B("para", LONG1), B("para", "Interlude."), B("para", LONG2),
                        B("para", "This is a short ending.")])  # five words
        self.assertEqual(len(src["paragraphs"]), 4)
        self.assertEqual(src["excluded"], [])
        src = assemble([B("para", LONG1), B("para", "This is the end.")])  # four words
        self.assertEqual(src["excluded"], [{"kind": "closing", "text": "This is the end."}])

    def test_set_aside_text_is_listed_in_document_order(self):
        # The title block keeps "One" a section heading, so "Detail" is a subheading.
        src = assemble([B("title", "Free Rails"), B("para", "By Lucas"), B("heading", "One", 1),
                        B("para", LONG1), B("heading", "Detail", 2), B("para", LONG2),
                        B("para", "PUBLIUS."), B("heading", "Notes", 1), B("para", "n1")])
        self.assertEqual([(e["kind"], e["text"]) for e in src["excluded"]],
                         [("byline", "By Lucas"), ("subheading", "Detail"),
                          ("closing", "PUBLIUS."), ("references", "Notes\nn1")])


class CaptionTests(unittest.TestCase):
    # Body sentences that happen to open with a label. They are not captions.
    FIGURE_SENTENCE = ("Figure 1 shows that rents rise across the sample, which supports the first "
                       "claim.")
    TABLE_SENTENCE = "Table 2 lists which crops grow best on each slope in this valley."

    def test_figure_captions(self):
        for caption in ("Figure 1: Fees", "Fig. 3: Fees over time", "FIGURE 4", "figure 5 - fees",
                        "그림3. 수수료", "Fig.2"):
            with self.subTest(caption):
                src = assemble([B("para", LONG1), B("para", caption), B("para", LONG2)])
                self.assertEqual(src["figures"], [{"id": "F1", "caption": caption, "after": "P1"}])
                self.assertEqual(len(src["paragraphs"]), 2)

    def test_a_sentence_that_opens_with_a_label_is_body_text(self):
        for sentence in (self.FIGURE_SENTENCE, self.TABLE_SENTENCE):
            with self.subTest(sentence):
                src = assemble([B("para", LONG1), B("para", sentence), B("para", LONG2)])
                self.assertEqual((src["figures"], src["tables"]), ([], []))
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, sentence, LONG2])
                self.assertEqual(src["excluded"], [])

    def test_a_sentence_beside_a_table_is_not_its_caption(self):
        src = assemble([B("para", LONG1), B("para", self.TABLE_SENTENCE), B("table", "a | b"),
                        B("para", LONG2)])
        self.assertEqual(src["tables"], [{"id": "T1", "caption": "", "after": "P2", "text": "a | b"}])
        self.assertEqual(len(src["paragraphs"]), 3)

    def test_lines_that_read_like_captions_are_captions(self):
        figures = ("Figure 1: Relay costs and message volumes by year",
                   "Figure 3 Median relay costs across the largest message rails",
                   "그림 2 수수료 추이",
                   "Fig. 4 \N{EM DASH} Solver margins")
        for caption in figures:
            with self.subTest(caption):
                src = assemble([B("para", LONG1), B("para", caption), B("para", LONG2)])
                self.assertEqual(src["figures"], [{"id": "F1", "caption": caption, "after": "P1"}])
                self.assertEqual(len(src["paragraphs"]), 2)
        caption = "표 1. 보관, 중계, 수수료 배분"
        src = assemble([B("para", LONG1), B("para", caption), B("table", "a | b"), B("para", LONG2)])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": caption, "after": "P1", "text": "a | b"}])
        self.assertEqual(len(src["paragraphs"]), 2)

    def test_a_mark_after_the_number_makes_a_caption_whatever_follows(self):
        marks = (":", ".", ")", "-", "\N{EN DASH}", "\N{EM DASH}")
        for mark in marks:
            for space in ("", " "):
                caption = f"Figure 2{space}{mark} Rents were flat across the sample and then rose."
                with self.subTest(caption):
                    src = assemble([B("para", LONG1), B("para", caption), B("para", LONG2)])
                    self.assertEqual([f["caption"] for f in src["figures"]], [caption])

    def test_a_title_like_line_has_at_most_fifteen_words_and_does_not_end_like_a_sentence(self):
        fifteen = "Figure 3 " + " ".join(["w"] * 13)
        cases = [(fifteen, True), (fifteen + " w", False),
                 (fifteen + ".", False), (fifteen + "?", False), (fifteen + "!", False),
                 ("Figure 3 Fees by chain", True), ("Figure 3 Why do rents rise?", False)]
        for text, is_caption in cases:
            with self.subTest(text[-24:]):
                src = assemble([B("para", LONG1), B("para", text), B("para", LONG2)])
                self.assertEqual(len(src["figures"]), 1 if is_caption else 0)
                self.assertEqual(len(src["paragraphs"]), 2 if is_caption else 3)

    def test_a_decimal_label_number_is_read_whole(self):
        # The full stop of "1.5" is part of the number, not a mark after it.
        for label in ("Figure", "Table"):
            sentence = f"{label} 1.5 percent of the seeds sprout before the first frost."
            with self.subTest(sentence):
                src = assemble([B("para", LONG1), B("para", sentence), B("para", LONG2)])
                self.assertEqual((src["figures"], src["tables"]), ([], []))
                self.assertEqual(len(src["paragraphs"]), 3)
        for caption in ("Figure 2.1: Fees by chain", "Figure 2.1 Fees by chain"):
            with self.subTest(caption):
                src = assemble([B("para", LONG1), B("para", caption), B("para", LONG2)])
                self.assertEqual([f["caption"] for f in src["figures"]], [caption])
        for caption in ("Table 2.1: Fees by chain", "Table 2.1 Fees by chain"):
            with self.subTest(caption):
                src = assemble([B("para", LONG1), B("para", caption), B("para", LONG2)])
                self.assertEqual([t["caption"] for t in src["tables"]], [caption])

    def test_a_sentence_that_opens_with_a_label_is_ordinary_text_for_front_and_closing(self):
        # It is a long paragraph, so it ends the front matter instead of being skipped ...
        src = assemble([B("para", self.FIGURE_SENTENCE), B("para", "By Lucas"), B("para", LONG1)])
        self.assertEqual([p["text"] for p in src["paragraphs"]],
                         [self.FIGURE_SENTENCE, "By Lucas", LONG1])
        self.assertEqual(src["excluded"], [])
        # ... and a short one is a closing line like any other short line.
        src = assemble([B("para", LONG1), B("para", "Table 2 shows it.")])
        self.assertEqual(src["excluded"], [{"kind": "closing", "text": "Table 2 shows it."}])
        self.assertEqual(src["tables"], [])

    def test_lines_that_only_look_like_captions_stay_text(self):
        too_long = "Figure 1 shows " + " ".join(["word"] * 30)
        for text in ("Figures 1 and 2 show the trend.", "Figure out the fee quickly.",
                     "Tablet 3 is on sale", too_long):
            with self.subTest(text):
                src = assemble([B("para", LONG1), B("para", text), B("para", LONG2)])
                self.assertEqual((src["figures"], src["tables"]), ([], []))
                self.assertEqual(len(src["paragraphs"]), 3)

    def test_a_caption_after_the_last_long_paragraph_is_a_caption_not_a_closing_line(self):
        src = assemble([B("para", LONG1), B("para", "Figure 3: Fees")])
        self.assertEqual(src["figures"], [{"id": "F1", "caption": "Figure 3: Fees", "after": "P1"}])
        self.assertEqual(src["excluded"], [])
        src = assemble([B("para", LONG1), B("para", "Table 2: Costs"), B("table", "a | b")])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": "Table 2: Costs", "after": "P1", "text": "a | b"}])
        self.assertEqual(src["excluded"], [])

    def test_a_caption_before_the_first_long_paragraph_is_a_caption_not_front_matter(self):
        src = assemble([B("para", "Figure 1: Fees"), B("para", "By Lucas"), B("para", LONG1)])
        self.assertEqual(src["figures"], [{"id": "F1", "caption": "Figure 1: Fees", "after": None}])
        self.assertEqual(src["excluded"], [{"kind": "byline", "text": "By Lucas"}])

    def test_closing_lines_after_a_caption_are_still_closing_lines(self):
        src = assemble([B("para", LONG1), B("para", "Figure 1: Fees"), B("para", "PUBLIUS.")])
        self.assertEqual(len(src["figures"]), 1)
        self.assertEqual(src["excluded"], [{"kind": "closing", "text": "PUBLIUS."}])

    def test_a_long_caption_does_not_end_the_front_matter(self):
        caption = "Figure 1: " + " ".join(["w"] * 11)  # thirteen words
        src = assemble([B("para", caption), B("para", "By Lucas"), B("para", LONG1)])
        self.assertEqual(len(src["figures"]), 1)
        self.assertEqual(src["excluded"], [{"kind": "byline", "text": "By Lucas"}])

    def test_a_paragraph_over_thirty_words_that_opens_like_a_caption_is_body_text(self):
        body = "Figure 1 shows " + " ".join(["word"] * 30)
        src = assemble([B("para", "By Lucas"), B("para", body)])
        self.assertEqual(src["excluded"], [{"kind": "byline", "text": "By Lucas"}])
        self.assertEqual([p["text"] for p in src["paragraphs"]], [body])

    def test_a_caption_has_at_most_thirty_words(self):
        thirty, thirty_one = "Figure 1: " + " ".join(["w"] * 28), "Figure 1: " + " ".join(["w"] * 29)
        figures = [assemble([B("para", LONG1), B("para", text), B("para", LONG2)])["figures"]
                   for text in (thirty, thirty_one)]
        self.assertEqual(figures, [[{"id": "F1", "caption": thirty, "after": "P1"}], []])

    def test_a_table_caption_above_its_table(self):
        src = assemble([B("para", LONG1), B("para", "Table 1: Owners."), B("table", "a | b"),
                        B("para", LONG2)])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": "Table 1: Owners.", "after": "P1", "text": "a | b"}])
        self.assertEqual(len(src["paragraphs"]), 2)

    def test_table_captions_may_be_in_any_case_and_without_a_space(self):
        for caption in ("TABLE 2: Costs", "table 3", "Table4.", "표2"):
            with self.subTest(caption):
                src = assemble([B("para", LONG1), B("para", caption), B("table", "a | b"),
                                B("para", LONG2)])
                self.assertEqual([(t["caption"], t["text"]) for t in src["tables"]],
                                 [(caption, "a | b")])

    def test_a_table_caption_below_its_table(self):
        src = assemble([B("para", LONG1), B("table", "a | b"), B("para", "표 1: 소유자"),
                        B("para", LONG2)])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": "표 1: 소유자", "after": "P1", "text": "a | b"}])

    def test_a_caption_prefers_the_table_after_it(self):
        src = assemble([B("para", LONG1), B("table", "x | y"), B("para", "Table 1: Z"),
                        B("table", "a | b"), B("para", LONG2)])
        self.assertEqual([(t["id"], t["caption"], t["text"]) for t in src["tables"]],
                         [("T1", "", "x | y"), ("T2", "Table 1: Z", "a | b")])

    def test_a_table_has_one_caption_and_no_text_is_lost(self):
        src = assemble([B("para", LONG1), B("para", "Table 1: A"), B("table", "a | b"),
                        B("para", "Table 2: B"), B("para", LONG2)])
        self.assertEqual([(t["id"], t["caption"], t["text"]) for t in src["tables"]],
                         [("T1", "Table 1: A", "a | b"), ("T2", "Table 2: B", "")])

    def test_a_table_caption_beside_no_table_is_a_caption_only_table(self):
        src = assemble([B("para", LONG1), B("para", "Table 3: Missing."), B("para", LONG2)])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": "Table 3: Missing.", "after": "P1", "text": ""}])
        self.assertEqual(len(src["paragraphs"]), 2)

    def test_a_heading_between_a_caption_and_a_table_separates_them(self):
        src = assemble([B("para", LONG1), B("para", "Table 1: Z"), B("heading", "Next", 1),
                        B("table", "a | b"), B("para", LONG2)])
        self.assertEqual([(t["caption"], t["text"]) for t in src["tables"]],
                         [("Table 1: Z", ""), ("", "a | b")])

    def test_items_are_numbered_in_order_and_follow_the_last_paragraph(self):
        src = assemble([B("table", "a | b"), B("para", LONG1), B("para", "Figure 7: A"),
                        B("table", "c | d"), B("para", LONG2), B("para", "Figure 9: B"),
                        B("para", LONG3)])
        self.assertEqual(src["tables"], [
            {"id": "T1", "caption": "", "after": None, "text": "a | b"},
            {"id": "T2", "caption": "", "after": "P1", "text": "c | d"}])
        self.assertEqual(src["figures"], [
            {"id": "F1", "caption": "Figure 7: A", "after": "P1"},
            {"id": "F2", "caption": "Figure 9: B", "after": "P2"}])


class SectionTests(unittest.TestCase):
    def test_deeper_headings_are_set_aside_as_subheadings(self):
        src = assemble([B("heading", "One", 2), B("para", LONG1), B("heading", "Detail", 3),
                        B("para", LONG2), B("heading", "Two", 2), B("para", LONG3)])
        self.assertEqual(src["sections"], [{"title": "One", "first": "P1", "last": "P2"},
                                           {"title": "Two", "first": "P3", "last": "P3"}])
        self.assertEqual(src["excluded"], [{"kind": "subheading", "text": "Detail"}])

    def test_paragraphs_before_the_first_heading_are_an_untitled_section_and_empty_ones_go(self):
        src = assemble([B("para", LONG1), B("heading", "Empty", 1), B("heading", "Full", 1),
                        B("para", LONG2), B("heading", "Also empty", 1)])
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P1"},
                                           {"title": "Full", "first": "P2", "last": "P2"}])
        # Nothing leaves the map unlisted: the heading of a section left empty is listed (R72).
        self.assertEqual(src["excluded"], [{"kind": "heading", "text": "Empty"},
                                           {"kind": "heading", "text": "Also empty"}])

    def test_a_section_emptied_by_a_closing_line_lists_its_heading(self):
        src = assemble([B("heading", "Fees", 2), B("para", LONG1), B("heading", "Detail", 3),
                        B("para", LONG2), B("heading", "Conclusion", 2), B("para", "Thanks.")])
        self.assertEqual([s["title"] for s in src["sections"]], ["Fees"])
        self.assertEqual(src["excluded"], [{"kind": "subheading", "text": "Detail"},
                                           {"kind": "heading", "text": "Conclusion"},
                                           {"kind": "closing", "text": "Thanks."}])

    def test_a_long_paragraph_right_over_a_rule_is_kept(self):
        # The repro of R72: the second paragraph became an empty "##" heading, and its section
        # was dropped without a trace, with exit 0.
        drafts = read_both(LONG1 + "\n\n" + LONG2 + "\n---\n", P(LONG1) + P(LONG2))
        for name, src in drafts:
            with self.subTest(name):
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual((src["sections"], src["excluded"]), ([], []))

    def test_a_draft_without_headings_has_no_sections(self):
        src = assemble([B("para", LONG1), B("para", LONG2)])
        self.assertEqual(src["sections"], [])
        self.assertEqual(len(src["paragraphs"]), 2)

    def test_a_title_block_and_the_references_are_not_section_headings(self):
        src = assemble([B("title", "Free Rails"), B("para", LONG1), B("heading", "References", 1),
                        B("para", "Aave (2026) ...")])
        self.assertEqual(src["sections"], [])
        self.assertEqual(len(src["paragraphs"]), 1)

    def test_one_heading_is_enough_for_the_untitled_lead_section(self):
        src = assemble([B("para", LONG1), B("para", LONG2), B("heading", "Last", 1),
                        B("para", LONG3)])
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P2"},
                                           {"title": "Last", "first": "P3", "last": "P3"}])

    def test_a_draft_without_paragraphs_has_no_sections(self):
        for blocks in ([], [B("heading", "Lonely", 1)]):
            with self.subTest(blocks):
                src = assemble(blocks)
                self.assertEqual((src["paragraphs"], src["sections"]), ([], []))
                self.assertEqual(src["essay"]["paragraph_count"], 0)
                self.assertEqual(src["essay"]["word_count"], 0)


class SourceShapeTests(unittest.TestCase):
    def test_shape(self):
        src = assemble_source([B("para", LONG1)], title_hint="T", source_name="t.md", source_kind="md")
        self.assertEqual(list(src), ["schema", "essay", "paragraphs", "tables", "figures",
                                     "sections", "excluded"])
        self.assertEqual(src["schema"], "throughmap-source/1")
        self.assertEqual(list(src["essay"]), ["title", "source", "source_kind", "word_count",
                                              "paragraph_count"])
        self.assertEqual(src["essay"], {"title": "T", "source": "t.md", "source_kind": "md",
                                        "word_count": word_count(LONG1), "paragraph_count": 1})

    def test_paragraph_text_is_kept_exactly(self):
        text = "“Free rails” — it’s 5–6 bps… 한국어 sof\N{SOFT HYPHEN}t, and a few more words here."
        self.assertEqual(assemble([B("para", text)])["paragraphs"], [{"id": "P1", "text": text}])

    def test_the_blocks_are_not_changed(self):
        blocks = [B("title", "T"), B("para", LONG1), B("heading", "H", 1), B("para", "PUBLIUS.")]
        before = copy.deepcopy(blocks)
        assemble(blocks)
        self.assertEqual(blocks, before)

    def test_the_source_is_plain_json(self):
        self.assertEqual(json.loads(json.dumps(FORTY_FIVE)), FORTY_FIVE)

    def test_the_title_flag_survives_corrections_and_a_section_choice(self):
        titled = assemble([B("title", "Free Rails"), B("heading", "A", 1), B("para", LONG1),
                           B("heading", "B", 1), B("para", LONG2)])
        self.assertTrue(apply_corrections(titled, drops=["P2"]).title_from_block)
        self.assertTrue(select_section(titled, "A").title_from_block)
        untitled = assemble([B("para", LONG1), B("heading", "A", 1), B("para", LONG2)])
        self.assertFalse(apply_corrections(untitled, drops=["P1"]).title_from_block)
        self.assertFalse(select_section(untitled, "A").title_from_block)


WITH_ITEMS = assemble([B("para", T1), B("para", T2), B("para", T3), B("para", "Table 1: Owners."),
                       B("table", "a | b"), B("para", T4), B("para", "Figure 1: Fees"),
                       B("para", T5)])  # table T1 follows P3, figure F1 follows P4


class CorrectionTests(unittest.TestCase):
    def texts(self, source):
        return [p["text"] for p in source["paragraphs"]]

    def test_ids_are_renumbered_and_sections_rebuilt(self):
        out = apply_corrections(FIVE_TWO_SECTIONS, joins=[("P1", "P2")], drops=["P5"])
        self.assertEqual([p["id"] for p in out["paragraphs"]], ["P1", "P2", "P3"])
        self.assertEqual(out["sections"], [{"title": "First", "first": "P1", "last": "P1"},
                                           {"title": "Second", "first": "P2", "last": "P3"}])

    def test_a_draft_without_sections_can_still_be_corrected(self):
        out = apply_corrections(FIVE, joins=[("P1", "P2")], drops=["P5"])
        self.assertEqual((self.texts(out), out["sections"]), ([T1 + " " + T2, T3, T4], []))

    def test_a_section_left_with_no_paragraphs_is_removed(self):
        out = apply_corrections(FIVE_TWO_SECTIONS, drops=["P1", "P2"])
        self.assertEqual(out["sections"], [{"title": "Second", "first": "P1", "last": "P3"}])

    def test_counts_follow_the_corrections(self):
        out = apply_corrections(FIVE, drops=["P1", "P5"])
        self.assertEqual(out["essay"]["paragraph_count"], 3)
        self.assertEqual(out["essay"]["word_count"], sum(word_count(t) for t in (T2, T3, T4)))

    def test_chained_joins_make_one_paragraph(self):
        out = apply_corrections(FIVE, joins=[("P1", "P2"), ("P2", "P3")])
        self.assertEqual(self.texts(out), [" ".join((T1, T2, T3)), T4, T5])

    def test_a_paragraph_can_be_split_more_than_once(self):
        out = apply_corrections(FIVE, splits=[("P4", "However,"), ("P4", "the neighbours")])
        self.assertEqual(self.texts(out),
                         [T1, T2, T3, T4_BEFORE, "However,", T4_AFTER.strip(), T5])

    def test_a_join_and_a_split_can_move_a_boundary(self):
        out = apply_corrections(FIVE, joins=[("P3", "P4")], splits=[("P4", "However,")])
        self.assertEqual(self.texts(out),
                         [T1, T2, T3 + " " + T4_BEFORE, "However," + T4_AFTER, T5])

    def test_the_cut_is_a_raw_search(self):
        out = apply_corrections(hand_made("Rents stay low. Then rents rise."), splits=[("P1", "Then")])
        self.assertEqual(self.texts(out), ["Rents stay low.", "Then rents rise."])
        with self.assertRaisesRegex(CorrectionError, "not found"):
            apply_corrections(hand_made("Rents stay low. Then rents rise."), splits=[("P1", "then")])

    def test_split_pieces_are_stripped_and_a_join_uses_one_space(self):
        out = apply_corrections(hand_made("First half.     However, second half."),
                                splits=[("P1", "However,")])
        self.assertEqual(self.texts(out), ["First half.", "However, second half."])
        out = apply_corrections(hand_made("A   ", "  B  "), joins=[("P1", "P2")])
        self.assertEqual(self.texts(out), ["A B"])

    def test_a_paragraph_nobody_touches_keeps_its_exact_text(self):
        out = apply_corrections(hand_made(" X  y ", "Z"), drops=["P2"])
        self.assertEqual(self.texts(out), [" X  y "])

    def test_tables_and_figures_follow_the_paragraph_they_followed(self):
        def after(out):
            return out["tables"][0]["after"], out["figures"][0]["after"]

        self.assertEqual(after(WITH_ITEMS), ("P3", "P4"))
        self.assertEqual(after(apply_corrections(WITH_ITEMS, drops=["P3"])), ("P2", "P3"))
        self.assertEqual(after(apply_corrections(WITH_ITEMS, joins=[("P2", "P3")])), ("P2", "P3"))
        self.assertEqual(after(apply_corrections(WITH_ITEMS, splits=[("P4", "However,")])),
                         ("P3", "P5"))
        # With nothing left before it, an item follows no paragraph.
        self.assertEqual(after(apply_corrections(WITH_ITEMS, drops=["P1", "P2", "P3"])), (None, "P1"))
        out = apply_corrections(WITH_ITEMS, drops=["P1"])
        self.assertEqual(out["tables"][0], {"id": "T1", "caption": "Table 1: Owners.", "after": "P2",
                                            "text": "a | b"})

    def test_dropped_paragraphs_join_the_excluded_list_in_document_order(self):
        src = assemble([B("para", "By Lucas"), *(B("para", text) for text in (T1, T2, T3))])
        out = apply_corrections(src, drops=["P3", "P1"])
        self.assertEqual(out["excluded"], [{"kind": "byline", "text": "By Lucas"},
                                           {"kind": "dropped", "text": T1},
                                           {"kind": "dropped", "text": T3}])

    def test_the_source_is_not_changed(self):
        before = copy.deepcopy(FIVE_TWO_SECTIONS)
        apply_corrections(FIVE_TWO_SECTIONS, joins=[("P1", "P2")], splits=[("P4", "However,")],
                          drops=["P5"])
        self.assertEqual(FIVE_TWO_SECTIONS, before)

    def test_no_corrections_give_an_equal_copy(self):
        out = apply_corrections(FORTY_FIVE)
        self.assertEqual(out, FORTY_FIVE)
        self.assertIsNot(out, FORTY_FIVE)

    def test_errors_name_the_problem(self):
        self.assertTrue(issubclass(CorrectionError, ValueError))
        cases = [
            (dict(joins=[("P3", "P2")]), "not adjacent"),       # the earlier paragraph goes first
            (dict(joins=[("P2", "P2")]), "not adjacent"),
            (dict(joins=[("P1", "P99")]), "P99"),
            (dict(splits=[("P99", "x")]), "P99"),
            (dict(drops=["P99"]), "P99"),
            (dict(splits=[("P2", T2)]), "starts"),              # a cut at position 0
            (dict(splits=[("P2", "")]), "starts"),
            (dict(drops=["P2"], joins=[("P2", "P3")]), "dropped"),
            (dict(drops=["P3"], joins=[("P2", "P3")]), "dropped"),
            (dict(drops=["P4"], splits=[("P4", "However,")]), "dropped"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs), self.assertRaisesRegex(CorrectionError, message):
                apply_corrections(FIVE, **kwargs)


class SelectSectionTests(unittest.TestCase):
    def test_by_number_or_exact_title(self):
        for which in ("2", "Two"):
            with self.subTest(which):
                sel = select_section(FORTY_FIVE, which)
                self.assertEqual([p["id"] for p in sel["paragraphs"]],
                                 [f"P{n}" for n in range(16, 31)])
                self.assertEqual(sel["sections"], [{"title": "Two", "first": "P16", "last": "P30"}])
                self.assertEqual(sel["essay"]["selected_section"], "Two")

    def test_the_counts_describe_the_selected_paragraphs(self):
        sel = select_section(FORTY_FIVE, "Two")
        self.assertEqual(sel["essay"]["paragraph_count"], 15)
        self.assertEqual(sel["essay"]["word_count"],
                         sum(word_count(p["text"]) for p in sel["paragraphs"]))
        self.assertEqual(FORTY_FIVE["essay"]["paragraph_count"], 45)  # the source is untouched

    def test_the_untitled_lead_section_is_number_one_or_the_empty_title(self):
        src = assemble([B("para", LONG1), B("heading", "Next", 1), B("para", LONG2)])
        for which in ("1", ""):
            with self.subTest(which):
                sel = select_section(src, which)
                self.assertEqual(sel["essay"]["selected_section"], "")
                self.assertEqual([p["id"] for p in sel["paragraphs"]], ["P1"])

    def test_tables_and_figures_stay_with_the_paragraph_they_follow(self):
        src = assemble([B("heading", "A", 1), B("table", "t | 0"), B("para", LONG1),
                        B("para", "Figure 1: F"), B("para", LONG2), B("heading", "B", 1),
                        B("para", LONG3), B("para", "Table 1: T"), B("table", "x | y"),
                        B("para", LONG4)])
        first, second = select_section(src, "A"), select_section(src, "B")
        # T1 follows no paragraph, so it stays with the first section.
        self.assertEqual(([t["id"] for t in first["tables"]], [f["id"] for f in first["figures"]]),
                         (["T1"], ["F1"]))
        self.assertEqual(([t["id"] for t in second["tables"]], second["figures"]), (["T2"], []))

    def test_a_title_that_is_a_number_is_found_by_title_when_it_is_no_section_number(self):
        src = assemble([B("heading", "2020", 1), B("para", LONG1), B("heading", "2021", 1),
                        B("para", LONG2)])
        self.assertEqual(select_section(src, "2021")["paragraphs"][0]["id"], "P2")

    def test_a_draft_without_headings_has_no_section_to_choose(self):
        for which in ("1", ""):
            with self.subTest(which):
                with self.assertRaisesRegex(CorrectionError, "no section headings"):
                    select_section(FIVE, which)

    def test_a_section_number_wins_over_a_title(self):
        src = assemble([B("heading", "x", 1), B("para", LONG1), B("heading", "1", 1),
                        B("para", LONG2)])
        self.assertEqual(select_section(src, "1")["essay"]["selected_section"], "x")

    def test_choices_that_match_no_single_section(self):
        twin = assemble([B("heading", "Same", 1), B("para", LONG1), B("heading", "Same", 1),
                         B("para", LONG2)])
        with self.assertRaisesRegex(CorrectionError, "several"):
            select_section(twin, "Same")
        self.assertEqual(select_section(twin, "2")["paragraphs"][0]["id"], "P2")
        for which in ("Nope", "0", "4", "9" * 5000, "two"):
            with self.subTest(which[:12]), self.assertRaises(CorrectionError):
                select_section(FORTY_FIVE, which)


class ResolveOutDirTests(unittest.TestCase):
    BASE = os.path.join(tempfile.gettempdir(), "essays")

    def test_relative_paths_are_resolved_against_the_working_directory(self):
        self.assertEqual(resolve_out_dir("a.md", None, None, self.BASE),
                         os.path.join(self.BASE, "a.throughmap"))
        self.assertEqual(resolve_out_dir(os.path.join("docs", "a.md"), None, None, self.BASE),
                         os.path.join(self.BASE, "docs", "a.throughmap"))

    def test_only_the_last_suffix_is_dropped_from_the_stem(self):
        path = os.path.join(self.BASE, "draft.v2.markdown")
        self.assertEqual(resolve_out_dir(path, None, None, "/cwd"),
                         os.path.join(self.BASE, "draft.v2.throughmap"))

    def test_out_beats_a_file_and_a_file_beats_a_name(self):
        path = os.path.join(self.BASE, "a.md")
        self.assertEqual(resolve_out_dir(path, "Other", "/o", "/cwd"), "/o")
        self.assertEqual(resolve_out_dir(None, None, "/o", "/cwd"), "/o")
        self.assertEqual(resolve_out_dir(path, "Other", None, "/cwd"),
                         os.path.join(self.BASE, "a.throughmap"))

    def test_the_name_becomes_a_slug(self):
        self.assertEqual(resolve_out_dir(None, "자유 레일!", None, "/cwd"),
                         os.path.join("/cwd", "자유-레일.throughmap"))
        self.assertEqual(resolve_out_dir(None, "!!!", None, "/cwd"),
                         os.path.join("/cwd", "essay.throughmap"))


class ExtractPathTests(unittest.TestCase):
    def write(self, name, text, encoding="utf-8"):
        path = os.path.join(tmp_dir(), name)
        with open(path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        return path

    def test_each_suffix_picks_its_reader(self):
        markdown = "# Free Rails\n\n## One\n\n" + LONG1 + "\n\n" + LONG2 + "\n"
        plain = LONG1 + "\n\n" + LONG2 + "\n"
        cases = [("essay.md", "md", markdown), ("essay.markdown", "md", markdown),
                 ("ESSAY.MD", "md", markdown), ("essay.txt", "txt", plain)]
        for name, kind, text in cases:
            with self.subTest(name):
                src = extract_path(self.write(name, text))
                self.assertEqual((src["essay"]["source"], src["essay"]["source_kind"]), (name, kind))
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])

    def test_a_text_file_is_plain_and_a_markdown_file_is_not(self):
        text = ("Use *stars* and [a link](http://x) as plain text, because nothing in a text file "
                "is interpreted.")
        marked_up = ("Use stars and a link as plain text, because nothing in a text file "
                     "is interpreted.")
        self.assertEqual([p["text"] for p in extract_path(self.write("a.txt", text))["paragraphs"]],
                         [text])
        self.assertEqual([p["text"] for p in extract_path(self.write("a.md", text))["paragraphs"]],
                         [marked_up])

    def test_a_word_document_with_everything_in_it(self):
        path = os.path.join(tmp_dir(), "draft.docx")
        body = (P("Free Rails", "Title") + P("By Lucas Jang") + P("Intro", "Heading1") + P(LONG1)
                + P("Table 1: Owners.") + TABLE([["a", "b"], ["c", "d"]]) + P(LONG2)
                + P("References", "Heading1") + P("Aave (2026) ..."))
        make_docx(path, body, STYLES_EN)
        src = extract_path(path)
        self.assertEqual((src["essay"]["title"], src["essay"]["source"], src["essay"]["source_kind"]),
                         ("Free Rails", "draft.docx", "docx"))
        self.assertEqual(src["sections"], [{"title": "Intro", "first": "P1", "last": "P2"}])
        self.assertEqual(src["tables"], [{"id": "T1", "caption": "Table 1: Owners.", "after": "P1",
                                          "text": "a | b\nc | d"}])
        self.assertEqual([e["kind"] for e in src["excluded"]], ["byline", "references"])

    def test_the_title_comes_from_the_text_then_the_hint_then_the_file_name(self):
        plain = self.write("my essay.txt", LONG1)
        self.assertEqual(extract_path(plain)["essay"]["title"], "my essay")
        self.assertEqual(extract_path(plain, title_hint="Free Rails")["essay"]["title"], "Free Rails")
        titled = self.write("t.md", "# Real Title\n\n## Part\n\n" + LONG1)
        self.assertEqual(extract_path(titled, title_hint="Hint")["essay"]["title"], "Real Title")

    def test_a_text_file_with_one_paragraph_per_line(self):
        # As Word's "Save as Plain Text" and Notepad write it: CRLF and no blank lines. Each line
        # is a paragraph, so the title and byline lines are front matter as usual.
        path = self.write("my essay.txt", "\r\n".join(["Free Rails", "By Sam Rivera", LONG1, LONG2,
                                                     "PUBLIUS."]) + "\r\n")
        src = extract_path(path)
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
        self.assertEqual(src["excluded"], [{"kind": "front", "text": "Free Rails"},
                                           {"kind": "byline", "text": "By Sam Rivera"},
                                           {"kind": "closing", "text": "PUBLIUS."}])
        self.assertEqual((src["essay"]["title"], src["sections"]), ("my essay", []))

    def test_a_word_text_export_with_a_blank_line_after_its_title(self):
        path = self.write("export.txt", "\r\n".join(["Free Rails", "", LONG1, LONG2, LONG3]) + "\r\n")
        src = extract_path(path)
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3])
        self.assertEqual(src["excluded"], [{"kind": "front", "text": "Free Rails"}])

    def test_a_word_text_export_with_heading_lines(self):
        # One paragraph per long line; the heading line between them marks a section (R72).
        path = self.write("export.txt", "\r\n".join(
            ["Free Rails", "", "Introduction", LONG1, LONG2, "Analysis", LONG3, LONG4]) + "\r\n")
        src = extract_path(path)
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3, LONG4])
        self.assertEqual(src["sections"], [{"title": "", "first": "P1", "last": "P2"},
                                           {"title": "Analysis", "first": "P3", "last": "P4"}])
        self.assertEqual(src["excluded"], [{"kind": "front", "text": "Free Rails"},
                                           {"kind": "front", "text": "Introduction"}])

    def test_a_wrapped_paragraph_in_a_text_file_is_not_torn(self):
        # R73: a wrapped paragraph whose one long line is its last stays one paragraph, and no
        # fragment of it becomes a section.
        wrapped = ("The members of a choir can vote to sing on a\n"
                   "night in every month, but the singers would then rest on Sundays.")
        src = extract_path(self.write("wrapped.txt", "\n\n".join([LONG1, wrapped, LONG2]) + "\n"))
        self.assertEqual([p["text"] for p in src["paragraphs"]],
                         [LONG1, " ".join(wrapped.split()), LONG2])
        self.assertEqual((src["sections"], src["excluded"]), ([], []))

    def test_captions_in_a_line_by_line_text_file_are_captions(self):
        text = "\n".join([LONG1, "Figure 1: Fees by year", LONG2, "Table 1: Owners of each rail",
                          LONG3])
        src = extract_path(self.write("captions.txt", text + "\n"))
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3])
        self.assertEqual(src["figures"], [{"id": "F1", "caption": "Figure 1: Fees by year",
                                           "after": "P1"}])
        self.assertEqual(src["tables"], [{"id": "T1", "caption": "Table 1: Owners of each rail",
                                          "after": "P2", "text": ""}])
        self.assertEqual(src["sections"], [])

    def test_a_hard_wrapped_text_file_with_no_blank_line_has_no_sections(self):
        lines = ["The gardens grow each spring between the houses, and every garden needs",
                 "a plot of its own",
                 "that gets sun. The neighbours want a rota that would let them water each one",
                 "Of the gardens",
                 "and share the beans that the gardens grow with the people who tend them."]
        src = extract_path(self.write("wrapped.txt", "\n".join(lines) + "\n"))
        self.assertEqual(src["sections"], [])
        self.assertFalse([e for e in src["excluded"] if e["kind"] == "heading"])

    def test_a_long_or_question_title_over_equals_signs_is_the_title(self):
        sixteen = ("Why the Old Gardens That Line Every Street Between Two Rivers Will Always "
                   "Need Their Neighbours")
        for title in (sixteen, "Why do rents rise?"):
            with self.subTest(title[:20]):
                path = self.write("titled.md", f"{title}\n=====\n\n{LONG1}\n\n{LONG2}\n")
                src = extract_path(path)
                self.assertEqual(src["essay"]["title"], title)
                self.assertTrue(src.title_from_block)
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])

    def test_a_blog_post_with_front_matter(self):
        # Jekyll and Hugo posts open with YAML front matter; the layout prints the title.
        path = self.write("post.md", "\n".join([
            "---", "layout: post", 'title: "Free Rails"', "date: 2026-10-01 09:00:00 +0900",
            "categories: [rails, fees]", "---", "", LONG1, "", "## The switch", "", LONG2,
            "", "## The edges", "", LONG3 + "[^1]", "", "[^1]: A note on the sources."]) + "\n")
        src = extract_path(path, title_hint="the hint")
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertTrue(src.title_from_block)
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2, LONG3])
        self.assertEqual([s["title"] for s in src["sections"]], ["", "The switch", "The edges"])
        # Nothing leaves the map silently: the front matter and the footnote are listed (R70).
        self.assertEqual(src["excluded"], [
            {"kind": "front matter", "text": 'layout: post\ntitle: "Free Rails"\n'
                                             "date: 2026-10-01 09:00:00 +0900\n"
                                             "categories: [rails, fees]"},
            {"kind": "notes", "text": "[^1]: A note on the sources."}])

    def test_a_front_matter_title_over_a_different_level_one_heading_and_level_two_sections(self):
        # Under front matter, a first "#" heading above the body with "##" headings below it is
        # a title line (R69): it is set aside as front, and the "##" headings are the sections.
        path = self.write("post.md", "\n\n".join([
            "---\ntitle: Free Rails\n---", "# Free Rails: A Note on Fees", "## The switch", LONG1,
            "## The edges", LONG2]) + "\n")
        src = extract_path(path)
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual(src["sections"], [{"title": "The switch", "first": "P1", "last": "P1"},
                                           {"title": "The edges", "first": "P2", "last": "P2"}])
        self.assertEqual(src["excluded"], [{"kind": "front matter", "text": "title: Free Rails"},
                                           {"kind": "front", "text": "Free Rails: A Note on Fees"}])
        # With other "#" headings after it, a "#" heading with body under it is a section still.
        path = self.write("parts.md", "\n\n".join([
            "---\ntitle: Free Rails\n---", "# Part One", "## The switch", LONG1, "# Part Two",
            LONG2]) + "\n")
        src = extract_path(path)
        self.assertEqual([s["title"] for s in src["sections"]], ["Part One", "Part Two"])
        self.assertEqual(src["excluded"], [{"kind": "front matter", "text": "title: Free Rails"},
                                           {"kind": "subheading", "text": "The switch"}])

    def test_lines_between_rules_that_are_not_yaml_are_front_lines_as_usual(self):
        cases = {"Note: this draft argues that rents stay low in small towns.":
                     [{"kind": "front",
                       "text": "Note: this draft argues that rents stay low in small towns."}],
                 "To: Board\nFrom: Sam": [{"kind": "front", "text": "To: Board From: Sam"}]}
        for lines, excluded in cases.items():
            with self.subTest(lines):
                path = self.write("memo.md", "---\n" + lines + "\n---\n\n" + LONG1 + "\n\n" + LONG2)
                src = extract_path(path)
                self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1, LONG2])
                self.assertEqual(src["excluded"], excluded)
                self.assertEqual(src["sections"], [])

    def test_keep_short_reaches_the_assembly(self):
        path = self.write("a.md", "By Lucas Jang\n\n" + LONG1 + "\n\nPUBLIUS.\n")
        self.assertEqual(len(extract_path(path)["paragraphs"]), 1)
        self.assertEqual(len(extract_path(path, keep_short=True)["paragraphs"]), 3)

    def test_a_byte_order_mark_and_windows_line_endings(self):
        path = self.write("w.md", BOM + "# Free Rails\r\n\r\n## One\r\n\r\n" + LONG1 + "\r\n")
        src = extract_path(path)
        self.assertEqual(src["essay"]["title"], "Free Rails")
        self.assertEqual([p["text"] for p in src["paragraphs"]], [LONG1])

    def test_files_it_cannot_use_are_refused_with_a_reason(self):
        for name in ("draft.pdf", "draft", "draft.doc"):
            with self.subTest(name), self.assertRaisesRegex(ValueError, r"\.docx"):
                extract_path(os.path.join(tmp_dir(), name))
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            extract_path(self.write("old.txt", KOREAN, encoding="cp949"))
        with self.assertRaisesRegex(ValueError, "not a readable .docx"):
            extract_path(self.write("bad.docx", "not a zip"))
        with self.assertRaises(FileNotFoundError):
            extract_path(os.path.join(tmp_dir(), "missing.md"))


class ExtractCommandTests(unittest.TestCase):
    def md(self, text, name="essay.md"):
        path = os.path.join(tmp_dir(), name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return path

    def source_of(self, path):
        folder = os.path.splitext(path)[0] + ".throughmap"
        return json.loads(Path(folder, "source.json").read_text("utf-8"))

    def test_the_summary_has_three_lines(self):
        path = self.md("\n\n".join([
            "# Free Rails", "By Lucas Jang", "## A Switch", LONG1, "### Detail", LONG2,
            "## Another", "Figure 1: Fees", LONG3, "PUBLIUS."]))
        code, out = run_main(["extract", path])
        words = sum(word_count(text) for text in (LONG1, LONG2, LONG3))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "source: " + os.path.join(os.path.splitext(path)[0] + ".throughmap", "source.json"),
            f"paragraphs: 3 {DOT} tables: 0 {DOT} figures: 1 {DOT} sections: 2 {DOT} words: {words}",
            "set aside: title, byline, subheading, closing",
        ])

    def test_set_aside_counts_kinds_in_document_order_and_leaves_out_captions(self):
        path = self.md("\n\n".join([
            "# Free Rails", "By Lucas Jang", "## One", LONG1, "### First detail", LONG2,
            "### Second detail", "Table 1: Owners.", "| a | b |\n|---|---|\n| 1 | 2 |", LONG3,
            "## Notes", "n1"]))
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[1:], [
            f"paragraphs: 3 {DOT} tables: 1 {DOT} figures: 0 {DOT} sections: 1 {DOT} words: "
            f"{sum(word_count(text) for text in (LONG1, LONG2, LONG3))}",
            "set aside: title, byline, 2 subheadings, references",
        ])

    def test_a_title_from_the_text_stays_in_the_set_aside_line_after_corrections(self):
        path = self.md("# Free Rails\n\n## One\n\n" + LONG1 + "\n\n" + LONG2)
        self.assertEqual(run_main(["extract", path, "--drop", "P2"])[1].splitlines()[-1],
                         "set aside: title, dropped")
        self.assertEqual(run_main(["extract", path, "--section", "One"])[1].splitlines()[-1],
                         "set aside: title")

    def test_a_title_taken_from_the_name_is_not_set_aside(self):
        code, out = run_main(["extract", self.md(LONG1 + "\n\n## One\n\n" + LONG2)])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "set aside: none")

    def test_the_output_folder_can_be_chosen_and_is_created(self):
        folder = os.path.join(tmp_dir(), "made", "on the fly")
        code, out = run_main(["extract", self.md(LONG1), "--out", folder])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "source: " + os.path.join(folder, "source.json"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "source.json")))

    def test_source_json_is_readable_utf8_with_lf_endings(self):
        path = self.md("# 제목\n\n## 서론\n\n" + KOREAN + "\n")
        self.assertEqual(run_main(["extract", path])[0], 0)
        raw = Path(os.path.splitext(path)[0] + ".throughmap", "source.json").read_bytes()
        text = raw.decode("utf-8")
        self.assertIn('"title": "서론"', text)       # the text itself, not a JSON escape of it
        self.assertNotIn("\\u", text)
        self.assertNotIn(b"\r", raw)
        self.assertTrue(text.startswith(
            '{\n "schema": "throughmap-source/1",\n "essay": {\n  "title"'))
        self.assertTrue(text.endswith("}\n"))

    def test_corrections_through_the_command_line(self):
        path = self.md("\n\n".join([T1, T2, T3, T4, T5]))
        code, out = run_main(["extract", path, "--join", "P2,P3", "--split", "P4", "However,",
                              "--drop", "P5"])
        self.assertEqual(code, 0)
        src = self.source_of(path)
        self.assertEqual([p["text"] for p in src["paragraphs"]],
                         [T1, T2 + " " + T3, T4_BEFORE, "However," + T4_AFTER])
        self.assertEqual(src["excluded"], [{"kind": "dropped", "text": T5}])
        self.assertIn("paragraphs: 4", out)
        self.assertIn("set aside: dropped", out)

    def test_several_drops_are_counted(self):
        path = self.md("\n\n".join([T1, T2, T3, T4, T5]))
        code, out = run_main(["extract", path, "--drop", "P4", "--drop", "P5"])
        self.assertEqual(code, 0)
        self.assertEqual(self.source_of(path)["essay"]["paragraph_count"], 3)
        self.assertEqual(out.splitlines()[-1], "set aside: 2 dropped")

    def test_corrections_that_cannot_be_applied_exit_1_and_write_nothing(self):
        path = self.md("\n\n".join(["# One", T1, T2, "# Two", T3]))
        cases = [(["--join", "P1,P3"], "not adjacent"), (["--split", "P1", "zzz"], "not found"),
                 (["--drop", "P9"], "P9"), (["--section", "Nope"], "Nope")]
        for extra, message in cases:
            with self.subTest(extra):
                code, out, err = run_main_streams(["extract", path, *extra])
                self.assertEqual((code, out), (1, ""))
                self.assertIn(message, err)
                self.assertFalse(os.path.exists(os.path.splitext(path)[0] + ".throughmap"))

    def test_a_draft_with_no_paragraph_left_exits_1_and_writes_nothing(self):
        # Body text must never vanish behind exit 0: when the set-asides leave no paragraph,
        # extract names what it set aside, says where to look and writes no source.json.
        cases = [("Notes\n\nA short line.\n\nAnother short line.", [], "references"),
                 ("\n\n".join([T1, T2]), ["--drop", "P1", "--drop", "P2"], "2 dropped"),
                 ("# Only\n\n## Headings", [], "title, heading"),   # its section is empty
                 ("", [], "none")]
        for text, extra, set_aside in cases:
            with self.subTest(set_aside):
                path = self.md(text)
                code, out, err = run_main_streams(["extract", path, *extra])
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err, f"error: no paragraph is left to map (set aside: "
                                      f"{set_aside}); check the draft and any --drop\n")
                self.assertFalse(os.path.exists(os.path.splitext(path)[0] + ".throughmap"))

    def test_usage_errors_exit_2(self):
        path = self.md(LONG1)
        cases = [[], ["bogus"], ["extract"], ["extract", path, "--join", "P1"],
                 ["extract", path, "--join", "P1,P2,P3"], ["extract", path, "--split", "P1"],
                 ["extract", path, "--no-such-option"], ["extract", "-"],
                 ["extract", "-", "--out", os.path.join(tmp_dir(), "out")],
                 ["extract", os.path.join(tmp_dir(), "draft.pdf")],
                 ["extract", os.path.join(tmp_dir(), "missing.md")]]
        for argv in cases:
            with self.subTest(argv):
                code, out, err = run_main_streams(argv, stdin="Some text.")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith(("usage:", "error:")), err)

    def test_a_damaged_docx_is_a_usage_error(self):
        path = os.path.join(tmp_dir(), "damaged.docx")
        make_corrupt_docx(path)
        code, out, err = run_main_streams(["extract", path])
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith(f"error: {path} is not a readable .docx file ("), err)
        self.assertFalse(os.path.exists(os.path.splitext(path)[0] + ".throughmap"))

    def test_help_exits_0(self):
        for argv in (["--help"], ["extract", "--help"]):
            with self.subTest(argv):
                code, out = run_main(argv)
                self.assertEqual(code, 0)
                self.assertIn("extract", out)
        for option in ("--section", "--keep-short"):
            self.assertIn(option, run_main(["extract", "--help"])[1])

    def test_keep_short_keeps_a_byline_and_a_sign_off_that_drop_can_remove(self):
        path = self.md("\n\n".join(["By Lucas Jang", LONG1, LONG2, "PUBLIUS."]))
        self.assertEqual(run_main(["extract", path])[1].splitlines()[-1], "set aside: byline, closing")
        code, out = run_main(["extract", path, "--keep-short"])
        self.assertEqual(code, 0)
        self.assertEqual([p["text"] for p in self.source_of(path)["paragraphs"]],
                         ["By Lucas Jang", LONG1, LONG2, "PUBLIUS."])
        self.assertEqual(out.splitlines()[-1], "set aside: none")
        code, out = run_main(["extract", path, "--keep-short", "--drop", "P1", "--drop", "P4"])
        self.assertEqual(code, 0)
        self.assertEqual([p["text"] for p in self.source_of(path)["paragraphs"]], [LONG1, LONG2])
        self.assertEqual(out.splitlines()[-1], "set aside: 2 dropped")

    def test_keep_short_applies_to_standard_input_too(self):
        folder = os.path.join(tmp_dir(), "pasted")
        run_main(["extract", "-", "--name", "x", "--out", folder, "--keep-short"],
                 stdin="By Lucas\n\n" + LONG1)
        src = json.loads(Path(folder, "source.json").read_text("utf-8"))
        self.assertEqual([p["text"] for p in src["paragraphs"]], ["By Lucas", LONG1])

    def test_sentences_that_open_with_a_label_stay_paragraphs(self):
        sentences = [CaptionTests.FIGURE_SENTENCE, CaptionTests.TABLE_SENTENCE]
        path = self.md("\n\n".join([LONG1, *sentences, LONG2]))
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertIn(f"paragraphs: 4 {DOT} tables: 0 {DOT} figures: 0 {DOT}", out)
        self.assertEqual(out.splitlines()[-1], "set aside: none")
        self.assertEqual([p["text"] for p in self.source_of(path)["paragraphs"]],
                         [LONG1, *sentences, LONG2])

    def test_a_second_run_replaces_the_first(self):
        path = self.md("\n\n".join([T1, T2, T3]))
        run_main(["extract", path])
        run_main(["extract", path, "--drop", "P2"])
        self.assertEqual([p["text"] for p in self.source_of(path)["paragraphs"]], [T1, T3])

    def test_stdin_is_markdown_pasted_under_a_name(self):
        folder = os.path.join(tmp_dir(), "pasted")
        text = "# Pasted\n\n## One\n\n" + LONG1 + "\n\n" + LONG2
        code, out = run_main(["extract", "-", "--name", "Free Rails", "--out", folder], stdin=text)
        self.assertEqual(code, 0)
        src = json.loads(Path(folder, "source.json").read_text("utf-8"))
        self.assertEqual((src["essay"]["title"], src["essay"]["source"], src["essay"]["source_kind"]),
                         ("Pasted", "Free Rails", "paste"))
        self.assertEqual(src["sections"], [{"title": "One", "first": "P1", "last": "P2"}])
        self.assertIn("set aside: title", out)
        run_main(["extract", "-", "--name", "Free Rails", "--out", folder], stdin=LONG1)
        titled = json.loads(Path(folder, "source.json").read_text("utf-8"))
        self.assertEqual(titled["essay"]["title"], "Free Rails")       # the name is the fallback title

    def test_stdin_without_out_writes_a_folder_named_after_the_name_in_the_working_directory(self):
        folder = tmp_dir()
        with working_directory(folder):
            code, _ = run_main(["extract", "-", "--name", "Free Rails"], stdin=LONG1)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(folder, "free-rails.throughmap", "source.json")))

    def test_the_name_is_the_title_of_a_file_that_has_none(self):
        path = self.md(LONG1)
        run_main(["extract", path, "--name", "Free Rails"])
        self.assertEqual(self.source_of(path)["essay"]["title"], "Free Rails")

    def test_over_the_limit_the_sections_are_listed(self):
        path = write_md(tmp_dir(), "long.md", sections={"One": 15, "Two": 15, "Three": 15})
        code, out = run_main(["extract", path])
        folder = os.path.splitext(path)[0] + ".throughmap"
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "source: " + os.path.join(folder, "source.json"),
            f"paragraphs: 45 {DOT} tables: 0 {DOT} figures: 0 {DOT} sections: 3 {DOT} words: "
            f"{FORTY_FIVE['essay']['word_count']}",
            "set aside: none",
            "over 40 paragraphs: pick a section with --section",
            f"  1. One P1{EN_DASH}P15, 15 paragraphs",
            f"  2. Two P16{EN_DASH}P30, 15 paragraphs",
            f"  3. Three P31{EN_DASH}P45, 15 paragraphs",
        ])
        self.assertEqual(len(self.source_of(path)["paragraphs"]), 45)      # still written, in full

    def test_the_listing_names_untitled_and_single_paragraph_sections(self):
        texts = [text for _, group in sections_of({"x": 41}) for text in group]
        path = self.md("\n\n".join(texts[:40] + ["# Last"] + texts[40:]))
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-2:], [f"  1. (untitled) P1{EN_DASH}P40, 40 paragraphs",
                                                "  2. Last P41, 1 paragraph"])

    def test_a_chosen_section_is_written_alone_and_summarised(self):
        path = write_md(tmp_dir(), "long.md", sections={"One": 15, "Two": 15, "Three": 15})
        for which in ("2", "Two"):
            with self.subTest(which):
                code, out = run_main(["extract", path, "--section", which])
                src = self.source_of(path)
                self.assertEqual(code, 0)
                self.assertNotIn("over 40", out)
                self.assertIn("paragraphs: 15", out)
                self.assertEqual(src["essay"]["selected_section"], "Two")
                self.assertEqual([p["id"] for p in src["paragraphs"]][::14], ["P16", "P30"])

    def test_forty_paragraphs_are_not_over_the_limit(self):
        path = write_md(tmp_dir(), "forty.md", sections={"One": 20, "Two": 20})
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertNotIn("over 40", out)

    def headless_draft(self, count):
        """A Markdown file of ``count`` paragraphs and no headings, and the words in them."""
        texts = [text for _, group in sections_of({"x": count}) for text in group]
        return self.md("\n\n".join(texts)), sum(word_count(text) for text in texts)

    def test_a_draft_without_headings_over_the_limit_says_so_instead_of_listing(self):
        path, words = self.headless_draft(41)
        code, out = run_main(["extract", path])
        folder = os.path.splitext(path)[0] + ".throughmap"
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "source: " + os.path.join(folder, "source.json"),
            f"paragraphs: 41 {DOT} tables: 0 {DOT} figures: 0 {DOT} sections: 0 {DOT} words: {words}",
            "set aside: none",
            "over 40 paragraphs and no section headings: add headings or split the draft",
        ])
        src = self.source_of(path)                                   # still written, in full
        self.assertEqual((len(src["paragraphs"]), src["sections"]), (41, []))

    def test_forty_paragraphs_without_headings_are_not_over_the_limit(self):
        path, _ = self.headless_draft(40)
        code, out = run_main(["extract", path])
        self.assertEqual(code, 0)
        self.assertNotIn("over 40", out)
        self.assertIn(f"sections: 0 {DOT}", out)

    def test_a_section_cannot_be_chosen_in_a_draft_without_headings(self):
        path, _ = self.headless_draft(41)
        code, out, err = run_main_streams(["extract", path, "--section", "1"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no section headings", err)


class ScriptProcessTests(unittest.TestCase):
    """Run the real script the way an agent does, with its input and output on pipes.

    A pipe uses the machine's code page (cp949 on a Korean Windows), which cannot print an en dash,
    so the script must choose UTF-8 itself. The settings that would hide a failure are removed.
    """

    SCRIPT = SCRIPTS_DIR / "throughmap.py"

    def run_script(self, *args, stdin=None):
        env = {key: value for key, value in os.environ.items()
               if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run([sys.executable, str(self.SCRIPT), *args], capture_output=True,
                              env=env, timeout=120, **feed)

    def test_output_is_utf8(self):
        path = write_md(tmp_dir(), "long.md", sections={"One": 15, "Two": 15, "Three": 15})
        done = self.run_script("extract", path)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout.decode("utf-8")
        self.assertIn(f"2. Two P16{EN_DASH}P30, 15 paragraphs", out)
        self.assertIn(DOT, out)

    def test_error_messages_are_utf8(self):
        done = self.run_script("extract", os.path.join(tmp_dir(), "없는 글.md"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("없는 글.md", done.stderr.decode("utf-8"))

    def test_standard_input_is_read_as_utf8(self):
        folder = os.path.join(tmp_dir(), "pasted")
        done = self.run_script("extract", "-", "--name", "한글 글", "--out", folder,
                               stdin=KOREAN.encode("utf-8"))
        self.assertEqual(done.returncode, 0, done.stderr)
        src = json.loads(Path(folder, "source.json").read_text("utf-8"))
        self.assertEqual([p["text"] for p in src["paragraphs"]], [KOREAN])
        self.assertEqual(src["essay"]["source"], "한글 글")


if __name__ == "__main__":
    unittest.main()
