#!/bin/bash
# GenerelSchwerz moe-cache 分支（commit 9259338）：專家釘主記憶體、顯存 LRU 快取、路由預取
export LD_LIBRARY_PATH=/data/src/llama-moecache/build/bin:/usr/local/cuda/lib64
export GGML_CUDA_MOE_EARLY_ROUTER=1 GGML_CUDA_MOE_EARLY_ROUTER_LOOKAHEAD=1 CUDA_VISIBLE_DEVICES=0
exec /data/src/llama-moecache/build/bin/llama-server --offline \
  -m /data/models/Flash-Next/UD-IQ3_XXS/Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf \
  -md /data/models/Flash-Next/MTP/mtp-Qwen3.8-Flash-Next-Q8_0.gguf --spec-type draft-mtp --spec-draft-n-max 2 \
  -c 65536 -b 512 -ub 512 -np 1 -t 12 -ngl all -fa on -fit off \
  --load-mode none --lazy-mode on --moe-expert-cache-size 56 \
  -ctk f16 -ctv f16 -kvo --cache-ram 0 --jinja --no-warmup \
  --backend-sampling --decode-overlap --decode-boundary-overlap --ple-prefetch \
  --phase-aware-workspace --live-context-workspace \
  --host 127.0.0.1 --port 8080 "$@"
