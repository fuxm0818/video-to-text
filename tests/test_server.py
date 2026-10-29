import http.client
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_text import config, server  # noqa: E402


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        patcher = mock.patch.object(config, "config_dir", lambda: root / "config")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = server.AppContext(
            output_dir=str(root / "out"), check_models=False, token="test-token"
        )
        self.httpd = server.create_server(self.ctx, 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.ctx.manager.shutdown()
        self.tmp.cleanup()

    def _request(self, path, method="GET", token=None, origin=None, body=None):
        headers = {}
        if token:
            headers["X-V2T-Token"] = token
        if origin:
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_index_and_static_assets(self):
        status, body = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())
        for asset in ("/static/app.js", "/static/style.css", "/static/logo.svg"):
            self.assertEqual(self._request(asset)[0], 200, asset)

    def test_health_is_public(self):
        status, body = self._request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_api_requires_token(self):
        self.assertEqual(self._request("/api/state")[0], 403)
        self.assertEqual(self._request("/api/state", token="wrong")[0], 403)
        status, body = self._request("/api/state", token="test-token")
        self.assertEqual(status, 200)
        self.assertIn("settings", json.loads(body))

    def test_post_rejects_foreign_origin(self):
        status, _ = self._request(
            "/api/clear", method="POST", token="test-token",
            origin="http://evil.example", body={},
        )
        self.assertEqual(status, 403)

        status, _ = self._request(
            "/api/clear", method="POST", token="test-token",
            origin=f"http://127.0.0.1:{self.port}", body={},
        )
        self.assertEqual(status, 200)

    def test_foreign_host_header_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.putrequest("GET", "/", skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", "evil.example")
            conn.endheaders()
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()
        self.assertEqual(resp.status, 403)

    def test_file_endpoint_requires_query_token(self):
        self.assertEqual(self._request("/api/file?token=bad")[0], 403)

    def test_existing_instance_probe(self):
        self.assertTrue(server._existing_instance(self.port))

    def test_settings_validation_through_context(self):
        with self.assertRaises(RuntimeError):
            self.ctx.update_settings({"formats": [], "audio_format": "none"})
        file_path = Path(self.tmp.name) / "not-a-dir.txt"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.ctx.update_settings({"output_dir": str(file_path)})
        settings = self.ctx.update_settings({"workers": 99})
        self.assertEqual(settings["workers"], 4)


if __name__ == "__main__":
    unittest.main()
