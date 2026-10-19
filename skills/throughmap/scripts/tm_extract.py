"""Readers that turn a draft into a flat list of blocks.

Each reader returns its blocks in document order. A block is a dict
``{"type": "title" | "heading" | "para" | "table", "text": str}``, and a heading also carries
``"level": int``. The Markdown reader also gives "front matter" and "notes" blocks, which are set
aside as they are. The text keeps its original characters (curly quotes, dashes, ellipses and
soft hyphens included). Only whitespace changes: every run of Unicode whitespace becomes one space
and the ends are stripped, except that a "front matter" or "notes" block keeps one line per line.
Blocks left with no text are dropped.

The checker matches every quote against this text, so each reader aims to return what a person
reading the draft sees.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass

from tm_text import FIGURE_LABEL, TABLE_LABEL

_BYTE_ORDER_MARK = "\N{ZERO WIDTH NO-BREAK SPACE}"
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _block(kind: str, text: str, level: int | None = None) -> dict:
    """Return a block; a heading passes its ``level``."""
    if level is None:
        return {"type": kind, "text": text}
    return {"type": kind, "level": level, "text": text}


def _collapse(text: str) -> str:
    """Turn each run of whitespace into one space and strip the ends."""
    return " ".join(text.split())


def _table_text(rows: list[list[str]]) -> str:
    """Join the cells of each row with " | " and the rows with a newline, skipping empty rows."""
    return "\n".join(" | ".join(cells).strip() for cells in rows if any(cells))


def _lines(text: str) -> list[str]:
    """Split ``text`` into lines, whatever the line endings, after a leading byte order mark."""
    return text.lstrip(_BYTE_ORDER_MARK).splitlines()


# A line of this many words or more is long: tm_source's front-line threshold. A long line that
# ends a sentence can be a paragraph of its own, and only a short line can be a heading.
_LONG_LINE_WORDS = 12
_SENTENCE_MARKS = (".", "?", "!", "\N{HORIZONTAL ELLIPSIS}", "\N{IDEOGRAPHIC FULL STOP}")
_CLOSING_MARKS = "".join(('"', "'", ")", "]", "\N{RIGHT DOUBLE QUOTATION MARK}",
                          "\N{RIGHT SINGLE QUOTATION MARK}", "\N{RIGHT CORNER BRACKET}",
                          "\N{RIGHT WHITE CORNER BRACKET}"))


def _is_long(line: str) -> bool:
    """True for a line of 12 words or more."""
    return len(line.split()) >= _LONG_LINE_WORDS


def _ends_a_sentence(line: str) -> bool:
    """True when ``line`` ends with . ? ! ... or the ideographic full stop, perhaps followed by
    closing quotes or brackets."""
    return line.rstrip().rstrip(_CLOSING_MARKS).endswith(_SENTENCE_MARKS)


def _reads_like_a_heading(line: str) -> bool:
    """True for a short line that does not end a sentence: what a heading line looks like."""
    return not _is_long(line) and not _ends_a_sentence(line)


# What a heading line of plain text does not end with: a line that does is cut off mid-phrase.
_CUT_OFF_ENDS = (",", ";", "-")


def _splits_line_by_line(rows: list[str]) -> bool:
    """True when the lines of a plain-text chunk are blocks of their own, one per line.

    At least two lines are long, every long line ends a sentence (see _ends_a_sentence), and no
    line after the first starts with a lowercase letter, as a wrapped continuation usually does.
    A wrapped paragraph's one long line is often its last, so one is never enough.
    """
    long_rows = [row for row in rows if _is_long(row)]
    return (len(long_rows) >= 2 and all(map(_ends_a_sentence, long_rows))
            and not any(row.lstrip()[:1].islower() for row in rows[1:]))


def _plain_heading_line(line: str) -> bool:
    """True for a short line of plain text that reads as a heading.

    It is not a caption ("Figure 1: Fees", left for the caption rule), it starts with a capital
    or with a letter of a script without Latin letters (Korean, say), and it ends with no
    sentence mark and no comma, semicolon or hyphen.
    """
    first = line[:1]
    return (_reads_like_a_heading(line)
            and not (FIGURE_LABEL.match(line) or TABLE_LABEL.match(line))
            and first.isalpha()
            and (first.isupper() or "LATIN" not in unicodedata.name(first, ""))
            and not line.rstrip().endswith(_CUT_OFF_ENDS))


# --- Word documents (.docx) --------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCUMENT_PART = "word/document.xml"
_STYLES_PART = "word/styles.xml"
_HEADING_NAME = re.compile(r"heading\s*(\d)")
# w:outlineLvl counts levels from 0, and 9 means body text.
_BODY_TEXT_OUTLINE = 9


def _tag(name: str) -> str:
    """Return the qualified name of the WordprocessingML element ``name``."""
    return _W + name


_BODY, _P, _PPR, _R, _T = (_tag(name) for name in ("body", "p", "pPr", "r", "t"))
_TBL, _TR, _TC = (_tag(name) for name in ("tbl", "tr", "tc"))
_VAL = _tag("val")
# Content controls and custom XML can wrap paragraphs and tables.
_BLOCK_WRAPPERS = frozenset(_tag(name) for name in ("sdt", "sdtContent", "customXml"))
_TABLE_PARTS = frozenset((_TBL, _TR, _TC))
# Inside a paragraph: properties hold no text, and deleted text (or the source of a tracked move)
# is not in the document the reader sees.
_NO_TEXT_IN_PARAGRAPH = frozenset(_tag(name) for name in ("pPr", "del", "moveFrom"))
_NOTE_REFERENCES = frozenset(_tag(name) for name in ("footnoteReference", "endnoteReference"))
# What the items directly inside a run (other than w:t) stand for. Everything else gives nothing.
_RUN_CHARACTERS = {
    _tag("tab"): " ", _tag("br"): " ", _tag("cr"): " ", _tag("noBreakHyphen"): "-",
}


@dataclass(frozen=True)
class _Style:
    name: str               # w:name, lower-cased
    based_on: str | None    # styleId of the style this one inherits from
    outline: int | None     # w:outlineLvl set on the style itself


def _child_val(parent: ET.Element | None, name: str) -> str | None:
    """Return the w:val of the child ``name`` of ``parent``, or None when there is none."""
    child = None if parent is None else parent.find(_tag(name))
    return None if child is None else child.get(_VAL)


def _outline_value(properties: ET.Element | None) -> int | None:
    """Return the w:outlineLvl value inside a w:pPr, or None when it has none."""
    try:
        return int(_child_val(properties, "outlineLvl"))
    except (TypeError, ValueError):
        return None


def _outline_level(value: int) -> int | None:
    """Return the heading level for a w:outlineLvl value (0 to 8 are levels 1 to 9), else None."""
    return value + 1 if 0 <= value < _BODY_TEXT_OUTLINE else None


def _read_styles(archive: zipfile.ZipFile) -> dict[str, _Style]:
    """Map each styleId in word/styles.xml to its name, parent style and outline level."""
    if _STYLES_PART not in archive.namelist():
        return {}
    styles = {}
    for element in ET.fromstring(archive.read(_STYLES_PART)).iter(_tag("style")):
        style_id = element.get(_tag("styleId"))
        if style_id is not None:
            styles[style_id] = _Style(
                name=(_child_val(element, "name") or "").lower(),
                based_on=_child_val(element, "basedOn"),
                outline=_outline_value(element.find(_PPR)),
            )
    return styles


def _style_chain(styles: dict[str, _Style], style_id: str | None) -> Iterator[_Style]:
    """Yield the style ``style_id``, then the style it is based on, and so on."""
    seen = set()
    while style_id in styles and style_id not in seen:
        seen.add(style_id)
        yield styles[style_id]
        style_id = styles[style_id].based_on


def _style_heading_level(styles: dict[str, _Style], style_id: str | None) -> int | None:
    """Return the heading level a paragraph style gives, or None.

    A style named like "heading 2" gives that level. So does a style with an outline level of its
    own, unless that level is body text. The nearest style in the based-on chain that says either
    wins.
    """
    for style in _style_chain(styles, style_id):
        named = _HEADING_NAME.match(style.name)
        if named:
            return int(named.group(1))
        if style.outline is not None:
            return _outline_level(style.outline)
    return None


def _run_text(run: ET.Element) -> str:
    """Return the text of one run: its w:t text, tabs and breaks as spaces, no-break hyphens as -.

    A run that holds a footnote or endnote reference gives no text. Only the run's own children
    count. A text box sits inside a drawing in the run, and its words belong to the paragraphs
    inside the box, so they never reach the paragraph that holds it.
    """
    if any(child.tag in _NOTE_REFERENCES for child in run):
        return ""
    return "".join(
        (child.text or "") if child.tag == _T else _RUN_CHARACTERS.get(child.tag, "")
        for child in run
    )


def _text_pieces(parent: ET.Element) -> Iterator[str]:
    """Yield the text of each run under ``parent``, however deep the wrappers around it nest.

    Hyperlinks, insertions, smart tags, content controls and fields are such wrappers. Deleted
    text and paragraph properties are skipped.
    """
    for child in parent:
        if child.tag == _R:
            yield _run_text(child)
        elif child.tag not in _NO_TEXT_IN_PARAGRAPH:
            yield from _text_pieces(child)


def _paragraph_text(paragraph: ET.Element) -> str:
    """Return the visible text of a w:p, whitespace collapsed."""
    return _collapse("".join(_text_pieces(paragraph)))


def _paragraph_block(paragraph: ET.Element, styles: dict[str, _Style]) -> dict | None:
    """Return the title, heading or para block for a w:p, or None when it has no text."""
    text = _paragraph_text(paragraph)
    if not text:
        return None
    properties = paragraph.find(_PPR)
    style_id = _child_val(properties, "pStyle")
    own_style = styles.get(style_id)
    if own_style is not None and own_style.name == "title":
        return _block("title", text)
    direct = _outline_value(properties)
    if direct is None:
        level = _style_heading_level(styles, style_id)
    else:
        level = _outline_level(direct)  # the paragraph's own setting overrides its style
    return _block("para", text) if level is None else _block("heading", text, level)


def _blocks_in(container: ET.Element) -> Iterator[ET.Element]:
    """Yield the paragraphs and tables in ``container``, looking inside content controls."""
    for child in container:
        if child.tag in (_P, _TBL):
            yield child
        elif child.tag in _BLOCK_WRAPPERS:
            yield from _blocks_in(child)


def _paragraphs_in(container: ET.Element) -> Iterator[ET.Element]:
    """Yield every paragraph in ``container``, looking inside nested tables and content controls.

    It never looks inside a paragraph: the paragraphs found there belong to text boxes.
    """
    for child in container:
        if child.tag == _P:
            yield child
        elif child.tag in _BLOCK_WRAPPERS or child.tag in _TABLE_PARTS:
            yield from _paragraphs_in(child)


def _cell_text(cell: ET.Element) -> str:
    """Return the text of a w:tc: its paragraphs, nested tables included, joined with spaces."""
    return _collapse(" ".join(_paragraph_text(paragraph) for paragraph in _paragraphs_in(cell)))


def _table_block(table: ET.Element) -> dict | None:
    """Return the table block for a w:tbl, or None when no cell has text."""
    rows = [[_cell_text(cell) for cell in row.findall(_TC)] for row in table.findall(_TR)]
    text = _table_text(rows)
    return _block("table", text) if text else None


# What a damaged or unusual package raises while it is read: not a zip, broken XML, a broken
# deflate stream (zlib.error) or one cut short (EOFError), a compression method zipfile does not
# know (NotImplementedError), and an encrypted part (RuntimeError).
_DAMAGED = (zipfile.BadZipFile, ET.ParseError, zlib.error, EOFError, NotImplementedError,
            RuntimeError)


def _unreadable(path: str, reason: object) -> ValueError:
    """Return the error read_docx raises for a file that is not a Word document."""
    return ValueError(f"{path} is not a readable .docx file ({reason})")


def read_docx(path: str) -> list[dict]:
    """Read a .docx file into blocks.

    The text is what Word shows with every tracked change accepted: inserted text is in, deleted
    text and moved-away text are out, and tabs and line breaks are spaces. Footnote and endnote
    marks are left out, and so is the text of text boxes. A paragraph is the title when its style
    is named "title". It is a heading of level N when its style is named like "heading N", or when
    it or its style sets an outline level. Style names come from word/styles.xml, so a style id
    such as "1" works. A table is one block: cells joined by " | " and rows by a newline.

    Raises ValueError when ``path`` is a file but not a readable Word document.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            if _DOCUMENT_PART not in archive.namelist():
                raise _unreadable(path, f"no {_DOCUMENT_PART}")
            document = ET.fromstring(archive.read(_DOCUMENT_PART))
            styles = _read_styles(archive)
    except _DAMAGED as error:
        raise _unreadable(path, error) from error
    body = document.find(_BODY)
    if body is None:
        raise _unreadable(path, "no document body")
    blocks = []
    for element in _blocks_in(body):
        block = _paragraph_block(element, styles) if element.tag == _P else _table_block(element)
        if block is not None:
            blocks.append(block)
    return blocks


# --- Markdown ----------------------------------------------------------------------------------

# A run of hashes closes the heading only when whitespace comes before it, so "C#" keeps its hash.
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
# A backtick fence cannot carry a backtick in its info string, so "```code```" is not a fence.
_FENCE = re.compile(r"^\s*(`{3,}(?=[^`]*$)|~{3,})")
# A horizontal rule: three or more of -, * or _ alone on a line, spaces allowed between them.
_THEMATIC_BREAK = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
# What can stand before the text of a line: the ">" marks of a quote, then one list marker. That is
# a bullet (-, * or +), or a number of at most nine digits (CommonMark's limit) and a . or ).
_QUOTE_MARKS = re.compile(r"\s*(?:>\s?)*\s*")
_BULLET_MARKER = re.compile(r"[-*+](?:\s+|$)")
_ORDERED_MARKER = re.compile(r"(\d{1,9})[.)](?:\s+|$)")
_BULLET, _ORDERED = "bullet", "ordered"  # the two kinds of list item a line can be
_TABLE_DELIMITER_CELL = re.compile(r"\s*:?-+:?\s*")
# A Setext underline: a run of = (level 1) or - (level 2) under a line of text, as in CommonMark.
_SETEXT_UNDERLINE = re.compile(r" {0,3}(=+|-+)[ \t]*$")
# YAML front matter: a first line "---", lines of YAML, then "---" or "...". A line of YAML is a
# "key: value" or "key:" line with an ASCII key, a "- item", an indented line or a "#" comment;
# prose is none of these. One key at least must be lowercase, as Jekyll and Hugo write them, so
# "Note: ..." or "To: ..." lines between two rules are not front matter, nor is a lone "# Title".
_FRONT_MATTER_OPENER, _FRONT_MATTER_CLOSERS = "---", ("---", "...")
_YAML_LINE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*:(?:\s|$)|-(?:\s|$)|\s|#")
_YAML_KEY = re.compile(r"[a-z_][a-z0-9_-]*:(?:\s|$)")
_YAML_TITLE = re.compile(r"title:\s*(.*?)\s*$", re.IGNORECASE)
# A footnote: its definition ("[^1]: text", at most 3 spaces in) and its mark in the text ("[^1]").
_FOOTNOTE_DEFINITION = re.compile(r" {0,3}\[\^[^\]\s]+\]:")
_FOOTNOTE_MARK = re.compile(r"\[\^[^\]\s]+\]")
_INDENTED = re.compile(r" {4}|\t")

_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_IMAGE = re.compile(r"!\[[^\]]*\]\((?:[^()]|\([^()]*\))*\)")
_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
_AUTOLINK = re.compile(r"<((?:https?|ftp|mailto):[^<>\s]+|[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>")
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>|<!--.*?-->")
# Emphasis marks must hug the text they wrap. An underscore inside a word (snake_case) is not one.
_EMPHASIS = (
    re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"),
    re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"),
    re.compile(r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)"),
    re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)"),
)
# Code spans wait under this character and an index while the other rules run, so what a code span
# holds (<b>, *args, [x](y)) is never taken for markup.
_HOLD = chr(0)
_HELD = re.compile(re.escape(_HOLD) + r"(\d+)" + re.escape(_HOLD))


def _strip_inline(text: str) -> str:
    """Reduce inline Markdown to its text and collapse the whitespace.

    Code spans become their content. Footnote marks ("[^1]"), images and HTML tags and comments
    are removed. A link becomes its text, an autolink its address, and **bold**, __bold__, *italic*
    and _italic_ lose their marks.
    """
    held: list[str] = []

    def hold(match: re.Match) -> str:
        held.append(match.group(2))
        return f"{_HOLD}{len(held) - 1}{_HOLD}"

    text = _CODE_SPAN.sub(hold, text.replace(_HOLD, ""))
    text = _FOOTNOTE_MARK.sub("", text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _AUTOLINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    for emphasis in _EMPHASIS:
        text = emphasis.sub(r"\1", text)
    return _collapse(_HELD.sub(lambda match: held[int(match.group(1))], text))


def _closes_fence(line: str, opener: str) -> bool:
    """True when ``line`` is a run of the opener's character at least as long as the opener."""
    stripped = line.strip()
    return len(stripped) >= len(opener) and stripped == opener[0] * len(stripped)


def _split_row(line: str) -> list[str]:
    """Split a pipe-table row into cells, ignoring one outer pipe at each end."""
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return row.split("|")


def _is_delimiter_row(line: str) -> bool:
    """True for a table delimiter row such as ``|---|:--:|``."""
    return "|" in line and all(_TABLE_DELIMITER_CELL.fullmatch(cell) for cell in _split_row(line))


def _pipe_table_at(lines: list[str], start: int) -> tuple[list[list[str]], int] | None:
    """Return the rows of the pipe table starting at ``lines[start]`` and the index after it.

    A table is a header row, a delimiter row with as many cells, and the rows below that hold a
    pipe. The delimiter row is not returned. Returns None when no table starts at ``start``.
    """
    if start + 1 >= len(lines) or "|" not in lines[start]:
        return None
    header = _split_row(lines[start])
    if not _is_delimiter_row(lines[start + 1]) or len(_split_row(lines[start + 1])) != len(header):
        return None
    rows = [header]
    end = start + 2
    while end < len(lines) and "|" in lines[end]:
        rows.append(_split_row(lines[end]))
        end += 1
    return rows, end


def _strip_line_markers(
    line: str, starts_block: bool, previous_marker: str | None
) -> tuple[str, str | None]:
    """Return ``line`` without its ">" marks and list marker, and the kind of marker it had.

    The kind is "bullet", "ordered" or None. A bullet marker goes wherever it stands. An ordered
    marker (1. or 1)) goes only on the first line of a paragraph, on a line numbered 1, or on a
    line right after another ordered item (``previous_marker`` is "ordered"). Anywhere else the
    number belongs to the text, as in "founded in" followed by "1998. It grew quickly.", and that
    includes the line after a bullet item.
    """
    rest = line[_QUOTE_MARKS.match(line).end():]
    bullet = _BULLET_MARKER.match(rest)
    if bullet:
        return rest[bullet.end():], _BULLET
    ordered = _ORDERED_MARKER.match(rest)
    if ordered and (starts_block or previous_marker == _ORDERED or int(ordered.group(1)) == 1):
        return rest[ordered.end():], _ORDERED
    return rest, None


def _yaml_text(value: str) -> str:
    """Return a YAML value as text: its quotes removed, or a plain value without its comment.

    A doubled quote inside single quotes and an escaped quote inside double quotes become one
    quote. A block value (one that opens with | or >) gives "".
    """
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace(chr(92) + '"', '"')
    if value[:1] in ("|", ">"):
        return ""
    return value.split(" #", 1)[0]


def _closing_rule(lines: list[str]) -> int | None:
    """Return the index of the "---" or "..." line that closes a first line "---", or None."""
    if not lines or lines[0].rstrip() != _FRONT_MATTER_OPENER:
        return None
    return next((n for n in range(1, len(lines)) if lines[n].rstrip() in _FRONT_MATTER_CLOSERS),
                None)


def _reads_as_yaml(lines: list[str]) -> bool:
    """True when one line with text has a lowercase "key:" and every one is a line of YAML (see
    _YAML_LINE). With a key line, a "#" line is a YAML comment, even "# Title"; without one, the
    block is prose and its "#" line a heading."""
    filled = [line for line in lines if line.strip()]
    return any(_YAML_KEY.match(line) for line in filled) and all(map(_YAML_LINE.match, filled))


def _front_matter(lines: list[str]) -> tuple[str, str, int] | None:
    """Return the title and the text of the YAML front matter that opens ``lines``, and the index
    after it.

    Front matter is a first line "---", lines of YAML (see _reads_as_yaml) and a line "---" or
    "...". The title is the value of its top-level title key, or "" when it has none; the text is
    its lines with text, without the two fences. Returns None when ``lines`` does not open with
    front matter: a "---" with no closer, or with prose under it, is a horizontal rule.
    """
    end = _closing_rule(lines)
    if end is None or not _reads_as_yaml(lines[1:end]):
        return None
    block = [line.rstrip() for line in lines[1:end] if line.strip()]
    titles = (_YAML_TITLE.match(line) for line in block)
    title = next((_collapse(_yaml_text(found.group(1))) for found in titles if found), "")
    return title, "\n".join(block), end + 1


def _starts_a_block(line: str) -> bool:
    """True for a line that cannot carry on a paragraph: a heading, a fence, a rule or a footnote."""
    return bool(_ATX_HEADING.match(line.lstrip()) or _FENCE.match(line)
                or _THEMATIC_BREAK.match(line) or _FOOTNOTE_DEFINITION.match(line))


def _footnote_end(lines: list[str], start: int) -> int:
    """Return the index after the footnote whose definition line comes just before ``start``.

    The note goes on over the lines right after it, up to a blank line or a line that starts a
    block of its own, and over any indented lines after that, blank lines between them included.
    """
    end = start
    lazy = True   # no blank line has come since the note's last line
    for position in range(start, len(lines)):
        line = lines[position]
        if not line.strip():
            lazy = False
        elif _INDENTED.match(line) or (lazy and not _starts_a_block(line)):
            lazy, end = True, position + 1
        else:
            break
    return end


def _quoted(line: str) -> bool:
    """True when ``line`` opens with the ">" mark of a quote."""
    return ">" in line[:_QUOTE_MARKS.match(line).end()]


def read_markdown(text: str) -> list[dict]:
    """Read Markdown into blocks.

    ATX headings (``# Title``), Setext headings, pipe tables and paragraphs become blocks. A
    paragraph is the lines up to a blank line, joined with spaces. Setext headings follow
    CommonMark for ``=``: a run of ``=`` under a paragraph of plain text (no ``>`` mark, no list
    marker) makes the whole paragraph a level-1 heading, since ``===`` means nothing else. A run
    of ``-`` makes a level-2 heading only of one plain line that reads like a heading (short, with
    no sentence mark at its end; see _reads_like_a_heading); under any other paragraph, and under
    a blank line, it is a horizontal rule, so a long paragraph over ``---`` stays a paragraph.
    Under a list item or a quote, a run of either is a rule. YAML front
    matter becomes a "front matter" block and its title a title block (see _front_matter); a
    first heading that repeats that title is then left out. When a first line "---" and its
    closer hold no front matter, both are rules, and the closer underlines nothing. Each footnote
    definition, with the lines that carry it on (see _footnote_end), becomes a "notes" block, and
    the marks are removed from the text. ``>`` marks and list markers are dropped (see
    _strip_line_markers), fenced code and horizontal rules are skipped, and inline markup is
    reduced to its text.
    """
    lines = _lines(text)
    blocks: list[dict] = []
    paragraph: list[str] = []
    plain_first_line = False   # the paragraph's first line has no quote mark and no list marker

    def end_paragraph() -> None:
        stripped = _strip_inline(" ".join(paragraph))
        paragraph.clear()
        if stripped:
            blocks.append(_block("para", stripped))

    front = _front_matter(lines)
    position = 0
    rule_at = None   # the closing "---" of a block that is not front matter: a rule, no underline
    if front is not None:
        front_title, front_text, position = front
        blocks.append(_block("front matter", front_text))
        if front_title:
            blocks.append(_block("title", front_title))
    else:
        rule_at = _closing_rule(lines)
    fence = ""
    previous_marker = None
    while position < len(lines):
        line = lines[position]
        position += 1
        if fence:
            if _closes_fence(line, fence):
                fence = ""
            continue
        opening = _FENCE.match(line)
        if opening:
            end_paragraph()
            fence = opening.group(1)
            continue
        if position - 1 == rule_at:
            end_paragraph()
            continue
        if _FOOTNOTE_DEFINITION.match(line):
            end_paragraph()
            start, position = position - 1, _footnote_end(lines, position)
            note = "\n".join(row.strip() for row in lines[start:position] if row.strip())
            blocks.append(_block("notes", note))
            continue
        heading = _ATX_HEADING.match(line.lstrip())
        if heading:
            end_paragraph()
            title = _strip_inline(heading.group(2))
            if title:
                blocks.append(_block("heading", title, len(heading.group(1))))
            continue
        underline = _SETEXT_UNDERLINE.match(line)
        if underline and paragraph:
            title = _strip_inline(" ".join(paragraph))
            equals = underline.group(1)[0] == "="
            if plain_first_line and (equals or len(paragraph) == 1
                                     and _reads_like_a_heading(title)):
                paragraph.clear()
                if title:
                    blocks.append(_block("heading", title, 1 if equals else 2))
            else:
                end_paragraph()   # under any other text, the run is a rule
            continue
        if _THEMATIC_BREAK.match(line):
            end_paragraph()
            continue
        table = _pipe_table_at(lines, position - 1)
        if table:
            end_paragraph()
            rows, position = table
            table_text = _table_text([[_strip_inline(cell) for cell in row] for row in rows])
            if table_text:
                blocks.append(_block("table", table_text))
            continue
        content, marker = _strip_line_markers(line, not paragraph, previous_marker)
        if content.strip():
            if not paragraph:
                plain_first_line = marker is None and not _quoted(line)
            paragraph.append(content)
            previous_marker = marker
        else:
            end_paragraph()
    end_paragraph()
    # The post's own "# Title" under front matter that names the same title: the title, once.
    # The blocks then open with the front matter, its title and that heading.
    if (front is not None and front[0] and len(blocks) > 2 and blocks[2]["type"] == "heading"
            and blocks[2]["text"].casefold() == front[0].casefold()):
        del blocks[2]
    return blocks


# --- Plain text --------------------------------------------------------------------------------


def read_plain(text: str) -> list[dict]:
    """Read plain text into paragraph and heading blocks.

    One or more blank lines (empty, or only whitespace) end a paragraph, and the lines between them
    are joined with spaces. A text with no blank line between its lines has one paragraph per
    line instead: Word's "Save as Plain Text", Notepad and TextEdit write a draft that way. Blank
    lines before the first line of text or after the last do not count.

    A chunk (the lines between two blank lines, or the whole of a text without one) is one block
    per line, its short lines able to be headings, only when it clearly is one paragraph per line
    (see _splits_line_by_line), as in such an export with a blank line after its title or with
    heading lines. Otherwise a chunk between blank lines stays one paragraph, since hard-wrapped
    prose tears otherwise, and a text without blank lines keeps one plain paragraph per line.

    In a chunk that splits, a short line between two long lines of the draft is a level-1 heading
    when it reads as one (see _plain_heading_line); a caption or any other short line is a
    paragraph. Short lines before the first long line or after the last are paragraphs, for the
    front-line and closing-line rules of tm_source.
    """
    lines = _lines(text)
    filled = [n for n, line in enumerate(lines) if line.strip()]
    inner = lines[filled[0]:filled[-1] + 1] if filled else []
    pieces: list[tuple[str, bool]] = []   # (text, from a chunk that splits line by line)
    if not any(not line.strip() for line in inner):
        split = _splits_line_by_line(inner)
        pieces = [(line, split) for line in inner]
    else:
        for chunk in _PARAGRAPH_BREAK.split("\n".join(inner)):
            rows = [row for row in chunk.split("\n") if row.strip()]
            if len(rows) > 1 and _splits_line_by_line(rows):
                pieces.extend((row, True) for row in rows)
            else:
                pieces.append((chunk, False))
    texts = [(clean, split) for clean, split in
             ((_collapse(piece), split) for piece, split in pieces) if clean]
    long_at = [n for n, (clean, _) in enumerate(texts) if _is_long(clean)]
    return [_block("heading", clean, 1)
            if split and long_at and long_at[0] < n < long_at[-1] and _plain_heading_line(clean)
            else _block("para", clean)
            for n, (clean, split) in enumerate(texts)]
