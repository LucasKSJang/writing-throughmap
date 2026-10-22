"""Builders and sample data shared by the test modules.

Sections: temporary files, Word documents (.docx), reader blocks with sample sources, running the
command line, the sample draft with its analysis, the stub page and analyses for build, the
real page with the analyses its tests open, and the sentences, items, versions and builds of a draft
that the comparison of two versions works on. Later tasks add their helpers below.
"""

from __future__ import annotations

import atexit
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from throughmap import main
from tm_build import DEFAULT_TEMPLATE, build, compute_observations, compute_runs, render_html
from tm_check import ROLES
from tm_source import assemble_source
from tm_text import word_count

# --- Temporary files ---------------------------------------------------------------------------


def _scratch_dir() -> str:
    """Create an empty directory that is deleted when the test run ends."""
    path = tempfile.mkdtemp(prefix="throughmap-test-")
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def tmp_path(name: str) -> str:
    """Return the path of ``name`` inside a fresh temporary directory, one directory per call."""
    return os.path.join(_scratch_dir(), name)


def tmp_dir(*parts: str) -> str:
    """Create a fresh temporary directory holding the nested folders ``parts``; return the last."""
    path = os.path.join(_scratch_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


# --- Word documents (.docx) --------------------------------------------------------------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_PACKAGE_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Prefixes a test body may use. Real Word files declare these and more on w:document.
_BODY_NAMESPACES = {
    "w": W_NS,
    "r": _OFFICE_REL,
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
}


def P(text: str, style: str | None = None) -> str:
    """Return one paragraph holding one run of ``text``, in the paragraph style id ``style``."""
    properties = f"<w:pPr><w:pStyle w:val={quoteattr(style)}/></w:pPr>" if style else ""
    return f'<w:p>{properties}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def TABLE(rows: list[list[str]]) -> str:
    """Return a table with one paragraph in each cell. ``rows`` lists the cell texts of each row."""
    grid = '<w:gridCol w:w="2000"/>' * max(len(row) for row in rows)
    body = "".join(
        "<w:tr>" + "".join(f"<w:tc>{P(cell)}</w:tc>" for cell in row) + "</w:tr>" for row in rows
    )
    return (f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>")


def wrap_styles(styles: str) -> str:
    """Wrap ``w:style`` elements in a complete word/styles.xml document."""
    return f'{_XML_DECLARATION}<w:styles xmlns:w="{W_NS}">{styles}</w:styles>'


# The built-in names Word stores, whatever language its menus are in.
STYLES_EN = wrap_styles(
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
)


def _document_xml(body_xml: str) -> str:
    declared = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in _BODY_NAMESPACES.items())
    return f"{_XML_DECLARATION}<w:document {declared}><w:body>{body_xml}</w:body></w:document>"


def _content_types_xml(with_styles: bool) -> str:
    kind = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    styles = (f'<Override PartName="/word/styles.xml" ContentType="{kind}.styles+xml"/>'
              if with_styles else "")
    return (f'{_XML_DECLARATION}'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{kind}.document.main+xml"/>'
            f"{styles}</Types>")


def _relationships_xml(kind: str, target: str) -> str:
    return (f'{_XML_DECLARATION}<Relationships xmlns="{_PACKAGE_RELS_NS}">'
            f'<Relationship Id="rId1" Type="{_OFFICE_REL}/{kind}" Target="{target}"/>'
            "</Relationships>")


def make_docx(path: str, body_xml: str, styles_xml: str | None = None) -> None:
    """Write a minimal, valid .docx at ``path``.

    ``body_xml`` becomes the content of ``w:body``. ``styles_xml`` is a complete word/styles.xml
    document (see wrap_styles); without it the package has no styles part.
    """
    parts = {
        "[Content_Types].xml": _content_types_xml(with_styles=styles_xml is not None),
        "_rels/.rels": _relationships_xml("officeDocument", "word/document.xml"),
        "word/document.xml": _document_xml(body_xml),
    }
    if styles_xml is not None:
        parts["word/_rels/document.xml.rels"] = _relationships_xml("styles", "styles.xml")
        parts["word/styles.xml"] = styles_xml
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def make_corrupt_docx(path: str) -> None:
    """Write a .docx at ``path`` whose word/document.xml has a broken deflate stream.

    The package and its directory are intact, so the file opens as a zip; only reading the
    document part fails, with zlib.error, as it does for a file damaged in a download.
    """
    make_docx(path, P("A paragraph that the damage makes unreadable."), STYLES_EN)
    with zipfile.ZipFile(path) as archive:
        offset = archive.getinfo("word/document.xml").header_offset
    with open(path, "r+b") as handle:
        handle.seek(offset + 26)   # the local header gives the lengths of the name and extra field
        name_length, extra_length = (int.from_bytes(handle.read(2), "little") for _ in range(2))
        handle.seek(offset + 30 + name_length + extra_length)
        handle.write(b"\xff" * 8)  # a deflate block of the reserved type 3 is invalid


# --- Reader blocks and sample sources ----------------------------------------------------------


def B(kind: str, text: str, level: int | None = None) -> dict:
    """Return a block as the readers give it: ``B("heading", "Intro", 1)`` or ``B("para", "x")``."""
    if level is None:
        return {"type": kind, "text": text}
    return {"type": kind, "level": level, "text": text}


# Paragraphs of 12 words or more, so the rules for front matter and closing lines leave them be.
LONG1 = "Gardens grow beans between the houses, and every garden needs a little rain each week."
LONG2 = "Beans in these gardens grow fast because rain keeps the soil damp all summer."
LONG3 = "A rota would let neighbours water every bed, but nobody would then skip a week."
LONG4 = "Tomatoes ripen first in the sunny corners, since the brick walls hold the heat."

# The paragraphs behind FIVE. T4 is T4_BEFORE and T4_AFTER with "However," between them.
T1 = "The first paragraph states the problem plainly and gives the reader a reason to keep going."
T2 = "The second paragraph names the first claim and ties it to the rain that every garden needs."
T3 = "The third paragraph adds a case showing the claim holds while the neighbours share the crop."
T4_BEFORE = "The fourth paragraph opens by describing the rule as it stands today in most gardens."
T4_AFTER = " the neighbours can still change the rule once the summer is far drier than the spring."
T4 = T4_BEFORE + " However," + T4_AFTER
T5 = "The fifth paragraph closes the argument and names the question the next section answers."


def sections_of(sizes: dict[str, int]) -> list[tuple[str, list[str]]]:
    """Return ``(title, paragraph texts)`` for each section of ``sizes``; the numbering runs on."""
    sections, number = [], 0
    for title, count in sizes.items():
        texts = []
        for _ in range(count):
            number += 1
            texts.append(f"Paragraph {number} adds one more step to the argument, in plain words "
                         "that are easy to follow.")
        sections.append((title, texts))
    return sections


def _sample(blocks: list[dict]) -> dict:
    return assemble_source(blocks, title_hint="Essay", source_name="essay.md", source_kind="md")


# Prebuilt sources. Tests must not change them: apply_corrections and select_section return copies.
FIVE = _sample([B("para", text) for text in (T1, T2, T3, T4, T5)])
FIVE_TWO_SECTIONS = _sample([
    B("heading", "First", 1), B("para", T1), B("para", T2),
    B("heading", "Second", 1), B("para", T3), B("para", T4), B("para", T5),
])
FORTY_FIVE = _sample([
    block
    for title, texts in sections_of({"One": 15, "Two": 15, "Three": 15})
    for block in [B("heading", title, 1), *(B("para", text) for text in texts)]
])


def write_md(folder: str, name: str, sections: dict[str, int]) -> str:
    """Write a Markdown draft with a "# title" heading per section of ``sections``; return its path.

    ``sections`` maps each section title to its number of paragraphs, as in sections_of().
    """
    lines = []
    for title, texts in sections_of(sections):
        lines.extend([f"# {title}", *texts])
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(lines) + "\n")
    return path


# --- Running the command line ------------------------------------------------------------------


def run_main_streams(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    """Run throughmap.main(argv) in this process; return its exit code, stdout and stderr.

    Standard input is replaced by ``stdin`` (empty when None), so a command that reads it never
    waits on the test runner's terminal.
    """
    out, err = io.StringIO(), io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin or "")
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    finally:
        sys.stdin = saved_stdin
    return code, out.getvalue(), err.getvalue()


def run_main(argv: list[str], stdin: str | None = None) -> tuple[int, str]:
    """Run throughmap.main(argv); return its exit code and what it printed on stdout."""
    code, out, _ = run_main_streams(argv, stdin)
    return code, out


# --- The sample draft and its analysis (check and build) ----------------------------------------

SAMPLE_P1 = ("Small bakeries bake bread for every street, and every loaf needs a long rest before "
             "the oven.")
SAMPLE_P2 = ("Acme runs one such bakery and keeps most of the dough overnight, so its bakers "
             "ask how long it should rest.")
# What a draft from Word holds: curly quotes, an em dash and a no-break space.
SAMPLE_P3 = ("Critics call the rest a \N{LEFT DOUBLE QUOTATION MARK}curly"
             "\N{RIGHT DOUBLE QUOTATION MARK} delay\N{EM DASH}yet bakers knead the dough only"
             "\N{NO-BREAK SPACE}once, and the starter keeps working when shifts change.")
# P3 as an agent types it back: straight quotes, a hyphen and a plain space.
STRAIGHT_VERSION_OF_P3_SENTENCE = ('Critics call the rest a "curly" delay-yet bakers knead the '
                                   "dough only once, and the starter keeps working when shifts "
                                   "change.")
SAMPLE_P4 = ("The table below sets out how long each loaf rests, and it shows that the slow loaf, "
             "not the quick one, keeps its crumb soft.")
SAMPLE_TABLE_CAPTION = "Table 1: Rest times, rise and crumb."
SAMPLE_TABLE_TEXT = "Loaf | Rest | Soft on day two\nQuick | One hour | No\nSlow | Overnight | Yes"
SAMPLE_P5 = ("Acme shows the pattern well because the slow loaf stays soft while the quick loaf "
             "on the shelf goes stale by Monday.")
SAMPLE_P6 = ("In the end the question is not how fast the dough rises but how long it rests where "
             "the kitchen stays cool.")
# Thirteen words in a row, with no stop among them, so a direction can quote them as they are.
THIRTEEN_WORDS_FROM_P5 = " ".join(SAMPLE_P5.split()[:13])


def sample_source() -> dict:
    """Return the source of the sample essay, assembled the way ``extract`` assembles a draft.

    Six paragraphs in three sections (an untitled P1 to P2, "Middle" P3 to P4, "End" P5 to P6) and
    the table T1 after P4. P3 holds the typography of SAMPLE_P3. A new source on every call.
    """
    return assemble_source(
        [B("para", SAMPLE_P1), B("para", SAMPLE_P2),
         B("heading", "Middle", 1), B("para", SAMPLE_P3), B("para", SAMPLE_P4),
         B("para", SAMPLE_TABLE_CAPTION), B("table", SAMPLE_TABLE_TEXT),
         B("heading", "End", 1), B("para", SAMPLE_P5), B("para", SAMPLE_P6)],
        title_hint="Sample Essay", source_name="sample.md", source_kind="md")


# Per item: id, kind, section, role, label, evidence, and the lane marks as {lane: (weight, quote)}.
_SAMPLE_ITEMS = (
    ("P1", "paragraph", "S1", "problem", "Every loaf rests long",
     "every loaf needs a long rest before the oven",
     {"q1": ("major", "every loaf needs a long rest")}),
    ("P2", "paragraph", "S1", "example", "Acme keeps dough overnight",
     "Acme runs one such bakery and keeps most of the dough",
     {"q2": ("minor", "keeps most of the dough"), "own": ("major", "how long it should rest")}),
    ("P3", "paragraph", "S2", "claim", "The rest costs little",
     "bakers knead the dough only once",
     {"q1": ("major", "the starter keeps working when shifts change")}),
    ("P4", "paragraph", "S2", "evidence", "Slow loaves stay soft",
     "the slow loaf, not the quick one, keeps its crumb soft",
     {"own": ("minor", "how long each loaf rests")}),
    ("T1", "table", "S2", "synthesis", "Rest times by loaf",
     SAMPLE_TABLE_CAPTION,
     {"own": ("major", "Slow | Overnight | Yes")}),
    ("P5", "paragraph", "S3", "example", "Acme repeats the pattern",
     "the slow loaf stays soft",
     {"q2": ("major", "goes stale by Monday")}),
    ("P6", "paragraph", "S3", "conclusion", "Rest time decides",
     "how long it rests",
     {"q1": ("minor", "how fast the dough rises"),
      "q2": ("major", "where the kitchen stays cool"),
      "own": ("major", "how long it rests")}),
)


def sample_analysis(ui_language: str = "en") -> dict:
    """Return a valid analysis of sample_source(), a new one on every call.

    The items run P1, P2, P3, P4, T1, P5, P6, so the table is the item at index 4. P3 is a claim
    and T1 a synthesis. There are the questions Q1 and Q2 and the lanes q1 (question Q1), q2
    (question Q2) and own (a concept lane for Q2), each marked at least once. The case Acme recurs
    in P2 and P5, and one gap sits at P3.
    """
    source = sample_source()
    texts = {paragraph["id"]: paragraph["text"] for paragraph in source["paragraphs"]}
    table = source["tables"][0]
    texts[table["id"]] = table["caption"] + "\n" + table["text"]
    return {
        "schema": "throughmap/1",
        "essay": {"title": "Sample Essay", "source": "sample.md", "source_kind": "md",
                  "language": "en", "word_count": source["essay"]["word_count"]},
        "ui_language": ui_language,
        "thesis": "How long the dough rests, not how fast it rises, keeps a loaf soft for days.",
        "questions": [{"id": "Q1", "text": "Does a long rest slow the bakery down?"},
                      {"id": "Q2", "text": "What keeps a loaf soft?"}],
        "lanes": [
            {"id": "q1", "kind": "question", "label": "Pace", "sub": "Does resting slow it?",
             "question": "Q1"},
            {"id": "q2", "kind": "question", "label": "Softness", "question": "Q2"},
            {"id": "own", "kind": "concept", "label": "Rest time", "question": "Q2"},
        ],
        "sections": [
            {"id": "S1", "short": "Opening", "title": "", "inferred": False,
             "first": "P1", "last": "P2",
             "conclusion": "Every loaf needs a long rest, and Acme keeps its dough overnight.",
             "baton": "Does the rest slow the bakery?", "answers": ["Q1"]},
            {"id": "S2", "short": "Middle", "title": "Middle", "inferred": False,
             "first": "P3", "last": "P4",
             "conclusion": "The rest costs little, and the slow loaf keeps its crumb soft.",
             "baton": "Does Acme show the pattern?", "answers": ["Q1", "Q2"]},
            {"id": "S3", "short": "End", "title": "End", "inferred": False,
             "first": "P5", "last": "P6",
             "conclusion": "How long the dough rests, not how fast it rises, decides the crumb.",
             "baton": "", "answers": ["Q2"]},
        ],
        "paragraphs": [
            {"id": item_id, "kind": kind, "section": section, "text": texts[item_id], "role": role,
             "label": label, "evidence": evidence,
             "lanes": {lane: {"weight": weight, "quote": quote}
                       for lane, (weight, quote) in marks.items()}}
            for item_id, kind, section, role, label, evidence, marks in _SAMPLE_ITEMS
        ],
        "cases": [{"name": "Acme", "at": ["P2", "P5"],
                   "note": "Acme returns as the running example of a bakery resting its dough."}],
        "gaps": [{"at": ["P3"],
                  "note": "P3 says the rest costs little but never ties it to the rest times.",
                  "direction": "Connect P3 to the rest-time thread."}],
    }


def with_lanes(analysis: dict, count: int) -> dict:
    """Return a copy of ``analysis`` with exactly ``count`` lanes, each of them marked.

    The first three lanes are q1, q2 and own. Further ones are concept lanes named extra4, extra5
    and so on, marked in P1. Lanes cut away take their marks with them.
    """
    result = copy.deepcopy(analysis)
    lanes = result["lanes"][:count]
    lanes += [{"id": f"extra{n}", "kind": "concept", "label": f"Extra {n}"}
              for n in range(len(lanes) + 1, count + 1)]
    result["lanes"] = lanes
    kept = {lane["id"] for lane in lanes}
    for item in result["paragraphs"]:
        item["lanes"] = {lane: mark for lane, mark in item["lanes"].items() if lane in kept}
    first = result["paragraphs"][0]
    for lane in lanes:
        if not any(lane["id"] in item["lanes"] for item in result["paragraphs"]):
            first["lanes"][lane["id"]] = {"weight": "minor", "quote": "Small bakeries"}
    return result


def with_questions(analysis: dict, count: int) -> dict:
    """Return a copy of ``analysis`` with exactly ``count`` questions, Q1 to Q<count>."""
    result = copy.deepcopy(analysis)
    known = result["questions"]
    result["questions"] = [known[n] if n < len(known)
                           else {"id": f"Q{n + 1}", "text": f"Question {n + 1}?"}
                           for n in range(count)]
    return result


def with_paragraphs(count: int) -> tuple[dict, dict]:
    """Return ``(analysis, source)`` for a draft of ``count`` paragraphs in one section, "One".

    The analysis is valid apart from what its size breaks. Only P1 is on a thread, the lane q1.
    """
    texts = sections_of({"One": count})[0][1]
    # "# Numbered Essay" then "## One": a lone heading that opens a draft would be its title.
    source = assemble_source([B("heading", "Numbered Essay", 1), B("heading", "One", 2),
                              *(B("para", text) for text in texts)],
                             title_hint="Numbered Essay", source_name="numbered.md",
                             source_kind="md")
    analysis = sample_analysis()
    analysis["essay"].update(title="Numbered Essay", source="numbered.md",
                             word_count=source["essay"]["word_count"])
    analysis["lanes"] = analysis["lanes"][:1]
    analysis["sections"] = [{
        "id": "S1", "short": "One", "title": "One", "inferred": False, "first": "P1",
        "last": f"P{count}", "conclusion": "Each paragraph adds one step.", "baton": "",
        "answers": ["Q1"]}]
    analysis["paragraphs"] = [
        {"id": paragraph["id"], "kind": "paragraph", "section": "S1", "text": paragraph["text"],
         "role": "claim", "label": f"Step {number}", "evidence": "adds one more step",
         "lanes": {"q1": {"weight": "major", "quote": "adds one more step"}} if number == 1 else {}}
        for number, paragraph in enumerate(source["paragraphs"], 1)]
    analysis["cases"], analysis["gaps"] = [], []
    return analysis, source


def without_marks(analysis: dict, lane_id: str) -> dict:
    """Return a copy of ``analysis`` in which no item is marked on the lane ``lane_id``."""
    result = copy.deepcopy(analysis)
    for item in result["paragraphs"]:
        item["lanes"].pop(lane_id, None)
    return result


def table_item(analysis: dict) -> dict:
    """Return the table item of ``analysis`` itself, so that a test can change it in place."""
    return next(item for item in analysis["paragraphs"] if item["kind"] == "table")


def rewrite_draft(draft: str, source: dict, analysis: dict) -> None:
    """Write source.json and draft.json beside ``draft``, as write_draft writes them.

    The files that are there are replaced: this is the next analysis of the same draft.
    """
    folder = os.path.dirname(draft)
    for name, data in (("source.json", source), ("draft.json", analysis)):
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.write("\n")


def write_draft(source: dict, analysis: dict) -> str:
    """Write source.json and draft.json into a new x.throughmap folder; return draft.json's path."""
    draft = os.path.join(tmp_dir("x.throughmap"), "draft.json")
    rewrite_draft(draft, source, analysis)
    return draft


# --- Build: the stub page and analyses for the computed fields ----------------------------------

# The skeleton page, as assets/template.html first had it. The build tests use this instead of the
# real template, so that they do not depend on the page renderer.
STUB_TEMPLATE = (
    "<!doctype html>\n"
    "<html>\n"
    "<head>\n"
    '<meta charset="utf-8">\n'
    "<title>throughmap</title>\n"
    "</head>\n"
    "<body>\n"
    '<script id="throughmap-data" type="application/json">__THROUGHMAP_DATA__</script>\n'
    "</body>\n"
    "</html>\n"
)


def _write_stub_template() -> str:
    path = tmp_path("template.html")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(STUB_TEMPLATE)
    return path


STUB_TEMPLATE_PATH = _write_stub_template()


def lanes_marked(marks: dict[str, list[str]]) -> dict:
    """Return the sample analysis with only the lane marks in ``marks``, a lane id to item ids.

    Each mark is major and quotes the first five words of its item, so every quote is verbatim. A
    lane that ``marks`` leaves out has no marks at all: the result is for the computed fields, not
    for check. Raises KeyError for a lane or an item that the sample does not have.
    """
    analysis = sample_analysis()
    lanes = {lane["id"] for lane in analysis["lanes"]}
    items = {item["id"]: item for item in analysis["paragraphs"]}
    for item in items.values():
        item["lanes"] = {}
    for lane_id, item_ids in marks.items():
        if lane_id not in lanes:
            raise KeyError(lane_id)
        for item_id in item_ids:
            item = items[item_id]
            item["lanes"][lane_id] = {"weight": "major",
                                      "quote": " ".join(item["text"].split()[:5])}
    return analysis


def n_paragraphs(n: int, marks: dict[str, list[str]], table_after: str | None = None) -> dict:
    """Return an analysis of the paragraphs P1 to P<n> in one section, S1, for the computed fields.

    ``marks`` maps a lane id to the ids of the items that mark it, and names the lanes: each is a
    question lane. ``table_after`` is the id of the paragraph that the table T1 follows; the table
    may be marked as T1. The source of the draft is not part of the result, so check would not
    find the table in it.
    """
    analysis, _ = with_paragraphs(n)
    analysis["lanes"] = [{"id": lane_id, "kind": "question", "label": lane_id, "question": "Q1"}
                         for lane_id in marks]
    if table_after is not None:
        position = [item["id"] for item in analysis["paragraphs"]].index(table_after) + 1
        analysis["paragraphs"].insert(position, {
            "id": "T1", "kind": "table", "section": "S1", "text": "Table 1: Sizes.",
            "role": "evidence", "label": "Sizes", "evidence": "Table 1: Sizes.", "lanes": {}})
    for item in analysis["paragraphs"]:
        item["lanes"] = {lane_id: {"weight": "major", "quote": "adds one more step"}
                         for lane_id, item_ids in marks.items() if item["id"] in item_ids}
    return analysis


def quiet(observations: list[dict]) -> list[dict]:
    """Return the quiet-thread entries of ``observations``, in their order."""
    return [observation for observation in observations if observation["type"] == "quiet"]


def built_sample() -> dict:
    """Return sample_analysis() as build writes it to v1.json: with version, time and computed.

    The runs and observations are worked out by hand from the items P1, P2, P3, P4, T1, P5, P6.
    Every paragraph is on a thread, no thread rests for 6 paragraphs and each one is marked in S3.
    """
    data = sample_analysis()
    data.update(version=1, generated_at="2026-10-17T12:00:00Z", computed={
        "runs": {
            "q1": {"span": ["P1", "P6"], "solid": []},
            "q2": {"span": ["P2", "P6"], "solid": [["P5", "P6"]]},
            "own": {"span": ["P2", "P6"], "solid": [["P4", "T1"]]},
        },
        "observations": [],
    })
    return data


def sample_with_unthreaded_P3_and_own_missing_from_last_section() -> dict:
    """Return the sample analysis changed so that it has two observations.

    P3 has no marks. P4 has the role transition and no marks. The lane own, marked in P2 and T1,
    loses its mark in P6 and so has none in the last section, End.
    """
    analysis = sample_analysis()
    items = {item["id"]: item for item in analysis["paragraphs"]}
    items["P3"]["lanes"] = {}
    items["P4"]["role"], items["P4"]["lanes"] = "transition", {}
    del items["P6"]["lanes"]["own"]
    return analysis


# --- The page: the real template, and the analyses its tests open --------------------------------

TEMPLATE_PATH = Path(DEFAULT_TEMPLATE)   # assets/template.html, the page renderer

EVIDENCE_OF_P2 = next(evidence for item_id, _, _, _, _, evidence, _ in _SAMPLE_ITEMS
                      if item_id == "P2")


def source_of(analysis: dict) -> dict:
    """Return the source.json that ``analysis`` agrees with, shaped as extract writes it.

    The paragraphs, tables and figures are the items of the analysis with their texts. A table's
    text is split at its first line break into the caption and the rows; a figure's text is its
    caption. Each table and figure follows the paragraph before it. The sections are the ones
    that are not inferred, since extract finds only the headings the draft has. A new source on
    every call: ``source_of(sample_analysis())`` equals ``sample_source()``.
    """
    paragraphs, tables, figures, before = [], [], [], None
    for item in analysis["paragraphs"]:
        if item["kind"] == "paragraph":
            paragraphs.append({"id": item["id"], "text": item["text"]})
            before = item["id"]
        elif item["kind"] == "table":
            caption, _, rows = item["text"].partition("\n")
            tables.append({"id": item["id"], "caption": caption, "after": before, "text": rows})
        else:
            figures.append({"id": item["id"], "caption": item["text"], "after": before})
    essay = analysis["essay"]
    return {
        "schema": "throughmap-source/1",
        "essay": {"title": essay["title"], "source": essay["source"],
                  "source_kind": essay["source_kind"], "word_count": essay["word_count"],
                  "paragraph_count": len(paragraphs)},
        "paragraphs": paragraphs,
        "tables": tables,
        "figures": figures,
        "sections": [{"title": section["title"], "first": section["first"],
                      "last": section["last"]}
                     for section in analysis["sections"] if not section["inferred"]],
        "excluded": [],
    }


def page(analysis: dict) -> str:
    """Build ``analysis`` into a page with the real template; return the path of its index.html.

    source.json is source_of(analysis), so the two agree. build checks the analysis first and
    raises BuildError if it has errors, as it does for an agent.
    """
    draft = write_draft(source_of(analysis), analysis)
    return build(draft, str(TEMPLATE_PATH))["html_path"]


def write_page_directly(analysis: dict) -> str:
    """Put ``analysis`` into the real template with render_html, unchecked; return the page's path.

    This is the page an agent without Python makes (spec 5.4): nothing has checked the quotes, so
    the page's own check is all there is. ``analysis`` may be built data, with version and
    computed, or lack them.
    """
    path = tmp_path("index.html")
    with open(path, "wb") as handle:
        handle.write(render_html(analysis, TEMPLATE_PATH.read_text("utf-8")).encode("utf-8"))
    return path


def analysis_with_text(item_id: str, text: str) -> dict:
    """Return sample_analysis() with ``text`` as the text of the item ``item_id``.

    The evidence and each lane quote of the item become the whole new text, so they stay
    verbatim. page() derives source.json from the analysis, so the source holds the new text too.
    Raises KeyError for an id that the sample does not have.
    """
    analysis = sample_analysis()
    items = {item["id"]: item for item in analysis["paragraphs"]}
    item = items[item_id]
    item["text"] = item["evidence"] = text
    for mark in item["lanes"].values():
        mark["quote"] = text
    return analysis


# The marks of forty_paragraphs(): lane -> paragraph numbers. q1 has two solid runs and a rest of
# 16 paragraphs (P14 to P29); q2 never marks two paragraphs in a row; own has two solid runs.
_FORTY_MARKS = {"q1": (1, 2, 3, 12, 13, 30, 40), "q2": tuple(range(4, 41, 4)),
                "own": (5, 6, 20, 21, 22, 38)}


def forty_paragraphs(first_section_size: int = 7) -> dict:
    """Return a valid analysis of 40 paragraphs, the most that one map holds, in four sections.

    The first section, S1, holds P1 to P<first_section_size> (1 to 37). The other paragraphs are
    split as evenly as possible into S2, S3 and S4, named "Part 2" and so on. The lanes are the
    sample's q1, q2 and own, marked as _FORTY_MARKS says: a mark on a multiple of 3 is minor,
    the others are major. The roles go through ROLES in turn. Every quote is verbatim.
    """
    if not 1 <= first_section_size <= 37:
        raise ValueError("the first section holds 1 to 37 of the 40 paragraphs")
    analysis, _ = with_paragraphs(40)
    analysis["essay"].update(title="Forty Paragraphs", source="forty.md")
    analysis["lanes"] = sample_analysis()["lanes"]
    rest = 40 - first_section_size
    sizes = [first_section_size] + [rest // 3 + (1 if n < rest % 3 else 0) for n in range(3)]
    sections, first = [], 1
    for number, size in enumerate(sizes, 1):
        last = first + size - 1
        sections.append({
            "id": f"S{number}", "short": f"Part {number}", "title": f"Part {number}",
            "inferred": False, "first": f"P{first}", "last": f"P{last}",
            "conclusion": f"Part {number} takes the argument one step further.",
            "baton": "What comes next?" if number < len(sizes) else "",
            "answers": ["Q1"] if number % 2 else ["Q2"]})
        for item in analysis["paragraphs"][first - 1:last]:
            item["section"] = f"S{number}"
        first = last + 1
    analysis["sections"] = sections
    for number, item in enumerate(analysis["paragraphs"], 1):
        item["role"] = ROLES[(number - 1) % len(ROLES)]
        item["lanes"] = {lane: {"weight": "minor" if number % 3 == 0 else "major",
                                "quote": "adds one more step"}
                         for lane, numbers in _FORTY_MARKS.items() if number in numbers}
    analysis["cases"] = [{"name": "Acme", "at": ["P2", "P30"],
                          "note": "Acme comes back near the end."}]
    return analysis


def total_marks(analysis: dict) -> int:
    """Count the lane marks on all the items of ``analysis``: the dots its map draws."""
    return sum(len(item["lanes"]) for item in analysis["paragraphs"])


# --- Comparison: two versions of a draft -------------------------------------------------------

# Thirty statements about bread or gardens, each of 12 to 15 words. No two share more than three
# words besides "the", "a", "and" and "of", so paragraphs built from different ones are unrelated to
# the matching. A test names a sentence by its number from 1: para(1, 2) joins the first two.
SENTENCES = (
    "Rye loaves need patience, because the sour starter wakes slowly in a cold kitchen overnight.",
    "Sunflowers turn their heavy heads toward the east every morning until August ends.",
    "Our baker scores each loaf with a razor so steam can escape.",
    "Compost warms beneath old straw, feeding worms that loosen soil around young carrots.",
    "Flour, water and salt are all a loaf needs, yet nobody bakes two the same.",
    "Marigolds planted between the tomato rows keep aphids away without any spray.",
    "Warm bread tastes best when the crust crackles softly while you slice it.",
    "A cracked terracotta pot still holds basil, provided the roots find some shade.",
    "Sourdough keeps its tang because wild yeast and friendly bacteria share one jar.",
    "Neighbours swap surplus zucchini over the fence every July, grumbling about how many grew.",
    "Kneading stretches the gluten until the dough turns smooth, elastic and faintly shiny.",
    "Raised beds drain faster than flat ground, which suits lettuce in a wet spring.",
    "Her grandmother braided the festival bread from seven ropes, one for every weekday.",
    "Slugs gather under damp boards at dawn, so lift them and move the whole crowd.",
    "Stale baguette becomes breadcrumbs, croutons or pudding, so the pantry throws nothing away.",
    "Peas climb the netting unaided once their tendrils discover something thin enough to hold.",
    "The village oven fires at four, and queues form long before the shutters lift.",
    "Frost nips the pumpkin vines overnight, though the squash beneath their leaves survives.",
    "Brioche is rich with butter and eggs, a treat nobody finishes alone.",
    "Mint spreads underground, so most gardeners confine it to a bucket sunk in the lawn.",
    "Flatbreads blister on the hot stone, and the cook flips them with bare fingers.",
    "Bees visit the lavender hedge all afternoon, humming louder as the heat rises.",
    "Yeast feeds on sugar and breathes out tiny bubbles that lift the dough.",
    "Rhubarb returns each spring without help, pushing pink stalks through the cold mud.",
    "Customers argue whether a seeded crust beats a plain one, and the baker just smiles.",
    "Watering at noon wastes most of it, since the sun drinks first.",
    "Rice flour makes a crumb that is tender but crumbles when spread with jam.",
    "Beetroot leaves taste sweet when picked small, but turn tough once the summer peaks.",
    "The apprentice woke at midnight to shape rolls while everyone else slept.",
    "A scarecrow in the orchard has never frightened a single crow, only amused them.",
)

# A Korean paragraph about a bakery and its garden plot, and the same paragraph with the endings of
# five words changed from the present to the past: 섞는다, 부푼다, 지피고, 굽는다 and 맞바꾼다.
KO_BEFORE = ("빵집 주인은 새벽마다 텃밭에서 딴 허브를 반죽에 섞는다. 반죽은 밤새 서늘한 곳에서 천천히 부푼다. "
             "아침에 주인은 화덕에 불을 지피고 빵을 굽는다. 이웃들은 갓 구운 빵을 상추와 맞바꾼다.")
KO_AFTER = ("빵집 주인은 새벽마다 텃밭에서 딴 허브를 반죽에 섞었다. 반죽은 밤새 서늘한 곳에서 천천히 부풀었다. "
            "아침에 주인은 화덕에 불을 지폈고 빵을 구웠다. 이웃들은 갓 구운 빵을 상추와 맞바꿨다.")


def para(*numbers: int) -> str:
    """Return the sentences of SENTENCES numbered ``numbers`` (from 1), joined by spaces."""
    return " ".join(SENTENCES[number - 1] for number in numbers)


def items_of(*texts: str) -> list[dict]:
    """Return the paragraph items P1, P2 and so on, one for each of ``texts``, with no marks.

    Only the id, the kind and the text of an item matter to the matching. A new list every call.
    """
    return [{"id": f"P{number}", "kind": "paragraph", "text": text, "lanes": {}}
            for number, text in enumerate(texts, 1)]


def version_of(paragraphs: Sequence[str], marks: dict[str, Sequence[int]],
               gaps: Sequence[tuple[Sequence[int], str]] = (),
               ui_language: str = "en") -> tuple[dict, dict]:
    """Return ``(source, analysis)`` for a draft made of the texts ``paragraphs``; check passes both.

    The source holds the paragraphs P1 and on and no sections, so the analysis has one section, S1
    "Body", and it is inferred. The analysis is titled "Revision Essay" and has the question Q1
    and a lane for each key of ``marks``, in its order. A key that starts with "q" is a question
    lane for Q1, any other key a concept lane that serves Q1, and a lane's label is its id
    capitalized. ``marks`` maps a lane to the numbers (from 1) of the paragraphs it marks; each
    mark is major and quotes the first five words of its paragraph. Every paragraph is a claim,
    labelled "Part N", whose evidence is its first five words. ``gaps`` holds a pair of paragraph
    numbers and a note for each gap. New dicts on every call.
    """
    lanes = [{"id": lane_id, "kind": "question" if lane_id.startswith("q") else "concept",
              "label": lane_id.capitalize(), "question": "Q1"} for lane_id in marks]
    items = []
    for number, text in enumerate(paragraphs, 1):
        opening = " ".join(text.split()[:5])
        items.append({
            "id": f"P{number}", "kind": "paragraph", "section": "S1", "text": text,
            "role": "claim", "label": f"Part {number}", "evidence": opening,
            "lanes": {lane_id: {"weight": "major", "quote": opening}
                      for lane_id, numbers in marks.items() if number in numbers}})
    analysis = {
        "schema": "throughmap/1",
        "essay": {"title": "Revision Essay", "source": "revision.md", "source_kind": "md",
                  "language": "en", "word_count": sum(word_count(text) for text in paragraphs)},
        "ui_language": ui_language,
        "thesis": "Patient work in the kitchen and the garden pays off.",
        "questions": [{"id": "Q1", "text": "What does patience give a baker or a gardener?"}],
        "lanes": lanes,
        "sections": [{"id": "S1", "short": "Body", "title": "", "inferred": True, "first": "P1",
                      "last": f"P{len(paragraphs)}",
                      "conclusion": "Each paragraph adds one more observation.", "baton": "",
                      "answers": ["Q1"]}],
        "paragraphs": items,
        "cases": [],
        "gaps": [{"at": [f"P{number}" for number in numbers], "note": note,
                  "direction": "Tie it to the thesis, so that the reader sees why it matters."}
                 for numbers, note in gaps],
    }
    return source_of(analysis), analysis


def built_version(analysis: dict, version: int) -> dict:
    """Return ``analysis`` as build saves it as v<version>.json: with version, time and computed.

    The time is fixed. The runs and observations are the ones build works out for the analysis.
    """
    return {**analysis, "version": version, "generated_at": "2026-10-19T12:00:00Z",
            "computed": {"runs": compute_runs(analysis),
                         "observations": compute_observations(analysis)}}


# The note of the gap at P8 in the first version of revision(), a gap the second version drops.
GAP_AT_P8_NOTE = "P8 adds a claim that nothing before it supports."
# What changes_line says of revision(): its edited, added, removed, split, merged and moved
# paragraphs, then the marks, the threads, the quiet stretches and the gaps, in that order.
REVISION_CHANGES = ("changes from v1: 1 edited (P7) · 1 added (P8) · 1 removed (v1 P8) · "
                    "1 split (v1 P2 into P2 and P3) · 1 merged (v1 P5 and v1 P6 into P5) · "
                    "1 moved (v1 P3 to P7) · marks: 2 gained, 2 lost · 1 new thread (Cost) · "
                    "1 dropped thread (Gone) · quiet: 1 closed, 1 opened · "
                    "1 earlier gap no longer applies")


def revision(ui_language: str = "en") -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    """Return the first and the second version of one draft, each a (source, analysis) pair.

    What became of the eight paragraphs of v1 in v2 (v1's P8 is removed, and v2 has a new P8):
    - P1 and P4 stay as they are, and v1 P7 stays as P6.
    - v1 P2 is split into P2 and P3, and v1 P5 and P6 are merged into P5.
    - v1 P3 gets a sentence (it is edited) and moves to P7.
    The threads: v1 has q1, own, pace and gone; v2 has q1, own, pace and cost. The marks gained
    are q1 on v2's P6 and P7, the marks lost own on P4 and pace on P7.
    The gaps: v1 has one at P3 and one at P8 (GAP_AT_P8_NOTE), v2 one at P7. So the gap at P3 goes
    on at P7, and the one at P8 no longer applies. The quiet stretch of q1 from P1 to P8 (6
    paragraphs) ends in v2, and one of pace from P1 to P8 begins.
    """
    first = version_of(
        [para(1, 2, 3), para(4, 5, 6), para(7, 8, 9), para(10, 11, 12), para(13, 14, 15),
         para(16, 17, 18), para(19, 20, 21), para(22, 23, 24)],
        {"q1": [1, 8], "own": [2, 4, 5], "pace": [1, 2, 3], "gone": [8]},
        gaps=[([3], "The case in P3 is never tied to the thesis."), ([8], GAP_AT_P8_NOTE)],
        ui_language=ui_language)
    second = version_of(
        [para(1, 2, 3), para(4, 5), para(6), para(10, 11, 12), para(13, 14, 15, 16, 17, 18),
         para(19, 20, 21), para(7, 8, 9, 25), para(26, 27, 28)],
        {"q1": [1, 6, 7], "own": [2, 5], "pace": [1, 8], "cost": [8]},
        gaps=[([7], "The case in P7 is never tied to the thesis.")],
        ui_language=ui_language)
    return first, second


def two_builds(first: tuple[dict, dict], second: tuple[dict, dict],
               template_path: str = STUB_TEMPLATE_PATH, compare_with: int | None = None) -> dict:
    """Build ``first`` as v1 and then ``second`` as v2 in the same folder; return the second build.

    Each is a (source, analysis) pair. ``first`` is written with write_draft and built, then
    rewrite_draft puts ``second`` in its place, and ``second`` is built with ``compare_with`` as
    build takes it. The result is the second build's: its json_path is v2.json, and draft.json
    lies beside it.
    """
    draft = write_draft(*first)
    build(draft, template_path)
    rewrite_draft(draft, *second)
    return build(draft, template_path, compare_with)
