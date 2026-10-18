"""Temporary TLS-tunnel origin with bounded, agent-only public ingress.

The full operator/collector API stays on a separate loopback port. The public
origin exposes only this run's admission/output checks, status and inference.
"""

import argparse
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.service import Application, MAX_BODY, server


def ingress(port, private_port, run_id, token):
    slots = threading.BoundedSemaphore(8)
    recent = deque()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def reply(self, status, body=b'{}', content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.reply(401)
                return
            allowed = ({'/runs/' + run_id} if self.command == 'GET' else {
                '/runs/' + run_id + '/admission', '/runs/' + run_id + '/output-check', '/v1/chat/completions'})
            if self.path not in allowed:
                self.reply(403)
                return
            with lock:
                now = time.monotonic()
                while recent and recent[0] < now - 60:
                    recent.popleft()
                if len(recent) >= 120:
                    self.reply(429)
                    return
                recent.append(now)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.reply(400)
                return
            if not 0 <= size <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                self.reply(413)
                return
            try:
                body = self.rfile.read(size) if self.command == 'POST' else None
                req = Request(f'http://127.0.0.1:{private_port}' + self.path,
                              data=body, method=self.command,
                              headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                try:
                    response = urlopen(req, timeout=45)
                except HTTPError as exc:
                    response = exc
                with response:
                    data = response.read(MAX_BODY + 1)
                    if len(data) > MAX_BODY:
                        self.reply(502)
                        return
                    self.reply(response.code, data, response.headers.get('Content-Type', 'application/json'))
            except (OSError, ValueError):
                self.reply(503)

    class BoundedServer(ThreadingHTTPServer):
        daemon_threads = True

        def process_request(self, request, client_address):
            if not slots.acquire(blocking=False):
                request.close()
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                slots.release()

    return BoundedServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--provider-key-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--private-port', type=int, default=8081)
    args = parser.parse_args()
    folder = args.directory
    app = Application(folder / 'controller.sqlite', (folder / 'collector.key').read_bytes(),
                      json.loads((folder / 'auth.json').read_text()),
                      json.loads((folder / 'gateway.json').read_text()), folder / 'staged',
                      provider_key=args.provider_key_file.read_text().strip())
    private = server(app, port=args.private_port)
    worker = threading.Thread(target=private.serve_forever, daemon=True)
    worker.start()
    token = json.loads((folder / 'credentials.json').read_text())['agent']
    public = ingress(args.port, args.private_port, args.run, token)
    print('Pilot controller ready. Public ingress is agent-only; operator API is loopback-only.', flush=True)
    try:
        public.serve_forever()
    finally:
        public.server_close()
        private.shutdown()
        private.server_close()


if __name__ == '__main__':
    main()
