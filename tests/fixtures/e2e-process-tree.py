"""Synthetic wrapper/server only: no application, settings, or browser access."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

port = int(sys.argv[sys.argv.index('--port') + 1])
root = Path(os.environ['MAW_APP_DATA_ROOT']).parent
mode = (Path.cwd() / 'scenario.txt').read_text()
if '--leaf' not in sys.argv:
    (root / 'runtime-environment.json').write_text(json.dumps({
        'localAppData': os.environ.get('LOCALAPPDATA'),
        'parentOnlyMarker': 'MAW_LIFECYCLE_PARENT_ONLY' in os.environ,
    }))
    child = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], '--leaf'], stdin=subprocess.PIPE)
    (root / 'owned-pids.json').write_text(json.dumps([os.getpid(), child.pid]))
    # The leaf must not advertise readiness until the process evidence is complete.
    assert child.stdin is not None
    child.stdin.write(b'1')
    child.stdin.close()
    if mode == 'wrapper-exit':
        sys.exit(7)
    child.wait()
else:
    # Bound the handshake too, without keeping an EOF-exiting leaf alive.
    watchdog = threading.Timer(60, lambda: os._exit(91))
    watchdog.daemon = True
    watchdog.start()
    if os.environ.get('MAW_LIFECYCLE_TEST_HANDSHAKE'):
        print('LEAF_WAITING', flush=True)
    # EOF means the wrapper died before publishing complete evidence.
    if sys.stdin.buffer.read(1) != b'1':
        watchdog.cancel()
        sys.exit(1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if mode == 'hang':
                threading.Event().wait(60)
                return
            self.send_response(200)
            self.end_headers()
            status = {'startup-error': 'error', 'wrapper-exit': 'loading'}.get(mode, 'ready')
            self.wfile.write(json.dumps({'status': status}).encode())

        def log_message(self, *_args):
            pass

    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
