"""The English and Korean READMEs: install commands, privacy copy, prompts, structure and links.

Both READMEs must give every install command, the privacy statement and the three example prompts
exactly, share one heading structure, show one poster in their own language, link to each other on
their first line and point only at files that exist.
"""

import re
import unittest

from tests.support import ROOT

READMES = ("README.md", "README.ko.md")
INSTALLER_URL = "https://github.com/LucasKSJang/writing-throughmap/tree/main/skills/throughmap"
INSTALL = (
    "/plugin marketplace add LucasKSJang/writing-throughmap",
    "/plugin install writing-throughmap@writing-throughmap",
    "codex plugin marketplace add LucasKSJang/writing-throughmap",
    "$skill-installer install " + INSTALLER_URL,
    "npx skills add LucasKSJang/writing-throughmap",
)
PRIVACY = {
    "README.md": (
        "throughmap itself sends nothing off your computer.",
        "throughmap reads only the draft you give it and never changes it. Its output goes into one "
        "`<essay>.throughmap/` folder next to the draft. A PDF, pasted text or a Google Doc is first "
        "saved as one Markdown file, beside the PDF or in the current folder, and the folder goes "
        "next to that file.",
        "under your agent's own terms",
    ),
    "README.ko.md": (
        "throughmap 자체는 아무것도 컴퓨터 밖으로 보내지 않아요.",
        "throughmap은 지정한 초안만 읽고, 초안 자체는 고치지 않아요. 결과는 초안 옆의 "
        "`<글>.throughmap/` 폴더에 저장돼요. PDF, 붙여넣은 글, Google Docs는 먼저 텍스트를 마크다운 "
        "파일 하나로 저장한 뒤(PDF 옆이나 현재 폴더), 그 파일 옆에 폴더를 만들어요.",
        "에이전트의 약관에 따라",
    ),
}
PRIVACY_HEADINGS = {"README.md": "## Privacy", "README.ko.md": "## 개인정보"}
# What "Privacy" tells a writer who shares index.html rather than the PNG: the page holds the whole
# text of the draft, and after a revision the text of the version it was compared with as well.
SHARING = {
    "README.md": "`index.html` holds the full text of the draft, and after a revision, the text of "
                 "the version it is compared with as well. To share only the map, share the PNG.",
    "README.ko.md": "`index.html`에는 초안 전문이 들어 있고, 고친 뒤에는 비교한 이전 버전의 글도 "
                    "들어 있어요. 지도만 공유하려면 PNG를 공유하세요.",
}
PROMPTS = ("Map the structure of essay.docx.", "이 글 구조 지도 그려줘",
           "I revised it. Compare with the first draft.")
# The start of the paragraph that says what the page shows from the second version on, and of the
# Limits bullet about how the comparison pairs paragraphs.
COMPARISON = {
    "README.md": ("From the second version on, the page also shows what changed:",
                  "- The comparison matches paragraphs by their words."),
    "README.ko.md": ("두 번째 버전부터는 바뀐 점도 보여 줘요.", "- 비교는 문단의 단어로 짝을 지어요."),
}
# The route without Python saves no version and compares nothing, so the two places that describe
# it say so, each under its own heading: the Codex note on Windows' elevated sandbox, and the
# paragraph on the route in "How it works". Each is a heading and the sentence that ends there.
NO_PYTHON = {
    "README.md": (
        ("### Codex", "but a .docx cannot be read, so paste its text instead, and a revised draft "
                      "is not compared with the earlier one."),
        ("## How it works", "A .docx needs Python, so paste its text instead. Versions are not "
                            "saved either, so a revised draft is not compared with the earlier "
                            "one."),
    ),
    "README.ko.md": (
        ("### Codex", "글을 붙여넣어 주세요. 고친 초안도 이전 버전과 비교하지 않고 그려요."),
        ("## 작동 방식", "글을 붙여넣어 주세요. 버전도 저장되지 않아서, 고친 초안을 이전 버전과 "
                       "비교하지 못해요."),
    ),
}
HEADINGS = {
    "README.md": ["# writing-throughmap", "## What you get", "## Install", "### Claude Code",
                  "### Codex", "### Other agents", "## Use it", "## Privacy", "## How it works",
                  "## Limits", "## License"],
    "README.ko.md": ["# writing-throughmap", "## 결과물", "## 설치", "### Claude Code",
                     "### Codex", "### 다른 에이전트", "## 사용법", "## 개인정보", "## 작동 방식",
                     "## 한계", "## 라이선스"],
}
LIMITS = {"README.md": "## Limits", "README.ko.md": "## 한계"}
POSTER = {"README.md": "-en.png", "README.ko.md": "-ko.png"}
DASHES = (chr(0x2013), chr(0x2014))   # the en and em dash, as chr() so that no tool rewrites them


def read(name: str) -> str:
    return (ROOT / name).read_text("utf-8")


def part(name: str, heading: str) -> str:
    """Return the text under the line ``heading`` (such as "## Privacy") up to the next heading."""
    return read(name).split(heading + "\n", 1)[1].split("\n#", 1)[0]


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    return re.sub(r"`[^`\n]*`", "", text)


class ReadmeTests(unittest.TestCase):
    def test_the_python_floor_and_the_versions_tested(self):
        # The floor stays 3.9, but only 3.11 and 3.13 run the suite, so both READMEs say so.
        sentences = {
            "README.md": "The script needs Python 3.9 or newer (standard library only) and is "
                         "tested on 3.11 and 3.13.",
            "README.ko.md": "스크립트는 파이썬 3.9 이상에서 돌아가고 표준 라이브러리만 써요. "
                            "테스트는 3.11과 3.13에서 했어요.",
        }
        for name, sentence in sentences.items():
            self.assertIn(sentence, read(name), name)

    def test_word_counts_outside_code(self):
        for name in READMES:
            self.assertGreaterEqual(len(strip_code(read(name)).split()), 40, name)

    def test_install_and_privacy(self):
        for name in READMES:
            text = read(name)
            for cmd in INSTALL:
                self.assertIn(cmd, text, (name, cmd))
            for phrase in PRIVACY[name]:
                self.assertIn(phrase, text, (name, phrase))
            self.assertIn(SHARING[name], part(name, PRIVACY_HEADINGS[name]), name)

    def test_example_prompts(self):
        for name in READMES:
            text = read(name)
            for prompt in PROMPTS:
                self.assertIn(prompt, text, (name, prompt))
            third = [line for line in text.splitlines() if "I revised it." in line]
            self.assertEqual(len(third), 1, name)
            self.assertIn("v0.2", third[0], name)

    def test_the_comparison_is_described(self):
        for name, sentences in COMPARISON.items():
            for sentence in sentences:
                self.assertIn(sentence, read(name), name)
        self.assertNotIn("This one is coming in v0.2", read("README.md"))
        self.assertNotIn("v0.2에 들어갈 예정", read("README.ko.md"))
        for name, places in NO_PYTHON.items():
            for heading, sentence in places:
                self.assertIn(sentence, part(name, heading), (name, heading))

    def test_same_headings_in_both(self):
        for name, headings in HEADINGS.items():
            self.assertEqual(re.findall(r"^#+ .*$", strip_code(read(name)), re.M), headings, name)
        levels = [[heading.split()[0] for heading in HEADINGS[name]] for name in READMES]
        self.assertEqual(levels[0], levels[1])

    def test_limits_give_the_numbers(self):
        for name, heading in LIMITS.items():
            limits = read(name).split(heading + "\n", 1)[1].split("\n#", 1)[0]
            for number in ("40", "18"):
                self.assertRegex(limits, rf"(?<!\d){number}(?!\d)", (name, number))

    def test_no_dashes_or_emoji(self):
        for name in READMES:
            text = read(name)
            for dash in DASHES:
                self.assertNotIn(dash, text, name)
            emoji = [c for c in text if 0x2600 <= ord(c) <= 0x27BF or 0x1F000 <= ord(c) <= 0x1FAFF]
            self.assertEqual(emoji, [], name)

    def test_only_url_is_the_skill_installer(self):
        for name in READMES:
            self.assertEqual(re.findall(r"https?://[^\s)]+", read(name)), [INSTALLER_URL], name)

    def test_language_switch_on_first_line(self):
        for name, other in (("README.md", "README.ko.md"), ("README.ko.md", "README.md")):
            self.assertIn(f"]({other})", read(name).splitlines()[0], name)

    def test_one_poster_in_the_readers_language(self):
        for name, suffix in POSTER.items():
            images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", read(name))
            self.assertEqual(len(images), 1, name)
            self.assertTrue(images[0].endswith(suffix), (name, images[0]))

    def test_images_exist(self):
        for name in READMES:
            for rel in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", read(name)):
                self.assertTrue((ROOT / rel).exists(), rel)

    def test_relative_links_exist(self):
        for name in READMES:
            for rel in re.findall(r"\]\(([^)#\s]+)[^)]*\)", strip_code(read(name))):
                if not rel.startswith(("http://", "https://")):
                    self.assertTrue((ROOT / rel).exists(), (name, rel))


if __name__ == "__main__":
    unittest.main()
