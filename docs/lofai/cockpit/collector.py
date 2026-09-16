#!/usr/bin/env python3
"""主機A 駕駛台收集器：只用標準庫。

每 2 秒讀 nvidia-smi、/proc、llama-server 的 /slots 與 log；每 30 秒讀慢速項（df、hwmon、tailscale、systemd、dmesg）。
提供 /api/now、/api/history、/api/events、/api/push（mini-1 回報 hermes 路徑）與首頁。
只綁 Tailscale IP；沒有驗證，靠 tailnet 隔離。
"""
import collections, json, os, re, statistics, subprocess, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("COCKPIT_HOST", "100.85.251.56")
PORT = int(os.environ.get("COCKPIT_PORT", "8091"))
LLAMA = os.environ.get("COCKPIT_LLAMA", "http://100.85.251.56:8080")
LOG = os.environ.get("COCKPIT_LOG", "/data/src/server-current.log")
SERVICE = os.environ.get("COCKPIT_SERVICE", "flash-next.service")
STATE_DIR = os.environ.get("COCKPIT_STATE", "/data/src/cockpit")
HERE = os.path.dirname(os.path.abspath(__file__))
EXPERT_MB = 1.97
N_LAYERS, N_ATTN_LAYERS, KV_BYTES_PER_TOKEN_LAYER = 48, 12, 1088

_lock = threading.Lock()
now = {"ts": 0}
slow = {}
static = {}
peer = {"ts": 0}
requests_ring = collections.deque(maxlen=200)
events = collections.deque(maxlen=300)
minute_ring = collections.deque(maxlen=1440)
_minute_bucket = {"m": None, "tps": [], "req": 0, "temp": [], "watt": [], "pcie": []}
_live = {"tg": None, "tg_ts": 0, "n_gen": 0, "task": None, "prompt_tps": None, "ttft": None, "accept": None, "mean_len": None}
_cpu_prev = None
_io_prev = None


def sh(cmd, timeout=8):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def add_event(kind, level, text):
    with _lock:
        if events and events[-1]["text"] == text and time.time() - events[-1]["ts"] < 600:
            return
        events.append({"ts": time.time(), "kind": kind, "level": level, "text": text})
    save_state()


def save_state():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, "state.json.tmp"), "w") as f:
            json.dump({"minute": list(minute_ring), "events": list(events), "requests": list(requests_ring)}, f)
        os.replace(os.path.join(STATE_DIR, "state.json.tmp"), os.path.join(STATE_DIR, "state.json"))
    except Exception:
        pass


def load_state():
    try:
        with open(os.path.join(STATE_DIR, "state.json")) as f:
            d = json.load(f)
        cutoff = time.time() - 86400
        minute_ring.extend(x for x in d.get("minute", []) if x["ts"] > cutoff)
        events.extend(d.get("events", []))
        requests_ring.extend(d.get("requests", []))
    except Exception:
        pass


# ---------- 快速項 ----------
def read_gpu():
    out = sh(["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,power.limit,fan.speed,clocks.sm,utilization.gpu,memory.used,memory.total,pcie.link.gen.current,pcie.link.width.current",
              "--format=csv,noheader,nounits"])
    g = {}
    try:
        v = [x.strip() for x in out.strip().split(",")]
        g = {"temp": float(v[0]), "watt": float(v[1]), "watt_limit": float(v[2]), "fan": float(v[3]), "clock": float(v[4]),
             "util": float(v[5]), "vram_used": float(v[6]), "vram_total": float(v[7]), "pcie_gen": int(v[8]), "pcie_width": int(v[9])}
    except Exception:
        pass
    dm = sh(["nvidia-smi", "dmon", "-s", "t", "-c", "1"], timeout=6)
    for line in dm.splitlines():
        if line.strip() and not line.startswith("#"):
            p = line.split()
            try:
                g["pcie_rx_gbs"] = float(p[1]) / 1000.0
                g["pcie_tx_gbs"] = float(p[2]) / 1000.0
            except Exception:
                pass
    return g


def read_cpu():
    global _cpu_prev
    d = {}
    try:
        with open("/proc/loadavg") as f:
            la = f.read().split()
        d["load1"], d["load5"], d["load15"] = float(la[0]), float(la[1]), float(la[2])
        d["ncpu"] = os.cpu_count()
        with open("/proc/stat") as f:
            p = f.readline().split()[1:]
        vals = list(map(int, p))
        idle, total = vals[3] + vals[4], sum(vals)
        if _cpu_prev:
            di, dt = idle - _cpu_prev[0], total - _cpu_prev[1]
            d["util"] = round(100.0 * (1 - di / dt), 1) if dt else 0.0
        _cpu_prev = (idle, total)
        with open("/proc/meminfo") as f:
            mi = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
        d["mem_total_gb"] = mi["MemTotal"] / 1e6
        d["mem_used_gb"] = (mi["MemTotal"] - mi["MemAvailable"]) / 1e6
    except Exception:
        pass
    return d


def llama_pid():
    out = sh(["pgrep", "-f", "build/bin/llama-server"])
    for tok in out.split():
        if tok.isdigit():
            return int(tok)
    return None


def read_proc(pid):
    global _io_prev
    d = {}
    if not pid:
        return d
    try:
        with open(f"/proc/{pid}/status") as f:
            for l in f:
                if l.startswith("VmRSS:"):
                    d["rss_gb"] = int(l.split()[1]) / 1e6
        with open(f"/proc/{pid}/io") as f:
            io = {l.split(":")[0]: int(l.split()[1]) for l in f}
        t = time.time()
        if _io_prev and _io_prev[0] == pid:
            dt = t - _io_prev[2]
            d["read_mbs"] = (io["read_bytes"] - _io_prev[1]) / 1e6 / dt if dt > 0 else 0
        _io_prev = (pid, io["read_bytes"], t)
    except Exception:
        pass
    return d


def http_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


RE_TG = re.compile(r"task (\d+) \| n_gen =\s*(\d+), tg =\s*([\d.]+) t/s, tg_3s =\s*([\d.]+)")
RE_PROMPT = re.compile(r"task (\d+) \| prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second")
RE_EVAL = re.compile(r"task (\d+) \|\s+eval time =\s*([\d.]+) ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second")
RE_ACCEPT = re.compile(r"task (\d+) \| draft acceptance = ([\d.]+) \(\s*(\d+) accepted /\s*(\d+) generated\), mean len =\s*([\d.]+)")
RE_RELEASE = re.compile(r"release: id\s+\d+ \| task (\d+) \| stop processing: n_tokens = (\d+)")
RE_ERR = re.compile(r"cudaMalloc failed|CUDA error|GGML_ASSERT|out of memory|\bE srv\b|\bE ggml\b")
_pending = {}
_log_pos = None


def tail_log():
    global _log_pos
    try:
        size = os.path.getsize(LOG)
        if _log_pos is None or size < _log_pos:
            _log_pos = max(0, size - 65536)
        with open(LOG, "rb") as f:
            f.seek(_log_pos)
            chunk = f.read()
            _log_pos = f.tell()
    except Exception:
        return
    for raw in chunk.decode("utf-8", "replace").splitlines():
        m = RE_TG.search(raw)
        if m:
            _live.update({"task": m.group(1), "n_gen": int(m.group(2)), "tg": float(m.group(3)), "tg_3s": float(m.group(4)), "tg_ts": time.time()})
            continue
        m = RE_PROMPT.search(raw)
        if m:
            _pending.setdefault(m.group(1), {})
            _pending[m.group(1)].update({"ttft_s": float(m.group(2)) / 1000, "prompt": int(m.group(3)), "prefill_tps": float(m.group(4))})
            continue
        m = RE_EVAL.search(raw)
        if m:
            _pending.setdefault(m.group(1), {}).update({"gen": int(m.group(3)), "tps": float(m.group(4))})
            continue
        m = RE_ACCEPT.search(raw)
        if m:
            _pending.setdefault(m.group(1), {}).update({"accept": float(m.group(2)), "mean_len": float(m.group(5))})
            _live.update({"accept": float(m.group(2)), "mean_len": float(m.group(5))})
            continue
        m = RE_RELEASE.search(raw)
        if m:
            rec = _pending.pop(m.group(1), {})
            rec.update({"ts": time.time(), "task": int(m.group(1)), "n_ctx_used": int(m.group(2))})
            if "tps" in rec:
                with _lock:
                    requests_ring.append(rec)
                    _minute_bucket["tps"].append(rec["tps"])
                    _minute_bucket["req"] += 1
                _live["prompt_tps"], _live["ttft"] = rec.get("prefill_tps"), rec.get("ttft_s")
            continue
        if RE_ERR.search(raw):
            add_event("model", "crit", raw[-160:])


def read_service():
    out = sh(["systemctl", "show", SERVICE, "-p", "NRestarts,ActiveState,ActiveEnterTimestampMonotonic,ActiveEnterTimestamp"])
    d = {}
    for l in out.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            d[k] = v
    return d


def fast_loop():
    prev_restarts = None
    while True:
        t0 = time.time()
        g = read_gpu()
        c = read_cpu()
        pid = llama_pid()
        p = read_proc(pid)
        slots = http_json(f"{LLAMA}/slots")
        health = http_json(f"{LLAMA}/health")
        tail_log()
        svc = read_service()
        slot = slots[0] if isinstance(slots, list) and slots else {}
        if slot.get("is_processing") and slot.get("id_task") is not None:
            _pending.setdefault(str(slot["id_task"]), {}).update({"cached": slot.get("n_prompt_tokens_cache"), "prompt_total": slot.get("n_prompt_tokens")})
        state = "idle"
        if slot.get("is_processing"):
            npt, npp = slot.get("n_prompt_tokens", 0), slot.get("n_prompt_tokens_processed", 0)
            state = "prefill" if (npp < npt and time.time() - _live["tg_ts"] > 5) else "generating"
        live_tps = _live["tg"] if time.time() - _live["tg_ts"] < 6 and state == "generating" else None
        ctx_used = (slot.get("n_prompt_tokens") or 0) + (_live["n_gen"] if state == "generating" else 0)
        if state == "idle" and requests_ring:
            ctx_used = requests_ring[-1].get("n_ctx_used", 0)
        n_ctx = slot.get("n_ctx") or 131072
        cache_slots = static.get("cache_slots", 56)
        kv_gb = N_ATTN_LAYERS * n_ctx * KV_BYTES_PER_TOKEN_LAYER / 1e9
        cache_gb = N_LAYERS * cache_slots * EXPERT_MB / 1e3
        vram = {"cache": round(cache_gb, 2), "dense": 4.0, "mtp": 2.0, "kv": round(kv_gb, 2)}
        used = g.get("vram_used", 0) / 1024
        vram["other"] = round(max(0.0, used - sum(vram.values())), 2)
        vram["free"] = round(max(0.0, g.get("vram_total", 16303) / 1024 - used), 2)
        if prev_restarts is not None and svc.get("NRestarts") != prev_restarts:
            add_event("host", "info", f"{SERVICE} 重啟（第 {svc.get('NRestarts')} 次）")
        prev_restarts = svc.get("NRestarts")
        if g.get("temp", 0) >= 80:
            add_event("host", "warn", f"GPU 溫度 {g['temp']:.0f} °C")
        recent10 = list(requests_ring)[-10:]
        def med(k):
            v = sorted(r[k] for r in recent10 if r.get(k) is not None)
            return v[len(v) // 2] if v else None
        rolling = {"n": len(recent10), "tps": med("tps"), "accept": med("accept"), "prefill_tps": med("prefill_tps"), "ttft_s": med("ttft_s"), "mean_len": med("mean_len")}
        with _lock:
            now.update({
                "rolling": rolling, "last_request": (recent10[-1] if recent10 else None),
                "ts": time.time(), "gpu": g, "cpu": c, "proc": p, "pid": pid,
                "service": {"active": svc.get("ActiveState"), "restarts": svc.get("NRestarts"), "since": svc.get("ActiveEnterTimestamp")},
                "health": bool(health and health.get("status") == "ok"),
                "slot": {"state": state, "n_ctx": n_ctx, "ctx_used": ctx_used, "prompt_tokens": slot.get("n_prompt_tokens"),
                         "prompt_processed": slot.get("n_prompt_tokens_processed"), "prompt_cached": slot.get("n_prompt_tokens_cache"),
                         "n_gen": _live["n_gen"] if state == "generating" else 0, "task": slot.get("id_task")},
                "live": {"tps": live_tps, "accept": _live["accept"], "mean_len": _live["mean_len"], "prefill_tps": _live["prompt_tps"], "ttft_s": _live["ttft"]},
                "vram": vram, "cache_slots": cache_slots,
            })
            mb = _minute_bucket
            m = int(time.time() // 60)
            if mb["m"] is not None and m != mb["m"]:
                minute_ring.append({"ts": mb["m"] * 60, "tps": round(statistics.median(mb["tps"]), 1) if mb["tps"] else None,
                                    "req": mb["req"], "temp": round(statistics.mean(mb["temp"]), 1) if mb["temp"] else None,
                                    "watt": round(statistics.mean(mb["watt"]), 0) if mb["watt"] else None,
                                    "pcie": round(statistics.mean(mb["pcie"]), 1) if mb["pcie"] else None})
                mb.update({"tps": [], "req": 0, "temp": [], "watt": [], "pcie": []})
                threading.Thread(target=save_state, daemon=True).start()
            mb["m"] = m
            if "temp" in g:
                mb["temp"].append(g["temp"]); mb["watt"].append(g.get("watt", 0)); mb["pcie"].append(g.get("pcie_rx_gbs", 0))
        time.sleep(max(0.5, 2.0 - (time.time() - t0)))


# ---------- 慢速項 ----------
def read_hwmon():
    d = {"nvme": [], "dimm": []}
    base = "/sys/class/hwmon"
    try:
        for h in sorted(os.listdir(base)):
            p = os.path.join(base, h)
            try:
                name = open(os.path.join(p, "name")).read().strip()
                t = int(open(os.path.join(p, "temp1_input")).read()) / 1000
            except Exception:
                continue
            if name == "k10temp":
                d["cpu_temp"] = t
            elif name == "nvme":
                d["nvme"].append(t)
            elif name == "spd5118":
                d["dimm"].append(t)
    except Exception:
        pass
    return d


def read_dmesg():
    out = sh(["sudo", "-n", "dmesg", "--time-format", "iso"], timeout=10)
    bad = [l for l in out.splitlines()[-400:] if re.search(r"NVRM: Xid|general protection|Oops|BUG:|segfault|fallen off the bus", l)
           and not re.search(r"traps: (ptxas|cicc|nvcc|cc1plus|python)", l)]
    return {"count": len(bad), "last": bad[-1][-160:] if bad else ""}


_dmesg_seen = ""


def slow_loop():
    global _dmesg_seen
    first = True
    while True:
        d = {}
        d["hwmon"] = read_hwmon()
        df = sh(["df", "-BG", "--output=target,used,size", "/data", "/"])
        d["disks"] = [{"mount": l.split()[0], "used_gb": int(l.split()[1].rstrip("G")), "size_gb": int(l.split()[2].rstrip("G"))}
                      for l in df.splitlines()[1:] if l.strip()]
        tsj = sh(["tailscale", "status", "--json"], timeout=6)
        try:
            j = json.loads(tsj); d["tailscale"] = {"online": j["Self"]["Online"], "ip": j["Self"]["TailscaleIPs"][0]}
        except Exception:
            d["tailscale"] = {"online": None, "ip": HOST}
        dm = read_dmesg()
        d["dmesg"] = dm
        if dm["last"] and dm["last"] != _dmesg_seen and not first:
            add_event("host", "crit", "dmesg: " + dm["last"])
        _dmesg_seen = dm["last"]
        up = sh(["cut", "-d ", "-f1", "/proc/uptime"])
        try:
            d["uptime_s"] = float(up)
        except Exception:
            pass
        with _lock:
            slow.update(d)
        first = False
        time.sleep(30)


def read_static():
    s = {}
    s["driver"] = sh(["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"]).strip()
    s["kernel"] = sh(["uname", "-r"]).strip()
    s["os"] = sh(["lsb_release", "-ds"]).strip()
    cpu = sh(["lscpu"])
    m = re.search(r"Model name:\s+(.*)", cpu)
    s["cpu_model"] = m.group(1).strip() if m else ""
    dmi = sh(["sudo", "-n", "dmidecode", "-t", "17"], timeout=10)
    speeds = re.findall(r"Configured Memory Speed: (\d+) MT/s", dmi)
    sizes = re.findall(r"\tSize: (\d+) GB", dmi)
    s["ddr"] = f"{len(sizes)} 條 {'+'.join(sizes)} GB · {speeds[0] if speeds else '?'} MT/s"
    pid = llama_pid()
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode().split("\0")
        for i, a in enumerate(cmd):
            if a == "--moe-expert-cache-size":
                s["cache_slots"] = int(cmd[i + 1])
            if a == "-m":
                s["model"] = os.path.basename(cmd[i + 1]).replace("-00001-of-00003.gguf", "")
            if a in ("-ub", "--ubatch-size"):
                s["ub"] = cmd[i + 1]
            if a == "--spec-draft-n-max":
                s["draft_n"] = cmd[i + 1]
        s["cwd"] = os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        pass
    try:
        env = dict(os.environ, LD_LIBRARY_PATH="/data/src/llama-moecache/build/bin:/usr/local/cuda/lib64")
        ver = subprocess.run(["/data/src/llama-moecache/build/bin/llama-server", "--version"], capture_output=True, text=True, timeout=10, env=env)
        ver = ver.stdout + ver.stderr
    except Exception:
        ver = ""
    m = re.search(r"commit ([0-9a-f]+)", ver)
    s["commit"] = m.group(1) if m else ""
    props = http_json(f"{LLAMA}/props")
    if props:
        s["alias"] = (props.get("model_alias") or "")
    return s


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                data = open(os.path.join(HERE, "index.html"), "rb").read()
            except Exception:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        with _lock:
            if path == "/api/now":
                body = dict(now); body["slow"] = dict(slow); body["static"] = dict(static); body["peer"] = dict(peer)
                body["recent"] = list(requests_ring)[-8:][::-1]
                self._json(body); return
            if path == "/api/history":
                self._json({"minute": list(minute_ring)}); return
            if path == "/api/events":
                self._json({"events": list(events)[-40:][::-1]}); return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/push":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(n).decode())
            except Exception:
                self._json({"error": "bad json"}, 400); return
            with _lock:
                prev = peer.get("primary_up")
                peer.clear(); peer.update(d); peer["ts"] = time.time()
            if prev is not None and prev != d.get("primary_up"):
                add_event("model", "warn" if not d.get("primary_up") else "good",
                          "hermes 切到備援 mini-1 27B" if not d.get("primary_up") else "hermes 切回主機A")
            self._json({"ok": True}); return
        self._json({"error": "not found"}, 404)


def main():
    load_state()
    static.update(read_static())
    threading.Thread(target=fast_loop, daemon=True).start()
    threading.Thread(target=slow_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"cockpit on http://{HOST}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
