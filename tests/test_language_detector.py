from __future__ import annotations

import unittest

from pipeline.language_detector import detect_language, is_minority_language


class LanguageDetectorTest(unittest.TestCase):
    def test_tibetan_script(self):
        result = detect_language({}, "མི་རིགས་མཐུན་སྒྲིལ")
        self.assertEqual(result["language"], "藏语")
        self.assertTrue(is_minority_language(result["language"]))

    def test_mongolian_script(self):
        result = detect_language({}, "ᠮᠣᠩᠭᠣᠯ ᠦᠨᠳᠦᠰᠦᠲᠡᠨ")
        self.assertEqual(result["language"], "蒙古语")

    def test_uyghur_script_markers(self):
        result = detect_language({}, "مىللەتلەر ئىتتىپاقى")
        self.assertEqual(result["language"], "维吾尔语")

    def test_zhuang_marker(self):
        result = detect_language({}, "Vahcuengh ndei")
        self.assertEqual(result["language"], "壮语")

    def test_explicit_metadata_wins(self):
        result = detect_language({"language": "壮文"}, "hello world")
        self.assertEqual(result["language"], "壮语")
        self.assertEqual(result["language_method"], "platform_metadata")

    def test_chinese(self):
        result = detect_language({}, "民族团结进步宣传周")
        self.assertEqual(result["language"], "汉语")


if __name__ == "__main__":
    unittest.main()
