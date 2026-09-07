import unittest

from status_normalizer import normalize_status


class StatusNormalizerTest(unittest.TestCase):
    def test_normalizes_text(self):
        self.assertEqual("active", normalize_status(" Active "))


if __name__ == "__main__":
    unittest.main()
