#!/bin/bash
# 安全重啟：只送一次 SIGINT、等舊行程完全退出、檢查 dmesg、再起新 server
# 用法: restart-server.sh <啟動腳本> [額外旗標...]   例: restart-server.sh /data/src/run-best2.sh
START=${1:?啟動腳本}; shift
P=$(pgrep -f "build/bin/llama-server" | head -1)
if [ -n "$P" ]; then
  kill -INT "$P"; echo "已送 SIGINT 給 $P，等待退出..."
  for i in $(seq 1 120); do pgrep -f "build/bin/llama-server" >/dev/null || break; sleep 1; done
  if pgrep -f "build/bin/llama-server" >/dev/null; then echo "!! 120 秒仍未退出，停止，不硬殺（見踩雷）"; exit 2; fi
  echo "舊行程已退出（$i 秒）"; sleep 5
fi
# 排除使用者空間編譯器自己崩潰的 trap（ptxas/cicc/nvcc segfault 是已知隨機現象，跟 GPU/核心無關）
if sudo -n dmesg | tail -50 | grep -viE "traps: (ptxas|cicc|nvcc|cc1plus)" | grep -qiE "oops|lockup|general protection|NVRM: Xid"; then echo "!! dmesg 有核心/GPU 錯誤，不起新 server，請先重開機"; sudo -n dmesg | tail -50 | grep -viE "traps: (ptxas|cicc|nvcc|cc1plus)" | grep -iE "oops|lockup|general protection|NVRM: Xid" | tail -3; exit 3; fi
nohup "$START" "$@" > /data/src/server-current.log 2>&1 < /dev/null &
for i in $(seq 1 120); do curl -s -m 3 http://127.0.0.1:8080/health | grep -q '"ok"' && { echo "新 server 就緒（$((i*5)) 秒）pid $(pgrep -f build/bin/llama-server | head -1)"; exit 0; }; pgrep -f "build/bin/llama-server" >/dev/null || { echo "!! 新 server 啟動失敗"; grep -E " E |error" /data/src/server-current.log | tail -3; exit 4; }; sleep 5; done
echo "!! 逾時未就緒"; exit 5
