#!/usr/bin/env python3
"""本機 LLM 故障轉移代理（純標準庫）。
hermes → http://127.0.0.1:8090/v1 → 主：主機A Flash-Next；主掛了 → 備：mini-1 27B。
- 背景每 HEALTH_INTERVAL 秒 GET 主的 /health；狀態轉換寫 log。
- 每個請求選上游：主健康走主，否則走備；主在「送出任何位元組前」失敗會立刻改走備。
- 串流（SSE/chunked）逐塊直通；回應加 X-LLM-Upstream 標頭。
環境變數：LLM_PRIMARY、LLM_BACKUP、LLM_LISTEN_PORT、LLM_LOG。"""
import http.client, http.server, json, os, socketserver, sys, threading, time, urllib.parse

PRIMARY = os.environ.get("LLM_PRIMARY", "http://100.85.251.56:8080")
BACKUP  = os.environ.get("LLM_BACKUP",  "http://100.99.178.74:8080")
PORT    = int(os.environ.get("LLM_LISTEN_PORT", "8090"))
LOG     = os.environ.get("LLM_LOG", os.path.expanduser("~/llm-failover/proxy.log"))
HEALTH_INTERVAL = 5
CONNECT_TIMEOUT = 3
READ_TIMEOUT    = 900

_state = {"primary_up": False, "checked": 0.0}
_lock = threading.Lock()

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)

def _split(url):
    u = urllib.parse.urlparse(url); return u.hostname, u.port or 80

def probe(url):
    host, port = _split(url)
    try:
        c = http.client.HTTPConnection(host, port, timeout=CONNECT_TIMEOUT)
        c.request("GET", "/health"); r = c.getresponse(); ok = r.status == 200; c.close(); return ok
    except Exception:
        return False

def _ensure_stream_usage(path, body):
    # llama-server 串流只在帶 stream_options.include_usage 時回 usage；
    # hermes 主流程不帶，拿不到真實 prompt token 就會一直用粗估壓縮。這裡代它補上。
    if not body or not path.endswith("/chat/completions"):
        return body
    try:
        req = json.loads(body)
    except ValueError:
        return body
    if not isinstance(req, dict) or not req.get("stream"):
        return body
    opts = req.get("stream_options") if isinstance(req.get("stream_options"), dict) else {}
    if opts.get("include_usage"):
        return body
    req["stream_options"] = {**opts, "include_usage": True}
    return json.dumps(req, ensure_ascii=False).encode("utf-8")

def health_loop():
    while True:
        ok = probe(PRIMARY)
        with _lock:
            if ok != _state["primary_up"]:
                log(f"主上游 {'恢復 → 走 Flash-Next' if ok else '失聯 → 改走 27B 備援'} ({PRIMARY})")
            _state["primary_up"] = ok; _state["checked"] = time.time()
        time.sleep(HEALTH_INTERVAL)

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _forward(self, upstream, body):
        host, port = _split(upstream)
        c = http.client.HTTPConnection(host, port, timeout=READ_TIMEOUT)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "content-length", "accept-encoding")}
        headers["Host"] = f"{host}:{port}"; headers["Connection"] = "close"
        if body is not None: headers["Content-Length"] = str(len(body))
        c.request(self.command, self.path, body=body, headers=headers)
        return c, c.getresponse()

    def _proxy(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        body = _ensure_stream_usage(self.path, body)
        if self.path == "/__failover_status":
            with _lock: st = dict(_state)
            data = json.dumps({"primary": PRIMARY, "backup": BACKUP, "primary_up": st["primary_up"], "last_check_age_s": round(time.time() - st["checked"], 1)}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        with _lock: primary_up = _state["primary_up"]
        order = [("primary", PRIMARY), ("backup", BACKUP)] if primary_up else [("backup", BACKUP), ("primary", PRIMARY)]
        t0 = time.time(); last_err = None
        for name, up in order:
            try:
                conn, resp = self._forward(up, body)
            except Exception as e:
                last_err = e; log(f"{name} 連線失敗 {self.path}: {e!r}")
                if name == "primary":
                    with _lock: _state["primary_up"] = False
                continue
            self.send_response(resp.status)
            chunked = (resp.getheader("Transfer-Encoding") or "").lower() == "chunked"
            for k, v in resp.getheaders():
                if k.lower() in ("connection", "transfer-encoding", "content-length"): continue
                self.send_header(k, v)
            self.send_header("X-LLM-Upstream", name)
            if chunked: self.send_header("Transfer-Encoding", "chunked")
            elif resp.getheader("Content-Length"): self.send_header("Content-Length", resp.getheader("Content-Length"))
            self.send_header("Connection", "close"); self.end_headers()
            sent = 0
            try:
                while True:
                    chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                    if not chunk: break
                    if chunked: self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                    else: self.wfile.write(chunk)
                    self.wfile.flush(); sent += len(chunk)
                if chunked: self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
            finally:
                conn.close()
            log(f"{name} {self.command} {self.path} {resp.status} {sent}B {time.time()-t0:.1f}s")
            return
        msg = json.dumps({"error": {"message": f"主與備援都無法連線: {last_err!r}"}}).encode()
        self.send_response(503); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(msg))); self.end_headers(); self.wfile.write(msg)

    do_GET = do_POST = _proxy

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

if __name__ == "__main__":
    threading.Thread(target=health_loop, daemon=True).start()
    log(f"代理啟動 127.0.0.1:{PORT} 主={PRIMARY} 備={BACKUP}")
    Server(("127.0.0.1", PORT), Handler).serve_forever()
