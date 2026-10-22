"""Compare: match the items of two versions of a map, say what changed, and read a saved version.

match_items() takes the items of an earlier and of a later version, the ``paragraphs`` of two
analyses (only ``id``, ``kind`` and ``text`` of an item are read), and says what became of each:

    "pairs":   [{"old", "new", "ratio", "edited", "moved"}]   in the new version's order
    "splits":  [{"old", "new": [first, second], "cover"}]     in the old order
    "merges":  [{"old": [first, second], "new", "cover"}]     in the new order
    "added":   [new id, ...]                                  in the new order
    "removed": [old id, ...]                                  in the old order

Every old id is in exactly one of pairs, splits, merges and removed, and every new id in exactly
one of pairs, splits, merges and added. ``ratio`` and ``cover`` are rounded to 2 decimals; every
decision is made on the unrounded values.

Items are compared by their tokens(): the words and punctuation marks of the normalized,
case-folded text. Whole words keep unrelated paragraphs apart where smaller units blur them, and
difflib's autojunk is off, since it would drop the common words of a long paragraph. The steps run
in this order:

1. Scores. An old and a new item of the same kind (a paragraph with a paragraph, a table with a
   table, a figure with a figure) are scored with SequenceMatcher(None, old, new,
   autojunk=False).ratio(). A pair that the upper bounds real_quick_ratio() and quick_ratio() put
   below MATCH_RATIO is not scored, which changes no result.
2. Pairs. The scores at or above MATCH_RATIO are taken from the highest ratio down, then from the
   earlier old item and the earlier new one, whenever neither item is taken yet. So a repeated
   paragraph pairs in document order, and look-alikes keep their own partners.
3. Splits and merges, among paragraphs only. Neighbours are consecutive paragraphs of one version,
   so a table or figure between them does not count. cover(a, b) is the share of the tokens of a
   that the matching blocks of a against b match.
   - A split candidate is an old paragraph and two new neighbours. If the old paragraph is paired,
     one of the two is its partner and the other is unpaired; if not, both are unpaired. It is
     valid when the two together cover at least SPLIT_COVER of the old paragraph and match it
     better than either does alone. The second test keeps an unchanged paragraph and any new
     neighbour from being called a split.
   - A merge candidate is the mirror image: a new paragraph and two old neighbours.
   Every candidate is judged against the pairs of step 2. A candidate whose texts share too few
   tokens to reach SPLIT_COVER (the size of the Counter intersection, an upper bound of what the
   matching blocks match) is skipped before the matching, which changes no result. The valid ones
   are accepted by highest cover, splits before merges on a tie, then by the first old and the
   first new position. One is skipped when a paragraph of it is already in an accepted split or
   merge. Accepting one removes the pair it took over.
4. Leftovers. The old items in no pair, split or merge are removed, the new ones are added.
5. Moved. The pairs, splits and merges are the anchors. A pair stands at its two positions, a split
   at its old paragraph and its first part, a merge at its first old paragraph and its new
   paragraph. The longest chain of anchors whose new positions rise in the old order is kept, and
   among equally long chains the one with the earliest old positions. A pair off the chain is
   moved; splits and merges are never flagged.
6. Edited. A pair is edited when its normalized texts differ.

compare_versions() takes two built versions, each an analysis plus ``computed`` as a vN.json holds
it, and returns the five keys of match_items() for their items, with these five more:

    "marks":        [{"old", "new", "gained": [lane id, ...], "lost": [lane id, ...]}]
    "lanes":        {"added": [lane id, ...], "removed": [lane id, ...]}
    "quiet_closed": [observation, ...]   earlier quiet observations, with old ids
    "quiet_opened": [observation, ...]   new quiet observations, with new ids
    "gaps_closed":  [gap, ...]           earlier gaps, unchanged

The counterparts of an old id are the new ids it became: its partner, the two parts of its split,
or the paragraph it merged into. A removed id has none.

- Marks. One entry for each pair whose new item marks other lanes than its old one, in the new
  order. Only the lanes that both versions list are compared, so a lane that one version lacks is
  in "lanes" and in no mark. "gained" follows the new lane order and "lost" the old one.
- Lanes. Two lanes are the same lane when their ids are equal. "added" are the lanes of the new
  version only, in its order; "removed" those of the earlier version only, in its order.
- Quiet. An earlier quiet observation (``computed``, type "quiet") still holds when the new version
  has one on the same lane whose two ends are counterparts of its own two ends. "quiet_closed" are
  the earlier ones that no new one continues, "quiet_opened" the new ones that continue no earlier
  one.
- Gaps. An earlier gap no longer applies when no gap of the new version names any counterpart of
  an item of its own ``at``; "gaps_closed" lists those gaps. A gap whose ``at`` is empty names no
  item to follow and is never listed.

changes_line() lays this out as one line for the build summary: ``changes from v{K}: `` and then
the parts below, in this order, joined by `` · ``. A part with nothing to say is left out, and
when no part is left the line ends in ``none``. An old id is written with its version (``v1 P8``),
and a list names at most 6 entries and counts the rest (``P2, P3, P4, P5, P6, P7 and 2 more``).

    {n} edited ({new ids})                   pairs whose text changed
    {n} added ({new ids})
    {n} removed ({old ids})
    {n} split ({old} into {first} and {second}, ...)
    {n} merged ({old} and {old} into {new}, ...)
    {n} moved ({old} to {new}, ...)          pairs that moved
    marks: {g} gained, {l} lost              the sum over "marks"; a side of 0 is left out
    {n} new thread(s) ({labels})             labels from the new version
    {n} dropped thread(s) ({labels})         labels from the earlier version
    quiet: {c} closed, {o} opened            a side of 0 is left out
    1 earlier gap no longer applies          or {n} earlier gaps no longer apply

load_version() reads a saved version, vN.json of an output folder, for a comparison. It raises
CompareError, with the message ``v{n}.json cannot be read: `` and one of these reasons:

    the file is missing
    the file cannot be opened                a folder of that name, or a file the system refuses
    it is not valid JSON                     or not UTF-8 text
    it is not a map build wrote; {what is wrong}

A map build wrote has the schema "throughmap/1". Its paragraphs, lanes, sections and gaps are lists
of objects. Every item has a string id, kind, text, section and role and an object lanes, every
lane and section has a string id, and every gap has a list at of strings. These are the fields
that the comparison reads of an earlier version, and that build reads to work its runs and
observations out again; nothing else is checked. The first thing wrong is named, by the path of
the value: ``gaps[1].at is not a list of strings``.

uncompared_line() is the changes line of a build that could not use the latest saved version:
``changes from v{n}: not compared (`` and the message of the CompareError, then ``)``.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import NamedTuple

from tm_check import SCHEMA, read_json
from tm_text import normalize, one_line

MATCH_RATIO = 0.55   # two items of a kind are one item at this ratio or above
SPLIT_COVER = 0.60   # two neighbours stand for one paragraph when they cover this share of it

_TOKEN = re.compile(r"\w+|[^\w\s]")
_PARAGRAPH = "paragraph"   # the only kind of item that is split or merged


def tokens(text: str) -> list[str]:
    """Return the words and punctuation marks of ``text``, in order.

    The text is normalized (tm_text.normalize) and case-folded first, so curly quotes, dashes,
    spaces and capitals make no difference. A word is a run of letters, digits and underscores in
    any script; every other character that is not whitespace is a token by itself.
    """
    return _TOKEN.findall(normalize(text).casefold())


class _Item(NamedTuple):
    """An item as the matching sees it. A position is an index into the list of a version."""

    kind: str
    tokens: list[str]
    counts: Counter   # how often each token occurs


def _items(items: list[dict]) -> list[_Item]:
    """Return the items of one version, tokenized, in the order they come."""
    found = []
    for item in items:
        words = tokens(item["text"])
        found.append(_Item(item["kind"], words, Counter(words)))
    return found


def _ratio_of(old: list[str], new: list[str]) -> float:
    """Return the ratio of two token lists, the old one first."""
    return SequenceMatcher(None, old, new, autojunk=False).ratio()


# --- Pairs -------------------------------------------------------------------------------------


def _scores(old: list[_Item], new: list[_Item]) -> dict[tuple[int, int], float]:
    """Score every old and new item of one kind, and return the scores from MATCH_RATIO up.

    The result is ``{(old position, new position): ratio}``.
    """
    scores = {}
    for n, now in enumerate(new):
        matcher = SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(now.tokens)   # the matcher caches its second sequence, so set it once
        for o, before in enumerate(old):
            if before.kind != now.kind:
                continue
            matcher.set_seq1(before.tokens)
            # Both are upper bounds of ratio(): a pair below MATCH_RATIO on either is out.
            if matcher.real_quick_ratio() >= MATCH_RATIO and matcher.quick_ratio() >= MATCH_RATIO:
                ratio = matcher.ratio()
                if ratio >= MATCH_RATIO:
                    scores[o, n] = ratio
    return scores


def _pair_greedily(scores: dict[tuple[int, int], float]) -> dict[int, int]:
    """Take pairs from the highest ratio down, then the earlier old, then the earlier new item.

    Returns ``{old position: new position}``.
    """
    pairs, taken = {}, set()
    for (o, n), _ in sorted(scores.items(), key=lambda entry: (-entry[1], entry[0])):
        if o not in pairs and n not in taken:
            pairs[o] = n
            taken.add(n)
    return pairs


# --- Splits and merges -------------------------------------------------------------------------


class _Candidate(NamedTuple):
    """A split (one old paragraph, two new ones) or a merge (two old paragraphs, one new one)."""

    cover: float
    merge: bool            # False for a split
    old: tuple[int, ...]   # the old positions: one for a split, two (in order) for a merge
    new: tuple[int, ...]   # the new positions: two (in order) for a split, one for a merge

    def acceptance_order(self) -> tuple:
        """Return the sort key of acceptance: highest cover, splits first, then the positions."""
        return -self.cover, self.merge, self.old[0], self.new[0]


def _shared_tokens(counts: Counter, first: Counter, second: Counter) -> int:
    """Count the tokens of ``counts`` that ``first`` and ``second`` together also hold.

    A token counts as often as both sides hold it. This is the size of the Counter intersection of
    a text and the two texts joined, and the most that the matching blocks could match.
    """
    return sum(min(count, first.get(token, 0) + second.get(token, 0))
               for token, count in counts.items())


def _could_cover(whole: _Item, first: _Item, second: _Item) -> bool:
    """True unless ``first`` and ``second`` together cannot cover SPLIT_COVER of ``whole``.

    A cheap upper bound, tried before the matching itself.
    """
    if not whole.tokens:
        return False
    shared = _shared_tokens(whole.counts, first.counts, second.counts)
    return shared / len(whole.tokens) >= SPLIT_COVER


def _covered(matcher: SequenceMatcher, length: int) -> float:
    """Return the share of the matcher's first sequence, ``length`` tokens, that is matched."""
    return sum(block.size for block in matcher.get_matching_blocks()) / length


class _Judge:
    """Decides whether a split or merge candidate is valid, for one pair of versions."""

    def __init__(self, old: list[_Item], new: list[_Item], scores: dict[tuple[int, int], float]):
        self.old, self.new = old, new
        self._ratios = dict(scores)   # step 1 kept only the scores from MATCH_RATIO up

    def ratio(self, o: int, n: int) -> float:
        """Return the ratio of old item ``o`` and new item ``n``, worked out if step 1 left it."""
        if (o, n) not in self._ratios:
            self._ratios[o, n] = _ratio_of(self.old[o].tokens, self.new[n].tokens)
        return self._ratios[o, n]

    def split_cover(self, o: int, first: int, second: int) -> float | None:
        """Return the cover of splitting old ``o`` into new ``first`` and ``second``, or None.

        None means that the two are no valid split of the paragraph.
        """
        whole, parts = self.old[o], (self.new[first], self.new[second])
        if not _could_cover(whole, *parts):
            return None
        matcher = SequenceMatcher(None, whole.tokens, parts[0].tokens + parts[1].tokens,
                                  autojunk=False)
        cover = _covered(matcher, len(whole.tokens))
        if cover < SPLIT_COVER:
            return None
        better = matcher.ratio() > max(self.ratio(o, first), self.ratio(o, second))
        return cover if better else None

    def merge_cover(self, first: int, second: int, n: int) -> float | None:
        """Return the cover of merging old ``first`` and ``second`` into new ``n``, or None.

        None means that the two are no valid merge into the paragraph.
        """
        whole, parts = self.new[n], (self.old[first], self.old[second])
        if not _could_cover(whole, *parts):
            return None
        joined = parts[0].tokens + parts[1].tokens
        cover = _covered(SequenceMatcher(None, whole.tokens, joined, autojunk=False),
                         len(whole.tokens))
        if cover < SPLIT_COVER:
            return None
        better = _ratio_of(joined, whole.tokens) > max(self.ratio(first, n), self.ratio(second, n))
        return cover if better else None


def _neighbours(positions: list[int]) -> list[tuple[int, int]]:
    """Return the consecutive pairs of ``positions``."""
    return list(zip(positions, positions[1:]))


def _can_replace(partner: int | None, parts: tuple[int, int], paired: set[int]) -> bool:
    """True when ``parts`` can replace a paragraph whose partner is ``partner``.

    The partner must be one of the parts and the other part unpaired; a paragraph with no partner
    (None) takes two unpaired parts. ``paired`` holds the positions that step 2 paired.
    """
    return (set(parts) & paired) == (set() if partner is None else {partner})


def _candidates(old: list[_Item], new: list[_Item], pairs: dict[int, int],
                judge: _Judge) -> list[_Candidate]:
    """Return the valid split and merge candidates, judged against the pairs of step 2."""
    old_paragraphs = [o for o, item in enumerate(old) if item.kind == _PARAGRAPH]
    new_paragraphs = [n for n, item in enumerate(new) if item.kind == _PARAGRAPH]
    partner_of_new = {n: o for o, n in pairs.items()}
    paired_old, paired_new = set(pairs), set(partner_of_new)
    found = []
    for o in old_paragraphs:
        for first, second in _neighbours(new_paragraphs):
            if _can_replace(pairs.get(o), (first, second), paired_new):
                cover = judge.split_cover(o, first, second)
                if cover is not None:
                    found.append(_Candidate(cover, False, (o,), (first, second)))
    for n in new_paragraphs:
        for first, second in _neighbours(old_paragraphs):
            if _can_replace(partner_of_new.get(n), (first, second), paired_old):
                cover = judge.merge_cover(first, second, n)
                if cover is not None:
                    found.append(_Candidate(cover, True, (first, second), (n,)))
    return found


def _accept(candidates: list[_Candidate]) -> list[_Candidate]:
    """Accept the candidates in order, skipping one that shares a paragraph with one accepted."""
    accepted, used_old, used_new = [], set(), set()
    for candidate in sorted(candidates, key=_Candidate.acceptance_order):
        if used_old.intersection(candidate.old) or used_new.intersection(candidate.new):
            continue
        accepted.append(candidate)
        used_old.update(candidate.old)
        used_new.update(candidate.new)
    return accepted


# --- Moved -------------------------------------------------------------------------------------


def _on_longest_chain(new: list[int]) -> set[int]:
    """Return which anchors lie on the longest chain whose new positions rise in the old order.

    ``new[i]`` is the new position of the anchor that stands i-th in the old order. Among equally
    long chains the one with the earliest old positions is kept.
    """
    longest = [1] * len(new)                 # the longest rising chain that starts at anchor i
    for i in reversed(range(len(new))):
        for j in range(i + 1, len(new)):
            if new[j] > new[i]:
                longest[i] = max(longest[i], longest[j] + 1)
    kept, need, last = set(), max(longest, default=0), -1
    # The earliest anchor that still starts a chain of the length needed:
    for i in range(len(new)):
        if need and longest[i] == need and new[i] > last:
            kept.add(i)
            need, last = need - 1, new[i]
    return kept


def _moved_pairs(pairs: dict[int, int], accepted: list[_Candidate]) -> set[int]:
    """Return the old positions of the pairs that are off the longest chain of anchors.

    A pair stands at its two positions. A split stands at its old paragraph and its first part, and
    a merge at its first old paragraph and its new paragraph: the first position of each side.
    """
    anchors = sorted([(o, n, True) for o, n in pairs.items()]
                     + [(c.old[0], c.new[0], False) for c in accepted])
    kept = _on_longest_chain([n for _, n, _ in anchors])
    return {o for i, (o, _, is_pair) in enumerate(anchors) if is_pair and i not in kept}


# --- Matching ----------------------------------------------------------------------------------


def _ids(items: list[dict], positions: Sequence[int]) -> list[str]:
    """Return the ids of the items at ``positions``."""
    return [items[position]["id"] for position in positions]


def match_items(before: list[dict], now: list[dict]) -> dict:
    """Match the items of an earlier version, ``before``, with those of a later one, ``now``.

    Returns the dict of pairs, splits, merges, added and removed that the module docstring gives.
    """
    old, new = _items(before), _items(now)
    scores = _scores(old, new)
    pairs = _pair_greedily(scores)
    accepted = _accept(_candidates(old, new, pairs, _Judge(old, new, scores)))
    splits = sorted((c for c in accepted if not c.merge), key=lambda c: c.old[0])
    merges = sorted((c for c in accepted if c.merge), key=lambda c: c.new[0])
    # A split or merge takes over the pair of the paragraph it stands for; the other pairs stay.
    taken_old = {o for c in accepted for o in c.old}
    taken_new = {n for c in accepted for n in c.new}
    kept = {o: n for o, n in pairs.items() if o not in taken_old}
    moved = _moved_pairs(kept, accepted)
    matched_old, matched_new = taken_old | set(kept), taken_new | set(kept.values())
    return {
        "pairs": [{"old": before[o]["id"], "new": now[n]["id"], "ratio": round(scores[o, n], 2),
                   "edited": normalize(before[o]["text"]) != normalize(now[n]["text"]),
                   "moved": o in moved}
                  for o, n in sorted(kept.items(), key=lambda pair: pair[1])],
        "splits": [{"old": before[c.old[0]]["id"], "new": _ids(now, c.new),
                    "cover": round(c.cover, 2)} for c in splits],
        "merges": [{"old": _ids(before, c.old), "new": now[c.new[0]]["id"],
                    "cover": round(c.cover, 2)} for c in merges],
        "added": _ids(now, [n for n in range(len(now)) if n not in matched_new]),
        "removed": _ids(before, [o for o in range(len(before)) if o not in matched_old]),
    }


# --- Differences -------------------------------------------------------------------------------


def _counterparts(matched: dict) -> dict[str, list[str]]:
    """Return the new ids that each old id became, as ``{old id: [new id, ...]}``.

    An old id became its partner, the two parts of its split, or the paragraph it merged into. A
    removed id became nothing and is not a key.
    """
    found = {pair["old"]: [pair["new"]] for pair in matched["pairs"]}
    for split in matched["splits"]:
        found[split["old"]] = list(split["new"])
    for merge in matched["merges"]:
        for old in merge["old"]:
            found[old] = [merge["new"]]
    return found


def _lane_ids(version: dict) -> list[str]:
    """Return the ids of the lanes a built version lists, in its order."""
    return [lane["id"] for lane in version["lanes"]]


def _marks_changed(before: dict, now: dict, pairs: list[dict]) -> list[dict]:
    """Return the lanes gained and lost by each pair that marks other lanes than it did.

    Only the lanes that both versions list are compared. The result follows the order of ``pairs``.
    """
    old_lanes, new_lanes = _lane_ids(before), _lane_ids(now)
    shared = set(old_lanes) & set(new_lanes)
    old_marks = {item["id"]: item["lanes"] for item in before["paragraphs"]}
    new_marks = {item["id"]: item["lanes"] for item in now["paragraphs"]}
    changed = []
    for pair in pairs:
        marked_before, marked_now = old_marks[pair["old"]], new_marks[pair["new"]]
        gained = [lane for lane in new_lanes
                  if lane in shared and lane in marked_now and lane not in marked_before]
        lost = [lane for lane in old_lanes
                if lane in shared and lane in marked_before and lane not in marked_now]
        if gained or lost:
            changed.append({"old": pair["old"], "new": pair["new"],
                            "gained": gained, "lost": lost})
    return changed


def _quiet(version: dict) -> list[dict]:
    """Return the quiet observations of a built version, in their order."""
    return [entry for entry in version["computed"]["observations"] if entry["type"] == "quiet"]


def _continues(old: dict, new: dict, counterparts: dict[str, list[str]]) -> bool:
    """True when the new quiet observation ``new`` is the earlier one, ``old``, going on.

    They rest on the same lane, and each end of ``new`` is a counterpart of that end of ``old``.
    """
    return (old["lane"] == new["lane"]
            and new["from"] in counterparts.get(old["from"], ())
            and new["to"] in counterparts.get(old["to"], ()))


def _gaps_closed(before: dict, now: dict, counterparts: dict[str, list[str]]) -> list[dict]:
    """Return the earlier gaps that no gap of the new version names an item of.

    A gap goes on when a new gap names a counterpart of one of the items of its ``at``. A gap whose
    ``at`` is empty names no item that could be followed, so it is never closed: when in doubt, a
    gap still applies.
    """
    named = {item_id for gap in now["gaps"] for item_id in gap["at"]}
    closed = []
    for gap in before["gaps"]:
        became = {new for old in gap["at"] for new in counterparts.get(old, ())}
        if gap["at"] and not named & became:
            closed.append(gap)
    return closed


def compare_versions(before: dict, now: dict) -> dict:
    """Say what changed from the built version ``before`` to the built version ``now``.

    Both are an analysis plus ``computed``, as a vN.json holds it. Returns the dict of
    match_items() for their items with "marks", "lanes", "quiet_closed", "quiet_opened" and
    "gaps_closed", as the module docstring gives them. Neither argument is changed.
    """
    matched = match_items(before["paragraphs"], now["paragraphs"])
    counterparts = _counterparts(matched)
    old_lanes, new_lanes = _lane_ids(before), _lane_ids(now)
    quiet_before, quiet_now = _quiet(before), _quiet(now)
    return {
        **matched,
        "marks": _marks_changed(before, now, matched["pairs"]),
        "lanes": {"added": [lane for lane in new_lanes if lane not in old_lanes],
                  "removed": [lane for lane in old_lanes if lane not in new_lanes]},
        "quiet_closed": [old for old in quiet_before
                         if not any(_continues(old, new, counterparts) for new in quiet_now)],
        "quiet_opened": [new for new in quiet_now
                         if not any(_continues(old, new, counterparts) for old in quiet_before)],
        "gaps_closed": _gaps_closed(before, now, counterparts),
    }


# --- The changes line --------------------------------------------------------------------------

_DOT = "\N{MIDDLE DOT}"
_SHOWN = 6   # a list in the changes line names this many entries and counts the rest


def _listing(what: str, entries: list[str]) -> str:
    """Return ``{n} {what} ({entries})`` naming at most _SHOWN entries; "" when there are none."""
    if not entries:
        return ""
    more = f" and {len(entries) - _SHOWN} more" if len(entries) > _SHOWN else ""
    return f"{len(entries)} {what} ({', '.join(entries[:_SHOWN])}{more})"


def _tally(label: str, *sides: tuple[int, str]) -> str:
    """Return ``{label}: {n} {word}, ...`` for the sides that are not 0; "" when all are."""
    counted = ", ".join(f"{number} {word}" for number, word in sides if number)
    return f"{label}: {counted}" if counted else ""


def _threads_part(kind: str, ids: list[str], lanes: list[dict]) -> str:
    """Return ``{n} {kind} thread(s) ({labels})``: the lanes ``ids``, named by their labels."""
    labels = {lane["id"]: one_line(lane.get("label", lane["id"])) for lane in lanes}
    return _listing(f"{kind} thread" if len(ids) == 1 else f"{kind} threads",
                    [labels.get(lane_id, lane_id) for lane_id in ids])


def _gaps_part(count: int) -> str:
    """Return how many earlier gaps no longer apply; "" when none."""
    if count == 1:
        return "1 earlier gap no longer applies"
    return f"{count} earlier gaps no longer apply" if count else ""


def _paragraph_parts(compare: dict, earlier: str) -> list[str]:
    """Return the parts about paragraphs: edited, added, removed, split, merged and moved."""
    def old(item_id: str) -> str:
        return f"{earlier} {item_id}"

    pairs = compare["pairs"]
    splits = [f"{old(s['old'])} into {s['new'][0]} and {s['new'][1]}" for s in compare["splits"]]
    merges = [f"{old(m['old'][0])} and {old(m['old'][1])} into {m['new']}"
              for m in compare["merges"]]
    moves = [f"{old(p['old'])} to {p['new']}" for p in pairs if p["moved"]]
    return [
        _listing("edited", [pair["new"] for pair in pairs if pair["edited"]]),
        _listing("added", compare["added"]),
        _listing("removed", [old(item_id) for item_id in compare["removed"]]),
        _listing("split", splits),
        _listing("merged", merges),
        _listing("moved", moves),
    ]


def changes_line(data: dict) -> str:
    """Return the one line that says what changed from the earlier version to ``data``.

    ``data`` is a built version whose ``compare`` holds what compare_versions gives plus
    ``against``, the number K of the earlier version, and ``before``, the earlier version itself.
    The module docstring gives the form of the line.
    """
    compare = data["compare"]
    earlier = f"v{compare['against']}"
    marks = compare["marks"]
    parts = [
        *_paragraph_parts(compare, earlier),
        _tally("marks", (sum(len(mark["gained"]) for mark in marks), "gained"),
               (sum(len(mark["lost"]) for mark in marks), "lost")),
        _threads_part("new", compare["lanes"]["added"], data["lanes"]),
        _threads_part("dropped", compare["lanes"]["removed"], compare["before"]["lanes"]),
        _tally("quiet", (len(compare["quiet_closed"]), "closed"),
               (len(compare["quiet_opened"]), "opened")),
        _gaps_part(len(compare["gaps_closed"])),
    ]
    said = f" {_DOT} ".join(part for part in parts if part)
    return f"changes from {earlier}: {said or 'none'}"


# --- Reading a saved version -------------------------------------------------------------------

_LISTS = ("paragraphs", "lanes", "sections", "gaps")   # each a list of objects in a map
_ITEM_STRINGS = ("id", "kind", "text", "section", "role")


class CompareError(ValueError):
    """An earlier version cannot be compared with: it is not saved, or cannot be used.

    The message says which version and why.
    """


def _list_of_objects(value: object) -> bool:
    """True when ``value`` is a list that holds nothing but objects."""
    return isinstance(value, list) and all(isinstance(entry, dict) for entry in value)


def _flaw(data: object) -> str | None:
    """Say what keeps ``data`` from being a map that build wrote, or None when nothing does.

    Only what the module docstring lists is checked, and the first flaw in that order is named, by
    the path of the value at fault.
    """
    if not isinstance(data, dict):
        return "the top level is not an object"
    if data.get("schema") != SCHEMA:
        return f'schema is not "{SCHEMA}"'
    for key in _LISTS:
        if not _list_of_objects(data.get(key)):
            return f"{key} is not a list of objects"
    for number, item in enumerate(data["paragraphs"]):
        for key in _ITEM_STRINGS:
            if not isinstance(item.get(key), str):
                return f"paragraphs[{number}].{key} is not a string"
        if not isinstance(item.get("lanes"), dict):
            return f"paragraphs[{number}].lanes is not an object"
    for key in ("lanes", "sections"):
        for number, entry in enumerate(data[key]):
            if not isinstance(entry.get("id"), str):
                return f"{key}[{number}].id is not a string"
    for number, gap in enumerate(data["gaps"]):
        at = gap.get("at")
        if not (isinstance(at, list) and all(isinstance(item_id, str) for item_id in at)):
            return f"gaps[{number}].at is not a list of strings"
    return None


def load_version(out_dir: str, number: int) -> dict:
    """Read the saved version ``v{number}.json`` of the folder ``out_dir``, as the file holds it.

    Raises CompareError, with the message and reasons that the module docstring gives, when the
    file is missing, cannot be opened or is not JSON, or when what it holds is not a map that build
    wrote.
    """
    name = f"v{number}.json"
    try:
        data = read_json(os.path.join(out_dir, name))
    except FileNotFoundError:
        raise CompareError(f"{name} cannot be read: the file is missing") from None
    except OSError:
        raise CompareError(f"{name} cannot be read: the file cannot be opened") from None
    except ValueError:   # UnicodeDecodeError (not UTF-8 text) and json.JSONDecodeError
        raise CompareError(f"{name} cannot be read: it is not valid JSON") from None
    flaw = _flaw(data)
    if flaw is not None:
        raise CompareError(f"{name} cannot be read: it is not a map build wrote; {flaw}")
    return data


def uncompared_line(number: int, error: CompareError) -> str:
    """Return the changes line for a build that could not compare with the version ``number``."""
    return f"changes from v{number}: not compared ({error})"
