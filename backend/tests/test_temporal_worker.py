import unittest
from unittest.mock import patch

from app.temporal_worker import connect_temporal_client


class TemporalWorkerTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_connect_temporal_client_retries_until_success(self) -> None:
        attempts = 0

        class FakeClient:
            @staticmethod
            async def connect(target: str, namespace: str):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise RuntimeError("connection refused")
                return {
                    "target": target,
                    "namespace": namespace,
                }

        async def noop_sleep(_: float) -> None:
            return None

        with patch("app.temporal_worker.asyncio.sleep", new=noop_sleep):
            result = await connect_temporal_client(
                FakeClient,
                "temporal:7233",
                "default",
                max_attempts=3,
                delay_seconds=0.01,
            )

        self.assertEqual(attempts, 3)
        self.assertEqual(result["target"], "temporal:7233")
        self.assertEqual(result["namespace"], "default")

    async def test_connect_temporal_client_raises_after_max_attempts(self) -> None:
        attempts = 0

        class FakeClient:
            @staticmethod
            async def connect(target: str, namespace: str):
                nonlocal attempts
                attempts += 1
                raise RuntimeError("connection refused")

        async def noop_sleep(_: float) -> None:
            return None

        with patch("app.temporal_worker.asyncio.sleep", new=noop_sleep):
            with self.assertRaises(RuntimeError):
                await connect_temporal_client(
                    FakeClient,
                    "temporal:7233",
                    "default",
                    max_attempts=2,
                    delay_seconds=0.01,
                )

        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
