import json, sys, urllib.request, time
PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
think = len(sys.argv) > 2 and sys.argv[2] == "think"
QS = [
 ("滑點", "什麼是加密貨幣交易中的「滑點」？兩句話說明。"),
 ("funding", "永續合約的 funding rate（資金費率）是什麼？誰付給誰？兩句話。"),
 ("做市商", "交易所裡的「做市商」在做什麼？兩句話。"),
 ("台灣首都", "台灣的首都是哪個城市？一句話。"),
 ("Bitget UTA", "Bitget 的 UTA（統一交易帳戶）從錢包提幣前，通常需要先做什麼？一句話。"),
]
sp = {"temperature":1.0,"top_p":0.95,"top_k":20} if think else {"temperature":0.7,"top_p":0.8,"top_k":20,"presence_penalty":1.5}
for tag, q in QS:
    body = {"messages":[{"role":"system","content":"你是加密貨幣交易專家，一律用繁體中文回答，不要用簡體字。"},{"role":"user","content":q}],
            "max_tokens": 2000 if think else 200, "chat_template_kwargs":{"enable_thinking": think}, **sp}
    t0=time.time()
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", json.dumps(body).encode(), {"Content-Type":"application/json"}), timeout=600)
    j = json.load(r); c = j["choices"][0]["message"]["content"].strip().replace("\n"," ")
    simp = sum(ch in "这个们对时说为发经业务过种实现应该样问题点没关" for ch in c)
    print(f"[{tag}] {time.time()-t0:.0f}s 簡體字疑似 {simp} 個\n  {c[:260]}\n")
