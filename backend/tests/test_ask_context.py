import unittest

from app.ask_context import AskContextManager


class AskContextManagerTestCase(unittest.TestCase):
    def test_apply_patch_separates_conversation_working_and_pending(self) -> None:
        manager = AskContextManager()
        current = {
            "conversation_memory": {"recent_messages": ["old"]},
            "working_context": {"last_target": "Ai应用开发群"},
            "pending_action_draft": {"intent": "message.send"},
        }

        patched = manager.apply_patch(
            current,
            {
                "conversation_memory": {"recent_messages": ["new"]},
                "working_context": {"last_shareable_text": "你好"},
                "pending_action_draft": {},
            },
        )

        self.assertEqual(patched["conversation_memory"]["recent_messages"], ["new"])
        self.assertEqual(patched["working_context"]["last_target"], "Ai应用开发群")
        self.assertEqual(patched["working_context"]["last_shareable_text"], "你好")
        self.assertEqual(patched["pending_action_draft"], {})


if __name__ == "__main__":
    unittest.main()
