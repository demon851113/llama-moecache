import json, sys, urllib.request, time
PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
TOOLS = [
 {"type":"function","function":{"name":"get_funding_rate","description":"查詢某交易所某永續合約的當前資金費率","parameters":{"type":"object","properties":{"exchange":{"type":"string","enum":["binance","bybit","okx"]},"symbol":{"type":"string","description":"例如 BTCUSDT"}},"required":["exchange","symbol"]}}},
 {"type":"function","function":{"name":"get_withdraw_fee","description":"查詢某交易所某幣種在指定鏈上的提幣費","parameters":{"type":"object","properties":{"exchange":{"type":"string"},"coin":{"type":"string"},"chain":{"type":"string","description":"可選，例如 TRC20"}},"required":["exchange","coin"]}}},
]
CASES = [
 ("雙工具", "幫我查 binance 和 bybit 的 BTCUSDT 資金費率，還有 okx 的 USDT 在 TRC20 的提幣費。", {"get_funding_rate":2,"get_withdraw_fee":1}),
 ("不該叫", "資金費率為正的時候是誰付錢給誰？", {}),
]
for tag, q, expect in CASES:
  for n in range(3):
    body = {"messages":[{"role":"user","content":q}],"tools":TOOLS,"max_tokens":600,"temperature":0.7,"top_p":0.8,"top_k":20,
            "chat_template_kwargs":{"enable_thinking":False}}
    t0=time.time()
    j = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", json.dumps(body).encode(), {"Content-Type":"application/json"}), timeout=600))
    m = j["choices"][0]["message"]; calls = m.get("tool_calls") or []
    got = {}
    for c in calls: got[c["function"]["name"]] = got.get(c["function"]["name"],0)+1
    args = [c["function"]["arguments"] for c in calls]
    ok = "✓" if got == expect else "✗"
    print(f"[{tag} run{n+1}] {ok} {time.time()-t0:.0f}s 呼叫={got} 參數={args[:3]} 文字={(m.get('content') or '')[:60].replace(chr(10),' ')}")
