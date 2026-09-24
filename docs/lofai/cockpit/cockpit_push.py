#!/usr/bin/env python3
"""mini-1 → 主機A 駕駛台：每 5 秒回報 hermes 走哪台（failover proxy 狀態）與 proxy 最近幾筆。只用標準庫。"""
import json, os, re, time, urllib.request

PROXY = os.environ.get("LLM_PROXY_URL", "http://127.0.0.1:8090")
PROXY_LOG = os.path.expanduser(os.environ.get("LLM_PROXY_LOG", "~/llm-failover/proxy.log"))
COCKPIT = os.environ.get("COCKPIT_URL", "http://100.85.251.56:8091/api/push")
RE_LINE = re.compile(r"^(\S+ \S+) (primary|backup) (\w+) (\S+) (\d+) (\d+)B ([\d.]+)s")


def tail_lines(path, n=8, maxbytes=32768):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - maxbytes))
            lines = f.read().decode("utf-8", "replace").splitlines()
        out = []
        for l in reversed(lines):
            m = RE_LINE.match(l)
            if m and m.group(4).endswith("/chat/completions"):
                out.append({"t": m.group(1), "route": m.group(2), "status": int(m.group(5)), "bytes": int(m.group(6)), "secs": float(m.group(7))})
                if len(out) >= n:
                    break
        return out
    except Exception:
        return []


def main():
    while True:
        try:
            with urllib.request.urlopen(PROXY + "/__failover_status", timeout=3) as r:
                st = json.loads(r.read().decode())
        except Exception:
            st = {"primary_up": None}
        body = {"primary_up": st.get("primary_up"), "proxy_alive": st.get("primary_up") is not None,
                "recent": tail_lines(PROXY_LOG), "host": "mini-1"}
        try:
            req = urllib.request.Request(COCKPIT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass
        time.sleep(5)


if __name__ == "__main__":
    main()
