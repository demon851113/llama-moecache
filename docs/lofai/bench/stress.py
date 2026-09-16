#!/usr/bin/env python3
"""60 分鐘混合負載壓力測試：短生成 / 工具呼叫 / 4.3K 長提示 / 中長上下文，序列打（-np 1）。
用法：python3 stress.py <分鐘> [port]；輸出 /data/src/stress.log（每請求一行）+ 結尾摘要。"""
import json, sys, time, urllib.request, subprocess, random, statistics

MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 60
PORT = sys.argv[2] if len(sys.argv) > 2 else "8080"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"
LOG = open("/data/src/stress.log", "a")
random.seed(20260916)

def log(line):
    s = time.strftime("%H:%M:%S") + " " + line
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

def post(body, timeout=900):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    dt = time.time() - t0
    t = d.get("timings", {})
    return d, dt, t

def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False

def gpu():
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,utilization.gpu",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:
        return f"nvidia-smi 失敗 {e}"

SYS = "你是資深後端工程師，用繁體中文回答。"
short_qs = [
    "解釋 TCP 三次握手，並說明為什麼不是兩次。",
    "寫一個 Python 函式，判斷字串是否為回文，需處理大小寫與空白。",
    "資金費率套利的風險有哪些？列 5 點。",
    "PostgreSQL 的 MVCC 是什麼？跟鎖有什麼差別？",
    "把這段話翻成英文：我們明天早上九點在會議室討論部署流程。",
    "說明 Rust 的 borrow checker 解決了什麼問題。",
]
TOOLS = [{"type": "function", "function": {"name": "get_price", "description": "查幣價",
          "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "exchange": {"type": "string"}},
                         "required": ["symbol"]}}}]
long_body = json.load(open("/data/src/long-req.json"))

def needle_prompt(words):
    filler = " ".join(random.choice(["市場", "交易所", "套利", "價差", "資金費率", "永續合約", "現貨", "掛單", "滑點", "手續費"]) for _ in range(words))
    key = random.randint(1000, 9999)
    pos = random.randint(len(filler) // 4, len(filler) * 3 // 4)
    text = filler[:pos] + f" 【通關密碼是 {key}】 " + filler[pos:]
    return text + "\n\n問題：上文中的通關密碼是多少？只回數字。", str(key)

kinds = ["short", "short", "tool", "long", "short", "needle"]
stats = {k: [] for k in kinds}
errors = 0; n = 0
t_end = time.time() + MIN * 60
log(f"=== 壓力測試開始 {MIN} 分鐘 port={PORT} gpu={gpu()} ===")
while time.time() < t_end:
    if not health():
        errors += 1; log("🔴 /health 失敗，中止"); break
    kind = kinds[n % len(kinds)]; n += 1
    try:
        if kind == "short":
            d, dt, t = post({"messages": [{"role": "system", "content": SYS}, {"role": "user", "content": random.choice(short_qs)}],
                             "max_tokens": 300, "temperature": 0.7, "chat_template_kwargs": {"enable_thinking": False}})
            extra = ""
        elif kind == "tool":
            d, dt, t = post({"messages": [{"role": "user", "content": "幫我查 BTC 在 binance 的價格"}], "tools": TOOLS,
                             "max_tokens": 200, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}})
            tc = d["choices"][0]["message"].get("tool_calls")
            extra = " tool_call=" + ("✅" if tc and tc[0]["function"]["name"] == "get_price" else "❌")
        elif kind == "long":
            d, dt, t = post(long_body)
            extra = ""
        else:
            p, key = needle_prompt(random.choice([3000, 6000, 9000]))
            d, dt, t = post({"messages": [{"role": "user", "content": p}], "max_tokens": 50, "temperature": 0,
                             "chat_template_kwargs": {"enable_thinking": False}})
            got = d["choices"][0]["message"]["content"].strip()
            extra = f" needle={'✅' if key in got else '❌ ' + got[:30]!r}"
        pp = t.get("prompt_n", 0); pps = t.get("prompt_per_second", 0); gen = t.get("predicted_n", 0); gps = t.get("predicted_per_second", 0)
        stats[kind].append((pps, gps))
        log(f"#{n} {kind:6s} prompt={pp} @{pps:.0f} t/s gen={gen} @{gps:.1f} t/s wall={dt:.1f}s{extra}")
    except Exception as e:
        errors += 1
        log(f"🔴 #{n} {kind} 失敗: {e!r}")
        if errors >= 3:
            log("連續錯誤達 3 次，中止"); break
    if n % 12 == 0:
        log(f"   gpu={gpu()}")

log(f"=== 結束 請求={n} 錯誤={errors} gpu={gpu()} ===")
for k in ["short", "tool", "long", "needle"]:
    v = stats[k]
    if v:
        g = [x[1] for x in v if x[1]]; p = [x[0] for x in v if x[0]]
        log(f"   {k:6s} n={len(v)} 生成 中位={statistics.median(g):.1f} 最低={min(g):.1f} 最高={max(g):.1f} t/s | 預填 中位={statistics.median(p):.0f} t/s")
try:
    dm = subprocess.run(["bash", "-c", "dmesg 2>/dev/null | tail -5 | grep -Ei 'oops|lockup|general protection|NVRM: Xid' || echo '無'"],
                        capture_output=True, text=True, timeout=10).stdout.strip()
    log("   dmesg 異常: " + dm)
except Exception:
    pass
