#!/usr/bin/env python3
"""混合策略模擬：釘住 H 個熱門專家（名單用前半段算）+ 其餘槽位 LRU，在後半段驗證。
用法：sim-cache2.py trace.txt [slots=72] [group=3]"""
import sys, collections
path=sys.argv[1]; SLOTS=int(sys.argv[2]) if len(sys.argv)>2 else 72; G=int(sys.argv[3]) if len(sys.argv)>3 else 3
per_layer=collections.defaultdict(dict)
for line in open(path):
    p=line.split()
    if len(p)<3: continue
    per_layer[int(p[1])].setdefault(int(p[0]),set()).update(int(x) for x in p[2:])
layers=sorted(per_layer)
def batches(layer):
    steps=sorted(per_layer[layer]); gen=steps[len(steps)//4:]
    return [set().union(*[per_layer[layer][s] for s in gen[i:i+G]]) for i in range(0,len(gen),G)]
def lru_run(B, slots, pinned=frozenset()):
    cache=collections.OrderedDict(); h=m=0; dyn=slots-len(pinned)
    for b in B:
        for e in b:
            if e in pinned: h+=1; continue
            if e in cache: cache.move_to_end(e); h+=1
            else:
                m+=1
                if dyn<=0: continue  # 沒有動態槽：miss 但不快取（每次都搬）
                if len(cache)>=dyn: cache.popitem(last=False)
                cache[e]=None
    return h,m
def belady_run(B, slots):
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
                if len(cache)>=slots:
                    cache.remove(max(cache,key=lambda x:(nxt[x][ptr[x]] if ptr[x]<len(nxt[x]) else 10**9)))
                cache.add(e)
    return h,m
rows=[]
for H in [0,16,32,40,48,56,64,72]:
    h=m=0
    for L in layers:
        B=batches(L); half=len(B)//2; train,test=B[:half],B[half:]
        cnt=collections.Counter(e for b in train for e in b)
        pinned=frozenset(e for e,_ in cnt.most_common(H))
        hh,mm=lru_run(test,SLOTS,pinned); h+=hh; m+=mm
    rows.append((f"釘 {H:2d} 熱門 + LRU {SLOTS-H:2d}", h, m))
hb=mb=0
for L in layers:
    B=batches(L); half=len(B)//2; hh,mm=belady_run(B[half:],SLOTS); hb+=hh; mb+=mm
rows.append(("Belady（後半段，理論上限）",hb,mb))
n_steps=sum(len(batches(L))-len(batches(L))//2 for L in layers)
print(f"槽位={SLOTS} 每步 token={G}（名單用前半段、命中率算後半段）")
for name,h,m in rows: print(f"  {name:28s} 命中率 {100*h/(h+m):5.1f}%  每步每層 miss {m/n_steps:.2f}")
