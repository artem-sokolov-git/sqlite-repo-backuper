import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sqlite_repo_backuper.notify import notify_failure


def test_posts_json():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    notify_failure(f"http://127.0.0.1:{server.server_port}/fail", "boom")
    thread.join()
    server.server_close()
    assert received == [{"status": "error", "message": "boom"}]


def test_unreachable_webhook_is_swallowed():
    notify_failure("http://127.0.0.1:1/fail", "boom")
