"""Guard the multi-category extraction contract against accidental removal.

These are prompt-contract checks, not evidence that the model obeys the prompt.
"""
import unittest
from pathlib import Path


class EventClassificationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / 'ai.py').read_text(encoding='utf-8')

    def test_pass_one_independently_checks_categories(self):
        self.assertIn('Independently check each substantive discussion', self.source)
        self.assertIn('One passage may support multiple DIFFERENT event types', self.source)

    def test_pass_one_recognizes_material_concerns_without_keyword(self):
        self.assertIn('attrition pressure, unfunded supplier demand', self.source)
        self.assertIn('do not\n  invent an impact', self.source)

    def test_pass_two_does_not_treat_categories_as_exclusive(self):
        self.assertIn('Independently evaluate each event cluster', self.source)
        self.assertIn('neither category cancels the other', self.source)


if __name__ == '__main__':
    unittest.main()
