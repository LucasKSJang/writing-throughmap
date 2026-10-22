"""Tests for tm_compare: tokens, the matching of two versions, and what changed between them."""

import copy
import json
import os
import time
import unittest
from difflib import SequenceMatcher
from pathlib import Path

from tests.fixtures import (KO_AFTER, KO_BEFORE, REVISION_CHANGES, SENTENCES, STUB_TEMPLATE_PATH,
                            built_version, items_of, para, revision, tmp_dir, version_of,
                            write_draft)
from tests.support import ROOT
from tm_build import build
from tm_check import check
from tm_compare import (CompareError, changes_line, compare_versions, load_version, match_items,
                        tokens)


def W(first, last, prefix="w"):                 # "w1 w2 ... w20": tokens with exactly known overlaps
    return " ".join(f"{prefix}{n}" for n in range(first, last + 1))


def moved(m):
    return [pair["old"] for pair in m["pairs"] if pair["moved"]]


class AccountingCase(unittest.TestCase):
    def match(self, old, new):
        """match_items, checked: every old and every new id is accounted for exactly once."""
        m = match_items(old, new)
        olds = ([p["old"] for p in m["pairs"]] + [s["old"] for s in m["splits"]]
                + [o for g in m["merges"] for o in g["old"]] + m["removed"])
        news = ([p["new"] for p in m["pairs"]] + [n for s in m["splits"] for n in s["new"]]
                + [g["new"] for g in m["merges"]] + m["added"])
        self.assertEqual(sorted(olds), sorted(item["id"] for item in old))
        self.assertEqual(sorted(news), sorted(item["id"] for item in new))
        return m


class TokenTests(unittest.TestCase):
    def test_tokens_are_the_words_and_marks_of_the_normalized_folded_text(self):
        self.assertEqual(tokens("\N{LEFT DOUBLE QUOTATION MARK}Rain,\N{RIGHT DOUBLE QUOTATION MARK} "
                                "she said\N{EM DASH}twice."),
                         ['"', "rain", ",", '"', "she", "said", "-", "twice", "."])
        self.assertEqual(tokens("빵은 천천히  굽는다."), ["빵은", "천천히", "굽는다", "."])


class MatchTests(AccountingCase):
    def test_identical_versions_pair_every_item_in_place(self):
        texts = (para(1, 2, 3), para(4, 5, 6), para(7, 8, 9))
        m = self.match(items_of(*texts), items_of(*texts))
        self.assertEqual(m["pairs"], [{"old": f"P{n}", "new": f"P{n}", "ratio": 1.0, "edited": False,
                                       "moved": False} for n in (1, 2, 3)])
        self.assertEqual((m["splits"], m["merges"], m["added"], m["removed"]), ([], [], [], []))

    def test_the_threshold_is_0_55(self):
        old = items_of(W(1, 20))
        self.assertEqual(self.match(old, items_of(W(1, 11) + " " + W(1, 9, "x")))["pairs"][0]["ratio"], 0.55)
        apart = self.match(old, items_of(W(1, 10) + " " + W(1, 10, "x")))             # 0.50
        self.assertEqual((apart["pairs"], apart["added"], apart["removed"]), ([], ["P1"], ["P1"]))

    def test_an_edited_paragraph_pairs_and_is_marked_edited(self):
        pair = self.match(items_of(para(1, 2, 3)), items_of(para(1, 2, 3, 25)))["pairs"][0]
        self.assertTrue(pair["edited"])
        self.assertTrue(0.55 <= pair["ratio"] < 1)
        curly = "He said \N{LEFT DOUBLE QUOTATION MARK}rain.\N{RIGHT DOUBLE QUOTATION MARK}"
        self.assertFalse(self.match(items_of('He said "rain."'), items_of(curly))["pairs"][0]["edited"])

    def test_pairs_are_taken_from_the_highest_ratio_down(self):
        # Old P1 scores 0.7 with new P1 and old P2 scores 0.9; both score 0.6 with new P2.
        old = items_of(W(1, 14) + " " + W(1, 6, "a"), W(1, 18) + " " + W(1, 2, "b"))
        new = items_of(W(1, 20), W(1, 12) + " " + W(1, 8, "y"))
        self.assertEqual([(p["old"], p["new"]) for p in self.match(old, new)["pairs"]],
                         [("P2", "P1"), ("P1", "P2")])

    def test_duplicate_paragraphs_pair_in_document_order(self):                    # Review Focus 3
        texts = (para(1, 2, 3), para(1, 2, 3), para(4, 5, 6))
        m = self.match(items_of(*texts), items_of(*texts))
        self.assertEqual([(p["old"], p["new"], p["moved"]) for p in m["pairs"]],
                         [("P1", "P1", False), ("P2", "P2", False), ("P3", "P3", False)])

    def test_look_alike_paragraphs_keep_their_own_partners(self):                  # Review Focus 3
        m = self.match(items_of(para(1, 2, 3), para(1, 2, 4)), items_of(para(1, 2, 4), para(1, 2, 3)))
        self.assertEqual([(p["old"], p["new"], p["ratio"]) for p in m["pairs"]],
                         [("P2", "P1", 1.0), ("P1", "P2", 1.0)])

    def test_a_split_paragraph_is_found(self):
        m = self.match(items_of(para(1, 2, 3, 4)), items_of(para(1, 2), para(3, 4)))
        self.assertEqual(m["splits"], [{"old": "P1", "new": ["P1", "P2"], "cover": 1.0}])
        self.assertEqual((m["pairs"], m["added"], m["removed"]), ([], [], []))

    def test_a_split_with_a_sentence_added_to_one_part_is_found(self):
        m = self.match(items_of(para(1, 2, 3, 4)), items_of(para(1, 2), para(3, 4, 20)))
        self.assertEqual([(s["old"], s["new"]) for s in m["splits"]], [("P1", ["P1", "P2"])])

    def test_an_unchanged_paragraph_and_a_new_neighbour_are_no_split(self):
        m = self.match(items_of(para(1, 2, 3)), items_of(para(1, 2, 3), para(20, 21, 22)))
        self.assertEqual((m["splits"], m["added"], m["pairs"][0]["ratio"]), ([], ["P2"], 1.0))

    def test_the_parts_of_a_split_must_be_neighbours(self):
        m = self.match(items_of(para(1, 2, 3, 4)), items_of(para(1, 2), para(20, 21, 22), para(3, 4)))
        self.assertEqual(m["splits"], [])
        self.assertEqual([p["old"] for p in m["pairs"]], ["P1"])
        self.assertEqual(len(m["added"]), 2)
        self.assertIn("P2", m["added"])

    def test_a_merge_is_a_split_in_reverse(self):
        m = self.match(items_of(para(1, 2), para(3, 4)), items_of(para(1, 2, 3, 4)))
        self.assertEqual(m["merges"], [{"old": ["P1", "P2"], "new": "P1", "cover": 1.0}])
        self.assertEqual((m["pairs"], m["added"], m["removed"]), ([], [], []))

    def test_a_table_between_the_parts_does_not_stop_a_split(self):
        new = items_of(para(1, 2), para(3, 4))
        new.insert(1, {"id": "T1", "kind": "table", "text": "Table 1: Sizes.\nA | B", "lanes": {}})
        m = self.match(items_of(para(1, 2, 3, 4)), new)
        self.assertEqual(([(s["old"], s["new"]) for s in m["splits"]], m["added"]),
                         ([("P1", ["P1", "P2"])], ["T1"]))

    def test_items_pair_only_with_items_of_their_kind(self):
        old = items_of(para(1, 2, 3)) + [{"id": "T1", "kind": "table", "text": para(4, 5, 6), "lanes": {}}]
        m = self.match(old, items_of(para(1, 2, 3), para(4, 5, 6)))
        self.assertEqual((m["removed"], m["added"]), (["T1"], ["P2"]))

    def test_a_table_pairs_with_a_table(self):
        # The other half of the test above: two tables pair, and a slight change to the text of
        # one makes the pair edited.
        table = lambda text: [{"id": "T1", "kind": "table", "text": text, "lanes": {}}]
        old = items_of(para(1, 2, 3)) + table("Table 1: Loaves baked\nDay | Loaves\nMon | 40\nTue | 35")
        new = items_of(para(1, 2, 3)) + table("Table 1: Loaves baked\nDay | Loaves\nMon | 40\nTue | 38")
        m = self.match(old, new)
        self.assertEqual([(p["old"], p["new"], p["edited"], p["moved"]) for p in m["pairs"]],
                         [("P1", "P1", False, False), ("T1", "T1", True, False)])
        self.assertTrue(0.55 <= m["pairs"][1]["ratio"] < 1)
        self.assertEqual((m["splits"], m["merges"], m["added"], m["removed"]), ([], [], [], []))

    def test_a_paragraph_moved_past_others_is_moved(self):
        a, b, c, d = para(1, 2, 3), para(4, 5, 6), para(7, 8, 9), para(10, 11, 12)
        self.assertEqual(moved(self.match(items_of(a, b, c, d), items_of(b, c, d, a))), ["P1"])

    def test_of_two_swapped_paragraphs_the_later_one_is_moved(self):
        a, b = para(1, 2, 3), para(4, 5, 6)
        self.assertEqual(moved(self.match(items_of(a, b), items_of(b, a))), ["P2"])

    def test_splits_and_merges_hold_their_place_in_the_order(self):
        # Old P2 is split, and old P3 moves up before its parts: old P3 is the one that moved.
        a, b, c = para(1, 2, 3), para(4, 5, 6, 7), para(8, 9, 10)
        m = self.match(items_of(a, b, c), items_of(a, c, para(4, 5), para(6, 7)))
        self.assertEqual((moved(m), [s["old"] for s in m["splits"]]), (["P3"], ["P2"]))

    def test_unrelated_versions_match_nothing(self):                               # Review Focus 4
        m = self.match(items_of(para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)),
                       items_of(para(20, 21, 22), para(23, 24, 25), para(26, 27, 28)))
        self.assertEqual((m["pairs"], m["splits"], m["merges"]), ([], [], []))
        self.assertEqual((m["removed"], m["added"]), (["P1", "P2", "P3"], ["P1", "P2", "P3"]))

    def test_a_korean_paragraph_with_changed_endings_still_matches(self):
        m = self.match(items_of(KO_BEFORE), items_of(KO_AFTER))
        self.assertEqual([(p["old"], p["new"], p["edited"]) for p in m["pairs"]], [("P1", "P1", True)])

    def test_forty_long_paragraphs_compare_in_seconds(self):
        # The worst case: the same words in another order, so nothing pairs and every split and
        # merge candidate is scanned. Measured: 2.8 seconds.
        fed = [p["text"] for p in json.loads((ROOT / "examples/federalist-10/federalist-10.throughmap/"
                                               "source.json").read_text("utf-8"))["paragraphs"]]
        old = [fed[n % 23] + " " + fed[(n + 7) % 23] for n in range(40)]
        start = time.perf_counter()
        m = self.match(items_of(*old), items_of(*(" ".join(reversed(t.split())) for t in old)))
        self.assertLess(time.perf_counter() - start, 30)
        self.assertEqual((len(m["pairs"]), len(m["added"]), len(m["removed"])), (0, 40, 40))

    def test_the_sentence_pool_holds_unrelated_sentences(self):
        groups = [para(n, n + 1, n + 2) for n in range(1, 31, 3)]
        for i, a in enumerate(groups):
            for b in groups[i + 1:]:
                self.assertLess(SequenceMatcher(None, tokens(a), tokens(b), autojunk=False).ratio(), 0.4)
        self.assertEqual(len(set(SENTENCES)), 30)
        self.assertTrue(all(12 <= len(sentence.split()) <= 15 for sentence in SENTENCES))

    def test_an_unchanged_paragraph_and_an_old_neighbour_are_no_merge(self):
        m = self.match(items_of(para(1, 2, 3), para(20, 21, 22)), items_of(para(1, 2, 3)))
        self.assertEqual((m["merges"], [(p["old"], p["new"]) for p in m["pairs"]], m["removed"]),
                         ([], [("P1", "P1")], ["P2"]))

    def test_a_cover_of_0_60_is_enough_and_less_is_not(self):
        split = self.match(items_of(W(1, 20)), items_of(W(1, 8), W(9, 12)))          # 12 of 20
        self.assertEqual(split["splits"], [{"old": "P1", "new": ["P1", "P2"], "cover": 0.6}])
        short = self.match(items_of(W(1, 20)), items_of(W(1, 8), W(9, 11)))          # 11 of 20
        self.assertEqual((short["splits"], [(p["old"], p["new"]) for p in short["pairs"]], short["added"]),
                         ([], [("P1", "P1")], ["P2"]))
        merge = self.match(items_of(W(1, 8), W(9, 12)), items_of(W(1, 20)))
        self.assertEqual(merge["merges"], [{"old": ["P1", "P2"], "new": "P1", "cover": 0.6}])
        short = self.match(items_of(W(1, 8), W(9, 11)), items_of(W(1, 20)))
        self.assertEqual((short["merges"], [(p["old"], p["new"]) for p in short["pairs"]], short["removed"]),
                         ([], [("P1", "P1")], ["P2"]))

    def test_of_two_valid_candidates_that_share_a_paragraph_the_higher_cover_wins(self):
        # Splitting old P1 into new P1 and P2 covers 0.75 of it; merging old P1 and P2 into new P2
        # covers all of new P2. Both are valid and share old P1 and new P2: the merge wins.
        old = items_of(W(1, 6, "a") + " " + W(1, 6, "b") + " " + W(1, 4, "r"), W(1, 6, "c") + " " + W(1, 4, "s"))
        new = items_of(W(1, 6, "a"), W(1, 6, "b") + " " + W(1, 6, "c"))
        m = self.match(old, new)
        self.assertEqual((m["merges"], m["splits"], m["pairs"], m["added"], m["removed"]),
                         ([{"old": ["P1", "P2"], "new": "P2", "cover": 1.0}], [], [], ["P1"], []))

    def test_ratios_and_covers_are_rounded_to_two_decimals(self):
        pair = self.match(items_of(W(1, 20)), items_of(W(1, 13) + " " + W(1, 6, "x")))["pairs"][0]
        self.assertEqual(pair["ratio"], 0.67)                                           # 26 / 39
        split = self.match(items_of(W(1, 16)), items_of(W(1, 8), W(9, 11)))["splits"][0]
        self.assertEqual(split["cover"], 0.69)                                          # 11 / 16

    def test_a_merge_holds_its_place_in_the_order(self):
        # Old P2 and P3 merge, and old P4 moves up before the merged paragraph: old P4 moved.
        a, b1, b2, c = para(1, 2, 3), para(4, 5), para(6, 7), para(8, 9, 10)
        m = self.match(items_of(a, b1, b2, c), items_of(a, c, para(4, 5, 6, 7)))
        self.assertEqual((moved(m), [(g["old"], g["new"]) for g in m["merges"]]), (["P4"], [(["P2", "P3"], "P3")]))

    def test_a_paragraph_that_already_has_a_partner_is_no_part_of_a_split_or_merge(self):
        for old, new in (((W(1, 10), W(1, 20)), (W(1, 10), W(11, 20))),
                         ((W(1, 10), W(11, 20)), (W(1, 10), W(1, 20)))):
            m = self.match(items_of(*old), items_of(*new))
            self.assertEqual(([(p["old"], p["new"], p["ratio"]) for p in m["pairs"]],
                              m["splits"], m["merges"]),
                             ([("P1", "P1", 1.0), ("P2", "P2", 0.67)], [], []))


def compared(first, second):
    """compare_versions of two (source, analysis) pairs, built as v1 and v2."""
    return compare_versions(built_version(first[1], 1), built_version(second[1], 2))


class VersionFixtureTests(unittest.TestCase):
    def test_a_version_of_a_draft_passes_check(self):
        texts = [para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)]
        pairs = [*revision(), *revision("ko"),
                 version_of(texts, {"q1": [1], "a": [2], "b": [3]}, gaps=[([2, 3], "Gap one.")])]
        for source, analysis in pairs:
            self.assertEqual(check(analysis, source)["errors"], [])
            self.assertEqual(source["sections"], [])


class DifferenceTests(unittest.TestCase):
    def setUp(self):
        self.first, self.second = revision()
        self.c = compared(self.first, self.second)

    def test_the_revision_matches_as_the_table_says(self):
        self.assertEqual([(p["old"], p["new"], p["edited"], p["moved"]) for p in self.c["pairs"]],
                         [("P1", "P1", False, False), ("P4", "P4", False, False),
                          ("P7", "P6", False, False), ("P3", "P7", True, True)])
        self.assertEqual([(s["old"], s["new"]) for s in self.c["splits"]], [("P2", ["P2", "P3"])])
        self.assertEqual([(m["old"], m["new"]) for m in self.c["merges"]], [(["P5", "P6"], "P5")])
        self.assertEqual((self.c["added"], self.c["removed"]), (["P8"], ["P8"]))

    def test_marks_gained_and_lost_on_pairs(self):
        self.assertEqual(self.c["marks"], [
            {"old": "P4", "new": "P4", "gained": [], "lost": ["own"]},
            {"old": "P7", "new": "P6", "gained": ["q1"], "lost": []},
            {"old": "P3", "new": "P7", "gained": ["q1"], "lost": ["pace"]}])

    def test_threads_added_and_dropped(self):
        self.assertEqual(self.c["lanes"], {"added": ["cost"], "removed": ["gone"]})

    def test_a_renamed_thread_is_dropped_and_new_not_marks_lost(self):           # Review Focus 2
        texts = [para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)]
        c = compared(version_of(texts, {"q1": [1, 2], "own": [3]}),
                     version_of(texts, {"q1": [1, 2], "rest": [3]}))
        self.assertEqual((c["lanes"], c["marks"]), ({"added": ["rest"], "removed": ["own"]}, []))

    def test_quiet_stretches_closed_and_opened(self):
        self.assertEqual(self.c["quiet_closed"],
                         [{"type": "quiet", "lane": "q1", "from": "P1", "to": "P8", "length": 6}])
        self.assertEqual(self.c["quiet_opened"],
                         [{"type": "quiet", "lane": "pace", "from": "P1", "to": "P8", "length": 6}])

    def test_a_quiet_stretch_that_holds_is_not_reported(self):
        # The same rest, before and after a paragraph is added between its two ends.
        texts = [para(n, n + 1, n + 2) for n in range(1, 25, 3)]                 # 8 paragraphs
        c = compared(version_of(texts, {"q1": [1, 8]}),
                     version_of(texts[:4] + [para(25, 26, 27)] + texts[4:], {"q1": [1, 9]}))
        self.assertEqual((c["quiet_closed"], c["quiet_opened"]), ([], []))

    def test_an_earlier_gap_no_longer_applies_when_no_gap_carries_its_items(self):
        self.assertEqual([gap["at"] for gap in self.c["gaps_closed"]], [["P8"]])   # the P3 gap moved to P7

    def test_a_gap_that_names_no_item_is_never_closed(self):
        texts = [para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)]
        c = compared(version_of(texts, {"q1": [1]}, gaps=[([], "Names no item.")]),
                     version_of(texts, {"q1": [1]}))
        self.assertEqual(c["gaps_closed"], [])

    def test_a_gap_goes_on_through_a_split_and_a_merge(self):
        def texts(pair):
            return [item["text"] for item in pair[1]["paragraphs"]]
        c = compared(version_of(texts(self.first), {"q1": [1]},
                                gaps=[([2], "split"), ([6], "merged"), ([8], "gone")]),
                     version_of(texts(self.second), {"q1": [1]}, gaps=[([3], "p3"), ([5], "p5")]))
        self.assertEqual([gap["note"] for gap in c["gaps_closed"]], ["gone"])


class ChangesLineTests(unittest.TestCase):
    def data(self, first, second):
        """v2 as build will hold it: the analysis, computed, and compare with against and before."""
        before, now = built_version(first[1], 1), built_version(second[1], 2)
        return {**now, "compare": {"against": 1, "before": before, **compare_versions(before, now)}}

    def test_the_revision_line(self):
        self.assertEqual(changes_line(self.data(*revision())), REVISION_CHANGES)

    def test_no_change_is_none(self):
        first, _ = revision()
        self.assertEqual(changes_line(self.data(first, first)), "changes from v1: none")

    def test_counts_are_singular_and_plural(self):
        texts = [para(1, 2, 3), para(4, 5, 6), para(7, 8, 9)]
        first = version_of(texts, {"q1": [1], "a": [2], "b": [3]},
                           gaps=[([2], "Gap one."), ([3], "Gap two.")])
        self.assertEqual(changes_line(self.data(first, version_of(texts, {"q1": [1, 2, 3]}))),
                         "changes from v1: marks: 2 gained · 2 dropped threads (A, B) · "
                         "2 earlier gaps no longer apply")

    def test_long_lists_are_cut_after_six(self):
        first = version_of([para(1, 2, 3)], {"q1": [1]})
        second = version_of([para(1, 2, 3)] + [para(n, n + 1, n + 2) for n in range(4, 28, 3)], {"q1": [1]})
        self.assertIn("8 added (P2, P3, P4, P5, P6, P7 and 2 more)", changes_line(self.data(first, second)))


class LoadVersionTests(unittest.TestCase):
    def test_a_version_build_wrote_loads_as_it_is(self):
        result = build(write_draft(*revision()[0]), STUB_TEMPLATE_PATH)
        self.assertEqual(load_version(os.path.dirname(result["json_path"]), 1),
                         json.loads(Path(result["json_path"]).read_text("utf-8")))

    def test_reasons_a_version_cannot_be_read(self):
        folder = tmp_dir("x.throughmap")
        with self.assertRaisesRegex(CompareError, r"^v3\.json cannot be read: the file is missing$"):
            load_version(folder, 3)
        for text, reason in (("{not json", "it is not valid JSON"),
                             ('{"schema": "throughmap/1", "paragraphs": "x"}', "it is not a map build wrote")):
            Path(folder, "v1.json").write_text(text, "utf-8")
            with self.assertRaisesRegex(CompareError, rf"^v1\.json cannot be read: {reason}"):
                load_version(folder, 1)

    def test_other_ways_a_version_cannot_be_read(self):
        folder = tmp_dir("x.throughmap")
        Path(folder, "v1.json").write_text('{"schema": "throughmap/1"}', "utf-16")   # not UTF-8
        with self.assertRaisesRegex(CompareError,
                                    r"^v1\.json cannot be read: it is not valid JSON$"):
            load_version(folder, 1)
        os.mkdir(os.path.join(folder, "v2.json"))             # a folder cannot be read as a file
        with self.assertRaisesRegex(CompareError,
                                    r"^v2\.json cannot be read: the file cannot be opened$"):
            load_version(folder, 2)

    def test_a_map_that_is_not_one_build_wrote_says_what_is_wrong(self):
        base = json.loads(Path(build(write_draft(*revision()[0]), STUB_TEMPLATE_PATH)["json_path"])
                          .read_text("utf-8"))
        cases = (
            (lambda d: d.update(schema="throughmap/2"), 'schema is not "throughmap/1"'),
            (lambda d: d.pop("paragraphs"), "paragraphs is not a list of objects"),
            (lambda d: d.update(lanes=["q1"]), "lanes is not a list of objects"),
            (lambda d: d.update(sections={}), "sections is not a list of objects"),
            (lambda d: d.update(gaps=None), "gaps is not a list of objects"),
            (lambda d: d["paragraphs"][2].pop("text"), "paragraphs[2].text is not a string"),
            (lambda d: d["paragraphs"][0].update(role=3), "paragraphs[0].role is not a string"),
            (lambda d: d["paragraphs"][1].update(lanes=[]), "paragraphs[1].lanes is not an object"),
            (lambda d: d["lanes"][1].update(id=3), "lanes[1].id is not a string"),
            (lambda d: d["sections"][0].pop("id"), "sections[0].id is not a string"),
            (lambda d: d["gaps"][1].update(at="P8"), "gaps[1].at is not a list of strings"),
            (lambda d: d["gaps"][0].update(at=[["P3"]]), "gaps[0].at is not a list of strings"),
        )
        folder = tmp_dir("x.throughmap")
        for mutate, detail in cases:
            data = copy.deepcopy(base)
            mutate(data)
            Path(folder, "v1.json").write_text(json.dumps(data), "utf-8")
            with self.subTest(detail):
                with self.assertRaises(CompareError) as raised:
                    load_version(folder, 1)
                self.assertEqual(str(raised.exception),
                                 f"v1.json cannot be read: it is not a map build wrote; {detail}")
        Path(folder, "v1.json").write_text("[1, 2]", "utf-8")
        with self.assertRaisesRegex(CompareError, "; the top level is not an object$"):
            load_version(folder, 1)
        Path(folder, "v1.json").write_text(json.dumps(base), "utf-8")      # the unchanged map loads
        self.assertEqual(load_version(folder, 1), base)


if __name__ == "__main__":
    unittest.main()
