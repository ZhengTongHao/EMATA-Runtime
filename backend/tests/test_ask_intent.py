import unittest

from app.ask_intent import AskIntentRouter


class AskIntentRouterModuleTestCase(unittest.TestCase):
    def test_prefers_action_when_message_contains_explicit_send_intent(self) -> None:
        router = AskIntentRouter()
        result = router.route(
            message="给李雷发送“你好”",
            active_context={"pending_action_draft": {}},
        )
        self.assertEqual(result["route"], "action_only")

    def test_routes_previous_answer_plus_send_to_answer_then_action(self) -> None:
        router = AskIntentRouter()
        result = router.route(
            message="把刚才的结论发到 Ai应用开发群",
            active_context={
                "working_context": {"last_shareable_text": "报销额度是 3000 元"},
            },
        )
        self.assertEqual(result["route"], "answer_then_action")


if __name__ == "__main__":
    unittest.main()
