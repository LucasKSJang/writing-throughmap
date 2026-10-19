import sys
import unicodedata
import unittest

from tm_text import (contains_verbatim, normalize, quoted_segments, sentence_count,
                     slugify, word_count)


class TextTests(unittest.TestCase):
    def test_normalize_maps_quotes_dashes_spaces(self):
        self.assertEqual(normalize("“Hi”\u00a0it’s  a\u00adtest — ok… −1"),
                         '"Hi" it\'s atest - ok... -1')

    def test_normalize_is_nfc(self):
        self.assertEqual(normalize("e\u0301"), "\u00e9")
        self.assertEqual(normalize("\u1100\u1161"), "가")

    def test_contains_verbatim(self):
        self.assertTrue(contains_verbatim("He said “it’s fine.”", 'said "it\'s fine."'))
        self.assertFalse(contains_verbatim("abc", ""))
        self.assertFalse(contains_verbatim("Abc", "abc"))

    def test_word_count(self):
        self.assertEqual(word_count("One two  three\nfour"), 4)
        self.assertEqual(word_count("토큰이 경로 위에"), 3)

    def test_sentence_count(self):
        self.assertEqual(sentence_count("Fix P16. Then link it to P20."), 2)
        self.assertEqual(sentence_count("첫 문장이다. 둘째 문장이다."), 2)
        self.assertEqual(sentence_count("P16을 기준 3과 잇기"), 1)
        self.assertEqual(sentence_count("One. Two? Three!"), 3)

    def test_quoted_segments(self):
        self.assertEqual(quoted_segments('Link “a b c” and \'d e\' and "f"'), ["a b c", "d e", "f"])
        self.assertEqual(quoted_segments("it's Lucas's 'real one' here"), ["real one"])

    def test_slugify(self):
        self.assertEqual(slugify("Cheap Pipes, Rich Taps!"), "cheap-pipes-rich-taps")
        self.assertEqual(slugify("나의 소원"), "나의-소원")
        self.assertEqual(slugify("   "), "essay")
        self.assertLessEqual(len(slugify("a" * 100)), 60)

    def test_slugify_cut_never_leaves_a_trailing_hyphen(self):
        # The 60-character cut falls right after the hyphen that stands in for the space.
        self.assertEqual(slugify("a" * 59 + " b"), "a" * 59)

    def test_quoted_segments_closing_single_quote_before_non_ascii_letter(self):
        # Korean particles attach straight to the closing mark.
        self.assertEqual(quoted_segments("P16의 '밭을 돌아가며 맡을 수 있다'를 기준 3과 잇기"),
                         ["밭을 돌아가며 맡을 수 있다"])
        self.assertEqual(quoted_segments("‘기준 3’과 'real one' and it's Lucas's"),
                         ["기준 3", "real one"])
        # English apostrophes still never close a segment.
        self.assertEqual(quoted_segments("it's Lucas's 'real one' here"), ["real one"])

    def test_quoted_segments_closing_single_quote_boundaries(self):
        # Any non-ASCII letter may follow the closing mark; an ASCII letter or digit may not.
        self.assertEqual(quoted_segments("say 'abc'語 here"), ["abc"])
        self.assertEqual(quoted_segments("say 'abc'é here"), ["abc"])
        self.assertEqual(quoted_segments("say 'abc'd here"), [])
        self.assertEqual(quoted_segments("say 'abc'3 here"), [])

    def test_sentence_count_ignores_stops_that_do_not_end_a_sentence(self):
        self.assertEqual(sentence_count("Link P16 to P20, e.g. the rails claim."), 1)
        self.assertEqual(sentence_count("Tie P5 to Q2 (see Fig. 3). Then cut P6."), 2)
        self.assertEqual(sentence_count('Echo "Fix the rails. Then pay." in P20.'), 1)
        self.assertEqual(sentence_count("Wait... then link P3."), 1)
        self.assertEqual(sentence_count("The U.S. Senate voted. Then it adjourned."), 2)

    def test_sentence_count_counts_stops_that_do_end_a_sentence(self):
        self.assertEqual(sentence_count('Add "the rails claim." Then cut P20.'), 2)
        self.assertEqual(sentence_count("Connect P3 to Q2 (see P5.) Then cut P6."), 2)
        self.assertEqual(sentence_count("P3を繋ぐ。次を削る。"), 2)

    def test_sentence_count_rule_boundaries(self):
        # Empty text has no sentences; any other text has at least one.
        self.assertEqual(sentence_count(""), 0)
        self.assertEqual(sentence_count("  \n"), 0)
        # A digit can start a sentence, and abbreviations match in any case.
        self.assertEqual(sentence_count("Fix P16. 3 steps follow."), 2)
        self.assertEqual(sentence_count("See FIG. 3. Then cut P6."), 2)
        # Abbreviations and initials only affect periods, and initials are Latin letters.
        self.assertEqual(sentence_count("No! Then go."), 2)
        self.assertEqual(sentence_count("그는 갔다. 끝."), 2)
        # An ellipsis, spelled out or as one character, ends a sentence only at the end of the text.
        self.assertEqual(sentence_count("Wait. Then link P3..."), 2)
        self.assertEqual(sentence_count("Wait\N{HORIZONTAL ELLIPSIS} then link P3."), 1)
        # Stops in a row end one sentence, and a quote does not hide what follows it.
        self.assertEqual(sentence_count("Really?! Yes."), 2)
        self.assertEqual(sentence_count('"Stop." "Go."'), 2)
        self.assertEqual(sentence_count("Cut P6 (see P5.) and stop."), 1)

    def test_sentence_count_attached_text_keeps_the_sentence_going(self):
        # Korean particles attach straight to a closing quote.
        self.assertEqual(sentence_count('그가 "멈춰."라고 했다. 그리고 갔다.'), 2)
        self.assertEqual(sentence_count("P3의 '바꿔야 한다.'를 P20과 잇기. 그다음 P6을 줄이기."), 2)
        self.assertEqual(sentence_count('Add "the rails claim." Then cut P20.'), 2)
        # A closing quote or bracket ends a sentence only when the text ends, or whitespace and then
        # an uppercase letter, a non-Latin letter or a digit follow. Text attached to the closing
        # mark means the sentence goes on.
        self.assertEqual(sentence_count('He said "Stop."Then left.'), 1)
        self.assertEqual(sentence_count("Cut P6 (see P5.)Then stop."), 1)
        self.assertEqual(sentence_count('Add "the rails claim." 3 more steps follow.'), 2)
        self.assertEqual(sentence_count("Cut P6 (see P5.) 3 more steps follow."), 2)

    def test_sentence_count_skips_listed_abbreviations(self):
        self.assertEqual(sentence_count("Meet Prof. Kim. Then leave."), 2)
        words = (
            "e.g", "i.e", "etc", "vs", "cf", "fig", "figs", "no", "nos", "p", "pp", "vol", "ch",
            "sec", "dr", "mr", "mrs", "ms", "st", "prof", "gen", "sen", "rep", "gov", "jr", "sr",
            "inc", "ltd", "co", "corp", "dept", "approx", "al", "mt", "ave",
        )
        for word in words:
            with self.subTest(word=word):
                self.assertEqual(sentence_count("See %s. Then go." % word.capitalize()), 1)
        self.assertEqual(sentence_count("See Xyz. Then go."), 2)

    def test_normalize_removes_format_characters(self):
        # Text pasted from the web or a word processor carries characters that nobody can see.
        self.assertEqual(normalize("a" + "\N{ZERO WIDTH SPACE}" + "b"), "ab")
        self.assertEqual(normalize("x" + "\N{WORD JOINER}" + "y" + "\N{ZERO WIDTH NO-BREAK SPACE}"
                                   + "z" + "\N{LEFT-TO-RIGHT MARK}"), "xyz")
        self.assertEqual(normalize("수" + "\N{ZERO WIDTH SPACE}" + "수료"), "수수료")

    def test_normalize_removes_them_before_the_other_steps(self):
        # A space beside one still collapses, and an accent still composes with the letter before.
        self.assertEqual(normalize("a " + "\N{ZERO WIDTH SPACE}" + " b"), "a b")
        self.assertEqual(normalize("e" + "\N{ZERO WIDTH JOINER}" + "\N{COMBINING ACUTE ACCENT}"),
                         "\N{LATIN SMALL LETTER E WITH ACUTE}")

    def test_normalize_removes_every_format_character_and_only_those(self):
        format_characters = [chr(code) for code in range(sys.maxunicode + 1)
                             if unicodedata.category(chr(code)) == "Cf"]
        self.assertGreater(len(format_characters), 100)
        self.assertEqual([hex(ord(char)) for char in format_characters
                          if normalize("a" + char + "b") != "ab"], [])
        # A control character, a private-use character and a variation selector are not format
        # characters, so they stay.
        for char in ("\N{START OF HEADING}", chr(0xE000), "\N{VARIATION SELECTOR-16}"):
            with self.subTest(code=hex(ord(char))):
                self.assertEqual(normalize("a" + char + "b"), "a" + char + "b")

    def test_contains_verbatim_ignores_format_characters(self):
        zero_width = "\N{ZERO WIDTH SPACE}"
        self.assertTrue(contains_verbatim("small " + zero_width + "fee", "small fee"))
        self.assertTrue(contains_verbatim("small fee", "small " + zero_width + "fee"))
        self.assertFalse(contains_verbatim("small fee", zero_width))     # nothing is left to find
