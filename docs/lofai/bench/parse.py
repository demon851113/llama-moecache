import sys, json
r = json.load(sys.stdin); t = r.get("timings", {})
label, run = sys.argv[1], sys.argv[2]
print(f"[{label} run{run}] prompt {t.get('prompt_n')} tok @ {t.get('prompt_per_second',0):.1f} tok/s | 生成 {t.get('predicted_n')} tok @ {t.get('predicted_per_second',0):.1f} tok/s | 首字延遲 {t.get('prompt_ms',0)/1000:.1f}s")
print("  回答開頭:", r["choices"][0]["message"]["content"][:120].replace("\n", " "))
