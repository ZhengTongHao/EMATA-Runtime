import unittest

from app.ask_action_planner import AskActionPlanner


class FakeParseService:
    def __init__(self, payload):
        self.payload = payload

    def parse_message_action(self, *, message, working_context):
        del message, working_context
        return dict(self.payload)


class AskActionPlannerTestCase(unittest.TestCase):
    def test_message_plan_uses_explicit_target_and_body(self) -> None:
        planner = AskActionPlanner()
        plan = planner.plan_message_action(
            message="把“你好”发到 Ai应用开发群",
            working_context={},
        )
        self.assertEqual(plan["intent"], "message.send")
        self.assertEqual(plan["target_query"], "Ai应用开发群")
        self.assertEqual(plan["text"], "你好")
        self.assertTrue(plan["requires_preview"])

    def test_message_plan_reuses_last_shareable_text(self) -> None:
        planner = AskActionPlanner()
        plan = planner.plan_message_action(
            message="把刚才的结论发给李雷",
            working_context={"last_shareable_text": "候选人通过一面"},
        )
        self.assertEqual(plan["text"], "候选人通过一面")

    def test_message_plan_handles_quoted_target_before_body(self) -> None:
        planner = AskActionPlanner()
        plan = planner.plan_message_action(
            message="给“Ai应用开发群”发送消息“你好”",
            working_context={},
        )
        self.assertEqual(plan["target_query"], "Ai应用开发群")
        self.assertEqual(plan["text"], "你好")

    def test_message_plan_prefers_llm_parse_result_when_available(self) -> None:
        planner = AskActionPlanner(
            parse_service=FakeParseService(
                {
                    "intent": "message.send",
                    "target_query": "Ai应用开发群",
                    "text": "你好",
                    "summary": "发送消息给 Ai应用开发群",
                    "confidence": 0.94,
                    "parse_mode": "llm",
                }
            )
        )
        plan = planner.plan_message_action(
            message="给“Ai应用开发群”发送消息“你好”",
            working_context={},
        )
        self.assertEqual(plan["target_query"], "Ai应用开发群")
        self.assertEqual(plan["text"], "你好")
        self.assertEqual(plan["parse_mode"], "llm")
        self.assertEqual(plan["confidence"], 0.94)


if __name__ == "__main__":
    unittest.main()
