# The Federalist No. 10

Two throughmap maps of James Madison's Federalist No. 10 (1787), one with English labels and one with Korean labels. In both, every quote is Madison's English.

| File | What it is |
|---|---|
| `federalist-10.md` | The text, as the draft the skill reads |
| `federalist-10.throughmap/` | The map with English labels: `source.json` from `extract`, the analysis `draft.json`, and `v1.json` and `index.html` from `build` |
| `federalist-10-ko.throughmap/` | The same map with Korean labels |
| `federalist-10-en.png`, `federalist-10-ko.png` | The posters of the two pages |

Open either `index.html` in a browser. It works without an internet connection.

## Source

The text comes from The Avalon Project at Yale Law School, "The Federalist Papers : No. 10", <https://avalon.law.yale.edu/18th_century/fed10.asp>, accessed 18 October 2026.

Madison wrote it under the pen name Publius, and it first appeared in New York newspapers in November 1787. The text is in the public domain.

`federalist-10.md` keeps, in order, the two subtitle lines, the salutation, the 23 paragraphs and the signature "PUBLIUS.". It leaves out the site's navigation and two lines of Avalon's header, "From the New York Packet. Friday, November 23, 1787." and "MADISON". Avalon sets CAUSES and EFFECTS in bold, which the Markdown keeps; Avalon's link on "Constitution" becomes the plain word. The wording and spelling are Avalon's, including "wellconstructed" in the first sentence, where other editions print "well constructed" or "well-constructed".

The text was checked against Project Gutenberg's edition of The Federalist Papers (eBook #1404). The 23 paragraphs agree word for word, apart from "wellconstructed".

## How the maps were made

Madison wrote no headings, so the Markdown has none and the title comes from `--name`. From the repository root:

```
python skills/throughmap/scripts/throughmap.py extract examples/federalist-10/federalist-10.md --name "The Federalist No. 10"
python skills/throughmap/scripts/throughmap.py check examples/federalist-10/federalist-10.throughmap/draft.json
python skills/throughmap/scripts/throughmap.py build examples/federalist-10/federalist-10.throughmap/draft.json
```

The Korean map runs the same `extract` with `--out examples/federalist-10/federalist-10-ko.throughmap` added, then `check` and `build` on the `draft.json` in that folder.

`extract` sets the subtitle lines and the salutation aside as front matter and "PUBLIUS." as a closing line. It finds no sections, so the five sections on each map are inferred, and the page marks them so.

Each PNG is its page's poster (`index.html#poster`) at twice its size.
