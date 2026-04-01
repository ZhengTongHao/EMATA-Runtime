import unittest
from datetime import timedelta

from app.temporal_workflow import controlled_step_timeout


class TemporalWorkflowTestCase(unittest.TestCase):
    def test_controlled_step_timeout_returns_timedelta(self) -> None:
        timeout = controlled_step_timeout()

        self.assertIsInstance(timeout, timedelta)
        self.assertEqual(timeout, timedelta(seconds=30))


if __name__ == "__main__":
    unittest.main()
