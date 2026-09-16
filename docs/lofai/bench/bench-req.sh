#!/bin/bash
P=${2:-8080}
for n in 1 2; do
curl -s -m 600 http://127.0.0.1:$P/v1/chat/completions -H "Content-Type: application/json" -d '{
 "messages":[{"role":"system","content":"你是資深後端工程師，用繁體中文回答。"},{"role":"user","content":"請解釋跨交易所套利中「資金費率套利」的原理，並寫一段 Python 偽碼示範如何監控兩個交易所的資金費率差並在超過閾值時發出訊號。"}],
 "max_tokens":400,"temperature":0.7,"top_p":0.8,"top_k":20,"presence_penalty":1.5,
 "chat_template_kwargs":{"enable_thinking":false}}' | python3 /data/src/parse.py "$1" "$n"
done
