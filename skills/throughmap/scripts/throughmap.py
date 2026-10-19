"""Command line of the throughmap skill.

    python throughmap.py extract INPUT [--name NAME] [--out DIR] [--section S] [--keep-short]
                                       [--join A,B] [--split ID TEXT] [--drop ID]
    python throughmap.py check DRAFT
    python throughmap.py build DRAFT
    python throughmap.py versions OUT

Exit status: 0 on success; 1 when a correction or the choice of section does not fit the draft, no
paragraph is left to map, or check or build finds errors in the analysis; 2 for a usage error or an
input that cannot be read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from tm_build import SOURCE_FILE, BuildError, build, list_versions
from tm_check import check_files, format_report
from tm_extract import read_markdown
from tm_source import (
    CorrectionError, apply_corrections, assemble_source, extract_path, resolve_out_dir,
    select_section,
)

PARAGRAPH_LIMIT = 40  # the most paragraphs one map holds; check enforces the same limit
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
_SEPARATOR = " \N{MIDDLE DOT} "


def _use_utf8_streams() -> None:
    """Print and read UTF-8, whatever the console code page.

    A pipe on Windows uses the code page (cp949 on a Korean system), which cannot print a dash and
    would garble the Korean text an agent pipes in. A stream that cannot be reconfigured (a capture
    in a test, say) is left as it is.
    """
    for stream, errors in ((sys.stdout, "replace"), (sys.stderr, "replace"), (sys.stdin, "strict")):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except (AttributeError, ValueError, OSError):
            pass


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as error:
        raise ValueError(f"standard input is not UTF-8 text ({error.reason})") from error


def _write_source(source: dict, out_dir: str) -> str:
    """Write source.json into ``out_dir`` (made if need be) and return its path."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, SOURCE_FILE)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(source, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return path


def _plural(kind: str) -> str:
    return kind if kind.endswith(("s", "ed")) else kind + "s"


def _set_aside(source: dict) -> str:
    """Name what was set aside: the title if the text gave it, then each kind in document order.

    A kind that occurs more than once comes with its count, as in "byline, 2 subheadings".
    """
    counts = {"title": 1} if getattr(source, "title_from_block", False) else {}
    for entry in source["excluded"]:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    parts = [kind if count == 1 else f"{count} {_plural(kind)}" for kind, count in counts.items()]
    return ", ".join(parts) or "none"


def _summary(source: dict, path: str) -> list[str]:
    counts = _SEPARATOR.join((
        f"paragraphs: {len(source['paragraphs'])}", f"tables: {len(source['tables'])}",
        f"figures: {len(source['figures'])}", f"sections: {len(source['sections'])}",
        f"words: {source['essay']['word_count']}",
    ))
    return [f"source: {path}", counts, f"set aside: {_set_aside(source)}"]


def _over_limit_advice(source: dict) -> list[str]:
    """Say what to do with a draft that is too long to map whole.

    With section headings, list the sections and their paragraph ranges to choose from; without
    any, say so.
    """
    over = f"over {PARAGRAPH_LIMIT} paragraphs"
    if not source["sections"]:
        return [f"{over} and no section headings: add headings or split the draft"]
    lines = [f"{over}: pick a section with --section"]
    ids = [paragraph["id"] for paragraph in source["paragraphs"]]
    for number, section in enumerate(source["sections"], 1):
        first, last = section["first"], section["last"]
        count = ids.index(last) - ids.index(first) + 1
        span = first if first == last else f"{first}\N{EN DASH}{last}"
        noun = "paragraph" if count == 1 else "paragraphs"
        lines.append(f"  {number}. {section['title'] or '(untitled)'} {span}, {count} {noun}")
    return lines


def _nothing_left(source: dict) -> str:
    """Say that no paragraph is left to map, what was set aside, and where to look."""
    return (f"no paragraph is left to map (set aside: {_set_aside(source)}); "
            "check the draft and any --drop")


def _run_extract(args: argparse.Namespace) -> int:
    from_stdin = args.input == "-"
    if from_stdin and not args.name:
        raise ValueError("--name is required when INPUT is - (text on standard input)")
    out_dir = resolve_out_dir(None if from_stdin else args.input, args.name, args.out, os.getcwd())
    if from_stdin:
        source = assemble_source(read_markdown(_read_stdin()), title_hint=args.name,
                                 source_name=args.name, source_kind="paste",
                                 keep_short=args.keep_short)
    else:
        source = extract_path(args.input, title_hint=args.name, keep_short=args.keep_short)
    source = apply_corrections(source, joins=args.join or (), splits=args.split or (),
                               drops=args.drop or ())
    if not source["paragraphs"]:   # the body must never vanish behind exit 0
        print(f"error: {_nothing_left(source)}", file=sys.stderr)
        return EXIT_FAILED
    too_long = args.section is None and len(source["paragraphs"]) > PARAGRAPH_LIMIT
    if args.section is not None:
        source = select_section(source, args.section)
    lines = _summary(source, _write_source(source, out_dir))
    if too_long:
        lines += _over_limit_advice(source)
    print("\n".join(lines))
    return EXIT_OK


def _run_check(args: argparse.Namespace) -> int:
    source_path = os.path.join(os.path.dirname(args.draft), SOURCE_FILE)
    result = check_files(args.draft, source_path)
    print(format_report(result))
    return EXIT_FAILED if result["errors"] else EXIT_OK


def _run_build(args: argparse.Namespace) -> int:
    try:
        result = build(args.draft)
    except BuildError as error:   # the same report check prints; nothing was written
        print(error)
        return EXIT_FAILED
    print(result["summary"])
    return EXIT_OK


def _version_line(version: dict) -> str:
    noun = "paragraph" if version["paragraphs"] == 1 else "paragraphs"
    return (f"v{version['version']}  {version['generated_at'] or '-'}  "
            f"{version['paragraphs']} {noun}")


def _run_versions(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.out):
        raise ValueError(f"{args.out} is not a folder")
    versions = list_versions(args.out)
    print("\n".join(_version_line(version) for version in versions) or "no versions yet")
    return EXIT_OK


def _join_pair(value: str) -> tuple[str, str]:
    first, _, second = value.partition(",")
    first, second = first.strip(), second.strip()
    if not first or not second or "," in second:
        raise argparse.ArgumentTypeError(
            f"expected two paragraph ids with a comma between them, like P3,P4 (got {value!r})")
    return first, second


def _add_extract(commands) -> None:
    extract = commands.add_parser(
        "extract", help="turn a draft into numbered paragraphs (source.json)",
        description="Read a draft and write source.json: its numbered paragraphs, tables, figures "
                    "and sections, and what was set aside.")
    extract.add_argument(
        "input", metavar="INPUT",
        help="a .docx, .md, .markdown or .txt file, or - to read Markdown from standard input")
    extract.add_argument(
        "--name", help="the essay's name: its title when the text has none, and with INPUT - also "
                       "the name of the output folder (required then)")
    extract.add_argument(
        "--out", metavar="DIR",
        help="the folder to write source.json into (default: <draft name>.throughmap, next to "
             "the draft)")
    extract.add_argument(
        "--section", metavar="S",
        help="keep one section, by its number or exact title (for a draft over "
             f"{PARAGRAPH_LIMIT} paragraphs)")
    extract.add_argument(
        "--keep-short", action="store_true",
        help="keep short opening and closing paragraphs (a byline, a date, a sign-off) as "
             "paragraphs instead of setting them aside; --drop removes what you do not want")
    extract.add_argument(
        "--join", metavar="A,B", action="append", type=_join_pair,
        help="join paragraphs A and B, neighbours in one section (repeatable)")
    extract.add_argument(
        "--split", nargs=2, metavar=("ID", "TEXT"), action="append",
        help="split paragraph ID where TEXT first occurs (repeatable)")
    extract.add_argument(
        "--drop", metavar="ID", action="append", help="set paragraph ID aside (repeatable)")
    extract.set_defaults(run=_run_extract)


def _add_check(commands) -> None:
    check = commands.add_parser(
        "check", help="check an analysis (draft.json) against source.json",
        description="Check the analysis against source.json in the same folder: every quote must "
                    "be verbatim in its paragraph, and ids, texts, counts and references must "
                    "agree with the source. Each problem is listed with the JSON path of the value "
                    "at fault. Warnings do not fail the check.")
    check.add_argument(
        "draft", metavar="DRAFT",
        help="the analysis, draft.json; source.json is read from its folder")
    check.set_defaults(run=_run_check)


def _add_build(commands) -> None:
    build_command = commands.add_parser(
        "build", help="save an analysis (draft.json) as the next version and write the page",
        description="Check the analysis as check does. When it has no errors, save it as the next "
                    "version (vN.json, with the computed runs and observations) and write "
                    "index.html beside it, then print a short summary. Nothing is written when "
                    "check finds errors, and a saved version is never overwritten.")
    build_command.add_argument(
        "draft", metavar="DRAFT",
        help="the analysis, draft.json; source.json is read from its folder")
    build_command.set_defaults(run=_run_build)


def _add_versions(commands) -> None:
    versions = commands.add_parser(
        "versions", help="list the saved versions of a map",
        description="List the versions (vN.json) in an output folder, with the time each was "
                    "built and its number of paragraphs.")
    versions.add_argument(
        "out", metavar="OUT", help="the output folder, <draft name>.throughmap")
    versions.set_defaults(run=_run_versions)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="throughmap.py", description="Map the structure of an essay.",
        epilog="exit status: 0 success; 1 a correction or section choice does not fit the draft, "
               "no paragraph is left to map, or check or build finds errors in the analysis; "
               "2 usage error or unreadable input")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    _add_extract(commands)
    _add_check(commands)
    _add_build(commands)
    _add_versions(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    _use_utf8_streams()
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as stop:  # argparse exits for --help (0) and for a usage error (2)
        return stop.code if isinstance(stop.code, int) else EXIT_USAGE
    try:
        return args.run(args)
    except CorrectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
