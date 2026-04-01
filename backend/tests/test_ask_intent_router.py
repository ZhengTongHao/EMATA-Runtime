import unittest

from app.ask_runtime import AskIntentRouter


class AskIntentRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.router = AskIntentRouter()

    def test_routes_enterprise_question_to_knowledge_qa(self) -> None:
        result = self.router.route(
            message="报销额度是多少",
            active_context={},
        )
        self.assertEqual(result["route"], "knowledge_qa")

    def test_routes_plain_send_request_to_action_only(self) -> None:
        result = self.router.route(
            message="发信息给李雷，告诉他面试通过了",
            active_context={},
        )
        self.assertEqual(result["route"], "action_only")

    def test_routes_answer_then_action_when_referring_to_previous_summary(self) -> None:
        result = self.router.route(
            message="把刚才的结论发到 Ai应用开发群",
            active_context={"last_shareable_text": "报销额度是 3000 元"},
        )
        self.assertEqual(result["route"], "answer_then_action")

    def test_routes_missing_target_to_clarification(self) -> None:
        result = self.router.route(
            message="发给他",
            active_context={},
        )
        self.assertEqual(result["route"], "clarification")

    def test_routes_plain_meeting_request_to_action_only(self) -> None:
        result = self.router.route(
            message="下午五点 在Ai应用开发群开会",
            active_context={},
        )
        self.assertEqual(result["route"], "action_only")


if __name__ == "__main__":
    unittest.main()
