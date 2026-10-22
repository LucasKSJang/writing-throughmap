"""The drafts of the end-to-end runs, kept in tests/drafts/.

They are short synthetic texts written for the runs, with no real people in them: a memo, which
the skill maps, a revised memo, which the runs compare with it, and a narrative essay, which
stops at the skill's warning. Here extract must read them as the runs did.
"""

import json
import os
import unittest

from tests.fixtures import run_main, tmp_dir
from tests.support import ROOT
from tm_compare import match_items

DRAFTS = ROOT / "tests" / "drafts"


def extracted(name):
    """Run extract on a draft of tests/drafts/ into a temporary folder; return its source.json."""
    out = tmp_dir("out.throughmap")
    code, printed = run_main(["extract", str(DRAFTS / name), "--out", out])
    if code != 0:
        raise AssertionError(f"extract {name} exited {code}: {printed}")
    with open(os.path.join(out, "source.json"), encoding="utf-8") as handle:
        return json.load(handle)


class DraftTests(unittest.TestCase):
    def test_both_drafts_are_there(self):
        self.assertTrue((DRAFTS / "memo.md").is_file())
        self.assertTrue((DRAFTS / "narrative.md").is_file())

    def test_the_memo_is_six_paragraphs_under_its_title_with_its_header_lines_set_aside(self):
        source = extracted("memo.md")
        self.assertEqual(source["essay"]["title"],
                         "Replace the weekly status meeting with a written update")
        self.assertEqual(source["essay"]["paragraph_count"], 6)
        self.assertEqual(source["excluded"], [{"kind": "front", "text": "To: Product team leads"},
                                              {"kind": "front", "text": "From: Operations"},
                                              {"kind": "front", "text": "Date: 3 March"}])
        # Its one heading is its title, so it has no sections: the agent infers them.
        self.assertEqual(source["sections"], [])

    def test_the_narrative_is_seven_paragraphs(self):
        source = extracted("narrative.md")
        self.assertEqual(source["essay"]["title"], "The summer I worked at the lake")
        self.assertEqual(source["essay"]["paragraph_count"], 7)
        self.assertEqual(source["excluded"], [])

    def test_the_memo_revision_matches_as_written(self):
        paragraphs = lambda name: [{"id": p["id"], "kind": "paragraph", "text": p["text"]}
                                   for p in extracted(name)["paragraphs"]]
        m = match_items(paragraphs("memo.md"), paragraphs("memo-revised.md"))
        self.assertEqual([(p["old"], p["new"], p["edited"], p["moved"]) for p in m["pairs"]],
                         [("P1", "P1", True, False), ("P3", "P2", False, True), ("P4", "P5", False, False)])
        self.assertEqual([(s["old"], s["new"]) for s in m["splits"]], [("P2", ["P3", "P4"])])
        self.assertEqual([(g["old"], g["new"]) for g in m["merges"]], [(["P5", "P6"], "P6")])
        self.assertEqual((m["added"], m["removed"]), (["P7"], []))


if __name__ == "__main__":
    unittest.main()
