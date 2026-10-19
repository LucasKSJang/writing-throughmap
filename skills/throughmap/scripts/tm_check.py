"""The checker: may this analysis (draft.json) be built into a page?

check() holds the analysis up against the source document (source.json) and returns every problem
it finds, so that an agent can fix them all in one round. An error blocks ``build``; a warning
does not. Each problem names the JSON path of the value at fault, such as
``$.paragraphs[4].lanes.q3.quote``.

Text is compared the way tm_text.normalize leaves it: a straight quote where the draft has a curly
one, a hyphen for a dash, a plain space for a no-break space and a missing zero-width space are no
difference, while a changed letter or a different case is. A mistake is reported once, where it was
made: what refers to a missing or broken list (a lane's question, an item's section) is not
reported on top of it.
"""

from __future__ import annotations

import json
import re

from tm_text import contains_verbatim, normalize, quoted_segments, sentence_count, word_count

SCHEMA = "throughmap/1"
ROLES = (
    "problem", "thesis", "context", "claim", "evidence", "example", "counter", "implication",
    "framework", "transition", "synthesis", "conclusion",
)
LIMITS = {
    "paragraphs": 40, "lanes": 6, "questions": 4, "label": 28, "conclusion": 90, "baton": 40,
    "short": 12, "thesis": 160, "direction_sentences": 2, "unquoted_words": 12, "min_paragraphs": 5,
}
SOURCE_KINDS = ("docx", "md", "txt", "pdf", "paste", "gdoc")
LANE_KINDS = ("question", "concept")
WEIGHTS = ("major", "minor")
ITEM_KINDS = ("paragraph", "table", "figure")

_MISSING = object()
# A key that reads as it is in a path (.q1); any other key is written as ["a key"].
_PLAIN_KEY = re.compile(r"[^\s.\[\]\"']+")
_EXCERPT_CHARS = 60
_NAMES_SHOWN = 6


# --- Wording of the messages -------------------------------------------------------------------


def _member(path: str, key: str) -> str:
    """Return the path of the member ``key`` of the object at ``path``."""
    if _PLAIN_KEY.fullmatch(key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def _json_type(value) -> str:
    """Name the JSON type of ``value`` as a message reads it: "a string", "null" and so on."""
    names = ((type(None), "null"), (bool, "a boolean"), ((int, float), "a number"),
             (str, "a string"), (list, "a list"))
    return next((name for kind, name in names if isinstance(value, kind)), "an object")


def _problem(message: str) -> dict:
    """Return a result that holds one error, about the analysis as a whole."""
    return {"errors": [{"path": "$", "message": message}], "warnings": []}


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    """Return ``text`` on one line, cut to ``limit`` characters with "..." when it is longer."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


def _found(value) -> str:
    """Show ``value`` as JSON on one line, for "found ..." in a message."""
    return _excerpt(json.dumps(value, ensure_ascii=False, default=repr), 40)


def _quoted(text: str) -> str:
    return f'"{_excerpt(text)}"'


def _listed(names, limit: int = _NAMES_SHOWN) -> str:
    """Join ``names`` with commas, naming at most ``limit`` of them and counting the rest."""
    names = [" ".join(str(name).split()) for name in names]
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _visible(text: str) -> str:
    """Spell out the characters that do not show, a zero-width space for one, as escapes."""
    return "".join(char if char.isprintable() else "\\" + "u%04x" % ord(char) for char in text)


def _around(text: str, index: int) -> str:
    """Return a few words of ``text`` around ``index``, with "..." where the text goes on."""
    start = text.rfind(" ", 0, max(0, index - 15)) + 1
    end = index + 30
    return ("..." if start else "") + _visible(text[start:end]) + ("..." if end < len(text) else "")


def _first_difference(expected: str, found: str) -> str:
    """Say where two texts first differ once normalized, showing both sides."""
    a, b = normalize(expected), normalize(found)
    index = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return (f'at character {index + 1}: source.json has "{_around(a, index)}", '
            f'the analysis has "{_around(b, index)}"')


def _objects_in(value) -> list:
    """Return the objects of a list from source.json; anything else is left out."""
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


# --- The checks --------------------------------------------------------------------------------


class _Checker:
    """One run of the checks: it knows what source.json says and collects the problems."""

    def __init__(self, analysis: dict, source: dict):
        self.analysis = analysis
        self.errors: list = []
        self.warnings: list = []
        self._read_source(source)
        # What the analysis itself defines, for the checks that refer to it. None means the
        # definition is missing or broken, and the checks that depend on it are skipped.
        self.question_ids = None   # dict used as an ordered set
        self.lane_ids = None
        self.section_ids = None
        self.section_by_position = None   # the section id of each source paragraph, when valid
        self.marked_lanes = None
        self.reference_ids = None

    def _read_source(self, source: dict) -> None:
        """Take from source.json the text each analysis item must have, and where things sit."""
        self.texts: dict = {}    # id -> text; a table is its caption and rows, a figure its caption
        self.kinds: dict = {}    # id -> "paragraph", "table" or "figure"
        self.after: dict = {}    # id of a table or figure -> id of the paragraph it follows
        self.paragraph_ids: list = []
        for paragraph in _objects_in(source.get("paragraphs")):
            if isinstance(paragraph.get("id"), str):
                self.paragraph_ids.append(paragraph["id"])
                self.kinds[paragraph["id"]] = "paragraph"
                self.texts[paragraph["id"]] = str(paragraph.get("text", ""))
        others = []
        for kind, key, parts in (("table", "tables", ("caption", "text")),
                                 ("figure", "figures", ("caption",))):
            for entry in _objects_in(source.get(key)):
                if isinstance(entry.get("id"), str):
                    others.append(entry["id"])
                    wanted = (str(entry.get(part) or "") for part in parts)
                    self.kinds[entry["id"]] = kind
                    self.texts[entry["id"]] = "\n".join(text for text in wanted if text)
                    self.after[entry["id"]] = entry.get("after")
        self.position = {paragraph_id: n for n, paragraph_id in enumerate(self.paragraph_ids)}
        self.source_has_sections = bool(source.get("sections"))
        ids = self.paragraph_ids
        if not ids:
            self.paragraph_range = "no paragraphs"
        else:
            self.paragraph_range = ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}"
        self.source_ids = _listed(([self.paragraph_range] if ids else []) + others, 12)

    def error(self, path: str, message: str) -> None:
        self.errors.append({"path": path, "message": message})

    def warn(self, path: str, message: str) -> None:
        self.warnings.append({"path": path, "message": message})

    # Reading fields. Each reports what is wrong with the field and returns None or _MISSING.

    def _need(self, obj: dict, path: str, key: str):
        """Return ``obj[key]``; when the key is absent, report it and return _MISSING."""
        if key in obj:
            return obj[key]
        self.error(_member(path, key), "missing required field")
        return _MISSING

    def _string(self, obj: dict, path: str, key: str, *, blank_ok: bool = False):
        """Return the required string ``obj[key]``, or None after reporting why it is no good."""
        value = self._need(obj, path, key)
        if value is _MISSING:
            return None
        if not isinstance(value, str):
            self.error(_member(path, key), f"must be a string, not {_json_type(value)}")
            return None
        if not blank_ok and not value.strip():
            self.error(_member(path, key), "must not be empty")
            return None
        return value

    def _array(self, key: str):
        """Return the top-level list ``key``, or None after reporting it missing or no list."""
        value = self._need(self.analysis, "$", key)
        if value is _MISSING:
            return None
        if not isinstance(value, list):
            self.error(f"$.{key}", f"must be a list, not {_json_type(value)}")
            return None
        return value

    def _entries(self, entries: list, path: str):
        """Yield ``(index, entry path, entry)`` for the objects in a list; report the others."""
        for index, entry in enumerate(entries):
            where = f"{path}[{index}]"
            if isinstance(entry, dict):
                yield index, where, entry
            else:
                self.error(where, f"must be an object, not {_json_type(entry)}")

    def _enum(self, path: str, value: str, allowed) -> None:
        if value not in allowed:
            self.error(path, f"must be one of {', '.join(allowed)}; found {_found(value)}")

    def _limit(self, path: str, text: str, name: str) -> None:
        """Warn when ``text`` is longer than the limit called ``name``."""
        if len(text) > LIMITS[name]:
            self.warn(path, f"{len(text)} characters; keep it to {LIMITS[name]}")

    def run(self) -> dict:
        self._check_schema()
        self._check_essay()
        self._string(self.analysis, "$", "ui_language")
        self._check_thesis()
        self._check_ui_strings()
        self._scan_marks()
        self._check_questions()
        self._check_lanes()
        self._check_sections()
        self._check_items()
        self._check_cases()
        self._check_gaps()
        return {"errors": self.errors, "warnings": self.warnings}

    # The top of the analysis.

    def _check_schema(self) -> None:
        schema = self._need(self.analysis, "$", "schema")
        if schema is not _MISSING and schema != SCHEMA:
            self.error("$.schema", f'must be "{SCHEMA}"; found {_found(schema)}')

    def _check_essay(self) -> None:
        essay = self._need(self.analysis, "$", "essay")
        if essay is _MISSING:
            return
        if not isinstance(essay, dict):
            self.error("$.essay", f"must be an object, not {_json_type(essay)}")
            return
        for key in ("title", "source", "language"):
            self._string(essay, "$.essay", key)
        kind = self._string(essay, "$.essay", "source_kind")
        if kind is not None:
            self._enum("$.essay.source_kind", kind, SOURCE_KINDS)
        words = self._need(essay, "$.essay", "word_count")
        whole = isinstance(words, int) and not isinstance(words, bool) and words >= 0
        if words is not _MISSING and not whole:
            self.error("$.essay.word_count",
                       f"must be a whole number of words; found {_found(words)}")

    def _check_thesis(self) -> None:
        thesis = self._string(self.analysis, "$", "thesis")
        if thesis is not None:
            self._limit("$.thesis", thesis, "thesis")

    def _check_ui_strings(self) -> None:
        strings = self.analysis.get("ui_strings")
        if strings is not None and not isinstance(strings, dict):
            self.error("$.ui_strings", f"must be an object, not {_json_type(strings)}")

    def _scan_marks(self) -> None:
        """Find the lanes that some item marks, whatever else is wrong with the mark."""
        items = self.analysis.get("paragraphs")
        if isinstance(items, list):
            self.marked_lanes = {lane for item in items
                                 if isinstance(item, dict) and isinstance(item.get("lanes"), dict)
                                 for lane in item["lanes"]}

    # Questions and lanes.

    def _check_questions(self) -> None:
        questions = self._array("questions")
        if questions is None:
            return
        if not 1 <= len(questions) <= LIMITS["questions"]:
            self.error("$.questions",
                       f"needs 1 to {LIMITS['questions']} questions; found {len(questions)}")
        ids: dict = {}
        named = 0
        for _, path, question in self._entries(questions, "$.questions"):
            question_id = self._string(question, path, "id")
            self._string(question, path, "text")
            if question_id is not None:
                named += 1
                if question_id in ids:
                    self.error(_member(path, "id"), f"duplicate question id {_quoted(question_id)}")
                ids[question_id] = True
        self.question_ids = ids if ids and named == len(questions) else None

    def _check_lanes(self) -> None:
        lanes = self._array("lanes")
        if lanes is None:
            return
        if not 1 <= len(lanes) <= LIMITS["lanes"]:
            self.error("$.lanes", f"needs 1 to {LIMITS['lanes']} lanes; found {len(lanes)}")
        ids: dict = {}
        named = 0
        has_question_lane = False
        for _, path, lane in self._entries(lanes, "$.lanes"):
            lane_id = self._string(lane, path, "id")
            kind = self._string(lane, path, "kind")
            self._string(lane, path, "label")
            if kind is not None:
                self._enum(_member(path, "kind"), kind, LANE_KINDS)
            has_question_lane = has_question_lane or kind == "question"
            sub = lane.get("sub")
            if sub not in (None, "") and not isinstance(sub, str):
                self.error(_member(path, "sub"), f"must be a string; found {_found(sub)}")
            self._check_lane_question(lane, path, kind)
            if lane_id is None:
                continue
            named += 1
            if lane_id in ids:
                self.error(_member(path, "id"), f"duplicate lane id {_quoted(lane_id)}")
            elif self.marked_lanes is not None and lane_id not in self.marked_lanes:
                self.error(path, f"lane {_quoted(lane_id)} has no marks: mark it in the lanes of "
                                 "at least one paragraph, or remove it")
            ids[lane_id] = True
        if lanes and not has_question_lane:
            self.warn("$.lanes", 'no lane has kind "question"; the page tags threads with the '
                                 "question they answer")
        self.lane_ids = ids if ids and named == len(lanes) else None

    def _check_lane_question(self, lane: dict, path: str, kind) -> None:
        """A question lane names its question; a concept lane may, and a name must be a question."""
        where = _member(path, "question")
        value = lane.get("question")
        if value is None or value == "":
            if kind == "question":
                self.error(where, "is required for a question lane: name the question it answers")
        elif not isinstance(value, str):
            self.error(where, f"must be a question id such as Q1; found {_found(value)}")
        elif self.question_ids is not None and value not in self.question_ids:
            self.error(where, f"unknown question {_found(value)}; the questions are "
                              f"{_listed(self.question_ids)}")

    # Sections.

    def _check_sections(self) -> None:
        sections = self._array("sections")
        if sections is None:
            return
        if not sections:
            self.error("$.sections", f"needs at least one section covering {self.paragraph_range}")
            return
        ids: dict = {}
        named = 0
        spans = []   # (path, id, position of the first paragraph, position of the last)
        for index, path, section in self._entries(sections, "$.sections"):
            section_id = self._section_fields(section, path, last=index == len(sections) - 1)
            if section_id is not None:
                named += 1
                if section_id in ids:
                    self.error(_member(path, "id"), f"duplicate section id {_quoted(section_id)}")
                ids[section_id] = True
            first = self._paragraph_position(section, path, "first")
            last = self._paragraph_position(section, path, "last")
            if first is not None and last is not None:
                if first <= last:
                    spans.append((path, section_id, first, last))
                else:
                    self.error(path, f"first ({self.paragraph_ids[first]}) comes after last "
                                     f"({self.paragraph_ids[last]})")
        covers = len(spans) == len(sections) and self._covers_in_order(spans)
        if named == len(sections):
            self.section_ids = ids
            if covers:
                by_position = [None] * len(self.paragraph_ids)
                for _, section_id, first, last in spans:
                    by_position[first:last + 1] = [section_id] * (last + 1 - first)
                self.section_by_position = by_position

    def _section_fields(self, section: dict, path: str, *, last: bool):
        """Check a section apart from where it begins and ends; return its id (or None)."""
        section_id = self._string(section, path, "id")
        short = self._string(section, path, "short")
        if short is not None:
            self._limit(_member(path, "short"), short, "short")
        self._string(section, path, "title", blank_ok=True)
        self._check_inferred(section, path)
        conclusion = self._string(section, path, "conclusion")
        if conclusion is not None:
            self._limit(_member(path, "conclusion"), conclusion, "conclusion")
        self._check_baton(section, path, last)
        self._check_answers(section, path)
        return section_id

    def _check_inferred(self, section: dict, path: str) -> None:
        inferred = self._need(section, path, "inferred")
        where = _member(path, "inferred")
        if inferred is _MISSING:
            return
        if not isinstance(inferred, bool):
            self.error(where, f"must be true or false; found {_found(inferred)}")
        elif not inferred and not self.source_has_sections:
            self.warn(where, 'the draft has no section headings, so its sections are inferred: '
                             'set "inferred" to true')

    def _check_baton(self, section: dict, path: str, last: bool) -> None:
        """Every section but the last hands a question on; the last has nothing to hand on."""
        where = _member(path, "baton")
        if not last:
            baton = self._string(section, path, "baton")
            if baton is not None:
                self._limit(where, baton, "baton")
            return
        baton = section.get("baton")
        if baton is None:
            return
        if not isinstance(baton, str):
            self.error(where, f"must be a string; found {_found(baton)}")
        elif baton.strip():
            self.warn(where, "the last section hands nothing on: leave its baton empty")

    def _check_answers(self, section: dict, path: str) -> None:
        answers = self._need(section, path, "answers")
        where = _member(path, "answers")
        if answers is _MISSING:
            return
        if not isinstance(answers, list) or not all(isinstance(a, str) for a in answers):
            self.error(where, 'must be a list of question ids such as ["Q1"]; found '
                              f"{_found(answers)}")
        elif self.question_ids is not None:
            unknown = [_found(a) for a in answers if a not in self.question_ids]
            if unknown:
                self.error(where, f"unknown question {_listed(unknown)}; the questions are "
                                  f"{_listed(self.question_ids)}")

    def _paragraph_position(self, section: dict, path: str, key: str):
        """Return the position in the draft of the paragraph that ``section[key]`` names."""
        value = self._string(section, path, key)
        if value is None:
            return None
        if value not in self.position:
            self.error(_member(path, key), f"unknown paragraph {_found(value)}; the draft has "
                                           f"{self.paragraph_range}")
            return None
        return self.position[value]

    def _covers_in_order(self, spans: list) -> bool:
        """Say whether the sections tile the paragraphs in order; report where they do not."""
        ids = self.paragraph_ids
        reached = 0   # one past the furthest paragraph that the sections so far cover
        valid = True
        for path, _, first, last in spans:
            if first < reached:
                self.error(path, f"begins at {ids[first]}, but an earlier section already reaches "
                                 f"{ids[reached - 1]}: sections must not overlap and must follow "
                                 "the order of the draft")
                valid = False
            elif first > reached:
                self.error(path, f"begins at {ids[first]} and leaves {ids[reached]} uncovered: "
                                 "each section must begin right after the ones before it")
                valid = False
            reached = max(reached, last + 1)
        if reached < len(ids):
            self.error(spans[-1][0], f"the sections stop at {ids[reached - 1]} but the draft goes "
                                     f"on to {ids[-1]}: they must cover every paragraph")
            valid = False
        return valid

    # Items: the paragraphs, and the tables and figures that are part of the argument.

    def _check_items(self) -> None:
        items = self._array("paragraphs")
        if items is None:
            return
        listed = []   # (path, id) of each item whose id is a new id of source.json
        seen = set()
        paragraphs = 0
        for _, path, item in self._entries(items, "$.paragraphs"):
            item_id = self._item_id(item, path)
            if item_id is not None:
                if item_id in seen:
                    self.error(_member(path, "id"), f"{item_id} is listed twice")
                else:
                    seen.add(item_id)
                    listed.append((path, item_id))
            if item.get("kind") == "paragraph":
                paragraphs += 1
            self._check_item(item, path, item_id)
        self.reference_ids = set(self.paragraph_ids) | {
            item["id"] for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)}
        self._check_order(listed, seen)
        if paragraphs > LIMITS["paragraphs"]:
            # Without section headings there is no section to map alone (extract --section
            # exits 1), so the advice is extract's own.
            remedy = (": map one section, with extract --section" if self.source_has_sections
                      else ", and the draft has no section headings: add headings or split the "
                           "draft")
            self.error("$.paragraphs", f"{_count(paragraphs, 'paragraph')}; a map holds at most "
                                       f"{LIMITS['paragraphs']} (tables and figures do not count)"
                                       f"{remedy}")
        elif paragraphs < LIMITS["min_paragraphs"]:
            self.warn("$.paragraphs", f"only {_count(paragraphs, 'paragraph')}; a map needs at "
                                      f"least {LIMITS['min_paragraphs']} to show a flow")

    def _item_id(self, item: dict, path: str):
        """Return the id of an item when source.json has it, else report why not and return None."""
        value = self._need(item, path, "id")
        if value is _MISSING:
            return None
        if not isinstance(value, str):
            self.error(_member(path, "id"), f"must be a string such as P3; found {_found(value)}")
            return None
        if value not in self.texts:
            self.error(_member(path, "id"),
                       f"{_found(value)} is not in source.json, which has {self.source_ids}")
            return None
        return value

    def _check_order(self, listed: list, seen: set) -> None:
        """Check that every paragraph is there, in order, and each table where the draft puts it."""
        missing = [paragraph_id for paragraph_id in self.paragraph_ids if paragraph_id not in seen]
        if missing:
            self.error("$.paragraphs", f"missing {_listed(missing)}: every paragraph of "
                                       "source.json must be listed, in order")
        previous = None   # the last paragraph before this item, as an id
        for path, item_id in listed:
            if self.kinds[item_id] == "paragraph":
                if previous is not None and self.position[item_id] < self.position[previous]:
                    self.error(_member(path, "id"), f"{item_id} comes after {previous}: paragraphs "
                                                    "must follow the order of the draft")
                previous = item_id
                continue
            after = self.after[item_id]
            if previous != after and (after is None or after in seen):
                where = "before the first paragraph" if after is None else f"right after {after}"
                self.error(path, f"{item_id} belongs {where}, where it stands in the draft")

    def _check_item(self, item: dict, path: str, item_id) -> None:
        kind = self._string(item, path, "kind")
        if kind is not None:
            self._check_kind(_member(path, "kind"), kind, item_id)
        self._check_item_section(item, path, item_id)
        text = self._string(item, path, "text", blank_ok=True)
        if text is not None and item_id is not None:
            if normalize(text) != normalize(self.texts[item_id]):
                self.error(_member(path, "text"), f"differs from {item_id} in source.json "
                                                  f"{_first_difference(self.texts[item_id], text)}")
        role = self._string(item, path, "role")
        if role is not None:
            self._enum(_member(path, "role"), role, ROLES)
        label = self._string(item, path, "label")
        if label is not None:
            self._limit(_member(path, "label"), label, "label")
        evidence = self._string(item, path, "evidence")
        if evidence is not None:
            self._verbatim(_member(path, "evidence"), evidence, item_id)
        self._check_marks(item, path, item_id)

    def _check_kind(self, where: str, kind: str, item_id) -> None:
        self._enum(where, kind, ITEM_KINDS)
        if item_id is not None and kind in ITEM_KINDS and kind != self.kinds[item_id]:
            self.error(where, f"{item_id} is a {self.kinds[item_id]}: kind must be "
                              f'"{self.kinds[item_id]}"; found {_found(kind)}')

    def _check_item_section(self, item: dict, path: str, item_id) -> None:
        """A paragraph is in the section that covers it; a table or figure in any section."""
        section = self._string(item, path, "section")
        if section is None or self.section_ids is None:
            return
        where = _member(path, "section")
        if section not in self.section_ids:
            self.error(where, f"unknown section {_found(section)}; the sections are "
                              f"{_listed(self.section_ids)}")
        elif (self.section_by_position is not None and item_id is not None
              and self.kinds[item_id] == "paragraph"):
            covering = self.section_by_position[self.position[item_id]]
            if section != covering:
                self.error(where, f"{item_id} is in section {covering}, not {section}")

    def _check_marks(self, item: dict, path: str, item_id) -> None:
        marks = self._need(item, path, "lanes")
        if marks is _MISSING:
            return
        where = _member(path, "lanes")
        if not isinstance(marks, dict):
            self.error(where, "must be an object that maps lane ids to marks (use {} for an item "
                              f"on no thread); found {_found(marks)}")
            return
        for lane_id, mark in marks.items():
            mark_path = _member(where, lane_id)
            if self.lane_ids is not None and lane_id not in self.lane_ids:
                self.error(mark_path, f"unknown lane {_found(lane_id)}; the lanes are "
                                      f"{_listed(self.lane_ids)}")
            elif not isinstance(mark, dict):
                self.error(mark_path, 'must be an object like {"weight": "major", "quote": "..."}; '
                                      f"found {_found(mark)}")
            else:
                weight = self._string(mark, mark_path, "weight")
                if weight is not None:
                    self._enum(_member(mark_path, "weight"), weight, WEIGHTS)
                quote = self._string(mark, mark_path, "quote")
                if quote is not None:
                    self._verbatim(_member(mark_path, "quote"), quote, item_id)

    def _verbatim(self, where: str, quote: str, item_id) -> None:
        """Report a quote that is not in the draft's own text of its item."""
        if item_id is not None and not contains_verbatim(self.texts[item_id], quote):
            self.error(where, f"not found word for word in {item_id}: {_quoted(quote)}")

    # Recurring examples and gaps.

    def _check_cases(self) -> None:
        cases = self._array("cases")
        if cases is None:
            return
        for _, path, case in self._entries(cases, "$.cases"):
            self._string(case, path, "name")
            self._string(case, path, "note")
            places = self._references(case, path, "at")
            if places is not None and len(places) < 2:
                self.error(_member(path, "at"), "a recurring example must appear in at least 2 "
                                                f"places; found {len(places)}")

    def _check_gaps(self) -> None:
        gaps = self._array("gaps")
        if gaps is None:
            return
        for _, path, gap in self._entries(gaps, "$.gaps"):
            self._references(gap, path, "at")
            self._string(gap, path, "note")
            direction = self._string(gap, path, "direction")
            if direction is not None:
                self._check_direction(_member(path, "direction"), direction)

    def _references(self, entry: dict, path: str, key: str):
        """Return the distinct ids in the list ``entry[key]``, after reporting the unknown ones."""
        value = self._need(entry, path, key)
        if value is _MISSING:
            return None
        where = _member(path, key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.error(where, f'must be a list of ids such as ["P2", "P5"]; found {_found(value)}')
            return None
        ids = list(dict.fromkeys(value))
        unknown = [_found(v) for v in ids
                   if self.reference_ids is not None and v not in self.reference_ids]
        if unknown:
            self.error(where, f"unknown id {_listed(unknown)}: it is no paragraph, table or figure "
                              "in the analysis")
        return ids

    def _check_direction(self, where: str, direction: str) -> None:
        """A direction is at most two sentences and never smuggles in a passage of new writing."""
        sentences = sentence_count(direction)
        if sentences > LIMITS["direction_sentences"]:
            self.error(where, f"{sentences} sentences; a direction has at most "
                              f"{LIMITS['direction_sentences']}")
        for quote in quoted_segments(direction):
            words = word_count(quote)
            if words > LIMITS["unquoted_words"] and not any(
                    contains_verbatim(text, quote) for text in self.texts.values()):
                self.error(where, f"quotes {words} words that are not in the draft "
                                  f"({_quoted(quote)}): quote the draft as it is, or no more than "
                                  f"{LIMITS['unquoted_words']} words of your own")


# --- Entry points ------------------------------------------------------------------------------


def check(analysis: dict, source: dict) -> dict:
    """Check ``analysis`` against ``source`` and return ``{"errors": [...], "warnings": [...]}``.

    An entry is ``{"path": "$.paragraphs[4].lanes.q3.quote", "message": "..."}``. Neither argument
    is changed. ``analysis`` is what the agent wrote and may have any shape: whatever is wrong
    with it is reported, never raised.

    Errors are what ``build`` refuses: a wrong schema, field, type or enum value; ids and texts
    that differ from source.json (a table is its caption and rows joined by a newline, a figure its
    caption); a missing or misplaced paragraph; too many paragraphs, lanes or questions, or a lane
    with no marks; a quote that is not verbatim in its item; sections that do not tile the
    paragraphs, or an item in the wrong section; an unknown id or question; a case that appears
    once; a gap direction of more than two sentences, or quoting 13 words or more that the draft
    does not hold.

    Warnings let the build go on: a text over its length limit, fewer than 5 paragraphs, no
    question lane, a baton on the last section, sections that are not inferred in a draft without
    headings.
    """
    if not isinstance(analysis, dict):
        return _problem(f"the analysis must be a JSON object, not {_json_type(analysis)}")
    return _Checker(analysis, source if isinstance(source, dict) else {}).run()


def format_report(result: dict) -> str:
    """Lay out a result for the terminal: the ERROR lines, the WARN lines, then a final line.

    The final line is OK when there is nothing to report, else the counts, as in "1 error, 2
    warnings".
    """
    lines = [f"ERROR {entry['path']}: {entry['message']}" for entry in result["errors"]]
    lines += [f"WARN {entry['path']}: {entry['message']}" for entry in result["warnings"]]
    if lines:
        lines.append(f"{_count(len(result['errors']), 'error')}, "
                     f"{_count(len(result['warnings']), 'warning')}")
    else:
        lines.append("OK")
    return "\n".join(lines)


def read_json(path: str):
    """Read a JSON file as UTF-8; a byte order mark in front of the text is ignored.

    Raises OSError when the file cannot be read, and ValueError when it is not UTF-8 or not JSON.
    """
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def _read_source_file(source_path: str) -> dict:
    """Read source.json, or raise ValueError saying why that cannot be done."""
    try:
        source = read_json(source_path)
    except FileNotFoundError:
        raise ValueError(f"{source_path} not found: run extract first, and keep the analysis in "
                         "the same folder as source.json") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{source_path} is not valid JSON ({error}): run extract again") from None
    if not isinstance(source, dict) or not isinstance(source.get("paragraphs"), list):
        raise ValueError(f"{source_path} is not a source.json written by extract: "
                         "run extract again")
    return source


def check_files(draft_path: str, source_path: str) -> dict:
    """Check the analysis in the file ``draft_path`` against the source in ``source_path``.

    A draft that is not valid JSON, or not UTF-8 text, is a problem of the analysis and is reported
    like any other (an error at ``$``). A file that is missing, or a source file that is no
    source.json, is not: it raises ValueError (an OSError for a file that cannot be opened).
    """
    source = _read_source_file(source_path)
    try:
        analysis = read_json(draft_path)
    except FileNotFoundError:
        raise ValueError(f"{draft_path} not found") from None
    except UnicodeDecodeError:
        return _problem("not valid JSON: the file is not UTF-8 text")
    except json.JSONDecodeError as error:
        return _problem(f"not valid JSON: {error}")
    return check(analysis, source)
