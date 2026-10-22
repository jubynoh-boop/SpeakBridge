import re
import unicodedata
import unittest
from backend.text_segments import split_text


class TextSegmentsTests(unittest.TestCase):
    def test_long_unpunctuated_vietnamese_is_bounded_and_complete(self):
        text = ("Tôi muốn thanh toán hóa đơn 2.500 đô la bằng chuyển khoản " * 18).strip()
        chunks = split_text(text, 180)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 180 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_cjk_without_spaces_preserves_every_character(self):
        text = "你好世界这是全部需要翻译的内容" * 50
        chunks = split_text(text, 120)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))

    def test_combining_accents_and_punctuation_are_preserved(self):
        text = unicodedata.normalize("NFD", "Xin chào. Tôi muốn thanh toán; vui lòng giữ số 2.500 USD. " * 10)
        chunks = split_text(text, 180)
        normalized = unicodedata.normalize("NFC", text)
        self.assertEqual(re.sub(r"\s+", "", " ".join(chunks)), re.sub(r"\s+", "", normalized))
        self.assertFalse(any(unicodedata.combining(chunk[0]) for chunk in chunks))

    def test_empty_or_short_input(self):
        self.assertEqual(split_text("   "), [])
        self.assertEqual(split_text("  Xin chào.  "), ["Xin chào."])
        with self.assertRaises(ValueError):
            split_text("a", 1)
