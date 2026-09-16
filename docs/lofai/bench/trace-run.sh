#!/bin/bash
cd /data/src
echo "== 停 server（單一 SIGINT）"; P=$(pgrep -f build/bin/llama-server | head -1); [ -n "$P" ] && kill -INT $P
for i in $(seq 1 60); do pgrep -f build/bin/llama-server >/dev/null || break; sleep 2; done
pgrep -f build/bin/llama-server >/dev/null && { echo "server 沒退出，放棄"; exit 1; }
sleep 3; nvidia-smi --query-gpu=memory.used --format=csv,noheader
echo "== 跑路由追蹤（greedy 300 token）"
export LD_LIBRARY_PATH=/data/src/llama-moecache/build/bin:/usr/local/cuda/lib64 GGML_CUDA_MOE_EARLY_ROUTER=1 GGML_CUDA_MOE_EARLY_ROUTER_LOOKAHEAD=1 CUDA_VISIBLE_DEVICES=0
T0=$(date +%s)
timeout 900 /data/src/llama-moecache/build/bin/llama-moe-route-trace --offline \
  -m /data/models/Flash-Next/UD-IQ3_XXS/Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf \
  -c 4096 -b 512 -ub 512 -t 12 -ngl all -fa on -fit off --load-mode none --lazy-mode on --moe-expert-cache-size 16 \
  -n 300 -o /data/src/route-trace.txt \
  -p "請詳細解釋跨交易所套利中資金費率套利的原理、風險控制與執行流程，並舉兩個數字範例，最後給出一段 Python 偽碼示範如何監控兩個交易所的資金費率差。" 2>&1 | grep -E "prompt tokens|generated text|trace written|error|failed" | cut -c1-200
echo "追蹤耗時 $(( $(date +%s) - T0 ))s；行數 $(wc -l < /data/src/route-trace.txt)"
echo "== 重啟 server"; ./restart-server.sh /data/src/run-best2.sh 2>&1 | tail -1
echo "== 模擬（72 槽，每步 3 token）"; python3 sim-cache.py route-trace.txt 72 3
echo "== 模擬（72 槽，每步 1 token）"; python3 sim-cache.py route-trace.txt 72 1 | tail -5
echo "== 模擬（40 槽 / 128 槽，每步 3）"; python3 sim-cache.py route-trace.txt 40 3 | tail -4; python3 sim-cache.py route-trace.txt 128 3 | tail -4
echo "== TRACE DONE"
