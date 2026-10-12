import asyncio
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('rename_api', Path(__file__).parents[1] / 'backend/rename_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class UploadRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        api._task = None
        api._start_lock = asyncio.Lock()
        self.calls = []

        async def fake(action, payload=None):
            self.calls.append((action, payload))
            return {'ok': True}

        api.call_script = fake

    async def test_dispatch_and_request_identity(self):
        await api.run_upload_batch({'request_id': 'upload527-20261012-v1'})
        self.assertEqual(self.calls, [('upload_run', {'request_id': 'upload527-20261012-v1'})])

    async def test_no_run_during_rename(self):
        api._task = asyncio.create_task(asyncio.Event().wait())
        try:
            with self.assertRaises(api.HTTPException) as error:
                await api.run_upload_batch({'request_id': 'upload527-20261012-v1'})
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(self.calls, [])
        finally:
            api._task.cancel()

    async def test_invalid_request_is_rejected(self):
        with self.assertRaises(api.HTTPException):
            await api.run_upload_batch({'request_id': 'different/file'})
        self.assertEqual(self.calls, [])

    async def test_token_required(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'RENAME_API_TOKEN': 'test-only-token'}):
            with self.assertRaises(api.HTTPException):
                api.authorize_rename('Bearer wrong')
            api.authorize_rename('Bearer test-only-token')


if __name__ == '__main__':
    unittest.main()
