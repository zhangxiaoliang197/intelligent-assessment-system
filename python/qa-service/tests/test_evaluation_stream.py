import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from evaluation_api import EvaluationRequest, analyze_stream


async def _collect_ndjson(response):
    events = []
    async for chunk in response.body_iterator:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        events.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return events


class EvaluationStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_skill_returns_a_terminal_error_event(self):
        request = EvaluationRequest(
            query="Run it",
            dataSourceId="database-one",
            skillId="skill-missing",
        )
        with patch("evaluation_api._load_skill", return_value={
            "success": False,
            "message": "Skill 不存在",
        }):
            response = await analyze_stream(request)
            events = await _collect_ndjson(response)

        self.assertEqual(events, [{
            "type": "error",
            "message": "Skill 不存在",
            "session_id": events[0]["session_id"],
        }])

    async def test_success_persists_structured_result_and_final_steps(self):
        async def workflow(**kwargs):
            yield {
                "type": "step",
                "step": {"step": "skill", "status": "in_progress"},
            }
            yield {
                "type": "step",
                "step": {"step": "skill", "status": "completed"},
            }
            yield {
                "type": "result",
                "final_answer": "Verified answer",
                "result": {
                    "type": "skill_query",
                    "final_answer": "Verified answer",
                    "queryResults": [],
                },
            }

        request = EvaluationRequest(
            query="Run it",
            session_id="session-test",
            dataSourceId="database-one",
            skillId="skill-one",
        )
        skill = {"id": "skill-one", "databaseId": "database-one", "steps": [{}]}
        with patch("evaluation_api._load_skill", return_value={
            "success": True,
            "skill": skill,
        }), patch("evaluation_api.run_langgraph_workflow", workflow), patch(
            "evaluation_api._save_session_to_file"
        ) as save:
            response = await analyze_stream(request)
            events = await _collect_ndjson(response)

        self.assertEqual([event["type"] for event in events], ["step", "step", "result"])
        self.assertEqual(events[-1]["session_id"], "session-test")
        save.assert_called_once()
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["execution_steps"], [{"step": "skill", "status": "completed"}])
        self.assertEqual(kwargs["result"]["type"], "skill_query")
        self.assertEqual(kwargs["skill_id"], "skill-one")


if __name__ == "__main__":
    unittest.main()
