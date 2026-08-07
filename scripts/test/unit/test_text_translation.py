"""Focused unit tests for text-translation application contracts."""

import unittest

from application.text_translation import text_translation


class TextTranslationOptionTests(unittest.TestCase):
    def test_frequency_descriptor_requires_a_positive_number(self):
        frequency_setting = next(
            setting for setting in text_translation.add_options({}) if setting[0] == "frequency"
        )
        _name, value_type, condition, mandatory, default = frequency_setting

        self.assertIs(value_type, float)
        self.assertTrue(mandatory)
        self.assertIsNone(default)
        for value in (1, 0.5):
            with self.subTest(valid=value):
                self.assertTrue(condition(value))
        for value in (0, -1, True, False, "1"):
            with self.subTest(invalid=value):
                self.assertFalse(condition(value))


if __name__ == "__main__":
    unittest.main()
