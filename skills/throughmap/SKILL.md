---
name: throughmap
description: "Map the flow of an essay, report or article draft as a one-page offline infographic: section conclusions, paragraph roles, threads, recurring examples and gaps. Use when someone asks to map, visualize or check a draft's structure or argument (구조 지도, 흐름 점검, 문단 역할) or to check a draft before submitting it. Analysis only; it never rewrites the writing."
license: MIT
metadata:
  version: "0.1.0"
  homepage: "https://github.com/LucasKSJang/writing-throughmap"
---

# throughmap

Turn a draft of thesis-driven writing into a one-page map of its flow. Every label on the map sits next to a quote from the draft, and a script checks that each quote is really there. You analyze and diagnose; the prose stays the author's.

## What it produces

Everything goes into `<out>`, the folder `<draft name>.throughmap` beside the draft:

- `index.html`: one self-contained page that opens without an internet connection. It shows the title and thesis; a card per section with its conclusion, its paragraphs' roles in order and the question it hands on; the thread map, one row per thread with a dot on each paragraph that takes it up; the recurring examples; and the gaps, yours with their directions first, then what counting shows. The page saves a PNG and prints.
- `vN.json`: every built version (`v1.json`, `v2.json`, ...), kept. `index.html` shows the latest.
- `source.json`, the numbered paragraphs that `extract` writes, and `draft.json`, the analysis you write.
- A four-line summary in the terminal.

## When to use it, and when not to

Use it on a complete draft of thesis-driven writing (an essay, report, article, column, memo, paper, newsletter or blog post), during revision or as a last check before submitting.

- **Narrative or personal essays** (a story or memoir told in sequence rather than a position argued): tell the user that the map is designed for argumentative writing and ask whether to go on. Continue only when they say yes, even if they asked you to just draw it. When no one can answer, stop there.
- **Rewriting, polishing, grammar, spelling, citations and style** are outside this skill. If the user asks for a rewrite, finish the map first, then treat the rewrite as an ordinary request.
- **Comparing two drafts** is not in this version. Map the new draft; the earlier maps stay in `<out>`, and `versions` lists them.

### Limits

- One map holds at most 40 paragraphs; tables and figures do not count. A longer draft is mapped one section at a time.
- `extract` reads .docx files, and .md, .markdown and .txt files in UTF-8. A PDF, pasted text or a Google Doc is saved as Markdown first (step 1).
- From a .docx it reads the body text and the tables, as Word shows them with tracked changes accepted. Text boxes, footnotes and endnotes, headers and footers, comments and images are not read.
- From Markdown, YAML front matter and footnotes are set aside (`excluded` lists them, and the front matter's `title:` is the title), fenced code and horizontal rules are skipped, and links, emphasis and HTML tags are reduced to their text.

## Running the script

`<skill-dir>` means the folder that contains this `SKILL.md`. Run `python3 "<skill-dir>/scripts/throughmap.py" --help`. If it does not print the usage, try `python`, then `py -3`, in place of `python3`, and use the first that prints it for every command below.

| Command | What it does |
|---|---|
| `extract INPUT [--name NAME] [--out DIR] [--section S] [--keep-short] [--join A,B] [--split ID TEXT] [--drop ID]` | Numbers the draft's paragraphs into `<out>/source.json` and prints a summary. `--join`, `--split` and `--drop` can be repeated. |
| `check DRAFT` | Checks the analysis against the `source.json` beside it. Prints `ERROR` and `WARN` lines, each with the JSON path at fault, or `OK`. |
| `build DRAFT` | Checks again. On errors, prints the same report as `check` and writes nothing. Otherwise saves `vN.json`, writes `index.html` and prints the summary, without the warnings. |
| `versions OUT` | Lists the saved versions with their build times and paragraph counts. |

Exit status 0 means success. 1 means failure: `check` or `build` found errors, a correction does not fit the draft, `--section` names no section (or the draft has no section headings), or no paragraph is left to map. 2 means a usage error or an input that cannot be read.

### Without Python

When none of the three prints the usage, build the page yourself:

1. Number the paragraphs as `extract` would (its rules are in `references/schema.md`), copying each text from the draft exactly, and write the analysis as usual. A .docx cannot be read this way, so ask the user to paste its text.
2. Copy `<skill-dir>/assets/template.html` to `<out>/index.html`.
3. In the copy, replace `__THROUGHMAP_DATA__` (it occurs once, inside `<script id="throughmap-data" type="application/json">`) with the analysis JSON, writing every `</` as `<\/` and every `<!--` as `<\u0021--`, as `build` does. The inserted text then holds neither `</` nor `<!--`, the JSON value is unchanged, and the browser cannot end the data early.
4. Tell the user that quotes are checked in the browser instead (a quote that is not in its paragraph gets a warning mark), and that a .docx needs Python, so they should paste its text instead.

## Procedure

1. **Find the draft.**
   - A .docx, .md, .markdown or .txt file: use it as it is.
   - A PDF: read its text with your own PDF reader and save it as `<slug>.md` beside the PDF.
   - Pasted text: save it as `<slug>.md` in the working directory.
   - A Google Doc: use a connected Google Drive or Docs tool. Search by the title or link the user gave, and when several documents match, list them and ask which one. Only read it, and save its text as `<slug>.md` in the working directory. With no such tool, ask the user to download it as .docx and give you the path.

   For a `<slug>.md`, `<slug>` is the title (for a PDF, its file name) in lower case with hyphens between the words; choose a name that no file has yet. When the draft has section headings, put `# <title>` on the first line and `## ` before each section heading. When it has none, write no `#` at all and give the title to `extract` with `--name "<title>"`. Leave a blank line between paragraphs and keep every word as written; leave out page numbers and running headers, and rejoin words broken across lines.

2. **Extract.**

   ```
   python3 "<skill-dir>/scripts/throughmap.py" extract "<draft path>"
   ```

   It writes `<out>/source.json` and prints that path, the counts and what it set aside. Read `source.json`: the paragraphs, the tables and figures with their captions, the sections and `excluded`.
   - `over 40 paragraphs: pick a section with --section` comes with a list of the sections and their paragraph ranges. Show the list, ask which section to map, and extract that one:

     ```
     python3 "<skill-dir>/scripts/throughmap.py" extract "<draft path>" --section "<section title or number>"
     ```

     Its paragraphs keep their numbers from the whole draft. If the `paragraphs:` count it prints is still over 40, stop: tell the user that this section must be split before it can be mapped, for example by adding a heading inside it at the level of the other section headings.

     To map another section later, give it its own folder with `--out "<draft folder>/<draft name>-<section number>.throughmap"`, so that each map keeps its own versions. That folder is `<out>` for every later command on that section, `extract` included.
   - `over 40 paragraphs and no section headings`: ask the user to add headings or split the draft, then start again.
   - `"sections": []`: the draft has no headings besides its title and references, so you infer the sections.

3. **Outline.** Read every paragraph in `source.json`. If the draft reads as a narrative essay, warn and ask first (see "When to use it, and when not to"). Unless the user said to just draw it, post this outline in the user's language and wait for the answer:

   ```
   Thesis: …
   Questions: Q1 …; Q2 …
   Threads: Q1 · …; Q3 · …; <concept> (→ Q2) · …
   Sections: <short> — <conclusion> (P1–P3); …
   Paragraphs:
   P1 <role> · <label>
   …
   Tables and figures: T1 "<caption>" (after P2); F1 "<caption>" (after P3)
   Set aside: <from source.json "excluded">
   Draw it like this? Tell me what to change, or say "just draw it".
   ```

   - Threads: at most 6, chosen as "Writing the analysis" says. A question thread goes by its question id, a concept thread by its name and the question it serves.
   - Sections: mark the ones you inferred.
   - Paragraphs: one line each, in order. A table or figure that carries part of the argument gets its own line in its place, such as `T1 evidence · Crashes by year`.
   - Tables and figures: every caption in `source.json`, word for word, so that the user can spot a misread: a body sentence taken for a caption, or a caption left among the paragraphs. A misread table or figure can still go into the analysis as a table or figure item. Leave the line out when there are none.
   - Set aside: each entry of `excluded`, shortened, with its kind.

   Then apply the user's corrections:
   - Roles, labels, threads and sections change in the analysis.
   - Paragraph boundaries ("P4 and P5 are one paragraph", "split P7 at 'However,'", "P30 is not part of the essay") change by running `extract` again:

     ```
     python3 "<skill-dir>/scripts/throughmap.py" extract "<draft path>" --join P4,P5 --split P7 "However," --drop P30
     ```

     `--split` cuts where its text first occurs, matched exactly as `source.json` has it, curly quotes included. Every run starts again from the draft, and `source.json` keeps no record of the flags, so give every flag each time: `--name`, `--out`, `--keep-short`, `--section` and all the corrections so far. The ids in `--join`, `--split` and `--drop` are those of a run without them; when the user names a paragraph from an outline numbered otherwise, find it by its text.
   - A short opening or closing paragraph that belongs to the argument (a one-line hook, a closing line) was set aside as `front` or `closing`. Run `extract` again with `--keep-short` added and no corrections: it keeps every short opening and closing paragraph, and it renumbers the paragraphs. Then add `--drop` for the ones that are not part of the argument, such as a title line or byline that has become P1, and any other corrections, in the new numbering.
   - After a new `extract`, post the new Paragraphs lines and ask again; otherwise go on.

4. **Analysis.** Write `<out>/draft.json` as "Writing the analysis" and "Gaps and directions" describe: every paragraph with its role, label and evidence quote; a quote behind every thread mark; the sections with their conclusions and batons; the recurring examples; and the gaps with their directions. Last, make the consistency pass at the end of "Writing the analysis" and correct what it finds.

5. **Check.**

   ```
   python3 "<skill-dir>/scripts/throughmap.py" check "<out>/draft.json"
   ```

   Fix every `ERROR` line and check again, for at most 3 rounds. If errors remain after the third, tell the user what failed and stop. The check is done when it prints `OK` or only `WARN` lines. Tell the user about the warnings, since `build` does not print them.

6. **Build.**

   ```
   python3 "<skill-dir>/scripts/throughmap.py" build "<out>/draft.json"
   ```

   It saves `<out>/vN.json`, writes `<out>/index.html` and prints:

   ```
   throughmap · <title> (<n> paragraphs, <k> threads)
   flow: <short 1> → <short 2> (Q1) → … → <short m>
   gaps: ① <note> ② <note> ③ <note>
   open: <out>/index.html
   ```

   When `<out>` holds other files, a fifth line names them, such as `also in <out>: assemble.py (remove it if you created it)`. Delete the ones you wrote, and tell the user about the rest.

   Relay the summary in the user's language (the computed notes print in English) and give the `open:` path, which is absolute. In the Claude Code desktop app, the path opens in the browser pane when clicked. Anywhere else, ask before opening it, and then use the command for the shell you run:

   | Shell | Command |
   |---|---|
   | PowerShell | `Start-Process "<path>"` |
   | cmd or Git Bash | `start "" "<path>"` |
   | macOS | `open "<path>"` |
   | Linux | `xdg-open "<path>"` |

   In cmd and Git Bash, `start` takes its first quoted argument as a window title, so the empty `""` must come first.

When the user revises the draft, run steps 2 to 6 again, repeating `--name`, `--out`, `--keep-short`, `--section` and every correction that still fits the new text. `build` adds the next version and keeps the earlier ones. To list them:

```
python3 "<skill-dir>/scripts/throughmap.py" versions "<out>"
```

## Writing the analysis

`references/schema.md` gives the format field by field, with a complete example that passes `check`. `references/roles.md` defines the 12 paragraph roles and separates the pairs that are easy to confuse. Read both before writing your first `draft.json`. Every analysis follows these rules:

- **Texts.** List every paragraph of `source.json` in order, with its `text` copied exactly. A table's text is its caption and its table text joined by `"\n"`, leaving out an empty part; a figure's text is its caption. A table or figure stands right after the paragraph its `after` names, or first when `after` is `null`.
- **Quotes.** `evidence` and each thread mark's `quote` are a continuous stretch of the item's own `text`. They are compared after normalizing: format characters are removed, curly quotes become straight, dashes and the minus sign become `-`, `…` becomes `...` and whitespace collapses. So you may type straight quotes and plain spaces, but every word and capital letter must be the draft's.
- **Threads.** 1 to 6 `lanes`, each marked at least once. A question thread follows one of the 1 to 4 `questions` the piece answers, stated or implied. A concept thread follows a key idea that recurs, usually in the service of a question. A mark is `major` when the item advances the thread and `minor` when it mentions or sets it up. Its `quote` is the words where the item takes up that thread; when there is separate text for each thread, each thread gets its own stretch of it.
- **Sections.** They cover the paragraphs in order, without gaps or overlaps. Take them from the headings in `source.json`; with `"sections": []`, infer them and set `"inferred": true` on each. Every section but the last hands on a `baton`, the question that the next one takes up.
- **Caveats.** Before you write the thesis, a section's conclusion or its baton, list what limits the claims in the paragraphs it covers (for the thesis, every paragraph it draws on). Keep every one whose loss would change the meaning: what you write may compress those paragraphs but never harden them. List three kinds, or their equivalents in the draft's language:
  - modals and other hedges, such as "can", "may", "would", "tends to", "less" and "not every";
  - conditions, such as "if", "unless", "assuming", "provided" and "depends on", each with all of its parts;
  - alternatives: every option that an "or" offers, inside a condition as anywhere else. Dropping one hardens the claim: home visits for patients "over 80 or living alone" are not home visits for patients over 80.
- **Recurring examples.** `cases` lists only the examples (a case, a company, a person, an analogy) that appear in at least two items.
- **Language.** Write labels, conclusions, batons, notes and directions in the user's language, and set `ui_language` to its code (`en`, `ko`, ...). Quotes stay in the draft's language. The page's own text is built in for English and Korean; for another language, add `ui_strings` with the strings translated (the keys are listed in `references/schema.md`), or the page shows them in English.
- **Lengths.** A label fits in 28 characters, a conclusion in 90, a baton in 40, a section's `short` in 12 and the thesis in 160. `check` warns about longer ones. When a length and a caveat compete, the caveat wins: cut other words first, and let the text run long rather than drop a hedge, a condition or an alternative.
- **Consistency.** Last, when everything else is written, read the thesis against every section conclusion and against the labels of the paragraphs it draws on, and each section conclusion against the labels of its own paragraphs. A summary may say less than the parts it sums up, but never more firmly, and never the opposite: a thesis that says to stop planting street trees, over a section that concludes "plant fewer, water more", says what its own map denies. Where they part, re-read the paragraphs and correct whichever one departs from them; never bend a label to fit the thesis.

## Gaps and directions

`references/gaps.md` lists the gaps to look for, explains the observations that `build` counts, and shows good and bad directions. Read it before writing the gaps. Before any other gap, find every count or list the draft announces, its restatements in the conclusion included, and compare each with the paragraphs that carry it out: a list that disagrees is the first gap type in gaps.md. Write only the gaps you can support from the text you cite, usually one to three: a shorter list of sound gaps beats a long one. Do not restate an observation that `build` counts unless reading shows why it matters, since `build` already lists them.

A gap names its items (`at`), says what is wrong (`note`) and gives a `direction`. Before you write a note, re-read the items in `at` and any other item the gap names, and attribute nothing to them that they do not say. A direction is at most 2 plain sentences that say where and what to connect, and end with why: what the reader gains. It holds no sentence for the author to paste in, and no numbering or list markers. Put the most important gap first: the terminal summary shows only the first three notes.

## Guardrails

- Write no prose for the draft. Directions, labels, conclusions and batons never contain a new or rewritten sentence of the user's text, quoted or not: name the move and leave the wording to the author. `check` catches only a quoted passage of more than 12 words that is not in the draft. Two shorter invented quotes, an unquoted rewrite or a quote in 「」 all pass it, so this rule is yours to keep.
- A label, a section conclusion, a baton or the thesis may paraphrase freely, but never more strongly than the paragraphs it covers. The rule bans a move, not a list of words: no wording may turn a possibility, a tendency, a plan or one option among several into a certainty or the only option, or less of something into none of it. "Only", "must" and "always" make the move in the open; ordinary words make it as surely:

  | Move | The draft says | Hardened | Kept |
  |---|---|---|---|
  | A possibility | Later opening hours "can draw" more readers | Later hours draw readers | Later hours can draw readers |
  | A tendency | Hives that are moved "have tended to" lose fewer colonies | Moving hives saves colonies | Moving hives tends to help |
  | A plan | The museum "has announced" that it will close its west wing | Museum closed its west wing | Museum plans to close a wing |
  | One option among several | Floods "can" be cut by restoring wetlands "or" by raising levees | Floods need wetlands | Wetlands or levees can help |
  | Less of something | Volunteers "have less say" than paid staff | Volunteers lack a say | Volunteers have less say |

  Read what you wrote back against those paragraphs and ask of every verb and every negation whether the draft says that much. A strong verb such as "proves" or "shows" is fine when those paragraphs argue that strongly. A test the draft calls sufficient, or one condition among several, is not a necessary condition.
- The one hard line: a label, a section conclusion, a baton or the thesis never reverses or drops an explicit caveat that changes the meaning. A paragraph saying that crashes fell on streets that got bike lanes and a lower speed limit, but that the study "cannot tell which change did it", cannot be labelled "Bike lanes cut crashes". A label carries the paragraph's main move. A caveat sits beside it, as in "Fewer crashes, cause unclear", never in its place. In a label of the form "X, not Y", the "not Y" comes from the paragraph's own negation or caveat: never invent a contrast the paragraph does not draw. The evidence quote sits next to every label, so readers can judge the paraphrase themselves.
- The draft stays as it is. Write only the `<slug>.md` copy of step 1 and the files inside `<out>`.
- A helper script you write must be deleted before you finish, so that `<out>` ends holding only `source.json`, `draft.json`, the `vN.json` files and `index.html`.
- Ask before opening a file with an OS command.
- A request for a rewrite waits until the map is done, and is then an ordinary request outside this skill.
- A narrative essay gets the warning and the question first (see "When to use it, and when not to").

## Troubleshooting

| What you see | What to do |
|---|---|
| `python3`, `python` and `py -3` all fail | Build the page without Python (see "Running the script"). |
| `cannot read <file>: use a .docx, .md, .markdown or .txt file`, or `is not UTF-8 text` | Save the text as `<slug>.md`, as step 1 says. |
| `is not a readable .docx file` | Ask the user for a fresh .docx, or for the text. |
| A paragraph is missing from `source.json` | Look in `excluded` and among the captions. Run `extract` again with `--keep-short` for a short first or last paragraph; add a misread table or figure to the analysis as its own item. |
| `no paragraph is left to map (set aside: ...)` | `extract` wrote nothing. The draft holds only headings, captions or references, or the corrections dropped every paragraph: check the draft and any `--drop`, then run `extract` again. |
| `cannot join ...: they are not adjacent` or `... in different sections` | Number the paragraphs as a run without corrections does, and join only neighbours in one section. |
| `cannot split P7 ...` | Copy the text from that paragraph in `source.json` exactly, curly quotes and all, from a point after its start. |
| `ERROR ... a map holds at most 40` | Map one section, as step 2 says. If the map already holds a single section, stop: that section must be split first. When the message says the draft has no section headings, ask the user to add headings or split the draft. |
| `ERROR ... not found word for word in P4` | Copy the quote again from that item's `text` (a table's includes its caption), with the same words and capitals. |
| `ERROR ... differs from P4 in source.json` | Copy the text again from the current `source.json`; a new `extract` may have renumbered the paragraphs. |
| `ERROR ... N sentences; a direction has at most 2` | Rewrite it as at most two plain sentences; "1." and "2." count as sentence ends. |
| `ERROR ... quotes N words that are not in the draft` | Those are your words: remove them and name the move instead. Shortening them to slip under the limit is still a rewrite. |
| The page puts a warning mark on a quote | The quote is not in its paragraph: fix it in the analysis and build the page again. |
| The page says it has no readable analysis | Build it again; without Python, check the two escapes in the inserted JSON. |
