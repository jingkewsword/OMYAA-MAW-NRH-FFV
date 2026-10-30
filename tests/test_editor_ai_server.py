import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from maw.editor_ai_jobs import EditorAiJobs
from tests.test_local_editor_server import server_editor


class EditorAiServerTests(unittest.TestCase):
    def setUp(self):
        project = server_editor.ServerProject({"segments": []}, None, None, None, [])
        self.server = server_editor.EditorServer(("127.0.0.1", 0), project, no_waveform=True)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.binding = {"requestToken": self.server.request_token, **self.server.project_binding_payload()}

    def post(self, path, body, headers=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_job_is_bound_to_project_and_rejects_untrusted_origin_and_paths(self):
        payload = {**self.binding, "operation": "translate", "cues": [{"id": "a", "text": "hello", "start": 0, "end": 100}]}
        self.assertEqual(self.post('/api/editor-ai/start', payload, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post('/api/editor-ai/start', {**payload, "path": "ignored"})[0], 400)
        self.assertEqual(self.post('/api/editor-ai/start', {**payload, "requestToken": "bad"})[0], 403)
        with mock.patch.object(EditorAiJobs, "_compute", return_value={"translations": [{"id": "a", "text": "你好"}]}):
            status, job = self.post('/api/editor-ai/start', payload)
            self.assertEqual(status, 200)
            for _ in range(100):
                status, result = self.post('/api/editor-ai/status', {**self.binding, "id": job["id"]})
                if result["state"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(result["state"], "done")
            self.assertEqual(result["result"]["translations"][0]["text"], "你好")
            with self.server.settings_lock:
                self.server._bind_project_locked(self.server.project)
            self.assertEqual(self.post('/api/editor-ai/status', {**self.binding, "id": job["id"]})[0], 400)


if __name__ == '__main__':
    unittest.main()
