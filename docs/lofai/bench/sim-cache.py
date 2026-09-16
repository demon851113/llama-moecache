#!/usr/bin/env python3
"""離線模擬每層專家快取：LRU / LFU(頻率) / Belady 最佳，比較命中率。
用法：sim-cache.py trace.txt [slots=72] [group=3]  （group = 每步同時處理的 token 數，模擬 MTP 批 3）"""
import sys, collections
path=sys.argv[1]; SLOTS=int(sys.argv[2]) if len(sys.argv)>2 else 72; G=int(sys.argv[3]) if len(sys.argv)>3 else 3
per_layer=collections.defaultdict(dict)  # layer -> step -> set(experts)
prompt_steps=set()
for line in open(path):
    p=line.split()
    if len(p)<3: continue
    step,layer=int(p[0]),int(p[1]); per_layer[layer].setdefault(step,set()).update(int(x) for x in p[2:])
layers=sorted(per_layer); n_experts=1+max(e for l in layers for s in per_layer[l].values() for e in s)
print(f"層數={len(layers)} 專家數≈{n_experts} 步數={len(per_layer[layers[0]])} 槽位={SLOTS} 每步 token 數={G}")
def batches(layer):
    steps=sorted(per_layer[layer]); out=[]
    # 提示階段（step 連續且來自同一次 decode）在真實系統是一次大批；這裡只拿生成段（最後 N 步）逐 G 個合併
    gen=steps[len(steps)//4:]  # 丟掉前 1/4 當提示 warm-up
    for i in range(0,len(gen),G): out.append(set().union(*[per_layer[layer][s] for s in gen[i:i+G]]))
    return out
tot={"LRU":[0,0],"LFU":[0,0],"BELADY":[0,0]}; uniq=[]
for L in layers:
    B=batches(L); uniq += [len(b) for b in B]
    # LRU
    cache=collections.OrderedDict(); h=m=0
    for b in B:
        for e in b:
            if e in cache: cache.move_to_end(e); h+=1
            else:
                m+=1
                if len(cache)>=SLOTS: cache.popitem(last=False)
                cache[e]=None
    tot["LRU"][0]+=h; tot["LRU"][1]+=m
    # LFU（累積頻率，逐出最低頻）
    cache=set(); freq=collections.Counter(); h=m=0
    for b in B:
        for e in b:
            freq[e]+=1
            if e in cache: h+=1
            else:
                m+=1
                if len(cache)>=SLOTS: cache.remove(min(cache,key=lambda x:freq[x]))
                cache.add(e)
    tot["LFU"][0]+=h; tot["LFU"][1]+=m
    # Belady：逐出下次使用最遠者
    nxt=collections.defaultdict(list)
    for i,b in enumerate(B):
        for e in b: nxt[e].append(i)
    ptr=collections.defaultdict(int); cache=set(); h=m=0
    for i,b in enumerate(B):
        for e in b:
            ptr[e]+=1
            if e in cache: h+=1
            else:
                m+=1
                if len(cache)>=SLOTS:
                    def nextuse(x):
                        lst=nxt[x]; k=ptr[x]
                        return lst[k] if k<len(lst) else 10**9
                    cache.remove(max(cache,key=nextuse))
                cache.add(e)
    tot["BELADY"][0]+=h; tot["BELADY"][1]+=m
print(f"每步每層獨特專家數：平均 {sum(uniq)/len(uniq):.1f}，最大 {max(uniq)}")
for k,(h,m) in tot.items():
    print(f"  {k:7s} 命中率 {100*h/(h+m):5.1f}%  每步每層 miss {m/len(uniq):.2f}")
# 頻率偏斜：前 72 名專家覆蓋多少路由
cnt=collections.Counter()
for L in layers:
    for b in batches(L):
        for e in b: cnt[(L,e)]+=1
byL=collections.defaultdict(list)
for (L,e),c in cnt.items(): byL[L].append(c)
cov=[sum(sorted(v,reverse=True)[:SLOTS])/sum(v) for v in byL.values()]
print(f"每層前 {SLOTS} 名熱門專家覆蓋的路由比例：平均 {100*sum(cov)/len(cov):.1f}%（靜態釘住的天花板）")
