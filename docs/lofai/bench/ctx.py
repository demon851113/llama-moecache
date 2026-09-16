import json, urllib.request, time, random, sys
N=int(sys.argv[1]); LABEL=sys.argv[2]
random.seed(N)
words=["交易所","資金費率","永續合約","現貨","對沖","滑點","保證金","清算","訂單簿","做市商","價差","延遲","風控","倉位","槓桿","提幣","鏈上","撮合","深度","限價"]
# 約 N tokens：每個詞約 2 tokens
n_words=N//2
w=[random.choice(words) for _ in range(n_words)]
needles={int(n_words*0.05):"【密語甲=藍鯨7734】", int(n_words*0.5):"【密語乙=紅鶴2291】", int(n_words*0.95):"【密語丙=綠龜5108】"}
for k,v in needles.items(): w[k]=v
doc=" ".join(w)
body={"messages":[{"role":"user","content":"下面文字裡藏了三個【密語X=...】，請把三個密語的內容依甲乙丙順序列出，只輸出三行。\n"+doc}],
      "max_tokens":80,"temperature":0.7,"chat_template_kwargs":{"enable_thinking":False}}
t0=time.time()
try:
    j=json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=1700))
except Exception as e:
    print(f"[{LABEL} {N//1000}K] 失敗: {str(e)[:120]}"); sys.exit()
t=j.get("timings",{}); c=j["choices"][0]["message"]["content"]
hit=sum(x in c for x in ["藍鯨7734","紅鶴2291","綠龜5108"])
print(f"[{LABEL} {N//1000}K] prompt {t.get('prompt_n')} tok 讀取 {t.get('prompt_per_second',0):.0f} tok/s 耗時 {t.get('prompt_ms',0)/1000:.0f}s | 生成 {t.get('predicted_per_second',0):.1f} tok/s | 埋針命中 {hit}/3 | {time.time()-t0:.0f}s")
