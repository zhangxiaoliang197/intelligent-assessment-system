import asyncio
import datetime as dt
import unittest
from unittest.mock import patch

import main
from models import Report


class SharedSSESessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_subscribers_share_one_generation_and_resume_by_event_id(self):
        calls = 0

        async def fake_generate(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            yield "dataset", {"datasetId": "real_1", "source": "test", "summary": "real", "rows": 1}
            await asyncio.sleep(0)
            yield "done", {"reportId": "r_shared", "status": "ready", "partial": False}

        report = Report(reportId="r_shared", title="test", query="test")
        session = main._GenerationSession(report, None, {})

        async def collect(cursor=0):
            return [chunk async for chunk in main._stream_session(session, cursor)]

        with patch.object(main, "generate", fake_generate), \
             patch.object(main, "_persist", return_value=True), \
             patch.object(main, "_finish_skill_usage"):
            task = asyncio.create_task(main._run_generation("r_shared", session))
            first, second = await asyncio.gather(collect(), collect())
            await task
            resumed = await collect(cursor=1)

        self.assertEqual(calls, 1)
        self.assertEqual(first, second)
        self.assertTrue(any("event: dataset" in chunk for chunk in first))
        self.assertTrue(any("event: done" in chunk for chunk in first))
        self.assertFalse(any("event: dataset" in chunk for chunk in resumed))
        self.assertTrue(any("id: 2" in chunk and "event: done" in chunk for chunk in resumed))


if __name__ == "__main__":
    unittest.main()
