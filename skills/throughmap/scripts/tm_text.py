"""Text helpers shared by the extractor and the checker.

The checker decides whether a quote matches the draft with normalize() and contains_verbatim(),
so the rules below are exact and live in one place.
"""

import re
import unicodedata

# Typographic characters that normalize() replaces with plain ones.
_TYPOGRAPHY_TO_PLAIN = str.maketrans({
    **dict.fromkeys("‘’‚‛′", "'"),
    **dict.fromkeys("“”„‟″", '"'),
    **dict.fromkeys("–—―−‒", "-"),
    "…": "...",
    **dict.fromkeys(
        "\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}\N{FIGURE SPACE}", " "
    ),
})
# The label that opens a caption: Figure, Fig. or 그림, or Table or 표, and a number. The number may
# have a decimal part ("Figure 1.5"), so that its full stop is not taken for a mark after it.
FIGURE_LABEL = re.compile(r"(?:figure|fig\.|그림)\s*\d+(?:\.\d+)*", re.IGNORECASE)
TABLE_LABEL = re.compile(r"(?:table|표)\s*\d+(?:\.\d+)*", re.IGNORECASE)
_WHITESPACE_RUN = re.compile(r"\s+")
_SPACE_RUN = re.compile(r"\s*")
_NON_WORD_RUN = re.compile(r"[\W_]+")
_SLUG_MAX_LENGTH = 60

# Sentence stops. The CJK ones end a sentence wherever they stand.
_ASCII_STOPS = ".!?"
_CJK_STOPS = "。！？"
_STOP_RUN = re.compile("[" + re.escape(_ASCII_STOPS + _CJK_STOPS) + "]+")
# Words after which a period does not end a sentence, in lower case and without the dot.
_ABBREVIATIONS = frozenset({
    "e.g", "i.e", "etc", "vs", "cf", "fig", "figs", "no", "nos", "p", "pp", "vol", "ch", "sec",
    "dr", "mr", "mrs", "ms", "st",
    "prof", "gen", "sen", "rep", "gov", "jr", "sr", "inc", "ltd", "co", "corp", "dept", "approx",
    "al", "mt", "ave",
})

# A single quote mark can be an apostrophe inside a word (it's, Lucas's). So it opens a segment only
# at the start of the text or after whitespace or "(", and closes one unless an ASCII letter, digit
# or underscore follows. Non-ASCII characters may follow, because Korean particles attach straight
# to the closing mark ('...'를).
_SINGLE_OPENS = r"(?:^|(?<=[\s(]))"
_SINGLE_CLOSES = r"(?![A-Za-z0-9_])"
_QUOTE_PATTERNS = (
    re.compile(r'"(.*?)"'),
    re.compile(r"“(.*?)”"),
    re.compile(_SINGLE_OPENS + r"'(.*?)'" + _SINGLE_CLOSES),
    re.compile(_SINGLE_OPENS + r"‘(.*?)’" + _SINGLE_CLOSES),
)


def _without_format_characters(text: str) -> str:
    """Drop the format characters (Unicode category Cf): they do not show, nobody can retype them.

    Text pasted from the web or a word processor carries them: the zero-width space and joiners,
    the word joiner, the byte order mark, the bidirectional marks, the soft hyphen.
    """
    if text.isascii():   # every format character is outside ASCII
        return text
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


def normalize(text: str) -> str:
    """Return ``text`` in the form the checker compares: NFC, plain quotes, dashes and spaces.

    Format characters (the zero-width space and joiners, the word joiner, the byte order mark, the
    bidirectional marks, the soft hyphen) are removed first: they do not show, so nobody can
    retype them. Curly quotes and primes become ' or ", dashes and the minus sign become -, the
    ellipsis becomes three dots, no-break and narrow spaces become spaces, and each run of
    whitespace collapses to one space with the ends trimmed. Case is kept. Only the comparison is
    affected: the draft's own text is never changed.
    """
    plain = unicodedata.normalize("NFC", _without_format_characters(text))
    return _WHITESPACE_RUN.sub(" ", plain.translate(_TYPOGRAPHY_TO_PLAIN)).strip()


def contains_verbatim(haystack: str, needle: str) -> bool:
    """True when the normalized needle is non-empty and occurs in the normalized haystack."""
    wanted = normalize(needle)
    return bool(wanted) and wanted in normalize(haystack)


def word_count(text: str) -> int:
    """Count whitespace-separated tokens."""
    return len(text.split())


def _is_latin(char: str) -> bool:
    return "LATIN" in unicodedata.name(char, "")


def _starts_sentence(char: str) -> bool:
    """True for an uppercase letter or a non-Latin letter (Hangul, Cyrillic, CJK and so on)."""
    return char.isalpha() and (char.isupper() or not _is_latin(char))


def _next_non_space(text: str, index: int) -> int:
    """Return the index of the first non-whitespace character from ``index``, else len(text)."""
    return _SPACE_RUN.match(text, index).end()


def _new_sentence_follows(text: str, index: int) -> bool:
    """True when only space follows ``index``, or whitespace and then a new sentence starts.

    A new sentence starts with an uppercase letter, a non-Latin letter or a digit. A character
    attached at ``index``, with no whitespace first, means the sentence goes on.
    """
    following = _next_non_space(text, index)
    if following == len(text):
        return True
    char = text[following]
    return following > index and (_starts_sentence(char) or char.isdecimal())


def _word_before(text: str, end: int) -> str:
    """Return the word that ends at ``end``, dots inside it kept ("e.g", "U.S"), or ""."""
    start = end
    while start > 0:
        char = text[start - 1]
        inner_dot = char == "." and start > 1 and text[start - 2].isalnum()
        if not (char.isalnum() or char == "_" or inner_dot):
            break
        start -= 1
    return text[start:end]


def _follows_abbreviation(text: str, dot_index: int) -> bool:
    """True when the period at ``dot_index`` follows a known abbreviation or Latin initials."""
    word = _word_before(text, dot_index)
    if word.lower() in _ABBREVIATIONS:
        return True
    return all(len(part) == 1 and part.isalpha() and _is_latin(part) for part in word.split("."))


def _ends_sentence(text: str, stops: re.Match) -> bool:
    """Judge a run of stop characters that stands outside any quote: does it end a sentence?"""
    start, end = stops.span()
    run = stops.group()
    if any(char in _CJK_STOPS for char in run):
        return True
    if run.endswith("..."):
        return _next_non_space(text, end) == len(text)
    if run == "." and _follows_abbreviation(text, start):
        return False
    if end < len(text) and text[end] in ")]":
        return _new_sentence_follows(text, end + 1)
    return _new_sentence_follows(text, end)


def sentence_count(text: str) -> int:
    """Count the sentences in ``text``: none for empty text, otherwise at least one.

    An ASCII . ! or ? ends a sentence when the text ends after it, or when whitespace and then a
    new sentence follow: an uppercase letter, a non-Latin letter or a digit. A character attached
    directly after it, with no whitespace, means the sentence goes on ("3.5", "e.g").

    Quoted spans (the ones quoted_segments finds) are blanked out first, so a stop inside a quote
    never counts by itself. A quote whose text ends in . ! or ? counts as one sentence end, and so
    does a stop just before a closing ) or ], when the same test passes after the closing mark.
    Text attached to that mark, such as a Korean particle after a quote, keeps the sentence going.

    A period does not end a sentence after a known abbreviation (_ABBREVIATIONS: e.g, etc, vs, fig,
    no, dr, prof, inc and so on; any case) or after Latin initials (J., U.S.). An ellipsis ("..."
    or the one character) ends one only at the end of the text. The CJK stops 。！？ always end one.
    """
    work = text.replace("\N{HORIZONTAL ELLIPSIS}", "...").strip()
    if not work:
        return 0
    quotes = _quote_matches(work)
    characters = list(work)
    for quote in quotes:
        characters[quote.start():quote.end()] = " " * (quote.end() - quote.start())
    unquoted = "".join(characters)
    count = 0
    for quote in quotes:
        ends_in_stop = quote.group(1).endswith(tuple(_ASCII_STOPS))
        if ends_in_stop and _new_sentence_follows(unquoted, quote.end()):
            count += 1
    for stops in _STOP_RUN.finditer(unquoted):
        if _ends_sentence(unquoted, stops):
            count += 1
    return max(1, count)


def _quote_matches(text: str) -> list[re.Match]:
    """Find every quote in ``text``, in the order the quotes open."""
    matches = [match for pattern in _QUOTE_PATTERNS for match in pattern.finditer(text)]
    matches.sort(key=lambda match: match.start())
    return matches


def quoted_segments(text: str) -> list[str]:
    """Return the text inside quotation marks, in the order the quotes open in ``text``.

    Handles "double", “curly double”, 'single' and ‘curly single’ quotes; a quote never spans a
    line break. Each style is scanned on its own and the results are merged by position, so a
    quote nested inside another is returned too, after the one that contains it.
    """
    return [match.group(1) for match in _quote_matches(text)]


def slugify(text: str, fallback: str = "essay") -> str:
    """Lowercase ``text`` into a hyphenated slug of at most 60 characters, else ``fallback``.

    Letters and digits of any script are kept; every other run of characters becomes one hyphen.
    The slug never starts or ends with a hyphen, even when the cut lands right after one.
    """
    slug = _NON_WORD_RUN.sub("-", text.lower()).strip("-")
    return slug[:_SLUG_MAX_LENGTH].strip("-") or fallback
