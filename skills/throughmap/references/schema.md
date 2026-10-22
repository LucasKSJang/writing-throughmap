# The throughmap data format

`<out>` holds two JSON files: `source.json`, which `extract` writes, and `draft.json`, the analysis you write. `build` saves each analysis that passes `check` as `vN.json` and puts it into `index.html`. The example at the end shows both files for a short draft.

## source.json

`extract` writes it, and every analysis is checked against it. Leave it as it is: corrections go through the flags of `extract`.

- `schema`: `"throughmap-source/1"`.
- `essay`: `title`; `source`, the file name; `source_kind`, which is `docx`, `md` or `txt`; `word_count` and `paragraph_count`, counted over the paragraphs it holds; and, after `--section`, `selected_section`, the title of the chosen section.
- `paragraphs`: `{"id": "P1", "text": "..."}` in document order. The text is what a reader sees, with each run of whitespace as one space.
- `tables`: `{"id": "T1", "caption", "after", "text"}`. `caption` is `""` when the table has none. `after` is the id of the paragraph before the table, or `null` when no paragraph comes before it. `text` holds the rows, with the cells joined by ` | ` and the rows by a line break; it is `""` for a caption that has no table beside it.
- `figures`: `{"id": "F1", "caption", "after"}`, one per figure caption. The image itself is not read.
- `sections`: `{"title", "first", "last"}`, one per heading of the top level the draft uses, with the ids of its first and last paragraphs. Paragraphs before the first heading form a section titled `""`. When the draft has no heading besides its title and its references, `sections` is `[]`.
- `excluded`: `{"kind", "text"}` for everything set aside, in document order. The kinds are below.

### How extract reads a draft

1. **Blocks.** In Markdown, a paragraph is the lines up to a blank line, joined with spaces; `#` lines are headings. A paragraph underlined with `===` is a level-1 heading, as in CommonMark. One short line of text (under 12 words, not ending a sentence) underlined with `---` is a level-2 heading; under a blank line, a list item, a quote, a longer paragraph or a line that ends a sentence, `---` is a horizontal rule. Pipe tables are tables. YAML front matter (a first line `---`, then YAML lines with at least one lowercase `key:`, where `#` lines are comments, then `---` or `...`) is set aside as one `front matter` entry, and its `title:` is the title (rule 2). Lines between two rules with no such key line, such as `To:` and `From:`, a `Note:` sentence or a lone `# Title`, are read as ordinary Markdown, and the closing `---` is a rule. Each footnote definition (`[^1]: ...`, with the lines that carry it on) is set aside as a `notes` entry, and the `[^1]` marks are removed from the text. In plain text, blank lines separate the paragraphs, and a text with no blank line between its lines, as in a file saved by Word's "Save as Plain Text" or by Notepad, has one paragraph per line. A chunk (the lines between two blank lines, or the whole of a text without one) is read as one block per line only when it clearly is one paragraph per line: at least two of its lines have 12 or more words, every such long line ends a sentence (`.`, `?`, `!`, `…` or `。`, a closing quote or bracket allowed after the mark), and no line after the first starts with a lowercase letter, as a wrapped line usually does. Otherwise a chunk between blank lines stays one paragraph, so hard-wrapped prose is very rarely split (only when its lines happen to be whole sentences), and a text without blank lines keeps one plain paragraph per line. In a chunk read line by line, a short line standing between two long lines is a heading when it starts with a capital letter or a non-Latin letter (Korean, say), ends with no sentence mark and no `,`, `;` or hyphen, and is not a caption (`Figure 1: ...` stays a paragraph, for rule 5); every other line is a paragraph, and short lines before the first long line or after the last are front and closing lines as usual (rule 4). In a .docx, heading styles and outline levels mark the headings, and each table is one block.
2. **Title.** A Word paragraph in the Title style, or the `title:` of Markdown front matter (a first heading that repeats it is the same title and is not read again; a different first `#` heading over `##` headings, such as `# Free Rails: A Note on Fees`, is a title line, set aside as `front`, and the `##` headings mark the sections). Else, of the headings outside the references (rule 3), the first top-level heading (`#`, or Word's Heading 1) when deeper headings exist and it is the only top-level heading or has nothing under it, as in `# Title` followed by `## Section`; else the only one, of any level; else the first heading when no body paragraph stands under it before the next heading of its level or a higher one, as in `# My Essay` over `# Introduction` and `# Body`. Either way no body paragraph may come before it (rule 4), though front lines such as a byline or `To:` and `From:` lines may. A top-level heading with body under it and other top-level headings after it is a section: under a plain title line, `# Introduction`, `# Analysis` and `## Data` make the title line a front line and `Introduction` a section. That covers a memo whose one heading is its `# Title`, and an essay of `# Title`, its paragraphs and `# References`. The title becomes `essay.title` and is not listed in `excluded`, so a draft with no other heading outside its references has no sections. Without one, the title is `--name`, else the file name, and a `#` title line is read as a section heading.
3. **References.** A heading or one-line paragraph reading References, Bibliography, Works Cited, Sources, Notes, 참고문헌, 참고 문헌 or 참고자료 (any case, a closing colon allowed) opens the references, but only where the body has started (rule 4). They run to the next heading of the same level or a higher one (after `## Notes`, the next `##` or `#`), or to the end of the draft. After a one-line paragraph they run to the next heading at the draft's section level or higher: the top level of the headings between the start of the body and that line, or any heading when there are none. What follows is body again, so text after a mid-draft `## Notes` is kept and an appendix after the references is mapped (`--drop` sets it aside). Each stretch of references becomes one `references` entry, cut to 500 characters. Above the body such a line is the title or a front line, so a `# Notes` over the text is its title and the text is kept.
4. **Front lines and closing lines.** The body starts at the first paragraph of 12 or more words, or at the first paragraph when none is that long. Paragraphs before it are set aside: the first that starts like a byline ("By ", "by ", "글:" or "작성") as `byline`, the others as `front`. Paragraphs of 1 to 4 words after the last paragraph of 12 or more words are set aside as `closing`. Captions are left to rule 5. `--keep-short` turns this rule off, so a short first or last paragraph stays a paragraph; the body still starts where it would for rules 2 and 3.
5. **Captions.** A paragraph of at most 30 words that starts with Figure, Fig., 그림, Table or 표 and a number is a caption when one of `: . ) - – —` follows the number (or nothing does), or when it is a title-like line of at most 15 words that does not end in `.`, `?` or `!`. "Figure 3: Fees by chain" and "Table 2 Owners and users" are captions; "Figure 1 shows that rents rise." stays a paragraph. A figure caption makes a figure. A table caption goes to the table right after it, else the one right before it, and makes a table with `"text": ""` when there is none.
6. **Sections.** The headings of the top level used mark the sections. Deeper headings are set aside as `subheading`; the paragraphs under them stay. A section left with no paragraph (its text set aside, say, as a closing line) is dropped, and its heading is listed as `heading`, so no text leaves the map unlisted.
7. **Numbering.** Paragraphs are P1, P2, ... in document order, tables T1, ... and figures F1, ...; `after` ties each table and figure to the paragraph before it.

`--drop` sets a paragraph aside as `dropped`. So the kinds in `excluded` are `byline`, `front`, `closing`, `subheading`, `heading` (rule 6), `references`, `front matter` and `notes` (from Markdown, rule 1) and `dropped`.

## draft.json

Every field is required unless it says optional. An error from `check` blocks `build`; a warning does not.

### Top level

- `schema`: `"throughmap/1"`.
- `essay`: described below.
- `ui_language`: the code of the language the user chats in, such as `en` or `ko`.
- `ui_strings` (optional): the page's strings in that language, when it is neither English nor Korean. See "Page strings".
- `thesis`: the piece's main claim in one line. Warning over 160 characters.
- `questions`: 1 to 4 questions that the piece answers, stated or implied (error otherwise). Each is `{"id": "Q1", "text": "..."}`, and the ids are unique.
- `lanes`: 1 to 6 threads (error otherwise).
- `sections`: at least one.
- `paragraphs`: the items.
- `cases`: the recurring examples, or `[]`.
- `gaps`: the gaps you found by reading, or `[]`.

### essay

- `title`: the draft's title, as in `source.json`. When that is only the file name (a plain-text draft has no title `extract` can recognize), use the draft's own title line, which `excluded` lists, if it has one.
- `source`: the name the user knows the draft by: its file name, the PDF's file name, the Google Doc's title, or the saved `<slug>.md` for pasted text.
- `source_kind`: `docx`, `md`, `txt`, `pdf`, `paste` or `gdoc`; for a Markdown copy, the kind of the original.
- `language`: the draft's language, as a code such as `en`. The quotes are in it.
- `word_count`: a whole number, copied from `source.json`.

### lanes

Each thread is `{"id", "kind", "label", "sub", "question"}`.

- `id`: unique and short, such as `q1` or `sleep`.
- `kind`: `question` for the thread of one question (teal on the page), or `concept` for a key idea that recurs (purple).
- `label`: the thread's name in a word or two, as the map's column of names is narrow.
- `sub` (optional): a short description, shown after the name and on hover.
- `question`: a question id. A question thread names the question it follows (required); a concept thread may name the question it helps answer.
- Every thread is marked by at least one item (error otherwise). When no thread has kind `question`, `check` warns.

The page names a question thread by its question id followed by its label, and a concept thread by its label followed by `sub`.

### sections

Each section is `{"id", "short", "title", "inferred", "first", "last", "conclusion", "baton", "answers"}`.

- `id`: unique, such as `S1`.
- `short`: the name on the map's section band. Warning over 12 characters.
- `title`: the heading as the draft has it, or `""` for an untitled opening section or an inferred one.
- `inferred`: `true` for a section you drew yourself, `false` for a heading of the draft. When `source.json` has `"sections": []`, every section is inferred, and `check` warns about a `false`.
- `first`, `last`: paragraph ids. The sections cover every paragraph in order, each beginning right after the one before it ends, with no overlap (error otherwise).
- `conclusion`: what the section concludes, in one line. Warning over 90 characters.
- `baton`: the question this section hands to the next. Required and not empty on every section but the last; warning over 40 characters. The last section's is `""`, and `check` warns about any other.
- `answers`: the ids of the questions the section answers, or `[]`.

### paragraphs

Each item is `{"id", "kind", "section", "text", "role", "label", "evidence", "lanes"}`.

- The items are all the paragraphs of `source.json`, in order (error otherwise). A table or figure that carries part of the argument is an item too: it stands right after the paragraph its `after` names, or first when `after` is `null`. At most 40 items of kind `paragraph` (error); fewer than 5 gives a warning.
- `id`: the id in `source.json`, such as `P1`, `T1` or `F1`.
- `kind`: `paragraph`, `table` or `figure`, as `source.json` has it.
- `section`: the id of the section that covers the paragraph. A table or figure takes the section it stands in.
- `text`: the text in `source.json`, exactly. For a table, the caption and the table text joined by `"\n"`, leaving out an empty part; for a figure, its caption.
- `role`: one of the 12 keys in `roles.md`.
- `label`: a short summary in the user's language. Warning over 28 characters.
- `evidence`: a sentence or clause of `text`, word for word, that supports the role and the label.
- `lanes`: the thread marks, as `{"<lane id>": {"weight": "major", "quote": "..."}}`, or `{}` for an item on no thread. `weight` is `major` when the item advances the thread and `minor` when it mentions or sets it up. `quote` is a part of `text`, word for word, taken from where the item takes up that thread. When there is separate text for each thread, each thread gets its own stretch of it.

### cases

Each recurring example is `{"name", "at", "note"}`: a case, a company, a person or an analogy that appears in at least 2 items. `at` lists those items, at least 2 different ids (error otherwise), and `note` says in one line how the example recurs.

### gaps

Each gap is `{"at", "note", "direction"}`. `at` lists the ids of the items involved. `note` says what is wrong, neutrally. `direction` has at most 2 sentences (error otherwise) and quotes no more than 12 words that are not in the draft (error otherwise); `gaps.md` explains how to write one.

Every id named in `first`, `last`, `section`, `question`, `answers` and `at` must exist (error otherwise). `at` may name any item of the analysis.

### What build adds

`vN.json` is `draft.json` plus `version` (N), `generated_at` (the time, in UTC) and `computed`, which holds each thread's runs and the observations described in `gaps.md`. From the second version on it also holds `compare`, the comparison with an earlier version: `against` (that version's number), `before` (a copy of it), `versions` (every saved version, with its time and paragraph count), the matched items (`pairs`, `splits`, `merges`, `added`, `removed`) and what changed (`marks`, `lanes`, `quiet_closed`, `quiet_opened`, `gaps_closed`). They are worked out from your marks and the saved versions, so leave them out of `draft.json`; `build` replaces any it finds there.

## Quote matching

Before any comparison, both sides are normalized:

1. Unicode format characters are removed: zero-width spaces and joiners, the word joiner, the byte order mark, bidirectional marks and the soft hyphen.
2. The text is composed (NFC).
3. Curly quotes and primes become `'` or `"`; the en dash, the em dash, the figure dash, the horizontal bar and the minus sign become `-`; `…` becomes `...`; no-break, thin and narrow spaces become plain spaces.
4. Each run of whitespace becomes one space, and the ends are trimmed.

Matching is case-sensitive. A quote passes when its normalized form occurs in the normalized text of its item in `source.json`, and an item's `text` passes when the two normalized texts are equal.

## Limits

| What | Limit | When it is broken |
|---|---|---|
| paragraphs, not counting tables and figures | at most 40 | error |
| paragraphs | at least 5 | warning |
| lanes | 1 to 6, each marked | error |
| questions | 1 to 4 | error |
| lanes of kind `question` | at least 1 | warning |
| `label` | 28 characters | warning |
| `conclusion` | 90 characters | warning |
| `baton` | 40 characters | warning |
| `short` | 12 characters | warning |
| `thesis` | 160 characters | warning |
| a gap's `direction` | 2 sentences | error |
| words quoted in a direction that are not in the draft | 12 | error |

## Page strings

`ui_strings` maps these keys to text. The page looks a string up in `ui_strings` first, then in its built-in table for `ui_language` (English or Korean), then in English, so a key you leave out falls back to one of those. A key ending in `_1` is used when the number is 1; a language that does not mark the singular can leave those keys out. Keep each `{...}` placeholder as it is.

| Key | English | Where it shows |
|---|---|---|
| `thesis` | Thesis | header, before the thesis |
| `questions` | Questions | header, before the questions |
| `flow` | Section flow | title of the section flow |
| `flow_hint` | One line per section, then its paragraphs' roles in order. Click a role to find it on the map. | under the section flow title |
| `map` | Thread map | title of the thread map |
| `map_legend` | Large dot = main point · small dot = brief mention · solid line = consecutive paragraphs · dashed line = the thread rests · click a thread name to isolate it | under the thread map title |
| `poster_legend` | Large dot = main point · small dot = brief mention · solid line = consecutive paragraphs · dashed line = the thread rests | legend of the PNG poster |
| `detail_hint` | Hover or click a paragraph, a dot or a role to see its summary and evidence. | detail box, before anything is chosen |
| `list_toggle` | All paragraphs | the folded list of all paragraphs |
| `cases` | Recurring examples | title of the recurring examples |
| `cases_hint` | Click to highlight where each appears. | under the recurring examples title |
| `gaps` | Gaps | title of the gaps panel |
| `gaps_toggle` | click to expand | after the gaps title while folded |
| `computed` | Seen by counting | heading over the observations |
| `direction` | Direction | before each gap's direction |
| `threads` | Threads | detail box, before the thread marks |
| `major` | main point | weight of a major mark |
| `minor` | brief mention | weight of a minor mark |
| `png` | Save PNG | button |
| `print` | Print | button |
| `footer_offline` | Opens without an internet connection | footer |
| `warn_quote` | Quote not found in the paragraph | hover text of a quote's warning mark |
| `obs_quiet` | {lane} rests for {n} paragraphs ({from}–{to}) | a quiet-thread observation |
| `obs_unresolved` | {lane} does not return in the last section | an unresolved-thread observation |
| `obs_unthreaded` | {at} is on no thread | an unthreaded-paragraph observation |
| `table_prefix` | T | before a table's number, as in T1 |
| `figure_prefix` | F | before a figure's number, as in F1 |
| `inferred` | inferred | badge on an inferred section |
| `role.problem` | Problem | role name |
| `role.thesis` | Thesis | role name |
| `role.context` | Context | role name |
| `role.claim` | Claim | role name |
| `role.evidence` | Evidence | role name |
| `role.example` | Example | role name |
| `role.counter` | Counterpoint | role name |
| `role.implication` | Implication | role name |
| `role.framework` | Framework | role name |
| `role.transition` | Transition | role name |
| `role.synthesis` | Synthesis | role name |
| `role.conclusion` | Conclusion | role name |
| `para_row` | Paragraph | name of the map's row of paragraph numbers |
| `n_paragraphs` | {n} paragraphs | header counts |
| `n_paragraphs_1` | {n} paragraph | header counts |
| `n_words` | {n} words | header counts |
| `n_words_1` | {n} word | header counts |
| `version` | analysis v{v} | header, the version |
| `list_count` | {n} paragraphs | after the paragraph list's name |
| `list_count_1` | {n} paragraph | after the paragraph list's name |
| `list_count_and` | {n} paragraphs and {extra} | the same, when tables or figures are listed too |
| `list_count_and_1` | {n} paragraph and {extra} | the same, when tables or figures are listed too |
| `n_items` | ({n}) | the number of gaps, after the gaps title |
| `none` | none | an item on no thread; an empty gaps panel |
| `data_file` | Data file | footer, before the vN.json name |
| `judged_by` | judged by {lanes} | beside a question that only concept threads follow |
| `range` | {first}–{last} | a section's paragraph range |
| `changes_title` | What changed since v{v} | title of the what-changed panel |
| `changes_none` | Nothing changed in the paragraphs, threads or gaps. | the panel, when nothing changed |
| `changes_paragraphs` | Paragraphs | heading in the panel |
| `changes_quiet` | Quiet threads | heading in the panel |
| `changes_gaps` | Gaps that no longer apply | heading in the panel |
| `change_edited` | Edited: {ids} | a line of the panel |
| `change_added` | New: {ids} | a line of the panel |
| `change_removed` | Removed: {ids} | a line of the panel |
| `change_split` | Split: {old} → {new} | a line of the panel |
| `change_merged` | Merged: {old} → {new} | a line of the panel |
| `change_moved` | Moved: {old} → {new} | a line of the panel |
| `change_marks` | {id}: {marks} | a line of the panel |
| `change_thread_added` | New thread: {lanes} | a line of the panel |
| `change_thread_removed` | Dropped thread: {lanes} | a line of the panel |
| `change_quiet_closed` | {lane} no longer rests from {from} to {to} | a line of the panel |
| `change_quiet_opened` | {lane} now rests for {n} paragraphs ({from}–{to}) | a line of the panel |
| `change_gap` | {note} ({at}) | a line of the panel |
| `versions` | Saved versions: {list}. To compare with another one, ask your agent. | foot of the panel |
| `version_this` | this map | in the versions line |
| `version_compared` | compared | in the versions line |
| `detail_pair` | Before: {old}, {pct}% match | detail box |
| `detail_moved` | moved | detail box, after `detail_pair` |
| `detail_split` | Before: {old}, split into {new} | detail box |
| `detail_merged` | Before: {old}, merged into this one | detail box |
| `detail_new` | New since v{v} | detail box |
| `before_col` | Before · v{v} | heads of the earlier cards and map |
| `now_col` | Now · v{v} | heads of the current cards and map |
| `compare_legend` | Thin lines join each paragraph to its match; hover over one to see how close it is · + new · − removed · ÷ split · ∪ merged | under the map legend |
| `badge_added` | new | hover text of a `+` badge |
| `badge_removed` | removed | hover text of a `−` badge |
| `badge_split` | split | hover text of a `÷` badge and of a split's lines |
| `badge_merged` | merged | hover text of a `∪` badge and of a merge's lines |
| `link_title` | {old} → {new} · {pct}% match | hover text of a pair's line |
| `no_data` | No readable analysis in this page: its data is missing or broken. Ask for the page to be built again. | error shown when the page cannot read its data |

`no_data` appears only when the page cannot read its data at all, so it follows the browser's language (Korean, else English), and `ui_strings` cannot change it.

## Example

The draft `later-bells.md`:

```markdown
# Later Bells

By Sam Rivera

## Sleep

Most high schools ring the first bell before eight, and many parents expect a later start, like the one Hillview High tried, to give teenagers more sleep.

The early bell works against the body clock: teenagers fall asleep later than adults do, so a later start may let them sleep longer.

Table 1: Average sleep on school nights.

| Start | Sleep |
|---|---|
| 7:30 | 6.8 hours |
| 8:30 | 7.4 hours |

## Grades

So the extra sleep shows in the classroom: at Hillview, first-period grades rose in the year after the change.
```

`extract` takes `# Later Bells` as the title, since `##` headings follow it, sets the byline aside, and gives the caption to its table:

`source.json`:
```json
{
 "schema": "throughmap-source/1",
 "essay": {
  "title": "Later Bells",
  "source": "later-bells.md",
  "source_kind": "md",
  "word_count": 70,
  "paragraph_count": 3
 },
 "paragraphs": [
  {
   "id": "P1",
   "text": "Most high schools ring the first bell before eight, and many parents expect a later start, like the one Hillview High tried, to give teenagers more sleep."
  },
  {
   "id": "P2",
   "text": "The early bell works against the body clock: teenagers fall asleep later than adults do, so a later start may let them sleep longer."
  },
  {
   "id": "P3",
   "text": "So the extra sleep shows in the classroom: at Hillview, first-period grades rose in the year after the change."
  }
 ],
 "tables": [
  {
   "id": "T1",
   "caption": "Table 1: Average sleep on school nights.",
   "after": "P2",
   "text": "Start | Sleep\n7:30 | 6.8 hours\n8:30 | 7.4 hours"
  }
 ],
 "figures": [],
 "sections": [
  {
   "title": "Sleep",
   "first": "P1",
   "last": "P2"
  },
  {
   "title": "Grades",
   "first": "P3",
   "last": "P3"
  }
 ],
 "excluded": [
  {
   "kind": "byline",
   "text": "By Sam Rivera"
  }
 ]
}
```

The analysis keeps the table as an item, because its numbers carry the claim of P2, and every summary of P2 keeps its "may":

`draft.json`:
```json
{
  "schema": "throughmap/1",
  "essay": {"title": "Later Bells", "source": "later-bells.md", "source_kind": "md",
            "language": "en", "word_count": 70},
  "ui_language": "en",
  "thesis": "A later first bell may give teenagers more sleep, and the extra sleep shows in the classroom.",
  "questions": [
    {"id": "Q1", "text": "Would a later bell give teenagers more sleep?"},
    {"id": "Q2", "text": "Does the extra sleep show in the classroom?"}
  ],
  "lanes": [
    {"id": "sleep", "kind": "question", "label": "Sleep", "question": "Q1"},
    {"id": "grades", "kind": "question", "label": "Grades", "question": "Q2"},
    {"id": "clock", "kind": "concept", "label": "Body clock", "sub": "teenagers fall asleep later",
     "question": "Q1"}
  ],
  "sections": [
    {"id": "S1", "short": "Sleep", "title": "Sleep", "inferred": false, "first": "P1", "last": "P2",
     "conclusion": "A later start may give teenagers more sleep, as they fall asleep later.",
     "baton": "Does the extra sleep show in class?", "answers": ["Q1"]},
    {"id": "S2", "short": "Grades", "title": "Grades", "inferred": false, "first": "P3", "last": "P3",
     "conclusion": "The extra sleep shows in class: first-period grades at Hillview rose the next year.",
     "baton": "", "answers": ["Q2"]}
  ],
  "paragraphs": [
    {"id": "P1", "kind": "paragraph", "section": "S1",
     "text": "Most high schools ring the first bell before eight, and many parents expect a later start, like the one Hillview High tried, to give teenagers more sleep.",
     "role": "problem", "label": "Many expect more sleep",
     "evidence": "many parents expect a later start",
     "lanes": {"sleep": {"weight": "major", "quote": "to give teenagers more sleep"}}},
    {"id": "P2", "kind": "paragraph", "section": "S1",
     "text": "The early bell works against the body clock: teenagers fall asleep later than adults do, so a later start may let them sleep longer.",
     "role": "claim", "label": "A later start may add sleep",
     "evidence": "a later start may let them sleep longer",
     "lanes": {"clock": {"weight": "major", "quote": "teenagers fall asleep later than adults do"},
               "sleep": {"weight": "major", "quote": "a later start may let them sleep longer"}}},
    {"id": "T1", "kind": "table", "section": "S1",
     "text": "Table 1: Average sleep on school nights.\nStart | Sleep\n7:30 | 6.8 hours\n8:30 | 7.4 hours",
     "role": "evidence", "label": "36 more minutes at 8:30",
     "evidence": "8:30 | 7.4 hours",
     "lanes": {"sleep": {"weight": "minor", "quote": "Average sleep on school nights"}}},
    {"id": "P3", "kind": "paragraph", "section": "S2",
     "text": "So the extra sleep shows in the classroom: at Hillview, first-period grades rose in the year after the change.",
     "role": "conclusion", "label": "Extra sleep shows in class",
     "evidence": "the extra sleep shows in the classroom",
     "lanes": {"sleep": {"weight": "minor", "quote": "the extra sleep"},
               "grades": {"weight": "major", "quote": "first-period grades rose in the year after the change"}}}
  ],
  "cases": [
    {"name": "Hillview High", "at": ["P1", "P3"],
     "note": "Hillview opens as the school that tried a later start and returns with its first-period grades."}
  ],
  "gaps": [
    {"at": ["T1", "P3"],
     "note": "P3 says the extra sleep shows in the classroom, but only Hillview's first-period grades show it.",
     "direction": "Between T1 and P3, connect the extra sleep to grades at more schools or over more years, so that the conclusion rests on more than one school."}
  ]
}
```

`check` passes it with one warning, since a map needs at least 5 paragraphs to show a flow:

```
WARN $.paragraphs: only 3 paragraphs; a map needs at least 5 to show a flow
0 errors, 1 warning
```

`build` adds one observation, that the Body clock thread does not return in the last section, and its summary lists it after the gap. The last line gives the page's absolute path, with `<out>` standing for its folder:

```
throughmap · Later Bells (3 paragraphs, 3 threads)
flow: Sleep (Q1) → Grades (Q2)
gaps: ① P3 says the extra sleep shows in the classroom, but only Hillview's first-period grades show it. ② Body clock does not return in the last section
open: <out>/index.html
```
