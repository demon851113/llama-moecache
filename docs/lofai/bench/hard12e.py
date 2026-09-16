import json, sys, urllib.request, time, re, random
PORT = sys.argv[1]; LABEL = sys.argv[2]; EFFORT = sys.argv[3]
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"
def chat(msgs, think, max_tokens=16000, tools=None):
    sp = {"temperature":1.0,"top_p":0.95,"top_k":20} if think else {"temperature":0.7,"top_p":0.8,"top_k":20,"presence_penalty":1.5}
    body = {"messages":msgs,"max_tokens":max_tokens,"chat_template_kwargs":{"enable_thinking":think,"reasoning_effort":EFFORT},**sp}
    if tools: body["tools"]=tools
    t0=time.time()
    j = json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type":"application/json"}), timeout=1500))
    m = j["choices"][0]["message"]; return m, time.time()-t0, len(m.get("reasoning_content") or "")
def show(tag, key, m, dt, rc, extra=""):
    c=(m.get("content") or "").strip()
    print(f"\n===== [{LABEL}] {tag} | {dt:.0f}s | 思考 {rc} 字 {extra}\n標準：{key}\n{c[:700].replace(chr(10)+chr(10),chr(10))}", flush=True)

# T1 多路徑選路（正解：路徑2 +7.85；C 的最低提幣量無關）
T1 = """有三條跨所套利路徑，每條都是買 20 枚 X 幣、提幣、全數賣出，手續費以 USDT 計：
路徑1：A 所買 100.00（吃單費 0.1%）→ 提到 B 所（提幣費 0.5 枚）→ B 所賣 101.50（吃單費 0.1%）
路徑2：A 所買 100.00（吃單費 0.1%）→ 提到 C 所（提幣費 0.1 枚）→ C 所賣 101.20（吃單費 0.2%）
路徑3：D 所買 99.80（吃單費 0.05%）→ 提到 B 所（提幣費 0.5 枚）→ B 所賣 101.50（吃單費 0.1%）
另外已知：C 所的最低提幣量是 25 枚。
請一步一步算出三條路徑各自的淨利（USDT，小數第二位），選出最佳路徑，並說明「C 所最低提幣量 25 枚」對這個決定有沒有影響、為什麼。"""
m,dt,rc = chat([{"role":"user","content":T1}], True); show("T1 選路", "路徑2 +7.85（路徑1 −24.73、路徑3 −19.73）；C 的最低提幣量無關，因為提幣是從 A 所出", m,dt,rc)

# T2 三個 bug（正解：n 應為 24//interval_hours*days；range(1,n) 少算一次；多單付費應為負、空單為正）
T2 = """審查這段計算永續合約資金費損益的函式。規格：side 是 "long" 或 "short"；notional 是持倉名目 USDT；rates_pct 是每次結算的費率清單（百分比，0.01 代表 0.01%），依序循環使用；interval_hours 是結算間隔小時數（例如 8 代表每 8 小時結算一次）；days 是持有天數。正費率時多單付費給空單。回傳持有期間的總損益（正數=收到、負數=付出）。

def funding_pnl(side, notional, rates_pct, interval_hours, days):
    n = interval_hours * days
    total = 0.0
    for i in range(1, n):
        r = rates_pct[i % len(rates_pct)] / 100
        total += notional * r
    if side == "long":
        return round(total, 2)
    return round(-total, 2)

請找出所有真正的邏輯錯誤（不要挑風格），每個錯誤說明：哪一行、錯在哪、怎麼改。最後用一行列出你找到的錯誤總數。"""
m,dt,rc = chat([{"role":"user","content":T2}], True); show("T2 找 3 個 bug", "①n 應為 (24//interval_hours)*days ②range(1,n) 少算一次應 range(n) ③正負號反了：long 應回 −total、short 回 +total", m,dt,rc)

