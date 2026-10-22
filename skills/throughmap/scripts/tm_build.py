"""Build: save a checked analysis as the next version and write the page.

build() checks the analysis (draft.json), adds what the page and the summary need and saves the
result as vN.json beside it. It then writes index.html, which is the template with that data
embedded, and returns the terminal summary. An earlier version is never overwritten, and nothing at
all is written when check finds errors or a comparison that was asked for cannot be made.

vN.json is the input of the page renderer: the analysis as the agent wrote it, plus

    "version": N
    "generated_at": "2026-10-17T12:00:00Z"            (UTC, to the second)
    "computed": {"runs": {lane id: {"span": [first id, last id], "solid": [[id, ...], ...]}},
                 "observations": [{"type": "quiet", "lane", "from", "to", "length"},
                                  {"type": "unresolved", "lane"},
                                  {"type": "unthreaded", "at": [id]}]}

The runs and observations are worked out here, from the marks, so that the page and the terminal
summary show the same things.

From the second build on, the new version is compared with an earlier one: the latest saved
version, or the one that build() is told to compare with. Then vN.json also holds

    "compare": {"against": K,        the number of the version compared with
                "before": {...},     vK.json without a compare of its own, and with its computed
                                     worked out again from its items, so that copies never nest
                "versions": [{"version", "generated_at", "paragraphs"}, ...],
                                     every saved version, this one last
                ...}                 and what tm_compare.compare_versions says of the two

The first build has no compare, so v1.json keeps its v0.1 form, and a compare that an agent left in
draft.json is dropped. When the latest version cannot be used (see tm_compare.load_version), the
new one is built without a compare and the summary says so; a version that was asked for and
cannot be used is an error, and nothing is written.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from itertools import groupby

from tm_check import check_files, format_report, read_json
from tm_compare import CompareError, changes_line, compare_versions, load_version, uncompared_line
from tm_text import one_line

SOURCE_FILE = "source.json"   # written by extract; build and check look for it beside draft.json
DRAFT_FILE = "draft.json"     # the analysis, as SKILL.md names it
PAGE_FILE = "index.html"
PLACEHOLDER = "__THROUGHMAP_DATA__"
DEFAULT_TEMPLATE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets", "template.html"))

# A thread rests when it goes unmarked for at least max(6, a quarter of the paragraphs) paragraphs
# in a row between two of its marks.
_QUIET_MIN_PARAGRAPHS = 6
_QUIET_SHARE_OF_PARAGRAPHS = 0.25
_EXEMPT_ROLE = "transition"   # a paragraph that only bridges two parts needs no thread

# A saved version is v1.json, v2.json and so on: no leading zero, and at most 9 digits, so that
# int() can never meet a number it cannot take.
_VERSION_FILE = re.compile(r"v([1-9][0-9]{0,8})\.json")
# Files that Finder and Explorer write into a folder they show, in lower case: no agent wrote them.
_SYSTEM_FILES = frozenset((".ds_store", "thumbs.db", "desktop.ini"))

_DOT = "\N{MIDDLE DOT}"
_ARROW = "\N{RIGHTWARDS ARROW}"
_EN_DASH = "\N{EN DASH}"
_NOTE_MARKERS = ("\N{CIRCLED DIGIT ONE}", "\N{CIRCLED DIGIT TWO}", "\N{CIRCLED DIGIT THREE}")


class BuildError(ValueError):
    """The analysis has errors, so nothing was built. The message is the report check gives."""


# --- Computed by build: runs and observations --------------------------------------------------


def _paragraph_count(items: list[dict]) -> int:
    """Count the paragraphs among ``items``: tables and figures are not paragraphs."""
    return sum(1 for item in items if item["kind"] == "paragraph")


def _marked_stretches(items: list[dict], lane_id: str) -> list[list[str]]:
    """Return the ids of each stretch of consecutive items that all mark the lane, in order."""
    def marks(item: dict) -> bool:
        return lane_id in item["lanes"]

    return [[item["id"] for item in group] for marked, group in groupby(items, key=marks) if marked]


def compute_runs(analysis: dict) -> dict[str, dict]:
    """Return how each marked lane runs through the items: ``{lane id: {"span", "solid"}}``.

    Items are taken in the order of ``analysis["paragraphs"]``, tables and figures included. The
    marks of a lane on consecutive items make a solid run; a run holds at least 2 items. The span
    is ``[first id, last id]``, from the first mark of the lane to its last. A lane with no marks
    has no entry. The entries follow the order of ``analysis["lanes"]``.
    """
    runs = {}
    for lane in analysis["lanes"]:
        stretches = _marked_stretches(analysis["paragraphs"], lane["id"])
        if stretches:
            runs[lane["id"]] = {"span": [stretches[0][0], stretches[-1][-1]],
                                "solid": [stretch for stretch in stretches if len(stretch) >= 2]}
    return runs


def _quiet_threads(items: list[dict], lane_ids: list[str], paragraph_count: int) -> list[dict]:
    """Find the lanes that rest for a long stretch between two of their marks."""
    shortest = max(_QUIET_MIN_PARAGRAPHS, math.ceil(_QUIET_SHARE_OF_PARAGRAPHS * paragraph_count))
    found = []
    for lane_id in lane_ids:
        last_mark, resting = None, 0   # the latest mark, and the paragraphs since it
        for item in items:
            if lane_id in item["lanes"]:
                if last_mark is not None and resting >= shortest:
                    found.append({"type": "quiet", "lane": lane_id, "from": last_mark,
                                  "to": item["id"], "length": resting})
                last_mark, resting = item["id"], 0
            elif item["kind"] == "paragraph":
                resting += 1
    return found


def _unresolved_threads(sections: list[dict], paragraphs: list[dict],
                        lane_ids: list[str]) -> list[dict]:
    """Find the lanes that no paragraph of the last section marks."""
    if not sections:
        return []
    last = sections[-1]["id"]
    returning = {lane_id for paragraph in paragraphs if paragraph["section"] == last
                 for lane_id in paragraph["lanes"]}
    return [{"type": "unresolved", "lane": lane_id} for lane_id in lane_ids
            if lane_id not in returning]


def _unthreaded_paragraphs(paragraphs: list[dict]) -> list[dict]:
    """Find the paragraphs that are on no thread, leaving out the transitions."""
    return [{"type": "unthreaded", "at": [paragraph["id"]]} for paragraph in paragraphs
            if not paragraph["lanes"] and paragraph["role"] != _EXEMPT_ROLE]


def compute_observations(analysis: dict) -> list[dict]:
    """Return what counting shows, as quiet, unresolved and unthreaded entries, in that order.

    - ``{"type": "quiet", "lane", "from", "to", "length"}``: between the marks ``from`` and ``to``
      the lane rests for ``length`` paragraphs, at least max(6, 25% of the paragraphs). Only
      paragraphs are counted; a table or figure between the marks is not.
    - ``{"type": "unresolved", "lane"}``: no paragraph of the last section marks the lane.
    - ``{"type": "unthreaded", "at": [id]}``: a paragraph with no marks at all. A transition is
      left out.

    Only paragraphs count for the last two, because the section of a table or figure is not
    checked against where it stands. A lane without any mark is not reported.
    """
    items = analysis["paragraphs"]
    paragraphs = [item for item in items if item["kind"] == "paragraph"]
    lane_ids = [lane["id"] for lane in analysis["lanes"]
                if any(lane["id"] in item["lanes"] for item in items)]
    return (_quiet_threads(items, lane_ids, len(paragraphs))
            + _unresolved_threads(analysis["sections"], paragraphs, lane_ids)
            + _unthreaded_paragraphs(paragraphs))


# --- Versions ----------------------------------------------------------------------------------


def _version_numbers(out_dir: str) -> list[int]:
    """Return the numbers of the vN.json files in ``out_dir``, lowest first."""
    numbers = []
    for name in os.listdir(out_dir):
        match = _VERSION_FILE.fullmatch(name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def next_version(out_dir: str) -> int:
    """Return the number for the next version in ``out_dir``: 1, or one more than the highest."""
    return max(_version_numbers(out_dir), default=0) + 1


def list_versions(out_dir: str) -> list[dict]:
    """Return ``[{"version", "generated_at", "paragraphs"}]`` for the vN.json files, by number.

    ``paragraphs`` counts the paragraphs only. A file that is not a version build wrote (it is no
    JSON, or lacks the fields) is listed all the same, with ``generated_at`` None and 0 paragraphs,
    so that it shows. Raises OSError when ``out_dir`` cannot be read.
    """
    versions = []
    for number in _version_numbers(out_dir):
        try:
            data = read_json(os.path.join(out_dir, f"v{number}.json"))
            generated_at, paragraphs = data["generated_at"], _paragraph_count(data["paragraphs"])
        except (OSError, ValueError, KeyError, TypeError):
            generated_at, paragraphs = None, 0
        versions.append({"version": number, "generated_at": generated_at,
                         "paragraphs": paragraphs})
    return versions


# --- The page and the summary ------------------------------------------------------------------


def _script_safe(json_text: str) -> str:
    """Make JSON text safe to put in a script element, without changing what it parses to.

    A "</" would end the element, so it is written "<\\/". A "<!--" followed later by "<script"
    would make the browser treat the next "</script>" as the end of a nested script, so that the
    element stayed open and swallowed the rest of the page; it is written "<\\u0021--". Both are
    escapes inside a JSON string, and "<" occurs nowhere else.
    """
    return json_text.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def render_html(data: dict, template: str) -> str:
    """Return ``template`` with ``data`` as JSON in place of the placeholder.

    Raises ValueError unless the placeholder occurs exactly once in the template.
    """
    found = template.count(PLACEHOLDER)
    if found != 1:
        raise ValueError(f"the template must hold {PLACEHOLDER} exactly once; found {found}")
    return template.replace(PLACEHOLDER, _script_safe(json.dumps(data, ensure_ascii=False)))


def _counted(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _flow_step(section: dict) -> str:
    """Name a section by its short name and, in brackets, the questions it answers."""
    short, answers = one_line(section["short"]), section.get("answers") or []
    return f"{short} ({', '.join(answers)})" if answers else short


def _observation_note(observation: dict, labels: dict[str, str]) -> str:
    """Say an observation in English, naming a lane by its label."""
    lane = observation.get("lane")
    label = labels.get(lane, lane)
    if observation["type"] == "quiet":
        return (f"{label} rests for {observation['length']} paragraphs "
                f"({observation['from']}{_EN_DASH}{observation['to']})")
    if observation["type"] == "unresolved":
        return f"{label} does not return in the last section"
    return f"{', '.join(observation['at'])} is on no thread"


def terminal_summary(data: dict, html_path: str, changes: str | None = None) -> str:
    """Return the summary of built ``data`` that build prints: four lines, or five with ``changes``.

    The gaps line numbers the notes: the agent's own gap notes first, then the observations, in
    English, and at most 3 in all. ``changes``, when given, is the line that says what changed
    from the version compared with (tm_compare.changes_line, or uncompared_line when that could not
    be done); it goes between the gaps line and the last. ``html_path`` goes on the last line as it
    is.
    """
    labels = {lane["id"]: lane["label"] for lane in data["lanes"]}
    notes = [gap["note"] for gap in data["gaps"]]
    notes += [_observation_note(observation, labels)
              for observation in data["computed"]["observations"]]
    numbered = " ".join(f"{marker} {one_line(note)}"
                        for marker, note in zip(_NOTE_MARKERS, notes))
    paragraphs = _counted(_paragraph_count(data["paragraphs"]), "paragraph")
    threads = _counted(len(data["lanes"]), "thread")
    flow = f" {_ARROW} ".join(_flow_step(section) for section in data["sections"])
    lines = [
        f"throughmap {_DOT} {one_line(data['essay']['title'])} ({paragraphs}, {threads})",
        f"flow: {flow}",
        f"gaps: {numbered or 'none'}",
    ]
    if changes is not None:
        lines.append(changes)
    lines.append(f"open: {html_path}")
    return "\n".join(lines)


def other_files(out_dir: str, draft_name: str) -> list[str]:
    """Return the names of the files in ``out_dir`` that are not the map's own, in name order.

    The map's own files are source.json, draft.json, the draft ``draft_name`` (whatever it is
    called), the vN.json versions and index.html. Folders are left out, whatever they hold, and so
    are .DS_Store, Thumbs.db and desktop.ini, in any case, which the system writes.
    """
    own = {SOURCE_FILE, DRAFT_FILE, PAGE_FILE, draft_name}
    with os.scandir(out_dir) as entries:
        return sorted(entry.name for entry in entries
                      if entry.is_file() and entry.name not in own
                      and entry.name.lower() not in _SYSTEM_FILES
                      and not _VERSION_FILE.fullmatch(entry.name))


def other_files_line(out_dir: str, names: list[str]) -> str:
    """Return the summary line that names the files ``names`` in ``out_dir``, for the agent.

    It asks the agent to remove only the files it created: ``--out`` may be a folder that also
    holds the user's own files.
    """
    advice = "remove it if you created it" if len(names) == 1 else "remove any you created"
    return f"also in {out_dir}: {', '.join(names)} ({advice})"


# --- Comparing with an earlier version ---------------------------------------------------------


def _version_to_compare(out_dir: str, saved: list[int], compare_with: int | None) -> int | None:
    """Return the number of the saved version that the new one is compared with, if any.

    That is ``compare_with``, else the highest of the ``saved`` numbers, else None. Raises
    CompareError when ``compare_with`` is given and is not among them.
    """
    if compare_with is None:
        return max(saved, default=None)
    if compare_with not in saved:
        names = ", ".join(f"v{number}" for number in saved)
        detail = f"; the saved versions are {names}" if saved else ": it holds no saved version yet"
        raise CompareError(f"no saved version v{compare_with} in {out_dir}{detail}")
    return compare_with


def _comparison(out_dir: str, against: int, earlier: dict, data: dict) -> dict:
    """Return what the ``compare`` of ``data`` holds when ``data`` follows the saved ``earlier``.

    ``earlier`` is the saved version number ``against``, as load_version gives it. Nothing is
    written, and the saved versions are listed before the new file exists.
    """
    before = {key: value for key, value in earlier.items() if key != "compare"}
    before["computed"] = {"runs": compute_runs(before),
                          "observations": compute_observations(before)}
    versions = list_versions(out_dir) + [{
        "version": data["version"], "generated_at": data["generated_at"],
        "paragraphs": _paragraph_count(data["paragraphs"])}]
    return {"against": against, "before": before, "versions": versions,
            **compare_versions(before, data)}


# --- Build -------------------------------------------------------------------------------------


def build(draft_path: str, template_path: str | None = None,
          compare_with: int | None = None) -> dict:
    """Check the analysis at ``draft_path``, save it as the next version and write the page.

    Writes ``vN.json`` and ``index.html`` in the folder of the draft, and returns
    ``{"version", "json_path", "html_path", "summary"}``, with absolute paths. ``source.json`` is
    read from the same folder. The template is ``assets/template.html`` of the skill unless
    ``template_path`` names another. When the folder holds other files (see other_files), the
    summary ends with a line that names them; build never deletes them.

    When the folder already holds a saved version, the new one is compared with the latest, or
    with the version number ``compare_with`` when that is given: vN.json gets a ``compare`` (the
    module docstring says what it holds), and the summary a ``changes from vK: ...`` line. When
    the latest version cannot be used, the new one is built without a ``compare`` and that line
    says it was not compared. Any ``compare`` in the draft itself is dropped.

    Raises BuildError, with the report check gives, when the analysis has errors; CompareError when
    ``compare_with`` names a version that is not saved or cannot be used; ValueError or OSError
    when a file is missing or cannot be used, as check does. Everything that can fail comes before
    the first file is written, and a version file that exists is never overwritten.
    """
    out_dir = os.path.dirname(os.path.abspath(draft_path))
    report = check_files(draft_path, os.path.join(out_dir, SOURCE_FILE))
    if report["errors"]:
        raise BuildError(format_report(report))
    # The file that check_files has just read, without any compare an agent left in it.
    analysis = {key: value for key, value in read_json(draft_path).items() if key != "compare"}
    with open(template_path or DEFAULT_TEMPLATE, encoding="utf-8") as handle:
        template = handle.read()

    against = _version_to_compare(out_dir, _version_numbers(out_dir), compare_with)
    earlier, unusable = None, None
    if against is not None:
        try:
            earlier = load_version(out_dir, against)
        except CompareError as error:
            if compare_with is not None:   # asked for by name: an error, and nothing is written
                raise
            unusable = error               # the latest cannot be used: build without a compare

    version = next_version(out_dir)
    data = {**analysis, "version": version,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "computed": {"runs": compute_runs(analysis),
                         "observations": compute_observations(analysis)}}
    changes = None
    if earlier is not None:
        data["compare"] = _comparison(out_dir, against, earlier, data)
        changes = changes_line(data)
    elif unusable is not None:
        changes = uncompared_line(against, unusable)
    json_path = os.path.join(out_dir, f"v{version}.json")
    html_path = os.path.join(out_dir, PAGE_FILE)
    json_bytes = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    html_bytes = render_html(data, template).encode("utf-8")
    summary = terminal_summary(data, html_path, changes)
    others = other_files(out_dir, os.path.basename(draft_path))
    if others:
        summary += "\n" + other_files_line(out_dir, others)

    with open(json_path, "xb") as handle:   # "x": fail rather than overwrite a saved version
        handle.write(json_bytes)
    with open(html_path, "wb") as handle:
        handle.write(html_bytes)
    return {"version": version, "json_path": json_path, "html_path": html_path,
            "summary": summary}
