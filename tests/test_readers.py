import unittest
import zipfile

import tm_extract
import tm_source
from tests.fixtures import (
    LONG1, LONG2, LONG3, LONG4, P, STYLES_EN, TABLE, W_NS, make_corrupt_docx, make_docx, tmp_path,
    wrap_styles,
)
from tm_extract import read_docx, read_markdown, read_plain

BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


class ReaderTests(unittest.TestCase):
    def test_read_docx_text_rules(self):
        body = (P("My Title", style="Title") + P("Intro", style="Heading1")
                + '<w:p><w:r><w:t>See </w:t></w:r><w:hyperlink><w:r><w:t>link text</w:t></w:r>'
                  '</w:hyperlink><w:r><w:t> here.</w:t></w:r></w:p>'
                + '<w:p><w:r><w:t>This was </w:t></w:r><w:ins><w:r><w:t>added</w:t></w:r></w:ins>'
                  '<w:del><w:r><w:delText>removed</w:delText></w:r></w:del>'
                  '<w:r><w:t>.</w:t></w:r></w:p>'
                + '<w:p><w:r><w:t>line one</w:t><w:br/><w:t>line two</w:t><w:tab/><w:t>end</w:t>'
                  '</w:r></w:p>'
                + '<w:p/>' + '<w:p><w:r><w:drawing/></w:r></w:p>'
                + TABLE([["a", "b"], ["c", "d"]]))
        path = tmp_path("t.docx"); make_docx(path, body, STYLES_EN)
        self.assertEqual(read_docx(path), [
            {"type": "title", "text": "My Title"},
            {"type": "heading", "level": 1, "text": "Intro"},
            {"type": "para", "text": "See link text here."},
            {"type": "para", "text": "This was added."},
            {"type": "para", "text": "line one line two end"},
            {"type": "table", "text": "a | b\nc | d"},
        ])

    def test_read_docx_style_names_from_styles_xml(self):
        styles = ('<w:style w:styleId="1"><w:name w:val="heading 1"/></w:style>'
                  '<w:style w:styleId="x2"><w:name w:val="heading 2"/></w:style>')
        body = (P("Section", style="1") + P("Sub", style="x2")
                + '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Outline</w:t></w:r></w:p>')
        path = tmp_path("k.docx"); make_docx(path, body, wrap_styles(styles))
        self.assertEqual([(b["type"], b.get("level")) for b in read_docx(path)],
                         [("heading", 1), ("heading", 2), ("heading", 1)])

    def test_read_markdown_blocks(self):
        md = ("# Title\n\nIntro **bold** and [link](http://x) and `code`.\n\n## One\n\n"
              "Body line one\ncontinues here.\n\n- item\n- item2\n\n| a | b |\n|---|---|\n| c | d |\n\n"
              "```\ncode block\n```\n\n## Two\n\nText.")
        self.assertEqual(read_markdown(md), [
            {"type": "heading", "level": 1, "text": "Title"},
            {"type": "para", "text": "Intro bold and link and code."},
            {"type": "heading", "level": 2, "text": "One"},
            {"type": "para", "text": "Body line one continues here."},
            {"type": "para", "text": "item item2"},
            {"type": "table", "text": "a | b\nc | d"},
            {"type": "heading", "level": 2, "text": "Two"},
            {"type": "para", "text": "Text."},
        ])

    def test_read_plain_splits_on_blank_lines(self):
        self.assertEqual(read_plain("One.\nStill one.\n\n\nTwo."),
                         [{"type": "para", "text": "One. Still one."}, {"type": "para", "text": "Two."}])


class TextFidelityTests(unittest.TestCase):
    """What every reader promises about the characters of the text."""

    def test_original_characters_survive(self):
        text = "“Free rails” — it’s 5–6 bps… 한국어 sof\N{SOFT HYPHEN}t"
        path = tmp_path("c.docx"); make_docx(path, P(text), STYLES_EN)
        expected = [{"type": "para", "text": text}]
        self.assertEqual(read_docx(path), expected)
        self.assertEqual(read_markdown(text), expected)
        self.assertEqual(read_plain(text), expected)

    def test_whitespace_runs_collapse_and_the_ends_are_stripped(self):
        text = "  spaced \t out\N{NO-BREAK SPACE}\N{IDEOGRAPHIC SPACE}text  "
        path = tmp_path("w.docx"); make_docx(path, P(text), STYLES_EN)
        expected = [{"type": "para", "text": "spaced out text"}]
        self.assertEqual(read_docx(path), expected)
        self.assertEqual(read_markdown(text), expected)
        self.assertEqual(read_plain(text), expected)


class DocxTests(unittest.TestCase):
    def read(self, body, styles=STYLES_EN):
        path = tmp_path("draft.docx")
        make_docx(path, body, styles)
        return read_docx(path)

    def test_run_properties_markers_and_section_settings_are_ignored(self):
        body = ('<w:p><w:pPr><w:pStyle w:val="Normal"/><w:rPr><w:b/></w:rPr></w:pPr>'
                '<w:bookmarkStart w:id="0" w:name="_GoBack"/>'
                '<w:r><w:rPr><w:b/><w:lang w:val="en-US"/></w:rPr><w:lastRenderedPageBreak/>'
                '<w:t xml:space="preserve">Rents </w:t></w:r>'
                '<w:proofErr w:type="spellStart"/><w:r><w:t>rise</w:t></w:r>'
                '<w:proofErr w:type="spellEnd"/><w:bookmarkEnd w:id="0"/>'
                '<w:r><w:t xml:space="preserve"> slowly.</w:t></w:r></w:p>'
                '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>')
        self.assertEqual(self.read(body), [{"type": "para", "text": "Rents rise slowly."}])

    def test_every_kind_of_break_is_a_space(self):
        body = ('<w:p><w:r><w:t>a</w:t><w:cr/><w:t>b</w:t><w:br w:type="page"/><w:t>c</w:t>'
                '<w:tab/><w:t>d</w:t></w:r></w:p>')
        self.assertEqual(self.read(body), [{"type": "para", "text": "a b c d"}])

    def test_text_inside_inline_wrappers(self):
        body = ('<w:p><w:r><w:t xml:space="preserve">Met in </w:t></w:r>'
                '<w:smartTag w:uri="urn:x" w:element="place"><w:r><w:t>Paris</w:t></w:r></w:smartTag>'
                '<w:r><w:t xml:space="preserve">, chose </w:t></w:r>'
                '<w:sdt><w:sdtPr><w:alias w:val="Pick"/></w:sdtPr>'
                '<w:sdtContent><w:r><w:t>one</w:t></w:r></w:sdtContent></w:sdt>'
                '<w:r><w:t xml:space="preserve"> on page </w:t></w:r>'
                '<w:fldSimple w:instr=" PAGE "><w:r><w:t>7</w:t></w:r></w:fldSimple>'
                '<w:ins><w:hyperlink><w:r><w:t xml:space="preserve"> (added link)</w:t></w:r>'
                '</w:hyperlink></w:ins><w:r><w:t>.</w:t></w:r></w:p>')
        self.assertEqual(self.read(body),
                         [{"type": "para", "text": "Met in Paris, chose one on page 7 (added link)."}])

    def test_field_codes_note_marks_and_hyphens(self):
        body = ('<w:p><w:r><w:t xml:space="preserve">Read </w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve"> HYPERLINK "http://x" </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>the memo</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                '<w:r><w:t>.</w:t></w:r>'
                '<w:r><w:footnoteReference w:id="2"/><w:t>2</w:t></w:r>'
                '<w:r><w:endnoteReference w:id="3"/><w:t>3</w:t></w:r>'
                '<w:r><w:t xml:space="preserve"> A state</w:t><w:noBreakHyphen/><w:t>of</w:t>'
                '<w:noBreakHyphen/><w:t>the</w:t><w:noBreakHyphen/><w:t xml:space="preserve">art ex</w:t>'
                '<w:softHyphen/><w:t>ample.</w:t></w:r></w:p>')
        self.assertEqual(self.read(body),
                         [{"type": "para", "text": "Read the memo. A state-of-the-art example."}])

    def test_tracked_moves_and_deleted_paragraphs(self):
        body = ('<w:p><w:r><w:t xml:space="preserve">Keep </w:t></w:r>'
                '<w:moveFrom><w:r><w:t>old place</w:t></w:r></w:moveFrom>'
                '<w:moveTo><w:r><w:t>new place</w:t></w:r></w:moveTo>'
                '<w:r><w:t xml:space="preserve"> text.</w:t></w:r></w:p>'
                '<w:p><w:del><w:r><w:delText>gone</w:delText></w:r></w:del></w:p>')
        self.assertEqual(self.read(body), [{"type": "para", "text": "Keep new place text."}])

    def test_text_boxes_do_not_leak_into_their_paragraph(self):
        box = '<w:txbxContent><w:p><w:r><w:t>Pull quote</w:t></w:r></w:p></w:txbxContent>'
        body = ('<w:p><w:r><w:t xml:space="preserve">Before </w:t></w:r>'
                '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor>'
                '<a:graphic><a:graphicData><wps:wsp><wps:txbx>' + box + '</wps:txbx></wps:wsp>'
                '</a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
                '<mc:Fallback><w:pict><v:shape><v:textbox>' + box + '</v:textbox></v:shape></w:pict>'
                '</mc:Fallback></mc:AlternateContent></w:r>'
                '<w:r><w:t>after.</w:t></w:r></w:p>')
        self.assertEqual(self.read(body), [{"type": "para", "text": "Before after."}])

    def test_block_level_content_controls(self):
        body = ('<w:sdt><w:sdtPr><w:alias w:val="Body"/></w:sdtPr><w:sdtContent>'
                + P("Wrapped", style="Heading1") + P("Inside a control.") + TABLE([["x", "y"]])
                + '</w:sdtContent></w:sdt>' + P("After."))
        self.assertEqual(self.read(body), [
            {"type": "heading", "level": 1, "text": "Wrapped"},
            {"type": "para", "text": "Inside a control."},
            {"type": "table", "text": "x | y"},
            {"type": "para", "text": "After."},
        ])

    def test_table_cells(self):
        body = ('<w:tbl><w:tblPr/><w:tblGrid/>'
                '<w:tr><w:tc>' + P("Fee") + P("(bps)") + '</w:tc><w:tc>' + P("Owner") + '</w:tc></w:tr>'
                '<w:tr><w:tc><w:p/></w:tc><w:tc>' + P("A") + '</w:tc></w:tr>'
                '<w:tr><w:tc><w:p/></w:tc><w:tc><w:p><w:del><w:r><w:delText>x</w:delText></w:r>'
                '</w:del></w:p></w:tc></w:tr></w:tbl>'
                + P("Between.")
                + '<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>'
                + '<w:tbl><w:tr><w:tc>' + P("Outer ")
                + '<w:tbl><w:tr><w:tc>' + P("inner") + '</w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>')
        self.assertEqual(self.read(body), [
            {"type": "table", "text": "Fee (bps) | Owner\n| A"},
            {"type": "para", "text": "Between."},
            {"type": "table", "text": "Outer inner"},
        ])

    def test_heading_levels_follow_based_on_and_outline_levels(self):
        styles = wrap_styles(
            '<w:style w:styleId="Heading1"><w:name w:val="heading 1"/>'
            '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
            '<w:style w:styleId="H3"><w:name w:val="Heading 3"/></w:style>'
            '<w:style w:styleId="Chapter"><w:name w:val="Chapter Head"/>'
            '<w:basedOn w:val="Heading1"/></w:style>'
            '<w:style w:styleId="Deep"><w:name w:val="Deep"/><w:basedOn w:val="Chapter"/></w:style>'
            '<w:style w:styleId="Outlined"><w:name w:val="Outlined"/>'
            '<w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>'
            '<w:style w:styleId="a4"><w:name w:val="개요 1"/>'
            '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
            '<w:style w:styleId="TOCHeading"><w:name w:val="TOC Heading"/>'
            '<w:basedOn w:val="Heading1"/><w:pPr><w:outlineLvl w:val="9"/></w:pPr></w:style>'
            '<w:style w:styleId="Title"><w:name w:val="Title"/></w:style>'
            '<w:style w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Title"/></w:style>'
            '<w:style w:styleId="Loop1"><w:name w:val="Loop 1"/><w:basedOn w:val="Loop2"/></w:style>'
            '<w:style w:styleId="Loop2"><w:name w:val="Loop 2"/><w:basedOn w:val="Loop1"/></w:style>')
        body = (P("Chapter", "Chapter") + P("Deep", "Deep") + P("Third", "H3")
                + P("Outlined", "Outlined") + P("서론", "a4") + P("Contents", "TOCHeading")
                + P("Sub", "Subtitle") + P("Loop", "Loop1")
                + '<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:outlineLvl w:val="9"/></w:pPr>'
                  '<w:r><w:t>Hidden from the outline</w:t></w:r></w:p>'
                + '<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:outlineLvl w:val="1"/></w:pPr>'
                  '<w:r><w:t>Moved down</w:t></w:r></w:p>')
        self.assertEqual(self.read(body, styles), [
            {"type": "heading", "level": 1, "text": "Chapter"},
            {"type": "heading", "level": 1, "text": "Deep"},
            {"type": "heading", "level": 3, "text": "Third"},
            {"type": "heading", "level": 3, "text": "Outlined"},
            {"type": "heading", "level": 1, "text": "서론"},
            {"type": "para", "text": "Contents"},
            {"type": "para", "text": "Sub"},
            {"type": "para", "text": "Loop"},
            {"type": "para", "text": "Hidden from the outline"},
            {"type": "heading", "level": 2, "text": "Moved down"},
        ])

    def test_without_a_styles_part_every_paragraph_is_body_text(self):
        self.assertEqual(self.read(P("A", style="Heading1") + P("B"), styles=None),
                         [{"type": "para", "text": "A"}, {"type": "para", "text": "B"}])

    def test_files_that_are_not_word_documents_are_rejected(self):
        not_a_zip = tmp_path("plain.docx")
        with open(not_a_zip, "wb") as handle:
            handle.write(b"just text")
        parts = {
            "sheet.docx": {"xl/workbook.xml": "<workbook/>"},
            "broken.docx": {"word/document.xml": "<w:document"},
            "bodyless.docx": {"word/document.xml": f'<w:document xmlns:w="{W_NS}"/>'},
        }
        paths = [not_a_zip]
        for name, content in parts.items():
            paths.append(tmp_path(name))
            with zipfile.ZipFile(paths[-1], "w") as archive:
                for part, xml in content.items():
                    archive.writestr(part, xml)
        for path in paths:
            with self.subTest(path), self.assertRaisesRegex(ValueError, "not a readable .docx"):
                read_docx(path)

    def test_a_damaged_document_part_is_rejected(self):
        # A broken deflate stream raised zlib.error, which reached the user as a traceback.
        path = tmp_path("damaged.docx")
        make_corrupt_docx(path)
        with self.assertRaisesRegex(ValueError, "not a readable .docx"):
            read_docx(path)

    def test_a_missing_file_is_not_hidden(self):
        with self.assertRaises(FileNotFoundError):
            read_docx(tmp_path("missing.docx"))


class MarkdownTests(unittest.TestCase):
    def test_headings_need_no_blank_line_around_them(self):
        md = ("## Heading above text\n"
              "The text starts at once.\n"
              "Then more text\n"
              "### Next heading ###\n"
              "and a closing line.\n\n"
              "#hashtag is not a heading\n\n"
              "####### seven hashes is not one\n\n"
              "   ## an indented heading\n")
        self.assertEqual(read_markdown(md), [
            {"type": "heading", "level": 2, "text": "Heading above text"},
            {"type": "para", "text": "The text starts at once. Then more text"},
            {"type": "heading", "level": 3, "text": "Next heading"},
            {"type": "para", "text": "and a closing line."},
            {"type": "para", "text": "#hashtag is not a heading"},
            {"type": "para", "text": "####### seven hashes is not one"},
            {"type": "heading", "level": 2, "text": "an indented heading"},
        ])

    def test_hashes_at_the_end_of_a_heading_are_text_unless_a_space_comes_first(self):
        # Only a run of hashes after whitespace closes a heading, as in CommonMark.
        self.assertEqual(read_markdown("# Learning C#"),
                         [{"type": "heading", "level": 1, "text": "Learning C#"}])
        self.assertEqual(read_markdown("## F# and Issue#"),
                         [{"type": "heading", "level": 2, "text": "F# and Issue#"}])
        self.assertEqual(read_markdown("### Next heading ###"),
                         [{"type": "heading", "level": 3, "text": "Next heading"}])
        # A closing run need not be as long as the opening one, so this one is dropped too.
        self.assertEqual(read_markdown("## F# and Issue #"),
                         [{"type": "heading", "level": 2, "text": "F# and Issue"}])
        self.assertEqual(read_markdown("# Title ##########  "),
                         [{"type": "heading", "level": 1, "text": "Title"}])

    def test_a_number_that_starts_a_wrapped_line_stays_in_the_text(self):
        cases = {
            "The company was founded in\n1998. It grew quickly.":
                "The company was founded in 1998. It grew quickly.",
            "Results came\n2) the next year.": "Results came 2) the next year.",
            "Growth was\n1.5 percent higher.": "Growth was 1.5 percent higher.",  # not a marker
            # Only the line right before counts: after a wrapped line the number is text again.
            "1. First\n   wraps here\n2. Second": "First wraps here 2. Second",
            # A bullet item does not make the next line a list item: the number is still text.
            "- The company was founded in\n1998. It grew quickly.":
                "The company was founded in 1998. It grew quickly.",
        }
        for source, expected in cases.items():
            with self.subTest(source):
                self.assertEqual(read_markdown(source), [{"type": "para", "text": expected}])

    def test_ordered_markers_are_dropped_where_a_list_item_starts(self):
        cases = {
            "1. a\n2. b\n3. c": "a b c",                                   # each follows an item
            "Intro line\n1. first\n2. second": "Intro line first second",  # a list starts at 1
            "2. b\n3. c": "b c",                                           # or opens its block
            "- a\n1. b": "a b",                                            # a 1 starts a list anywhere
            "- a\n2. b": "a 2. b",                                         # after a bullet, any other
            "1. a\n- b\n2. c": "a b 2. c",                                 # number is text again
            "Intro\n- one\n- two": "Intro one two",                        # bullets go anywhere
        }
        for source, expected in cases.items():
            with self.subTest(source):
                self.assertEqual(read_markdown(source), [{"type": "para", "text": expected}])

    def test_a_marker_has_at_most_nine_digits(self):
        # CommonMark's limit; it also keeps int() from ever seeing a huge number.
        giant = "9" * 5000
        self.assertEqual(read_markdown("a\n" + giant + ". x"),
                         [{"type": "para", "text": "a " + giant + ". x"}])
        self.assertEqual(read_markdown("123456789. item"), [{"type": "para", "text": "item"}])
        self.assertEqual(read_markdown("1234567890. item"),
                         [{"type": "para", "text": "1234567890. item"}])

    def test_list_markers_and_quote_marks_are_stripped(self):
        md = ("1. First\n2) Second\n\n"
              "* star\n+ plus\n  - nested\n\n"
              "> quoted line\n> continues\n>\n> new quoted paragraph\n\n"
              "-5 degrees, 1.5 percent and *emphasis* are not markers")
        self.assertEqual(read_markdown(md), [
            {"type": "para", "text": "First Second"},
            {"type": "para", "text": "star plus nested"},
            {"type": "para", "text": "quoted line continues"},
            {"type": "para", "text": "new quoted paragraph"},
            {"type": "para", "text": "-5 degrees, 1.5 percent and emphasis are not markers"},
        ])

    def test_pipe_tables(self):
        md = ("Data follows:\n"
              "| Name | **Fee** |\n"
              "|:-----|--------:|\n"
              "| `a` | 1 |\n"
              "|  | 2 |\n\n"
              "Not a table: a | b\n"
              "still text\n")
        self.assertEqual(read_markdown(md), [
            {"type": "para", "text": "Data follows:"},
            {"type": "table", "text": "Name | Fee\na | 1\n| 2"},
            {"type": "para", "text": "Not a table: a | b still text"},
        ])
        self.assertEqual(read_markdown("x | y\n--|--\n1 | 2"),
                         [{"type": "table", "text": "x | y\n1 | 2"}])
        # A delimiter row with a different number of cells does not make a table.
        self.assertEqual(read_markdown("x | y | z\n--|--\n1 | 2"),
                         [{"type": "para", "text": "x | y | z --|-- 1 | 2"}])

    def test_fenced_code_is_skipped(self):
        md = ("Before.\n"
              "```python\nprint('# not a heading')\n\nstill code\n```\n"
              "After the fence.\n\n"
              "~~~\ntilde fence\n~~~~~\n"
              "Closed by a longer run.\n\n"
              "````\n```\ninner line\n````\n"
              "Done.\n\n"
              "```\nnever closed\nso the rest is code")
        self.assertEqual([b["text"] for b in read_markdown(md)],
                         ["Before.", "After the fence.", "Closed by a longer run.", "Done."])

    def test_triple_backticks_on_one_line_are_a_code_span_not_a_fence(self):
        self.assertEqual(read_markdown("```a``` stays text\n\nNext."),
                         [{"type": "para", "text": "a stays text"}, {"type": "para", "text": "Next."}])

    def test_inline_markup_is_stripped(self):
        cases = {
            "__strong__ and _soft_ and *star* and ***both***": "strong and soft and star and both",
            "**bold *italic* bold** and *one\ntwo*": "bold italic bold and one two",
            "snake_case_name, 5 * 3 * 2 and a_b stay": "snake_case_name, 5 * 3 * 2 and a_b stay",
            "![diagram](a.png) Look [here (now)](http://x/a_(b) \"Title\") please":
                "Look here (now) please",
            "[![badge](b.svg)](http://x) end": "end",
            "Use <b>bold</b>, <br/><!-- note --> and a < b > c": "Use bold, and a < b > c",
            "Visit <https://example.com/a> or <me@example.com> now":
                "Visit https://example.com/a or me@example.com now",
            "Keep `<b>` and `</script>`, `*args and **kwargs`, ``a ` b`` here":
                "Keep <b> and </script>, *args and **kwargs, a ` b here",
            # A stray NUL (a UTF-16 file read as UTF-8, say) must not be taken for a code span.
            "x\0" + "5\0y `c`": "x5y c",
        }
        for source, expected in cases.items():
            with self.subTest(source):
                self.assertEqual(read_markdown(source), [{"type": "para", "text": expected}])

    def test_blocks_without_text_are_dropped(self):
        md = "![only an image](a.png)\n\n---\n\n<div></div>\n\n* * *\n\n# \n\nKept."
        self.assertEqual(read_markdown(md), [{"type": "para", "text": "Kept."}])

    def test_line_endings_and_byte_order_mark(self):
        md = BOM + "# Title\r\n\r\nFirst line\r\nsecond line.\r\n"
        self.assertEqual(read_markdown(md), [
            {"type": "heading", "level": 1, "text": "Title"},
            {"type": "para", "text": "First line second line."},
        ])


class FrontMatterFootnoteAndSetextTests(unittest.TestCase):
    """What blog posts and notes add to Markdown: YAML front matter, footnotes, Setext headings."""

    def test_yaml_front_matter_is_set_aside_and_its_title_is_the_title(self):
        # The block itself comes first, as a "front matter" block that extract lists (R70).
        cases = {
            # Jekyll and Hugo: a double-quoted title among other keys, a list, a --- closer.
            '---\nlayout: post\ntitle: "Free Rails: A Note"\ndate: 2026-10-01\ntags:\n'
            "  - rails\n  - fees\n---\n\nGardens need rain.\n":
                ("Free Rails: A Note",
                 'layout: post\ntitle: "Free Rails: A Note"\ndate: 2026-10-01\ntags:\n'
                 "  - rails\n  - fees"),
            # A ... closer, a single-quoted title with a doubled quote, a comment.
            "---\n#settings\ntitle: 'It''s Free'\n...\nGardens need rain.\n":
                ("It's Free", "#settings\ntitle: 'It''s Free'"),
            BOM + "---\r\ntitle: Free Rails\r\n---\r\nGardens need rain.\r\n":
                ("Free Rails", "title: Free Rails"),
        }
        for md, (title, block) in cases.items():
            with self.subTest(title):
                self.assertEqual(read_markdown(md), [{"type": "front matter", "text": block},
                                                     {"type": "title", "text": title},
                                                     {"type": "para", "text": "Gardens need rain."}])

    def test_front_matter_without_a_title_gives_none(self):
        self.assertEqual(read_markdown("---\nlayout: post\ndraft: true\n---\n\nText.\n"),
                         [{"type": "front matter", "text": "layout: post\ndraft: true"},
                          {"type": "para", "text": "Text."}])

    def test_a_first_heading_that_repeats_the_front_matter_title_is_not_read_twice(self):
        md = "---\ntitle: Free Rails\n---\n\n# Free Rails\n\nText.\n\n# Next\n\nMore.\n"
        self.assertEqual(read_markdown(md), [
            {"type": "front matter", "text": "title: Free Rails"},
            {"type": "title", "text": "Free Rails"}, {"type": "para", "text": "Text."},
            {"type": "heading", "level": 1, "text": "Next"}, {"type": "para", "text": "More."},
        ])

    def test_a_block_between_rules_that_is_not_yaml_is_read_as_markdown(self):
        # Front matter needs a lowercase ASCII "key:" line, as Jekyll and Hugo write them.
        # Otherwise both lines are rules: the closing one is not a Setext underline for the line
        # above it, and a "#" line in the block is a heading (R70).
        cases = {
            "---\nNote: this draft argues that rents stay low.\n---\n\nText.\n":
                [{"type": "para", "text": "Note: this draft argues that rents stay low."}],
            "---\n제목: 자유로운 레일\n---\n\nText.\n": [{"type": "para", "text": "제목: 자유로운 레일"}],
            "---\nTo: Board\nFrom: Sam\n---\n\nText.\n": [{"type": "para", "text": "To: Board From: Sam"}],
            "---\n# Free Rails\n---\n\nText.\n": [{"type": "heading", "level": 1,
                                                   "text": "Free Rails"}],
        }
        for md, blocks in cases.items():
            with self.subTest(md.split("\n")[1]):
                self.assertEqual(read_markdown(md), [*blocks, {"type": "para", "text": "Text."}])

    def test_hash_lines_in_front_matter_with_a_key_are_yaml_comments(self):
        # A standard YAML comment ("# post settings") made the block prose, so the comment
        # became the essay's title and the title: line a front line (R72).
        for comment in ("# post settings", "# Free Rails", "#settings"):
            with self.subTest(comment):
                md = f"---\n{comment}\ntitle: Free Rails\ndraft: true\n---\n\nText.\n"
                self.assertEqual(read_markdown(md), [
                    {"type": "front matter", "text": f"{comment}\ntitle: Free Rails\ndraft: true"},
                    {"type": "title", "text": "Free Rails"}, {"type": "para", "text": "Text."}])

    def test_a_rule_on_the_first_line_is_not_front_matter_without_yaml_under_it(self):
        # No closer: the first line is a horizontal rule. Prose between two rules is body text.
        self.assertEqual(read_markdown("---\nText.\n"), [{"type": "para", "text": "Text."}])
        self.assertEqual(read_markdown("---\n\nAn opening line of prose.\n\n---\n\nMore.\n"),
                         [{"type": "para", "text": "An opening line of prose."},
                          {"type": "para", "text": "More."}])

    def test_footnote_definitions_are_set_aside_as_notes_and_their_marks_removed(self):
        # Each definition, with the lines that carry it on, is a "notes" block that extract
        # lists (R70), so a body line taken for a note's continuation is still in view.
        md = ("Rents rise fast.[^1] Tenants notice.[^note] Use `[^2]` for a mark.\n\n"
              "[^1]: The data run to 2025\n"
              "    and cover nine towns.\n\n"
              "    A second paragraph of the note.\n\n"
              "[^note]: Tenants said so,\n"
              "in a line that wraps without an indent.\n\n"
              "Back to the body.\n")
        self.assertEqual(read_markdown(md), [
            {"type": "para", "text": "Rents rise fast. Tenants notice. Use [^2] for a mark."},
            {"type": "notes", "text": "[^1]: The data run to 2025\nand cover nine towns.\n"
                                      "A second paragraph of the note."},
            {"type": "notes", "text": "[^note]: Tenants said so,\n"
                                      "in a line that wraps without an indent."},
            {"type": "para", "text": "Back to the body."},
        ])

    def test_setext_headings(self):
        md = ("Free Rails\n==========\n\nIntro text.\n\n"
              "First part\n----------\nBody text.\n\n"
              "  Second part  \n=\n")
        self.assertEqual(read_markdown(md), [
            {"type": "heading", "level": 1, "text": "Free Rails"},
            {"type": "para", "text": "Intro text."},
            {"type": "heading", "level": 2, "text": "First part"},  # once read as a rule
            {"type": "para", "text": "Body text."},
            {"type": "heading", "level": 1, "text": "Second part"},
        ])

    def test_dashes_with_no_text_line_right_above_are_a_horizontal_rule(self):
        cases = {
            "Text.\n\n---\n\nMore.": ["Text.", "More."],         # a blank line above
            "## Heading\n---\nMore.": ["More."],                   # a heading above
            "- item\n---\nMore.": ["item", "More."],               # a list item above
            "> quoted\n---\nMore.": ["quoted", "More."],           # a quote above
            "Two lines of\nprose text\n---\nMore.": ["Two lines of prose text", "More."],
            "Text.\n- - -\nMore.": ["Text.", "More."],             # spaced dashes: a rule
        }
        for md, texts in cases.items():
            with self.subTest(md):
                self.assertEqual([b["text"] for b in read_markdown(md) if b["type"] == "para"],
                                 texts)

    def test_only_a_short_line_without_a_sentence_mark_is_underlined_into_a_heading(self):
        # A long paragraph right over "---" became an empty Setext H2 and vanished (R72). Over
        # "---", a heading line is short (under 12 words) and ends with no sentence mark; under
        # any other line, "---" is a rule. "===" has no rule meaning, so it always underlines
        # (R73).
        long_line = "Gardens grow beans between houses, and every garden needs a little rain."
        cases = {
            f"First paragraph.\n\n{long_line}\n---\nMore.": ["First paragraph.", long_line, "More."],
            "Thanks for reading.\n---\nMore.": ["Thanks for reading.", "More."],
            "A line that ends a sentence\N{IDEOGRAPHIC FULL STOP}\n---\nMore.":
                ["A line that ends a sentence\N{IDEOGRAPHIC FULL STOP}", "More."],
        }
        for md, texts in cases.items():
            with self.subTest(md[:24]):
                blocks = read_markdown(md)
                self.assertEqual([b["type"] for b in blocks], ["para"] * len(texts))
                self.assertEqual([b["text"] for b in blocks], texts)
        self.assertEqual(read_markdown("The switch, briefly\n---\nMore."),
                         [{"type": "heading", "level": 2, "text": "The switch, briefly"},
                          {"type": "para", "text": "More."}])

    def test_equals_signs_always_underline_a_level_one_heading(self):
        sixteen = ("Why the Old Gardens That Line Every Street Between Two Rivers Will Always "
                   "Need Their Neighbours")
        cases = {"Why do rents rise?\n===\nMore.": "Why do rents rise?",
                 sixteen + "\n=====\nMore.": sixteen,
                 "Two lines of\na title\n===\nMore.": "Two lines of a title"}
        for md, title in cases.items():
            with self.subTest(title[:20]):
                self.assertEqual(read_markdown(md), [{"type": "heading", "level": 1, "text": title},
                                                     {"type": "para", "text": "More."}])


class PlainTextTests(unittest.TestCase):
    def test_blank_lines_may_hold_whitespace(self):
        self.assertEqual(read_plain("One\nstill one.\n \t \nTwo.\n\n\n"),
                         [{"type": "para", "text": "One still one."}, {"type": "para", "text": "Two."}])

    def test_nothing_is_interpreted(self):
        text = "# not a heading\n\n*stars* and [x](y) stay"
        self.assertEqual(read_plain(text), [{"type": "para", "text": "# not a heading"},
                                            {"type": "para", "text": "*stars* and [x](y) stay"}])

    def test_empty_input_has_no_blocks(self):
        self.assertEqual(read_plain(""), [])
        self.assertEqual(read_plain(" \n\n \t"), [])

    def test_line_endings_and_byte_order_mark(self):
        self.assertEqual(read_plain(BOM + "One.\r\nStill one.\r\n\r\nTwo."),
                         [{"type": "para", "text": "One. Still one."}, {"type": "para", "text": "Two."}])

    def test_without_any_blank_line_each_line_is_a_paragraph(self):
        # Word's "Save as Plain Text", Notepad and TextEdit write one paragraph per line, with no
        # blank line between them; joined, the whole draft would be one paragraph.
        expected = [{"type": "para", "text": "One."}, {"type": "para", "text": "Two, still two."},
                    {"type": "para", "text": "Three."}]
        for ending in ("\r\n", "\n", "\r"):
            with self.subTest(ending=repr(ending)):
                text = ending.join(["One.", "  Two,  still two. ", "Three."])
                self.assertEqual(read_plain(text), expected)
                # Blank lines at the very start or end separate nothing, so they do not count.
                self.assertEqual(read_plain(BOM + ending * 2 + text + ending * 3), expected)

    def test_any_blank_line_means_blank_lines_separate_the_paragraphs(self):
        text = "One.\nStill one.\n\nTwo.\nStill two.\nAnd still two."
        self.assertEqual(read_plain(text), [{"type": "para", "text": "One. Still one."},
                                            {"type": "para", "text": "Two. Still two. And still two."}])
        self.assertEqual(read_plain(text.replace("\n", "\r\n")), read_plain(text))

    def test_a_word_export_with_a_blank_line_after_its_title(self):
        # Word's "Save as Plain Text" with one empty paragraph after the title: that one blank
        # line turned blank-line splitting on and joined every paragraph into one (R68). Lines
        # that are each long and each end a sentence are paragraphs of their own.
        quoted = ("\N{LEFT DOUBLE QUOTATION MARK}Gardens on these streets stay green because the "
                  "neighbours keep the beds well watered.\N{RIGHT DOUBLE QUOTATION MARK}")
        body = [LONG1, quoted, LONG3, "Will the neighbours water every bed once the summer turns "
                                      "dry and the wells run low?"]
        text = "\r\n".join(["Free Rails", "", *body]) + "\r\n"
        self.assertEqual(read_plain(text), [{"type": "para", "text": line}
                                            for line in ["Free Rails", *body]])

    def test_hard_wrapped_prose_stays_one_paragraph(self):
        wrapped = ("Gardens grow beans between houses, and every\n"
                   "garden needs a little rain in the summer, which\n"
                   "keeps the beds growing.")
        # Long lines too: a line that breaks mid-sentence joins the next one.
        wide = ("A rota would let the neighbours of every street water each bed that needs it,\n"
                "but the gardens would then grow faster than the paths that run between them.")
        for text in (wrapped, wide):
            with self.subTest(text[:20]):
                self.assertEqual(read_plain(text + "\n\nNext."),
                                 [{"type": "para", "text": " ".join(text.split())},
                                  {"type": "para", "text": "Next."}])

    def test_short_lines_beside_long_lines_that_end_sentences_are_their_own_blocks(self):
        # Two long lines that end sentences, and no line that carries on in lower case (R73).
        text = "\n".join(["By Sam Rivera", LONG1, LONG2]) + "\n\n" + LONG3
        self.assertEqual(read_plain(text), [{"type": "para", "text": line}
                                            for line in ["By Sam Rivera", LONG1, LONG2, LONG3]])

    def test_a_chunk_splits_only_with_two_long_lines(self):
        self.assertEqual(tm_extract._LONG_LINE_WORDS, tm_source._BODY_WORDS)
        # One long line, even one that ends a sentence, may be the last line of a wrapped
        # paragraph, so the chunk stays whole; with two long lines that end sentences it splits.
        for count, split in ((11, False), (12, True)):
            with self.subTest(words=count):
                line = "Leaves " + " ".join(["fall"] * (count - 2)) + " here."
                texts = [line, LONG1] if split else [line + " " + LONG1]
                self.assertEqual(read_plain(LONG2 + "\n\n" + line + "\n" + LONG1 + "\n\nNext."),
                                 [{"type": "para", "text": text}
                                  for text in [LONG2, *texts, "Next."]])

    def test_a_wrapped_paragraph_whose_only_long_line_is_its_last_stays_whole(self):
        # The re-review's repro (R73): an 11-word line, then a 12-word line that ends a
        # sentence, between blank lines. R72 tore it and made the first half a heading.
        first = "The members of a choir can vote to sing on a"
        second = "night in every month, but the singers would then rest on Sundays."
        self.assertEqual((len(first.split()), len(second.split())), (11, 12))
        self.assertEqual(read_plain(LONG1 + "\n\n" + first + "\n" + second + "\n\n" + LONG2),
                         [{"type": "para", "text": text}
                          for text in [LONG1, first + " " + second, LONG2]])

    def test_a_line_that_carries_on_in_lower_case_keeps_its_chunk_whole(self):
        # Every long line ends a sentence here, but two lines start in lower case, as wrapped
        # continuations do; a line that starts with "I" or a name does not undo that.
        lines = ["Gardeners can change the watering rota at any time, as the vote in March showed.",
                 "I doubt it matters, because the beans had already climbed past the fence.",
                 "and they had no reason to stop, whatever the gardeners chose to plant.",
                 "Madison saw the same pattern in factions that outlast the cause behind them.",
                 "which is why the remedy has to work on the effects and not the causes."]
        self.assertTrue(all(len(line.split()) >= 12 for line in lines))
        self.assertEqual(read_plain(LONG1 + "\n\n" + "\n".join(lines) + "\n\n" + LONG2),
                         [{"type": "para", "text": text}
                          for text in [LONG1, " ".join(lines), LONG2]])

    def test_captions_between_long_lines_are_paragraphs_not_headings(self):
        text = "\n".join([LONG1, "Figure 1: Fees by year", LONG2, "Table 1: Owners of each rail",
                          LONG3])
        self.assertEqual(read_plain(text), [{"type": "para", "text": line}
                                            for line in text.split("\n")])

    def test_a_hard_wrapped_text_with_no_blank_line_gives_plain_paragraphs(self):
        # No headings from its fragments (R73): a line carries on in lower case, so the text is
        # read one paragraph per line, as before R72.
        lines = ["The gardens grow each spring between the houses, and every garden needs",
                 "a plot of its own",
                 "that gets sun. The neighbours want a rota that would let them water each one",
                 "Of the gardens",
                 "and share the beans."]
        self.assertEqual(read_plain("\n".join(lines)),
                         [{"type": "para", "text": line} for line in lines])

    def test_a_heading_line_starts_with_a_capital_or_a_letter_without_case(self):
        for line, heading in (("Analysis", True), ("두 번째 부분", True), ("analysis", False),
                              ("Fees, rails and,", False), ("Fees and rails;", False),
                              ("Fees and rails -", False), ("2 Analysis", False),
                              ("Figure 2 Fees", False)):
            with self.subTest(line):
                blocks = read_plain("\n".join([LONG1, line, LONG2]))
                self.assertEqual(blocks[1]["type"], "heading" if heading else "para")

    def test_a_word_export_with_heading_lines(self):
        # Word's plain-text export of an essay with headings: short heading lines between
        # one-line paragraphs. A short line with no sentence mark between long lines is a
        # heading; one before the first long line is a front line, as usual (R72).
        text = "\r\n".join(["Free Rails", "", "Introduction", LONG1, LONG2, "Analysis", LONG3,
                            "Leaves fall.", LONG4]) + "\r\n"
        self.assertEqual(read_plain(text), [
            {"type": "para", "text": "Free Rails"}, {"type": "para", "text": "Introduction"},
            {"type": "para", "text": LONG1}, {"type": "para", "text": LONG2},
            {"type": "heading", "level": 1, "text": "Analysis"}, {"type": "para", "text": LONG3},
            {"type": "para", "text": "Leaves fall."}, {"type": "para", "text": LONG4}])
        # The same export with no blank line at all reads the same way.
        self.assertEqual(read_plain(text.replace("\r\n\r\n", "\r\n")), read_plain(text))

    def test_a_korean_word_export(self):
        sentences = ("마을 정원은 봄마다 집과 집 사이의 빈터에서 채소를 기르고 이웃들은 돌아가며 물을 "
                     "주어 밭을 지킨다.",
                     "비가 적게 와서 여름 내내 물을 길어야 했지만 이웃들은 그 수고를 거의 불평하지 않았다.",
                     "그래서 이웃들은 가을에 함께 모여 수확한 채소를 나누고 남은 씨앗을 다음 해를 위해 모아 둔다.")
        text = "\n".join(["자유로운 레일", "", sentences[0], sentences[1], "두 번째 부분", sentences[2]])
        self.assertEqual(read_plain(text), [
            {"type": "para", "text": "자유로운 레일"}, {"type": "para", "text": sentences[0]},
            {"type": "para", "text": sentences[1]},
            {"type": "heading", "level": 1, "text": "두 번째 부분"},
            {"type": "para", "text": sentences[2]}])
