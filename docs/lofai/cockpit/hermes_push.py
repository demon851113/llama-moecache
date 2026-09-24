#!/usr/bin/env python3
"""mini-2 → 主機A 駕駛台：每 30 秒回報 hermes 有沒有在跑、它的模型連到哪台。只用標準庫（相容 macOS 內建 Python 3.9）。

取代舊的 mini-1 cockpit_push.py（mini-1 的 failover proxy 已停用，hermes 2026-09 起在 mini-2 直連主機A）。
"""
import json, os, re, subprocess, time, urllib.request

COCKPIT = os.environ.get("COCKPIT_URL", "http://100.85.251.56:8091/api/push")
CONFIG = os.path.expanduser(os.environ.get("HERMES_CONFIG", "~/.hermes/config.yaml"))
LABEL = "ai.hermes.gateway"
KNOWN = {"100.85.251.56": "主機A"}


def hermes_pid():
    out = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True, timeout=5).stdout
    m = re.search(r'"PID"\s*=\s*(\d+);', out)
    return int(m.group(1)) if m else None


def model_route():
    # 只讀 config.yaml 最上層 model 區塊的 base_url（hermes 主模型的去處），其他設定不碰
    try:
        text = open(CONFIG).read()
    except OSError:
        return None
    m = re.search(r"^model:\s*\n((?:[ \t]+.*\n)+)", text, re.M)
    u = re.search(r"base_url:\s*(\S+)", m.group(1)) if m else None
    if not u:
        return None
    host = re.sub(r"^https?://", "", u.group(1)).split("/")[0].split(":")[0]
    return KNOWN.get(host, host)


def main():
    while True:
        try:
            pid = hermes_pid()
        except Exception:
            pid = None
        body = {"host": "mini-2", "hermes_up": pid is not None, "route": model_route()}
        try:
            req = urllib.request.Request(COCKPIT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
        time.sleep(30)


if __name__ == "__main__":
    main()
