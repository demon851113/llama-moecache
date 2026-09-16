#!/bin/bash
# 2026-09-16 新預設：GenerelSchwerz moe-cache 分支 + 專家快取 72 + 128K + KV q8 + MTP 草稿 2 + medium + 24GB 前綴快取
exec /data/src/run-moecache.sh -c 262144 -ctk q8_0 -ctv q8_0 --moe-expert-cache-size 40 \
  --chat-template-kwargs '{"reasoning_effort":"medium"}' --cache-ram 24576 --cache-reuse 256 -ub 256 "$@"
