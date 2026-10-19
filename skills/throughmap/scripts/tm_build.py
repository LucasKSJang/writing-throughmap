"""Build: save a checked analysis as the next version and write the page.

build() checks the analysis (draft.json), adds what the page and the summary need and saves the
result as vN.json beside it. It then writes index.html, which is the template with that data
embedded, and returns the terminal summary. An earlier version is never overwritten, and nothing at
all is written when check finds errors.

vN.json is the input of the page renderer: the analysis as the agent wrote it, plus

    "version": N
    "generated_at": "2026-10-17T12:00:00Z"            (UTC, to the second)
    "computed": {"runs": {lane id: {"span": [first id, last id], "solid": [[id, ...], ...]}},
                 "observations": [{"type": "quiet", "lane", "from", "to", "length"},
                                  {"type": "unresolved", "lane"},
                                  {"type": "unthreaded", "at": [id]}]}

The runs and observations are worked out here, from the marks, so that the page and the terminal
summary show the same things.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from itertools import groupby

from tm_check import check_files, format_report, read_json

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


def _one_line(text: str) -> str:
    """Return ``text`` with every run of whitespace, line breaks included, as one space."""
    return " ".join(str(text).split())


def _flow_step(section: dict) -> str:
    """Name a section by its short name and, in brackets, the questions it answers."""
    short, answers = _one_line(section["short"]), section.get("answers") or []
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


def terminal_summary(data: dict, html_path: str) -> str:
    """Return the four-line summary of built ``data`` that build prints.

    The gaps line numbers the notes: the agent's own gap notes first, then the observations, in
    English, and at most 3 in all. ``html_path`` goes on the last line as it is.
    """
    labels = {lane["id"]: lane["label"] for lane in data["lanes"]}
    notes = [gap["note"] for gap in data["gaps"]]
    notes += [_observation_note(observation, labels)
              for observation in data["computed"]["observations"]]
    numbered = " ".join(f"{marker} {_one_line(note)}"
                        for marker, note in zip(_NOTE_MARKERS, notes))
    paragraphs = _counted(_paragraph_count(data["paragraphs"]), "paragraph")
    threads = _counted(len(data["lanes"]), "thread")
    flow = f" {_ARROW} ".join(_flow_step(section) for section in data["sections"])
    return "\n".join((
        f"throughmap {_DOT} {_one_line(data['essay']['title'])} ({paragraphs}, {threads})",
        f"flow: {flow}",
        f"gaps: {numbered or 'none'}",
        f"open: {html_path}",
    ))


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


# --- Build -------------------------------------------------------------------------------------


def build(draft_path: str, template_path: str | None = None) -> dict:
    """Check the analysis at ``draft_path``, save it as the next version and write the page.

    Writes ``vN.json`` and ``index.html`` in the folder of the draft, and returns
    ``{"version", "json_path", "html_path", "summary"}``, with absolute paths. ``source.json`` is
    read from the same folder. The template is ``assets/template.html`` of the skill unless
    ``template_path`` names another. When the folder holds other files (see other_files), the
    summary ends with a line that names them; build never deletes them.

    Raises BuildError, with the report check gives, when the analysis has errors; ValueError or
    OSError when a file is missing or cannot be used, as check does. Everything that can fail comes
    before the first file is written, and a version file that exists is never overwritten.
    """
    out_dir = os.path.dirname(os.path.abspath(draft_path))
    report = check_files(draft_path, os.path.join(out_dir, SOURCE_FILE))
    if report["errors"]:
        raise BuildError(format_report(report))
    analysis = read_json(draft_path)   # the file that check_files has just read
    with open(template_path or DEFAULT_TEMPLATE, encoding="utf-8") as handle:
        template = handle.read()

    version = next_version(out_dir)
    data = {**analysis, "version": version,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "computed": {"runs": compute_runs(analysis),
                         "observations": compute_observations(analysis)}}
    json_path = os.path.join(out_dir, f"v{version}.json")
    html_path = os.path.join(out_dir, PAGE_FILE)
    json_bytes = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    html_bytes = render_html(data, template).encode("utf-8")
    summary = terminal_summary(data, html_path)
    others = other_files(out_dir, os.path.basename(draft_path))
    if others:
        summary += "\n" + other_files_line(out_dir, others)

    with open(json_path, "xb") as handle:   # "x": fail rather than overwrite a saved version
        handle.write(json_bytes)
    with open(html_path, "wb") as handle:
        handle.write(html_bytes)
    return {"version": version, "json_path": json_path, "html_path": html_path,
            "summary": summary}
