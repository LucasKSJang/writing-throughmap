"""The source document (source.json): numbered paragraphs, tables, figures and sections.

assemble_source numbers the blocks that the readers in tm_extract return, and lists what it set
aside. apply_corrections (join, split, drop) and select_section then work on that document, and
extract_path and resolve_out_dir tie it to files and folders.

The checker matches every quote against the text of a paragraph, so nothing here changes it.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass

from tm_extract import read_docx, read_markdown, read_plain
from tm_text import FIGURE_LABEL, TABLE_LABEL, slugify, word_count

# --- Assembling the source document ------------------------------------------------------------

SOURCE_SCHEMA = "throughmap-source/1"

# A heading or one-line paragraph with one of these texts (any case, a trailing colon allowed)
# opens the references; it and what follows it are set aside up to the next heading that ends
# them, or to the end of the draft (see _references_runs).
_REFERENCES_TITLES = frozenset((
    "references", "bibliography", "works cited", "sources", "notes", "참고문헌", "참고 문헌", "참고자료",
))
_REFERENCES_MAX_WORDS = 4
_REFERENCES_MAX_CHARS = 500
# The first paragraph of this many words ends the front lines and starts the body, and the last
# one starts the closing.
_BODY_WORDS = 12
_CLOSING_MAX_WORDS = 4
_BYLINE_STARTS = ("By ", "by ", "글:", "작성")
_CAPTION_MAX_WORDS = 30
_TITLE_LIKE_MAX_WORDS = 15
# The labels that open a caption (see tm_text), which the plain-text reader also knows.
_FIGURE_LABEL, _TABLE_LABEL = FIGURE_LABEL, TABLE_LABEL
# What may follow the number of a label: "Figure 3: Fees", "Table 2. Costs", "Fig. 4 - Margins".
_CAPTION_MARKS = ":.)-\N{EN DASH}\N{EM DASH}"
_SENTENCE_ENDINGS = (".", "?", "!")
# The roles of blocks that are listed in ``excluded``, each under its own name as the kind.
_SET_ASIDE_ROLES = frozenset(("byline", "front", "closing", "subheading", "front matter", "notes"))
# The kinds of reader block that are set aside as they come, under their own name: Markdown's YAML
# front matter and its footnote definitions.
_READ_AS_SET_ASIDE = frozenset(("front matter", "notes"))


class Source(dict):
    """The source document, a dict that also remembers where its title came from.

    ``title_from_block`` is True when the title is the text of a block of the draft (a title or a
    heading) and False when it is the hint. It is not part of the JSON.
    """

    title_from_block = False


@dataclass
class _Item:
    """A block on its way through assembly.

    Each rule of assemble_source claims blocks by giving them a ``role``; the role stays empty
    while a block is body text.
    """

    kind: str
    text: str
    level: int = 0
    role: str = ""
    caption_of: int | None = None  # for a table caption: the position of the table it names


def _opens_references(item: _Item) -> bool:
    """True for a heading or paragraph that reads "References", "Notes:" and the like."""
    if item.role or item.kind not in ("heading", "para"):
        return False
    return (word_count(item.text) <= _REFERENCES_MAX_WORDS
            and item.text.lower().rstrip(":") in _REFERENCES_TITLES)


def _reads_like_caption(text: str, label: re.Match) -> bool:
    """Say whether a paragraph that opens with a label is a caption and not a sentence.

    It is a caption when the number of the label is followed, after any spaces, by a colon, full
    stop, closing bracket, hyphen, en dash or em dash, or by the end of the text ("Figure 3: Fees",
    "Table 2"). It is also a caption when it is a title-like line: at most 15 words that do not end
    in . ? or ! ("Figure 3 Fees by chain"). Anything else, such as "Figure 1 shows that rents
    rise.", is body text.
    """
    following = text[label.end():].lstrip()
    if not following or following[0] in _CAPTION_MARKS:
        return True
    return (word_count(text) <= _TITLE_LIKE_MAX_WORDS
            and not text.rstrip().endswith(_SENTENCE_ENDINGS))


def _caption_role(item: _Item) -> str:
    """Return "figure" or "table-caption" for a paragraph of at most 30 words that reads like a
    caption ("Figure 3: Fees", "Fig. 3", "그림 3", "Table 3 Owners", "표 3."), and "" for every
    other block, a sentence that merely opens with a label ("Figure 1 shows ...") included.
    """
    if item.kind != "para" or word_count(item.text) > _CAPTION_MAX_WORDS:
        return ""
    for role, label in (("figure", _FIGURE_LABEL), ("table-caption", _TABLE_LABEL)):
        match = label.match(item.text)
        if match:
            return role if _reads_like_caption(item.text, match) else ""
    return ""


def _plain_paragraphs(items: list[_Item]) -> list[int]:
    """Return the positions of the paragraphs that are still body text, captions left out."""
    return [n for n, item in enumerate(items)
            if item.kind == "para" and not item.role and not _caption_role(item)]


def _long_paragraphs(items: list[_Item]) -> list[int]:
    """Return the positions of the plain paragraphs that are long: 12 words or more."""
    return [n for n in _plain_paragraphs(items) if word_count(items[n].text) >= _BODY_WORDS]


def _body_start(items: list[_Item]) -> int | None:
    """Return the position where the body starts, or None when the draft has no paragraph.

    The body starts at the first long paragraph; the lines before it are front lines (see
    _claim_front_and_closing). Without a long paragraph nothing is a front line, and the body
    starts at the first paragraph.
    """
    return next(iter(_long_paragraphs(items) or _plain_paragraphs(items)), None)


def _references_runs(items: list[_Item]) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` positions of each run of references, in document order.

    A run opens at a heading or paragraph reading "References" and the like once the body has
    started (see _body_start); above the body such a line is a title or a front line. A heading
    opens a run that ends at the next heading of its level or a higher one (a smaller or equal
    level number). A paragraph line has no level, so its run ends at the next heading of the
    draft's section level or higher: the shallowest level of the body headings between the start
    of the body and the line, or any heading when there are none. A run with no such heading
    after it goes to the end of the draft. Whatever follows a run is body again, so the body is
    never lost.
    """
    runs: list[tuple[int, int]] = []
    body = _body_start(items) or 0
    n = body
    while n < len(items):
        if not _opens_references(items[n]):
            n += 1
            continue
        if items[n].kind == "heading":
            limit = items[n].level
        else:
            set_aside = {m for start, end in runs for m in range(start, end)}
            levels = [items[m].level for m in range(body, n)
                      if items[m].kind == "heading" and m not in set_aside]
            limit = min(levels) if levels else None   # None: any heading ends the run
        end = next((m for m in range(n + 1, len(items)) if items[m].kind == "heading"
                    and (limit is None or items[m].level <= limit)), len(items))
        runs.append((n, end))
        n = end
    return runs


def _in_references(items: list[_Item]) -> set[int]:
    """Return the positions of the blocks inside the runs of references (see _references_runs)."""
    return {n for start, end in _references_runs(items) for n in range(start, end)}


def _nothing_under(items: list[_Item], headings: list[int], n: int, body: int | None) -> bool:
    """True when no body paragraph stands under the heading at position ``n``.

    That is when the next of ``headings`` at its level or a higher one comes before the body
    starts (see _body_start). Without such a heading, the rest of the draft is under it.
    """
    following = next((m for m in headings if m > n and items[m].level <= items[n].level), None)
    return following is not None and (body is None or following < body)


def _top_heading(items: list[_Item], headings: list[int], body: int | None) -> int | None:
    """Return the position of the level-1 heading that heads deeper ones, or None.

    It is the first level-1 heading of ``headings`` above the body (see _body_start), when deeper
    headings exist and it is either the only level-1 heading or has nothing under it (see
    _nothing_under), as "# Title" is over "##" sections.
    """
    if not any(items[n].level > 1 for n in headings):
        return None
    level_one = [n for n in headings if items[n].level == 1]
    top = next((n for n in level_one if body is None or n < body), None)
    if top is not None and (len(level_one) == 1 or _nothing_under(items, headings, top, body)):
        return top
    return None


def _claim_title(items: list[_Item]) -> _Item | None:
    """Mark the title block and return it, or return None when there is none.

    The title is the first title block. Without one, only the headings outside the references
    count, since those in them are set aside (see _references_runs). The title is then:

    - the first level-1 heading, when deeper headings exist and it is either the only level-1
      heading or has nothing under it (see _nothing_under), as in "# Title" over "##" sections;
    - else the only heading, of any level, as in a memo whose one heading is its "# title";
    - else the first heading when it has nothing under it, as in "# My Essay" over
      "# Introduction" and "# Body".

    Either way no body paragraph may come before it (see _body_start); front lines, such as a
    byline or a "To:" line, may. A level-1 heading with body under it and other level-1 headings
    after it is a section, as "# Introduction" is over "# Analysis" and "## Data". Any other
    title block becomes a paragraph.

    Under Markdown front matter that gives the title, a first heading that the first rule would
    have taken for the title is a title line instead, such as "# Free Rails: A Note on Fees" over
    "##" sections: it is set aside as "front", so the deeper headings mark the sections.
    """
    title = next((item for item in items if item.kind == "title"), None)
    in_references = _in_references(items)
    headings = [n for n, item in enumerate(items)
                if item.kind == "heading" and n not in in_references]
    body = _body_start(items)
    top = _top_heading(items, headings, body)
    if title is not None:
        if top is not None and top == headings[0] and any(
                item.kind == "front matter" for item in items):
            items[top].role = "front"   # the post's own title line under its front matter
    else:
        above_body = [n for n in headings if body is None or n < body]
        if top is not None:
            title = items[top]
        if title is None and len(headings) == 1 and above_body:
            title = items[headings[0]]   # as a section, a memo's lone "# title" would hold all
        if title is None and headings and _nothing_under(items, headings, headings[0], body):
            title = items[headings[0]]   # as a section it would hold nothing and be dropped
    for item in items:
        if item.kind == "title" and item is not title:
            item.kind = "para"
    if title is not None:
        title.role = "title"
    return title


def _claim_references(items: list[_Item]) -> None:
    """Set aside each run of references (see _references_runs): its opener and what follows it."""
    for n in sorted(_in_references(items)):
        items[n].role = items[n].role or "references"


def _claim_front_and_closing(items: list[_Item]) -> None:
    """Set aside the paragraphs before the first long one and the short ones after the last.

    A paragraph is long at 12 words. Of the lines before the first long paragraph, the first that
    starts like a byline is the byline and the others are front lines. After the last long
    paragraph, a line of one to four words is a closing line. Without a long paragraph nothing is
    set aside. A caption is none of these, wherever it stands: it is left to _claim_captions and
    does not count as a long paragraph.
    """
    paragraphs = _plain_paragraphs(items)
    long_ones = _long_paragraphs(items)
    if not long_ones:
        return
    byline_found = False
    for n in paragraphs:
        item = items[n]
        if n < long_ones[0]:
            is_byline = not byline_found and item.text.startswith(_BYLINE_STARTS)
            byline_found = byline_found or is_byline
            item.role = "byline" if is_byline else "front"
        elif n > long_ones[-1] and word_count(item.text) <= _CLOSING_MAX_WORDS:
            item.role = "closing"


def _claim_captions(items: list[_Item]) -> None:
    """Mark the figure captions and the table captions (see _caption_role).

    A table caption goes to the table block right after it, else to the one right before it, unless
    that table has a caption already. Only blocks still in the body count as neighbours, so text
    already set aside is skipped over, while a heading between a caption and a table separates them.
    """
    flow = [n for n, item in enumerate(items) if not item.role]
    captioned = set()
    for k, n in enumerate(flow):
        item = items[n]
        item.role = _caption_role(item)
        if item.role == "table-caption":
            for beside in flow[k + 1:k + 2] + flow[max(k - 1, 0):k]:
                if items[beside].kind == "table" and beside not in captioned:
                    item.caption_of = beside
                    captioned.add(beside)
                    break


def _claim_headings(items: list[_Item]) -> None:
    """The shallowest heading level marks the sections; deeper headings are set aside."""
    headings = [item for item in items if item.kind == "heading" and not item.role]
    if headings:
        top = min(item.level for item in headings)
        for item in headings:
            item.role = "section" if item.level == top else "subheading"


def _refresh_counts(source: dict) -> None:
    """Set the essay's word and paragraph counts from the paragraphs the source holds."""
    source["essay"]["word_count"] = sum(word_count(p["text"]) for p in source["paragraphs"])
    source["essay"]["paragraph_count"] = len(source["paragraphs"])


def _build(items: list[_Item], title: str, source_name: str, source_kind: str) -> Source:
    """Number the body text and list what was set aside, in document order.

    Each table and figure is filed ``after`` the last paragraph before it. A draft with no section
    heading has no sections. Otherwise the text before the first heading is a section titled "",
    and a section that ends up with no paragraph is dropped, its heading listed in ``excluded`` as
    a "heading", so that no text leaves the map unlisted. Each stretch of references, one run or
    several back to back, is one entry, cut to 500 characters.
    """
    captions = {item.caption_of: item.text for item in items if item.caption_of is not None}
    references: dict[int, list[str]] = {}   # the first position of each stretch -> its texts
    stretch = None
    for n, item in enumerate(items):
        if item.role != "references":
            stretch = None
        else:
            stretch = n if stretch is None else stretch
            references.setdefault(stretch, []).append(item.text)
    paragraphs, tables, figures, excluded = [], [], [], []
    sections = [{"title": "", "first": None, "last": None}]
    headings = []   # (section, its "heading" entry in excluded) for each section heading
    after = None  # the id of the last paragraph so far
    for n, item in enumerate(items):
        if item.role == "section":
            sections.append({"title": item.text, "first": None, "last": None})
            headings.append((sections[-1], {"kind": "heading", "text": item.text}))
            excluded.append(headings[-1][1])   # taken out below once the section holds text
        elif item.role == "references":
            if n in references:
                text = "\n".join(references[n])
                excluded.append({"kind": "references", "text": text[:_REFERENCES_MAX_CHARS]})
        elif item.role in _SET_ASIDE_ROLES:
            excluded.append({"kind": item.role, "text": item.text})
        elif item.role == "figure":
            figures.append({"id": f"F{len(figures) + 1}", "caption": item.text, "after": after})
        elif item.role == "table-caption":
            if item.caption_of is None:  # no table beside it: the caption stands alone
                tables.append({"id": f"T{len(tables) + 1}", "caption": item.text,
                               "after": after, "text": ""})
        elif item.kind == "table" and not item.role:
            tables.append({"id": f"T{len(tables) + 1}", "caption": captions.get(n, ""),
                           "after": after, "text": item.text})
        elif item.kind == "para" and not item.role:
            after = f"P{len(paragraphs) + 1}"
            paragraphs.append({"id": after, "text": item.text})
            sections[-1]["first"] = sections[-1]["first"] or after
            sections[-1]["last"] = after
    has_headings = any(item.role == "section" for item in items)
    mapped = {id(entry) for section, entry in headings if section["first"]}
    excluded = [entry for entry in excluded if id(entry) not in mapped]
    source = Source({
        "schema": SOURCE_SCHEMA,
        "essay": {"title": title, "source": source_name, "source_kind": source_kind,
                  "word_count": 0, "paragraph_count": 0},
        "paragraphs": paragraphs,
        "tables": tables,
        "figures": figures,
        "sections": [s for s in sections if s["first"]] if has_headings else [],
        "excluded": excluded,
    })
    _refresh_counts(source)
    return source


def assemble_source(blocks: list[dict], *, title_hint: str, source_name: str,
                    source_kind: str, keep_short: bool = False) -> Source:
    """Assemble the source document from reader blocks.

    The rules run in this order, each on what the ones before it left:

    1. Title: the first title block; else, of the headings outside the references (rule 2), the
       first level-1 heading while deeper headings exist, when it is the only level-1 heading or
       has nothing under it, or else the only one, or else the first one when no body paragraph
       stands under it before the next heading of its level or a higher one (see _claim_title),
       provided no body paragraph comes before it (see _body_start); else ``title_hint``. A
       block that is the title is removed.
    2. References: a heading or paragraph reading "References", "Bibliography" and the like once
       the body has started (see _body_start) opens a run of references that ends at the next
       heading of its level or higher, or for a paragraph line at the draft's section level or
       higher (see _references_runs). Each stretch of them becomes one ``excluded`` entry of
       kind "references", and what follows is body again. Above the body, such a line is left
       to rules 1 and 3.
    3. Front lines and closing lines (see _claim_front_and_closing): kinds "byline", "front"
       and "closing". Captions are left for rule 4. ``keep_short`` skips this rule, so a short
       opening or closing paragraph stays a paragraph (a byline too, for the user to drop).
    4. Captions (see _claim_captions): a figure caption makes a figure, a table caption goes to
       its table or makes a table with no text. A paragraph is a caption only when it reads like
       one (see _caption_role): "Figure 1 shows that rents rise." is a paragraph.
    5. Sections: the shallowest heading level marks them, deeper headings are set aside as
       "subheading", and text before the first heading is a section titled "". A section left
       with no paragraph goes, and its heading is listed as "heading", so that no text leaves
       the map unlisted. A draft with no heading left at this point has no sections at all.
    6. Numbering: P1 and on for paragraphs, T1 for tables, F1 for figures. ``after`` is the id of
       the last paragraph before the table or figure, or None when no paragraph comes before it.

    Before them, the "front matter" and "notes" blocks of a Markdown draft are set aside under
    those kinds, so that nothing leaves the map without a trace.

    ``excluded`` lists everything set aside, in document order. The text of a paragraph is never
    changed. The result is a Source, whose ``title_from_block`` says if rule 1 found a block.
    """
    items = [_Item(block["type"], block["text"], block.get("level", 0)) for block in blocks]
    for item in items:
        if item.kind in _READ_AS_SET_ASIDE:
            item.role = item.kind
    title_item = _claim_title(items)
    _claim_references(items)
    if not keep_short:
        _claim_front_and_closing(items)
    _claim_captions(items)
    _claim_headings(items)
    source = _build(items, title_item.text if title_item else title_hint, source_name, source_kind)
    source.title_from_block = title_item is not None
    return source


# --- Corrections and the choice of a section ---------------------------------------------------


class CorrectionError(ValueError):
    """A correction, or a choice of section, that does not fit the draft."""


def _section_numbers(source: dict, position: dict[str, int]) -> list[int | None]:
    """Return, for each paragraph, the position in ``source["sections"]`` of its section."""
    numbers: list[int | None] = [None] * len(source["paragraphs"])
    for number, section in enumerate(source["sections"]):
        for n in range(position[section["first"]], position[section["last"]] + 1):
            numbers[n] = number
    return numbers


def _cut(text: str, offsets: list[int]) -> list[str]:
    """Cut ``text`` at the sorted ``offsets`` and strip each piece; without offsets it is whole."""
    if not offsets:
        return [text]
    bounds = [0, *offsets, len(text)]
    return [text[start:end].strip() for start, end in zip(bounds, bounds[1:])]


def _plan_corrections(source: dict, position: dict[str, int], section_of: list[int | None],
                      joins, splits, drops) -> tuple[set[int], dict[int, set[int]], set[int]]:
    """Check the corrections against ``source`` and return what they ask for, by position.

    The result is ``(dropped, cuts, continued)``: the paragraphs to drop, the offsets at which each
    paragraph is cut, and the paragraphs that carry on the one before them. Raises CorrectionError
    for a correction that does not fit.
    """
    paragraphs = source["paragraphs"]

    def locate(paragraph_id: str) -> int:
        if paragraph_id not in position:
            raise CorrectionError(f"there is no paragraph {paragraph_id}")
        return position[paragraph_id]

    dropped = {locate(paragraph_id) for paragraph_id in drops}
    cuts: dict[int, set[int]] = {}
    for paragraph_id, text in splits:
        n = locate(paragraph_id)
        at = paragraphs[n]["text"].find(text)
        if at < 0:
            raise CorrectionError(f"cannot split {paragraph_id}: {text!r} not found in it")
        if at == 0:
            raise CorrectionError(
                f"cannot split {paragraph_id} at {text!r}: that is where the paragraph starts")
        cuts.setdefault(n, set()).add(at)
    continued: set[int] = set()
    touched = set(cuts)
    for first, second in joins:
        a, b = locate(first), locate(second)
        if b != a + 1:
            raise CorrectionError(f"cannot join {first} and {second}: they are not adjacent")
        if section_of[a] != section_of[b]:
            raise CorrectionError(
                f"cannot join {first} and {second}: they are in different sections")
        continued.add(b)
        touched.update((a, b))
    clash = sorted(dropped & touched)
    if clash:
        raise CorrectionError(
            f"{paragraphs[clash[0]]['id']} cannot be dropped and also joined or split")
    return dropped, cuts, continued


def _rebuilt_sections(sections: list[dict], origins: list[int | None]) -> list[dict]:
    """Return the sections that still hold paragraphs, with their new first and last ids.

    ``origins`` gives, for each new paragraph in order, the position of its old section.
    """
    spans: list[list[int]] = []  # [position of the old section, first and last new paragraph]
    for n, number in enumerate(origins):
        if number is None:
            continue
        if spans and spans[-1][0] == number:
            spans[-1][2] = n
        else:
            spans.append([number, n, n])
    return [dict(sections[number], first=f"P{first + 1}", last=f"P{last + 1}")
            for number, first, last in spans]


def apply_corrections(source: dict, *, joins=(), splits=(), drops=()) -> dict:
    """Return a copy of ``source`` with the corrections applied; ``source`` itself is untouched.

    Every id refers to ``source`` as it stands now.

    - ``joins`` are (first, second) pairs: adjacent paragraphs of one section, joined with one
      space. A chain such as (P2, P3) and (P3, P4) makes one paragraph.
    - ``splits`` are (id, text) pairs: the paragraph is cut where the text first occurs, by a raw
      search and never at the very start. Each piece is stripped. A paragraph may be cut at
      several places, and a join to a paragraph that is cut joins the pieces beside it.
    - ``drops`` are ids of paragraphs to set aside as "dropped". A dropped paragraph cannot also
      be joined or split.

    The paragraphs are then renumbered, and the sections, the counts and the ``after`` of every
    table and figure follow. A table or figure that came after a dropped paragraph now comes after
    the nearest paragraph before it. Raises CorrectionError when a correction does not fit.
    """
    paragraphs = source["paragraphs"]
    position = {paragraph["id"]: n for n, paragraph in enumerate(paragraphs)}
    section_of = _section_numbers(source, position)
    dropped, cuts, continued = _plan_corrections(source, position, section_of, joins, splits, drops)

    texts: list[str] = []
    origins: list[int | None] = []  # the old section of each new paragraph
    newest: list[int | None] = []   # for each old paragraph, the last new paragraph up to it
    removed = []
    for n, paragraph in enumerate(paragraphs):
        if n in dropped:
            removed.append({"kind": "dropped", "text": paragraph["text"]})
        else:
            pieces = _cut(paragraph["text"], sorted(cuts.get(n, ())))
            if n in continued:
                texts[-1] = f"{texts[-1].strip()} {pieces.pop(0).strip()}"
            texts.extend(pieces)
            origins.extend([section_of[n]] * len(pieces))
        newest.append(len(texts) - 1 if texts else None)

    result = copy.deepcopy(source)
    result["paragraphs"] = [{"id": f"P{n}", "text": text} for n, text in enumerate(texts, 1)]
    for item in (*result["tables"], *result["figures"]):
        if item["after"] is not None:
            latest = newest[position[item["after"]]]
            item["after"] = None if latest is None else f"P{latest + 1}"
    result["sections"] = _rebuilt_sections(source["sections"], origins)
    result["excluded"].extend(removed)
    _refresh_counts(result)
    return result


def _choose_section(sections: list[dict], which: str) -> int:
    """Return the position of the section ``which`` names: its number as listed, else its title."""
    if not sections:
        raise CorrectionError(
            "the draft has no section headings, so there is no section to choose")
    number = int(which) if which.isdecimal() and len(which) <= 9 else 0
    if 1 <= number <= len(sections):
        return number - 1
    matches = [n for n, section in enumerate(sections) if section["title"] == which]
    if len(matches) == 1:
        return matches[0]
    if matches:
        numbers = ", ".join(str(n + 1) for n in matches)
        raise CorrectionError(
            f"several sections are titled {which!r}: choose one by its number ({numbers})")
    raise CorrectionError(
        f"no section {which!r}: choose a number from 1 to {len(sections)} or a section title")


def select_section(source: dict, which: str) -> dict:
    """Return a copy of ``source`` that holds one section only.

    ``which`` is a section number as listed (1 is the first) or an exact title. A number wins over
    a title, and a title that is no section number is found by title. The paragraphs keep their
    ids, ``essay.selected_section`` is the section's title, and the counts describe the section.
    A table or figure stays when the paragraph it follows is in the section; one that follows no
    paragraph stays with the first section. Raises CorrectionError when ``which`` names no section
    or several, and when the draft has no sections (it has no section headings).
    """
    chosen = _choose_section(source["sections"], which)
    result = copy.deepcopy(source)
    section = result["sections"][chosen]
    ids = [paragraph["id"] for paragraph in result["paragraphs"]]
    first, last = ids.index(section["first"]), ids.index(section["last"])
    result["paragraphs"] = result["paragraphs"][first:last + 1]
    inside = {paragraph["id"] for paragraph in result["paragraphs"]}
    for key in ("tables", "figures"):
        result[key] = [item for item in result[key]
                       if item["after"] in inside or (item["after"] is None and chosen == 0)]
    result["sections"] = [section]
    result["essay"]["selected_section"] = section["title"]
    _refresh_counts(result)
    return result


# --- Files and folders -------------------------------------------------------------------------

_KIND_BY_SUFFIX = {".docx": "docx", ".md": "md", ".markdown": "md", ".txt": "txt"}
_OUTPUT_SUFFIX = ".throughmap"


def _read_text(path: str) -> str:
    """Read a UTF-8 text file, or raise ValueError when it is in another encoding."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError as error:
        raise ValueError(f"{path} is not UTF-8 text ({error.reason}): save it as UTF-8") from error


def extract_path(path: str, *, title_hint: str | None = None, keep_short: bool = False) -> Source:
    """Read a draft file and assemble its source document.

    The suffix (any case) picks the reader: .docx, .md or .markdown, .txt. Any other suffix raises
    ValueError. ``essay.source`` is the file name and ``essay.source_kind`` is docx, md or txt. When
    the text has no title, the title is ``title_hint``, or else the file name without its suffix.
    ``keep_short`` is passed on to assemble_source.
    """
    name = os.path.basename(path)
    stem, suffix = os.path.splitext(name)
    kind = _KIND_BY_SUFFIX.get(suffix.lower())
    if kind is None:
        raise ValueError(f"cannot read {name}: use a .docx, .md, .markdown or .txt file")
    if kind == "docx":
        blocks = read_docx(path)
    else:
        blocks = (read_markdown if kind == "md" else read_plain)(_read_text(path))
    return assemble_source(blocks, title_hint=title_hint or stem, source_name=name,
                           source_kind=kind, keep_short=keep_short)


def resolve_out_dir(input_path: str | None, name: str | None, out: str | None, cwd: str) -> str:
    """Return the folder that receives source.json and the files that come after it.

    ``out`` wins. Next comes the folder beside the draft, ``<file stem>.throughmap``, where a
    relative ``input_path`` is read from ``cwd``. Without a file it is ``<slug of name>.throughmap``
    in ``cwd``. Raises ValueError when there is no out, no file and no name.
    """
    if out:
        return out
    if input_path:
        folder, filename = os.path.split(os.path.join(cwd, input_path))
        return os.path.join(folder, os.path.splitext(filename)[0] + _OUTPUT_SUFFIX)
    if name:
        return os.path.join(cwd, slugify(name) + _OUTPUT_SUFFIX)
    raise ValueError("--name is required when the text does not come from a file")
