#!/bin/bash
cd /data/src
echo "== 以 nsys 包住啟動"; T0=$(date +%s)
./restart-server.sh /data/src/run-prof.sh 2>&1 | tail -1
echo "server 起來耗時 $(( $(date +%s) - T0 ))s，等到 delay 70s 過後打請求"
while [ $(( $(date +%s) - T0 )) -lt 74 ]; do sleep 1; done
for i in 1 2 3; do
  curl -s -m 60 http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"請詳細解釋永續合約資金費率的計算方式、結算時間與對多空雙方的影響，並舉兩個數字範例，再補充三個風險。"}],"max_tokens":450,"temperature":0.7,"chat_template_kwargs":{"enable_thinking":false}}' | python3 -c "import json,sys; t=json.load(sys.stdin)['timings']; print('  req',$i,'gen',t['predicted_n'],'@ %.1f t/s'%t['predicted_per_second'])"
done
echo "== 等 nsys 收尾（duration 到會終止 server）"
for i in $(seq 1 60); do pgrep -f "nsys profile" >/dev/null || break; sleep 2; done
sleep 3; pgrep -f build/bin/llama-server >/dev/null && echo "server 仍在（nsys 沒殺）" || echo "server 已被 nsys 收掉"
ls -la /data/src/decode-prof.nsys-rep 2>/dev/null
echo "== 正常重啟"; ./restart-server.sh /data/src/run-best2.sh 2>&1 | tail -1
echo "== PROF DONE"
