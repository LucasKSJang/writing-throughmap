"""Helpers shared by the test modules."""

import json
import pathlib
import re
import subprocess

ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent

_FENCE = "```"
# The label line of a JSON example in a Markdown file: `draft.json`: just before the fence.
_BLOCK_LABEL = re.compile(r"`([^`]+)`:")


def repo_files() -> list[pathlib.Path]:
    """Return the files git would commit: tracked, plus untracked files that are not ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [ROOT / name for name in listed.decode("utf-8").split("\0") if name]


def _unquote(value: str) -> str:
    """Strip one pair of matching double or single quotes from around ``value``."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def frontmatter(path) -> dict:
    """Return the frontmatter of a Markdown file, such as a SKILL.md, as a dict.

    A minimal parser, enough for a skill's header: top-level ``key: value`` lines, and a ``key:``
    line with nothing after it that opens a map of indented ``key: value`` lines (``metadata``).
    Surrounding quotes are stripped from each value; nothing else is unescaped. Raises ValueError
    when the file does not open with a ``---`` line, the block is not closed, or an indented line
    belongs to no map.
    """
    lines = pathlib.Path(path).read_text("utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} does not open with a frontmatter block")
    try:
        end = next(n for n, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        raise ValueError(f"{path}: the frontmatter block is not closed") from None
    result: dict = {}
    current = None   # the map that indented lines go into
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        value = _unquote(value.strip())
        if line[0].isspace():
            if current is None:
                raise ValueError(f"{path}: the indented line {line.strip()!r} belongs to no map")
            current[key] = value
        elif value:
            result[key], current = value, None
        else:
            result[key] = current = {}
    return result


def json_blocks(path) -> dict:
    """Return the labelled JSON examples of a Markdown file, as ``{label: parsed JSON}``.

    An example is a fence opened by ```json whose line just before it is its label, such as
    `` `draft.json`: ``. A fence without a label is left out. Raises ValueError when a labelled
    block is not closed or a label is used twice.
    """
    lines = pathlib.Path(path).read_text("utf-8").splitlines()
    blocks: dict = {}
    for n, line in enumerate(lines[1:], 1):
        label = _BLOCK_LABEL.fullmatch(lines[n - 1].strip())
        if line.strip() != _FENCE + "json" or not label:
            continue
        name = label.group(1)
        try:
            end = next(m for m in range(n + 1, len(lines)) if lines[m].strip() == _FENCE)
        except StopIteration:
            raise ValueError(f"{path}: the {name} block is not closed") from None
        if name in blocks:
            raise ValueError(f"{path}: {name} is given twice")
        blocks[name] = json.loads("\n".join(lines[n + 1:end]))
    return blocks
