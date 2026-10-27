import unittest
import bootstrap
from junzheng_match.windows_setup import progress_text


class SetupProgressTests(unittest.TestCase):
    def test_estimate_is_not_a_fake_percentage(self):
        text=progress_text(65)
        self.assertIn('1分05秒',text)
        self.assertIn('通常约10–60秒',text)
        self.assertNotIn('%',text)

    def test_slow_local_setup_reports_remaining_wait_limit(self):
        self.assertIn('最多再等待90秒',progress_text(210))
        self.assertIn('最多再等待0秒',progress_text(500))
