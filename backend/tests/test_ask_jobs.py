import time
import unittest

from app.ask_jobs import InMemoryAskJobStore


class AskJobStoreTestCase(unittest.TestCase):
    def test_enqueue_job_starts_in_pending_and_finishes(self) -> None:
        store = InMemoryAskJobStore()
        job = store.enqueue(
            job_type="message.send",
            summary="Send a message",
            runner=lambda: [{"type": "tool_result", "text": "done", "data": {}}],
        )

        self.assertEqual(job["status"], "pending")
        self.assertTrue(job["id"])

        deadline = time.time() + 2
        snapshot = store.get(job["id"])
        while snapshot["status"] not in {"finished", "failed"} and time.time() < deadline:
            time.sleep(0.05)
            snapshot = store.get(job["id"])

        self.assertEqual(snapshot["status"], "finished")
        self.assertEqual(snapshot["outputs"][0]["type"], "tool_result")
