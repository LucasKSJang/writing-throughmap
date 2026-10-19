"""The Federalist No. 10 demo: two maps of one text, with English and with Korean labels.

Both maps must pass check against their own source.json, the source must hold Madison's whole
text from his opening sentence on, and each map comes with a PNG of its poster. The committed
pages must also be what build makes of the committed drafts today, so that a change to the
template or to build is followed by rebuilding the demo.
"""

import json
import os
import re
import shutil
import unittest

from tests.fixtures import tmp_dir
from tests.support import ROOT
from tm_build import build
from tm_check import check

EXAMPLES = ROOT / "examples"
DEMO_FOLDERS = ("federalist-10.throughmap", "federalist-10-ko.throughmap")
BUILT_FILES = ("v1.json", "index.html")
# The one value that differs between two builds of the same analysis: the time of the build.
_GENERATED_AT = re.compile(r'"generated_at": "[^"]*"')
_CONTEXT = 60


def masked(path) -> str:
    """Return the text of a built file with its build time blanked out."""
    with open(path, encoding="utf-8") as handle:
        return _GENERATED_AT.sub('"generated_at": ""', handle.read())


def first_difference(expected: str, found: str) -> str:
    """Say where two texts first differ, with a little of each around that place.

    A plain assertEqual would diff the page's one long line of JSON character by character, which
    is slow; this names the place and stops.
    """
    at = next((n for n, (a, b) in enumerate(zip(expected, found)) if a != b),
              min(len(expected), len(found)))
    start = max(0, at - _CONTEXT)
    return (f"first difference at character {at}: committed {expected[start:at + _CONTEXT]!r}, "
            f"fresh build {found[start:at + _CONTEXT]!r}")


class ExampleTests(unittest.TestCase):
    def test_examples_pass_check(self):
        for folder, lang in (("federalist-10.throughmap", "en"), ("federalist-10-ko.throughmap", "ko")):
            d = EXAMPLES / "federalist-10" / folder
            data = json.loads((d / "v1.json").read_text("utf-8"))
            src = json.loads((d / "source.json").read_text("utf-8"))
            self.assertEqual(check(data, src)["errors"], [])
            self.assertEqual(data["ui_language"], lang)

    def test_source_text_is_complete(self):
        src = json.loads((EXAMPLES / "federalist-10/federalist-10.throughmap/source.json").read_text("utf-8"))
        self.assertTrue(20 <= len(src["paragraphs"]) <= 30)
        self.assertTrue(src["paragraphs"][0]["text"].startswith("AMONG the numerous advantages"))

    def test_pngs_exist(self):
        for name in ("federalist-10-en.png", "federalist-10-ko.png"):
            data = (EXAMPLES / "federalist-10" / name).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG"))
            self.assertLess(len(data), 2_000_000)

    def test_examples_match_a_fresh_build(self):
        # Build each committed draft again in a temporary folder: the version and the page must
        # come out as committed, apart from the build time. Rebuild the demo when this fails.
        for folder in DEMO_FOLDERS:
            with self.subTest(folder=folder):
                committed = EXAMPLES / "federalist-10" / folder
                fresh = tmp_dir(folder)
                for name in ("source.json", "draft.json"):
                    shutil.copyfile(committed / name, os.path.join(fresh, name))
                self.assertEqual(build(os.path.join(fresh, "draft.json"))["version"], 1)
                for name in BUILT_FILES:
                    expected, found = masked(committed / name), masked(os.path.join(fresh, name))
                    if expected != found:
                        self.fail(f"{folder}/{name} differs from a fresh build: "
                                  f"{first_difference(expected, found)}")


if __name__ == "__main__":
    unittest.main()
