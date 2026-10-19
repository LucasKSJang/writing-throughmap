"""SKILL.md and its references, held up against the code they describe.

The role keys must be tm_check.ROLES, the schema example must be what extract, check and build
make of its draft, the extract options must be the ones the command line offers, and the page
strings must be the template's own table.
"""

import os
import re
import unittest
from pathlib import Path

import throughmap
import tm_build
from tests.fixtures import FORTY_FIVE, run_main, tmp_dir
from tests.support import ROOT, frontmatter, json_blocks
from tm_build import DEFAULT_TEMPLATE, PLACEHOLDER, render_html
from tm_check import LIMITS, ROLES, check
from tm_text import normalize, quoted_segments, sentence_count

SKILL_DIR = ROOT / "skills" / "throughmap"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFS = SKILL_DIR / "references"
BACKSLASH = chr(92)   # written as chr() so that no tool turns an escape into its character
HANGUL = re.compile(f"[{chr(0xAC00)}-{chr(0xD7A3)}]")   # the Hangul syllables
# The private article's subject words, one per line, kept out of every tracked file.
PRIVATE_TERMS = ROOT / "tests" / "private" / "subject-terms.txt"

SECTIONS = ("What it produces", "When to use it, and when not to", "Running the script",
            "Procedure", "Writing the analysis", "Gaps and directions", "Guardrails",
            "Troubleshooting")
RUN = 'python3 "<skill-dir>/scripts/throughmap.py" '
COMMAND_LINES = (
    'extract "<draft path>"',
    'extract "<draft path>" --join P4,P5 --split P7 "However," --drop P30',
    'extract "<draft path>" --section "<section title or number>"',
    'check "<out>/draft.json"',
    'build "<out>/draft.json"',
    'versions "<out>"',
)


def section(path, heading):
    """Return the text under ``heading``, a whole line such as "## Guardrails", in a Markdown file.

    The text runs to the next heading of the same level or a higher one.
    """
    lines = Path(path).read_text("utf-8").splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = lines.index(heading) + 1
    end = next((n for n in range(start, len(lines)) if re.match(f"#{{1,{level}}} ", lines[n])),
               len(lines))
    return "\n".join(lines[start:end])


def bullet(text, lead):
    """Return the list item of ``text`` that starts with ``lead``, nested lines included.

    The item runs to the next line that starts at the margin, other than a blank one.
    """
    lines = text.splitlines()
    start = next((n for n, line in enumerate(lines) if line.startswith(lead)), None)
    if start is None:
        raise ValueError(f"no line starts with {lead!r}")
    end = next((n for n in range(start + 1, len(lines))
                if lines[n] and not lines[n].startswith(" ")), len(lines))
    return "\n".join(lines[start:end]).rstrip()


def words(text):
    """Return the words of ``text`` in lower case."""
    return re.findall(r"[a-z]+", text.lower())


def errors_as_a_direction(direction):
    """Return the errors check() finds when ``direction`` is the gap's in schema.md's example."""
    blocks = json_blocks(REFS / "schema.md")
    blocks["draft.json"]["gaps"][0]["direction"] = direction
    return check(blocks["draft.json"], blocks["source.json"])["errors"]


def schema_example() -> str:
    """Return schema.md's worked example, from its heading to the end of the file.

    section() cannot cut it out, since the Markdown draft it shows holds headings of its own.
    """
    schema = (REFS / "schema.md").read_text("utf-8")
    return schema[schema.index("\n## Example\n") + 1:]


def analysis_examples() -> list:
    """Return the texts an agent learns the analysis from, as (name, text) pairs."""
    return [(path.name, path.read_text("utf-8"))
            for path in (SKILL_MD, REFS / "roles.md", REFS / "gaps.md")] + [
        ("schema.md's worked example", schema_example())]


class SkillTests(unittest.TestCase):
    def test_frontmatter_keys_and_name(self):
        fm = frontmatter(SKILL_MD)
        self.assertLessEqual(set(fm), {"name", "description", "license", "metadata"})
        self.assertEqual(fm["name"], "throughmap")
        self.assertEqual(SKILL_MD.parent.name, "throughmap")

    def test_description_length_and_early_trigger(self):
        d = frontmatter(SKILL_MD)["description"]
        self.assertLess(len(d), 1024)
        self.assertIn("essay", d[:200].lower())
        self.assertIn("map", d[:200].lower())

    def test_no_claude_variables(self):
        for f in (ROOT / "skills").rglob("*"):
            if f.is_file():
                self.assertNotIn("${CLAUDE_", f.read_text("utf-8", errors="ignore"), f)

    def test_referenced_files_exist(self):
        text = SKILL_MD.read_text("utf-8")
        for rel in re.findall(r"(?:references|scripts|assets)/[\w.-]+\.(?:md|py|html)", text):
            self.assertTrue((SKILL_MD.parent / rel).exists(), rel)

    def test_commands_and_options_documented(self):
        text = SKILL_MD.read_text("utf-8")
        for word in ("extract", "check", "build", "versions", "--join", "--split", "--drop",
                     "--section"):
            self.assertIn(word, text)

    def test_roles_reference_matches_code(self):
        keys = re.findall(r"^\|\s*`(\w+)`", (REFS / "roles.md").read_text("utf-8"), re.M)
        self.assertEqual(tuple(keys), ROLES)

    def test_schema_example_passes_check(self):
        blocks = json_blocks(REFS / "schema.md")
        result = check(blocks["draft.json"], blocks["source.json"])
        self.assertEqual(result["errors"], [])


class SkillFollowsTheCodeTests(unittest.TestCase):
    def test_sections_in_order(self):
        headings = re.findall(r"^## (.+)$", SKILL_MD.read_text("utf-8"), re.M)
        self.assertEqual(tuple(headings), SECTIONS)

    def test_command_lines_given_in_full(self):
        text = SKILL_MD.read_text("utf-8")
        for line in COMMAND_LINES:
            self.assertIn(RUN + line + "\n", text)

    def test_every_extract_option_documented(self):
        code, usage = run_main(["extract", "--help"])
        self.assertEqual(code, 0)
        options = set(re.findall(r"--[a-z][a-z-]*", usage)) - {"--help"}
        self.assertGreaterEqual(options, {"--name", "--out", "--keep-short", "--section"})
        text = SKILL_MD.read_text("utf-8")
        for option in sorted(options):
            self.assertIn(option, text)

    def test_reruns_repeat_every_option_but_the_corrections(self):
        # Each run of extract starts again from the draft, and source.json does not record the
        # options, so both places that send the agent back to extract name every option to give
        # again. Without --out, a run for a section in its own folder writes over another map.
        code, usage = run_main(["extract", "--help"])
        self.assertEqual(code, 0)
        not_repeated = {"--help", "--join", "--split", "--drop"}
        repeated = sorted(set(re.findall(r"--[a-z][a-z-]*", usage)) - not_repeated)
        self.assertIn("--out", repeated)
        text = SKILL_MD.read_text("utf-8")
        for opening in ("give every flag each time", "When the user revises the draft"):
            sentence = re.search(re.escape(opening) + r".*?\.(?=\s|$)", text, re.M)
            self.assertIsNotNone(sentence, opening)
            for option in repeated:
                self.assertIn(f"`{option}`", sentence.group(), opening)

    def test_no_python_route_escapes_as_build_does(self):
        # A page filled in by hand must neither end its data early ("</") nor open a comment
        # that swallows the rest of the page ("<!--"), so SKILL.md gives the escapes that
        # render_html itself writes: each marker as a JSON string, embedded, quotes removed.
        written = {marker: render_html(marker, PLACEHOLDER)[1:-1] for marker in ("</", "<!--")}
        self.assertEqual(written, {"</": "<" + BACKSLASH + "/",
                                   "<!--": "<" + BACKSLASH + "u0021--"})
        text = SKILL_MD.read_text("utf-8")
        self.assertIn(PLACEHOLDER, text)
        for marker, escape in written.items():
            self.assertIn(f"every `{marker}` as `{escape}`", text)
        for doc in (SKILL_MD, *sorted(REFS.glob("*.md"))):
            self.assertNotIn(BACKSLASH + "u003c", doc.read_text("utf-8"), doc)   # the other form

    def test_schema_lists_every_page_string(self):
        template = Path(DEFAULT_TEMPLATE).read_text("utf-8")
        english = template[template.index("    en: {"):template.index("    ko: {")]
        keys = re.findall(r'^\s+"?([\w.]+)"?:\s+"', english, re.M)   # key: "text",
        self.assertIn("poster_legend", keys)
        self.assertIn("no_data", keys)
        schema = (REFS / "schema.md").read_text("utf-8")
        for key in keys:
            self.assertIn(f"| `{key}` |", schema)

    def test_schema_example_is_what_the_cli_makes_of_its_draft(self):
        # The worked example pastes what extract writes and what check and build print for its
        # draft. When this fails, run the three again on the draft and paste their output anew.
        example = schema_example()
        blocks = re.findall(r"^```(\w*)\n(.*?)\n```$", example, re.M | re.S)
        self.assertEqual([kind for kind, _ in blocks], ["markdown", "json", "json", "", ""])
        draft, source, analysis, checked, built = (text for _, text in blocks)
        name = re.search(r"^The draft `([^`]+)`:$", example, re.M).group(1)
        folder = tmp_dir("example")
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(draft + "\n")
        self.assertEqual(run_main(["extract", path])[0], 0)
        out = os.path.join(folder, os.path.splitext(name)[0] + ".throughmap")
        with open(os.path.join(out, tm_build.SOURCE_FILE), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), source + "\n")
        draft_json = os.path.join(out, tm_build.DRAFT_FILE)
        with open(draft_json, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(analysis + "\n")
        self.assertEqual(run_main(["check", draft_json]), (0, checked + "\n"))
        code, summary = run_main(["build", draft_json])
        self.assertEqual(code, 0)
        page = os.path.join(os.path.dirname(os.path.abspath(draft_json)), tm_build.PAGE_FILE)
        self.assertIn(page, summary)
        self.assertEqual(summary.replace(page, f"<out>/{tm_build.PAGE_FILE}"), built + "\n")

    def test_out_holds_only_the_maps_own_files(self):
        # build names any other file it finds in <out>, such as a helper script an agent left
        # there. The skill writes nowhere else but the <slug>.md copy, so the guardrails say
        # that a helper is deleted before the end, leaving the files build counts as the map's
        # own, and step 6 shows the line build prints about the others.
        guardrails = section(SKILL_MD, "## Guardrails")
        own = (f"`{tm_build.SOURCE_FILE}`, `{tm_build.DRAFT_FILE}`, the `vN.json` files and "
               f"`{tm_build.PAGE_FILE}`")
        self.assertIn("Write only the `<slug>.md` copy of step 1 and the files inside `<out>`.",
                      guardrails)
        self.assertIn("A helper script you write must be deleted before you finish, so that "
                      f"`<out>` ends holding only {own}.", guardrails)
        self.assertNotIn("elsewhere", guardrails)
        line = tm_build.other_files_line("<out>", ["assemble.py"])
        self.assertEqual(line, "also in <out>: assemble.py (remove it if you created it)")
        procedure = section(SKILL_MD, "## Procedure")
        self.assertIn(f"`{line}`", procedure)
        self.assertIn("Delete the ones you wrote, and tell the user about the rest.", procedure)

    def test_the_page_is_opened_with_the_command_of_the_shell(self):
        # Git for Windows' start runs cmd's start, which takes a first quoted argument as the
        # window title: start "<path>" opens an empty console and no page. So each shell gets
        # its own form, and the agent still asks first.
        procedure = section(SKILL_MD, "## Procedure")
        forms = (("PowerShell", 'Start-Process "<path>"'), ("cmd or Git Bash", 'start "" "<path>"'),
                 ("macOS", 'open "<path>"'), ("Linux", 'xdg-open "<path>"'))
        for shell, command in forms:
            self.assertIn(f"| {shell} | `{command}` |", procedure)
        self.assertIn("ask before opening it", procedure)
        self.assertNotIn('`start "<path>"`', SKILL_MD.read_text("utf-8"))

    def test_the_over_limit_lines_are_quoted_as_extract_prints_them(self):
        # Step 2 quotes the line extract prints over 40 paragraphs, with section headings and
        # without, so that the agent can tell which one it has read.
        procedure = section(SKILL_MD, "## Procedure")
        listed = throughmap._over_limit_advice(FORTY_FIVE)[0]
        headless = throughmap._over_limit_advice(dict(FORTY_FIVE, sections=[]))[0]
        self.assertIn(f"`{listed}` comes with a list", procedure)
        self.assertIn(f"`{headless.split(':')[0]}`:", procedure)


class RulesFromTheRunsTests(unittest.TestCase):
    """Rules that the end-to-end runs showed agents need, stated where an agent reads them.

    Each test pins the sentences that carry a rule, so that rewording the text keeps the rule.
    """

    def test_announced_lists_are_compared_before_any_other_gap(self):
        # No run compared the lists a draft announces with the ones it works through, although
        # Federalist No. 10 names "one of two only" and later three advantages.
        for path, heading in ((SKILL_MD, "## Gaps and directions"),
                              (REFS / "gaps.md", "## Gaps to look for")):
            with self.subTest(path.name):
                text = section(path, heading)
                self.assertIn("before any other gap", text.lower())
                self.assertIn("every count or list", text)
                self.assertIn("its restatements in the conclusion included", text)
                self.assertIn("compare each with the paragraphs that carry it out", text)

    def test_no_summary_drops_a_caveat_and_a_caveat_never_takes_the_main_move(self):
        # Two maps' last section conclusions dropped a proviso, and elsewhere a caveat or a side
        # point took the place of the paragraph's main move.
        guardrails = section(SKILL_MD, "## Guardrails")
        self.assertIn("The one hard line: a label, a section conclusion, a baton or the thesis "
                      "never reverses or drops an explicit caveat that changes the meaning.",
                      guardrails)
        self.assertIn("A paragraph saying that crashes fell on streets that got bike lanes and a "
                      'lower speed limit, but that the study "cannot tell which change did it", '
                      'cannot be labelled "Bike lanes cut crashes".', guardrails)
        self.assertIn("A label carries the paragraph's main move. A caveat sits beside it, as in "
                      '"Fewer crashes, cause unclear", never in its place.', guardrails)
        # The right label fits the length of a label, and it is not of the "X, not Y" form, which
        # the runs copied from the earlier example as a template.
        right = re.search(r'A caveat sits beside it, as in "([^"]+)"', guardrails).group(1)
        self.assertLessEqual(len(right), LIMITS["label"])
        self.assertNotIn(", not ", right)

    def test_no_wording_makes_a_claim_firmer_than_the_draft(self):
        # "Only" turned up in three of six theses: strong verbs "such as 'proves' or 'only'" were
        # read as leave to turn a possibility, a graded test or an assumption into a necessary
        # condition. The rule that followed listed the strong words, and the next runs kept clear
        # of them but hardened with ordinary words: a smaller share became none, a possibility a
        # certainty, an announced plan a thing done. So the rule bans the move, whatever the words.
        rule = bullet(section(SKILL_MD, "## Guardrails"), "- A label, a section conclusion, a "
                                                           "baton or the thesis may paraphrase")
        ban = ("no wording may turn a possibility, a tendency, a plan or one option among several "
               "into a certainty or the only option, or less of something into none of it.")
        for sentence in (
                "A label, a section conclusion, a baton or the thesis may paraphrase freely, but "
                "never more strongly than the paragraphs it covers.",
                "The rule bans a move, not a list of words: " + ban,
                "Read what you wrote back against those paragraphs and ask of every verb and every "
                "negation whether the draft says that much.",
                "Labels harden most often, because they are the shortest: when a paragraph reports "
                'a plan, a possibility or a tendency, its label keeps that word ("announced", '
                '"can", "tends to") even where a firmer one would be shorter.',
                'A strong verb such as "proves" or "shows" is fine when those paragraphs argue '
                "that strongly.",
                "A test the draft calls sufficient, or one condition among several, is not a "
                "necessary condition."):
            self.assertIn(sentence, rule)
        self.assertNotIn("own exclusivity", rule)   # the strong words are no longer the rule
        # The examples make each move that the ban names with an ordinary word, which drops the
        # draft's hedge, and keep the same point in a label that fits and holds a hedge.
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in rule.splitlines() if line.strip().startswith("|")]
        self.assertEqual(rows[0], ["Move", "The draft says", "Hardened", "Kept"])
        examples = rows[2:]
        self.assertEqual(len(examples), 5)
        self.assertEqual(len({move for move, *_ in examples}), 5)
        strong = {"only", "must", "always", "never", "all", "every", "necessary"}
        hedges = {"can", "may", "might", "would", "tends", "tended", "plans", "announced", "or",
                  "less", "fewer"}
        for move, says, hardened, kept in examples:
            with self.subTest(move):
                self.assertIn(move.lower(), ban)
                self.assertTrue(re.search(r'"[^"]+"', says), says)
                self.assertEqual(set(words(hardened)) & (strong | hedges), set())
                self.assertTrue(set(words(kept)) & hedges, kept)
                self.assertLessEqual(len(kept), LIMITS["label"])
        # Labels hardened a reported plan even with the table in view, so the words that a label
        # keeps are named, and each of them is a hedge.
        labels = re.search(r"its label keeps that word \(([^)]+)\)", rule).group(1)
        kept_words = re.findall(r'"([^"]+)"', labels)
        self.assertEqual(len(kept_words), 3)
        for word in kept_words:
            self.assertTrue(set(words(word)) & hedges, word)

    def test_a_caveat_pass_lists_hedges_conditions_and_alternatives(self):
        # Theses and section conclusions dropped a "may", a "can" or an "or" from the paragraphs
        # they summed up, so the analysis takes stock of those words first, as the gaps take
        # stock of the announced lists. With the "or" in a list of other words, a conclusion
        # still kept one of a condition's two alternatives and dropped the other, so the
        # alternatives are a kind of their own. Even then, summaries took one option to cover the
        # other, so a summary that states the condition keeps its "or" and every option.
        caveats = bullet(section(SKILL_MD, "## Writing the analysis"), "- **Caveats.**")
        for sentence in (
                "Before you write the thesis, a section's conclusion or its baton, list what limits "
                "the claims in the paragraphs it covers (for the thesis, every paragraph it draws "
                "on).",
                "Keep every one whose loss would change the meaning, and the loss of an alternative "
                "always does: what you write may compress those paragraphs but never harden them.",
                "List three kinds, or their equivalents in the draft's language:"):
            self.assertIn(sentence, caveats)
        kinds = [line[4:] for line in caveats.splitlines() if line.startswith("  - ")]
        self.assertEqual([words(kind)[0] for kind in kinds],
                         ["modals", "conditions", "alternatives"])
        modals, conditions, alternatives = kinds
        for word in ("can", "may", "would", "tends to", "less", "not every"):
            self.assertIn(f'"{word}"', modals)
        for word in ("if", "unless", "assuming", "provided", "depends on"):
            self.assertIn(f'"{word}"', conditions)
        self.assertIn('every option that an "or" offers, inside a condition as anywhere else. A '
                      'summary that states the condition keeps the "or" and names each option in '
                      "the draft's own words, even one that seems to fall under another",
                      alternatives)
        # The example narrows a condition by dropping exactly one of its two alternatives.
        example = re.search(r'a form that "([^"]+)" signs is not a form that ([^."]+) signs\.',
                            alternatives)
        self.assertIsNotNone(example, alternatives)
        options = example.group(1).split(" or ")
        self.assertEqual(len(options), 2)
        self.assertEqual(example.group(2), options[0])

    def test_a_caveat_wins_over_a_length_limit(self):
        # A section conclusion that keeps every alternative of its condition can run past 90
        # characters. The runs that met "keep it to 90" cut the alternative, word for word, to
        # get under it, so the rule stands where the conclusion is written, where check warns,
        # and in the warning itself.
        lengths = bullet(section(SKILL_MD, "## Writing the analysis"), "- **Lengths.**")
        self.assertIn("When a length and a caveat compete, the caveat wins: cut other words first, "
                      "and let the text run long rather than drop a hedge, a condition or an "
                      "alternative. A length warning on such a text is the right outcome.", lengths)
        procedure = section(SKILL_MD, "## Procedure")
        step = procedure[procedure.index("5. **Check.**"):procedure.index("6. **Build.**")]
        self.assertIn("A `WARN` about a length asks for fewer words, never a firmer claim: cut only "
                      "words that hold no hedge, condition or alternative, and leave the text long "
                      "when it cannot fit.", step)
        # Running long costs a warning, never an error, so the advice cannot loop the check, and
        # the warning on a summary of the draft says how to shorten it.
        blocks = json_blocks(REFS / "schema.md")
        analysis = blocks["draft.json"]
        analysis["thesis"] = " ".join(["more"] * (LIMITS["thesis"] // 4))
        analysis["sections"][0]["conclusion"] = " ".join(["more"] * (LIMITS["conclusion"] // 4))
        analysis["sections"][0]["baton"] = " ".join(["more"] * (LIMITS["baton"] // 4))
        analysis["paragraphs"][0]["label"] = " ".join(["more"] * (LIMITS["label"] // 4))
        analysis["sections"][0]["short"] = "x" * (LIMITS["short"] + 1)
        result = check(analysis, blocks["source.json"])
        self.assertEqual(result["errors"], [])
        warned = {entry["path"]: entry["message"] for entry in result["warnings"]}
        summaries = ("$.thesis", "$.sections[0].conclusion", "$.sections[0].baton",
                     "$.paragraphs[0].label")
        for path in summaries:
            with self.subTest(path):
                self.assertIn("cut only words that hold no hedge, condition or alternative, or "
                              "leave it long", warned[path])
        # A section's short name summarizes nothing, so its warning stays plain.
        self.assertEqual(warned["$.sections[0].short"],
                         f"{LIMITS['short'] + 1} characters; keep it to {LIMITS['short']}")

    def test_a_last_consistency_pass_holds_the_thesis_to_the_maps_own_summaries(self):
        # A thesis widened a negation that its own section conclusion and paragraph label drew
        # narrowly, so the map contradicted itself: nothing compared the thesis with the rest.
        # And a caveat pass made before writing did not stop a conclusion from losing an "or",
        # so the last pass first holds every summary against its paragraphs again.
        writing = section(SKILL_MD, "## Writing the analysis")
        rules = [line for line in writing.splitlines() if line.startswith("- **")]
        self.assertTrue(rules[-1].startswith("- **Consistency.**"), rules[-1])
        consistency = bullet(writing, "- **Consistency.**")
        for sentence in (
                "Last, when everything else is written, read the analysis through twice.",
                "First, hold every label, section conclusion and baton against its paragraphs and "
                "their caveats, and restore any caveat it lost or any claim it hardened: every "
                '"or" in a condition of those paragraphs is still there, with all its options.',
                "Then read the thesis against every section conclusion and against the labels of "
                "the paragraphs it draws on, and each section conclusion against the labels of its "
                "own paragraphs.",
                "A summary may say less than the parts it sums up, but never more firmly, and "
                'never the opposite: a thesis that says to stop planting street trees, over a '
                'section that concludes "plant fewer, water more", says what its own map denies.',
                "Where they part, re-read the paragraphs and correct whichever one departs from "
                "them; never bend a label to fit the thesis."):
            self.assertIn(sentence, consistency)
        # The analysis step ends with the pass, before the check.
        procedure = section(SKILL_MD, "## Procedure")
        step = procedure[procedure.index("4. **Analysis.**"):procedure.index("5. **Check.**")]
        self.assertIn('Last, make the consistency pass at the end of "Writing the analysis" and '
                      "correct what it finds.", step)

    def test_an_x_not_y_label_takes_its_contrast_from_the_paragraph(self):
        # Labels of the form "X, not Y" came to invent a contrast that the paragraph never drew.
        self.assertIn('In a label of the form "X, not Y", the "not Y" comes from the paragraph\'s '
                      "own negation or caveat: never invent a contrast the paragraph does not "
                      "draw.", section(SKILL_MD, "## Guardrails"))

    def test_a_thread_quote_is_where_the_item_takes_up_the_thread(self):
        # Some marks quoted another part of the paragraph than the one that takes up the thread,
        # or let one sentence serve several threads that each had words of their own.
        for path, heading in ((SKILL_MD, "## Writing the analysis"),
                              (REFS / "schema.md", "### paragraphs")):
            with self.subTest(path.name):
                text = section(path, heading)
                self.assertIn("where the item takes up that thread", text)
                self.assertIn("each thread gets its own stretch of it", text)
        # The example in schema.md does as it says: an item on two threads quotes two stretches.
        items = json_blocks(REFS / "schema.md")["draft.json"]["paragraphs"]
        shared = [item for item in items if len(item["lanes"]) > 1]
        self.assertTrue(shared)
        for item in shared:
            text = normalize(item["text"])
            quotes = [normalize(mark["quote"]) for mark in item["lanes"].values()]
            spans = sorted((text.index(quote), text.index(quote) + len(quote)) for quote in quotes)
            for (_, end), (start, _) in zip(spans, spans[1:]):
                self.assertLessEqual(end, start, item["id"])

    def test_a_direction_ends_with_why_and_a_good_one_is_shown_in_korean(self):
        # Several directions in the runs said where and what, but not why.
        for path, heading in ((SKILL_MD, "## Gaps and directions"),
                              (REFS / "gaps.md", "## Writing a direction")):
            with self.subTest(path.name):
                self.assertIn("end with why: what the reader gains", section(path, heading))
        good = [line[3:-1] for line in section(REFS / "gaps.md", "### Good").splitlines()
                if line.startswith('- "') and line.endswith('"')]
        self.assertGreaterEqual(len(good), 3)
        self.assertTrue([direction for direction in good if HANGUL.search(direction)], good)
        for direction in good:
            self.assertLessEqual(sentence_count(direction), 2, direction)

    def test_a_claim_stronger_than_its_support_gets_a_direction_not_a_hedge(self):
        # Runs flagged claims made more strongly than their support ("will be unable" after "less
        # probable") and improvised the direction; prescribing the weaker wording is a rewrite.
        gaps = (REFS / "gaps.md").read_text("utf-8")
        start = gaps.index("4. **A claim with no support.**")
        type_4 = gaps[start:gaps.index("5. **", start)]
        self.assertIn("made more strongly than its support allows", type_4)
        good = re.search(r'^\s+- Good: "(.+)"$', type_4, re.M)
        bad = re.search(r'^\s+- Bad: "(.+)"$', type_4, re.M)
        self.assertIsNotNone(good, type_4)
        self.assertIsNotNone(bad, type_4)
        good, bad = good.group(1), bad.group(1)
        self.assertLessEqual(sentence_count(good), 2)
        self.assertIn("names the support to connect or the step to argue", type_4)
        self.assertIn("prescribes the hedge, which is a rewrite", type_4)
        # The good one names the step in no words of its own; the bad one hands over the hedge.
        self.assertEqual(quoted_segments(good), [])
        self.assertNotRegex(good, '["\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}'
                                  '\N{LEFT CORNER BRACKET}\N{RIGHT CORNER BRACKET}]')
        self.assertEqual(quoted_segments(bad), ["on most farms", "always"])
        # check() passes the new examples, the bad one too, as gaps.md says: its quote is short.
        korean = [line[3:-1] for line in section(REFS / "gaps.md", "### Good").splitlines()
                  if line.startswith('- "') and HANGUL.search(line)]
        self.assertEqual(len(korean), 1)
        self.assertIn("short enough for `check` to pass", type_4)
        for direction in (good, bad, *korean):
            with self.subTest(direction[:20]):
                self.assertEqual(errors_as_a_direction(direction), [])

    def test_gap_notes_hold_to_their_items_and_a_map_keeps_to_sound_gaps(self):
        # Several notes misstated the paragraphs they cited, and maps padded to four or five gaps,
        # the last of them weak or restating what counting shows.
        # A note may name items besides those in `at`, as type 4's good direction names P12.
        reread = ("Before you write a note, re-read the items in `at` and any other item the gap "
                  "names, and attribute nothing to them that they do not say.")
        few = ("Write only the gaps you can support from the text you cite, usually one to three: "
               "a shorter list of sound gaps beats a long one.")
        gaps = (REFS / "gaps.md").read_text("utf-8")
        places = (
            ("SKILL.md", section(SKILL_MD, "## Gaps and directions"), (
                reread, few, "Do not restate an observation that `build` counts unless reading "
                             "shows why it matters, since `build` already lists them.")),
            ("gaps.md, before its first section", gaps[:gaps.index("\n## ")], (few,)),
            ("gaps.md, Gaps to look for", section(REFS / "gaps.md", "## Gaps to look for"),
             (reread,)),
            ("gaps.md, What counting shows", section(REFS / "gaps.md", "## What counting shows"),
             ("They are neutral and need no gap of their own: do not restate one unless reading "
              "shows why it matters, since `build` already lists them.",)),
        )
        for name, text, sentences in places:
            with self.subTest(name):
                for sentence in sentences:
                    self.assertIn(sentence, text)

    def test_evidence_brings_data_and_an_assertion_is_a_claim(self):
        # In two maps, a paragraph that a gap called unsupported was also tagged evidence: an
        # assertion or a step of reasoning that a claim leaned on had been taken for evidence.
        roles = (REFS / "roles.md").read_text("utf-8")
        row = re.search(r"^\| `evidence` \|.*$", roles, re.M).group()
        self.assertIn("| Brings data, findings, sources or quotations that support a claim. |", row)
        pair = section(REFS / "roles.md", "### `evidence` or `example`")
        self.assertIn("An assertion or a reasoning step is neither, however much a claim leans on "
                      "it: it is itself a `claim` (or a `framework` when it sets criteria, or an "
                      "`implication` when it draws on support already given), not `evidence`.",
                      pair)
        self.assertIn("A paragraph that a gap calls unsupported cannot be `evidence`.", pair)
        # Only a finding can be evidence by position: an assertion stays a claim however much a
        # claim leans on it.
        self.assertIn("The same finding can be `context` in one essay and `evidence` in another, "
                      "depending on whether a claim leans on it.",
                      section(REFS / "roles.md", "## Choosing a role"))
        # gaps.md says it again where such a gap is written.
        gaps = (REFS / "gaps.md").read_text("utf-8")
        start = gaps.index("4. **A claim with no support.**")
        self.assertIn("A paragraph you call unsupported cannot be `evidence`, as roles.md says.",
                      gaps[start:gaps.index("5. **", start)])

    def test_the_analysis_examples_come_from_outside_the_public_drafts(self):
        # The runs passed exactly the spots that the skill's examples were taken from, and missed
        # comparable ones. So the examples an agent learns the analysis from hold nothing on the
        # subjects of the public drafts that the runs map: Federalist No. 10, the Korean essay,
        # the memo and the narrative. The private article is the next test's.
        subjects = re.compile(r"\b(?:faction|republic|majority|Madison|Union|independence|freedom|"
                              r"culture|status meeting|lake|canoe)s?\b", re.IGNORECASE)
        korean_subjects = ("독립", "자유", "문화", "민족")
        for name, text in analysis_examples():
            with self.subTest(name):
                self.assertEqual(subjects.findall(text), [])
                self.assertEqual([word for word in korean_subjects if word in text], [])

    def test_the_analysis_examples_come_from_outside_the_private_article(self):
        # Words naming the private article's subject would describe it in a public file, so they
        # stay in the git-ignored tests/private/, and this test runs only where they are.
        if not PRIVATE_TERMS.is_file():
            self.skipTest("tests/private/subject-terms.txt is not here")
        terms = [line.strip() for line in PRIVATE_TERMS.read_text("utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        self.assertTrue(terms)
        subjects = re.compile(r"\b(?:" + "|".join(map(re.escape, terms)) + r")s?\b", re.IGNORECASE)
        for name, text in analysis_examples():
            with self.subTest(name):
                self.assertEqual(subjects.findall(text), [])
