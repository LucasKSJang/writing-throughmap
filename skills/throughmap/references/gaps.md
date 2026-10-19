# Gaps and directions

A gap is a place where the structure lets the reader down: something promised and not delivered, raised and then dropped, claimed and never supported. The page shows two kinds. Your gaps, found by reading, come first with their directions (`gaps` in the analysis). The observations that `build` finds by counting thread marks follow them, under "Seen by counting".

Write only the gaps you can support from the text you cite, usually one to three: a shorter list of sound gaps beats a long one. A tight piece may have none (`"gaps": []`). Put the most important first: the terminal summary shows only the first three notes, yours before the observations.

## Gaps to look for

Before any other gap, find every count or list the piece announces, its restatements in the conclusion included, and compare each with the paragraphs that carry it out. A count is easy to read past, so make this a pass of its own; then read for the other types.

1. **Lists that disagree.** The piece announces a list (three reasons, four criteria, two cases) and later works through a different one: another count, other names, a different order. A restatement in the conclusion can part from the list in the same ways. `at`: the announcement and the place where the lists part.
2. **An example introduced but never reused.** A case is set up at length, or with a promise to come back to it, and never returns, so the reader never learns what it shows. Recurring examples go in `cases`; this is the one that should have recurred. `at`: where it appears.
3. **A thread raised but not resolved.** A question or key idea is raised, often in the opening, and the ending never answers it. Counting reports a thread with no mark in the last section; reading also catches a question that the ending touches without answering, or one that never became a thread. `at`: where it is raised and where the answer should land.
4. **A claim with no support.** A `claim` (or the thesis) stands with no `evidence`, `example` or reasoning near it, or its support is one case where the claim is general. A claim made more strongly than its support allows belongs here too, such as "always" after data that show a rise "on most farms". A paragraph you call unsupported cannot be `evidence`, as roles.md says. `at`: the claim.
   - Good: "P14 says cover crops always raise yields, but P12 reports a rise on most of the farms studied; argue the step from one to the other, or tie P14 to support that goes that far, so that the reader sees why the claim can be that strong."
     It names the support to connect or the step to argue, and leaves the strength of the claim to the author.
   - Bad: "In P14, write "on most farms" instead of "always"."
     It prescribes the hedge, which is a rewrite. Its quotes are short enough for `check` to pass, but how strongly to claim is the author's choice.
5. **An objection left unanswered.** A `counter` raises an objection or a limit, and the piece moves on as if it had not. `at`: the counter and where the argument resumes.
6. **A conclusion that introduces new material.** The conclusion brings in a claim, an example or a concept the body never discussed, so the ending rests on something the reader has not seen argued. `at`: the new material and, when there is one, the earlier thread it belongs to.

Before you write a note, re-read the items in `at` and any other item the gap names, and attribute nothing to them that they do not say. Write the `note` neutrally, as what the reader meets, such as "P3 promises three ways to cut night waits in the emergency room, but P8 to P12 describe four."

## What counting shows

`build` adds these observations from the thread marks alone. They are neutral and need no gap of their own: do not restate one unless reading shows why it matters, since `build` already lists them. It can matter, for instance, when the quiet thread is the question the thesis answers.

- **Quiet thread:** a thread goes unmarked for at least max(6, 25% of the paragraphs, rounded up) consecutive paragraphs between two of its marks: 6 paragraphs in a map of up to 24, 8 in a map of 32, 10 in a map of 40. Only paragraphs count; a table or figure between the marks does not. The reader may lose the thread, which is not a fault in itself when the paragraphs between are busy with another.
- **Unresolved thread:** no paragraph of the last section marks the thread. The ending does not come back to it.
- **Unthreaded paragraph:** a paragraph has no thread marks at all. Transitions are left out. Either the paragraph serves no question or concept on the map, or it is missing a mark it deserves: check its marks before calling it a digression.

## Writing a direction

A direction tells the author where to work, what to connect, and why, in at most 2 sentences:

- **Where:** item ids such as P7 or T1, or a few of the draft's own words in quotation marks.
- **What to connect:** the two places, the claim and its support, the thread and the section that drops it, the objection and the reply it needs.
- **Why:** what the reader gains, in a clause at the end.

Rules:

- Say where and what, then end with why: what the reader gains. A direction that stops at where and what leaves the author to guess what the move is for.
- Write plain sentences. Leave out numbering, bullets and list markers: "1." and "2." count as sentence ends, so a numbered direction fails the 2-sentence limit.
- Name the move (tie, move, answer, bring back, cut back to) and leave the wording to the author. A direction never holds a sentence for the author to paste in, quoted or not.
- Quote only the draft's own words, and briefly, to point at a place.
- Write in the user's language.
- `check` rejects a direction of more than 2 sentences, or one that quotes more than 12 words that are not in the draft. It cannot see an unquoted rewrite or a short invented quote; those are yours to keep out. It can miscount after an abbreviation it does not know, such as "Jan. 5"; rephrase such a direction.

### Good

- "Bring the table of waiting times (T1) back in P9, where the essay says night waits have doubled, so that the claim rests on the numbers shown earlier."
  It names the place (P9), what to connect (T1 and the claim) and why (the claim gains its support).
- "P3 promises three ways to cut night waits but P8 to P12 describe four; make the two lists match, so that the reader can follow each one from P3 to the paragraph that argues it."
  It names both places, the move (make the lists match) and why (the reader can follow each one), and leaves the wording to the author.
- "풍력 발전기의 소음을 문제 삼는 P7의 반론에 P10의 측정 결과로 답하는 자리를 P8에 마련해서, 독자가 반론이 해소된 것을 보고 다음 절로 넘어갈 수 있게 하세요."
  The same plain style for a user who writes in Korean. It names the place (P8), what to connect (the objection to turbine noise in P7 and the measurements in P10) and, at the end, why (the reader sees the objection settled before the next section).

### Bad

- "End P6 by saying that a second night nurse halves the wait, so patients who arrive after midnight are seen within the hour."
  This writes the author's sentence for them. It has no quotation marks, so `check` lets it pass, but it is a rewrite. Name the move instead: "P6 asserts that a second night nurse halves the wait; tie it to P4's waiting times by hour, so that the reader sees why."
- "1. Fix the flow. 2. Add more evidence. 3. Strengthen the conclusion."
  The numbering makes `check` count six sentences, and it never says where, what to connect or why.
