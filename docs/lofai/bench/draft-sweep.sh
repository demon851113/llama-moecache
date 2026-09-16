#!/bin/bash
cd /data/src
for N in 3 4 1; do
  echo "== spec-draft-n-max $N"
  ./restart-server.sh /data/src/run-best2.sh --spec-draft-n-max $N 2>&1 | tail -1
  for i in 1 2; do
    curl -s -m 120 http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"請詳細解釋永續合約資金費率的計算方式、結算時間與對多空雙方的影響，並舉兩個數字範例，再補充三個風險。"}],"max_tokens":450,"temperature":0.7,"chat_template_kwargs":{"enable_thinking":false}}' | python3 -c "
import json,sys; t=json.load(sys.stdin)['timings']
acc=100*t['draft_n_accepted']/max(1,t['draft_n']); steps=t['predicted_n']-t['draft_n_accepted']
print('  gen %d @ %.1f t/s | 草稿接受率 %.1f%% | 每步吐 %.2f token | 每步 %.1f ms'%(t['predicted_n'],t['predicted_per_second'],acc,t['predicted_n']/max(1,steps),1000/(t['predicted_per_second']/(t['predicted_n']/max(1,steps)))))"
  done
done
echo "== 回到預設 2"; ./restart-server.sh /data/src/run-best2.sh 2>&1 | tail -1
curl -s -m 120 http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"請詳細解釋永續合約資金費率的計算方式、結算時間與對多空雙方的影響，並舉兩個數字範例，再補充三個風險。"}],"max_tokens":450,"temperature":0.7,"chat_template_kwargs":{"enable_thinking":false}}' | python3 -c "
import json,sys; t=json.load(sys.stdin)['timings']; acc=100*t['draft_n_accepted']/max(1,t['draft_n']); steps=t['predicted_n']-t['draft_n_accepted']
print('  gen %d @ %.1f t/s | 草稿接受率 %.1f%% | 每步吐 %.2f token'%(t['predicted_n'],t['predicted_per_second'],acc,t['predicted_n']/max(1,steps)))"
echo "== SWEEP DONE"
