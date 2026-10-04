"""Aggregate results/*.json into a metrics table (results/report.md) and plots."""
import argparse, glob, json, statistics as st

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import HERE, auroc, bootstrap_ci, ece, hit, mrr, ndcg, recall

ap = argparse.ArgumentParser()
ap.add_argument("--llm-price", type=float, default=0.50, help="ASSUMED blended $/1M tokens for the HF-hosted LLM; edit to your actual rate")
ap.add_argument("--gpu-hour", type=float, default=0.80, help="ASSUMED $/GPU-hour used to price Kev's GPU time (local = $0 marginal)")
a = ap.parse_args()

def pct(x): return f"{100 * x:.1f}"
def prf(kept, gold):
    tp = len(set(kept) & set(gold)); p, r = tp / len(kept) if kept else 0.0, tp / len(gold)
    return p, r, 2 * p * r / (p + r) if tp else 0.0
table = []
for f in sorted(glob.glob(str(HERE / "results/*.json"))):
    d = json.load(open(f))
    if "rows" not in d: continue
    R, n = d["rows"], len(d["rows"])
    h1 = [hit(r["ranked"], r["gold"], 1) for r in R]; h3 = [hit(r["ranked"], r["gold"], 3) for r in R]
    lat = sorted(r["latency"] for r in R)
    gpu = [r["latency"] if d["method"].startswith("kev") else r["kev_gpu_sec"] for r in R]   # Kev holds the GPU for the whole question
    cost = sum(r["api_tokens"] for r in R) / 1e6 * a.llm_price + sum(gpu) / 3600 * a.gpu_hour
    conf = [(r["conf"], h) for r, h in zip(R, h1) if r["conf"] is not None]
    cs, ys = [c for c, _ in conf], [bool(h) for _, h in conf]
    row = {"method": d["method"], "n": n, "hit1": st.mean(h1), "hit1_ci": bootstrap_ci(h1), "hit3": st.mean(h3), "hit3_ci": bootstrap_ci(h3),
           "hit5": st.mean(hit(r["ranked"], r["gold"], 5) for r in R), "rec5": st.mean(recall(r["ranked"], r["gold"], 5) for r in R),
           "mrr": st.mean(mrr(r["ranked"], r["gold"]) for r in R), "ndcg5": st.mean(ndcg(r["ranked"], r["gold"]) for r in R),
           "p50": lat[n // 2], "p95": lat[int(.95 * (n - 1))], "mean": st.mean(lat), "calls": st.mean(r["calls"] for r in R),
           "api_tok": st.mean(r["api_tokens"] for r in R), "kev_tok": st.mean(r["kev_tokens"] for r in R),
           "gpu_s": st.mean(gpu), "usd_per_1k": cost / n * 1000, "index_sec_doc": st.mean(d["index_sec"].values()),
           "auroc": auroc(cs, ys) if cs else None, "ece": ece(cs, ys) if cs else None}
    if cs:  # selective accuracy: hit@1 on the more-confident half
        top = sorted(conf, key=lambda x: -x[0])[:max(1, len(conf) // 2)]; row["sel50"] = st.mean(h for _, h in top)
    if K := [r for r in R if r.get("kept") is not None]:  # set metrics of the verified ("kept") pages vs gold
        row["kept"] = (len(K), st.mean(len(r["kept"]) for r in K), *(st.mean(v) for v in zip(*(prf(r["kept"], r["gold"]) for r in K))))
    table.append(row)

table.sort(key=lambda r: -r["hit3"])
L = ["| method | n | hit@1 (95% CI) | hit@3 (95% CI) | hit@5 | recall@5 | MRR | nDCG@5 | p50 s | p95 s | calls/q | LLM tok/q | Kev tok/q | GPU s/q | $/1k q | index s/doc | conf AUROC | ECE | hit@1 top-50% conf |",
     "|" + "---|" * 19]
for r in table:
    f = lambda v, p=2: "–" if v is None else f"{v:.{p}f}"
    L.append(f"| {r['method']} | {r['n']} | {pct(r['hit1'])} ({pct(r['hit1_ci'][0])}–{pct(r['hit1_ci'][1])}) | {pct(r['hit3'])} ({pct(r['hit3_ci'][0])}–{pct(r['hit3_ci'][1])}) | "
             f"{pct(r['hit5'])} | {pct(r['rec5'])} | {r['mrr']:.3f} | {r['ndcg5']:.3f} | {r['p50']:.3f} | {r['p95']:.3f} | {r['calls']:.1f} | {r['api_tok']:.0f} | "
             f"{r['kev_tok']:.0f} | {r['gpu_s']:.2f} | {r['usd_per_1k']:.3f} | {r['index_sec_doc']:.2f} | {f(r['auroc'])} | {f(r['ece'])} | {f(r.get('sel50'), 3) if 'sel50' in r else '–'} |")
if K := [r for r in table if "kept" in r]:
    L += ["", "Verified page set (`kept`, pages that passed the Noul check) vs gold pages, averaged over questions:", "",
          "| method | n | pages kept/q | precision | recall | F1 |", "|" + "---|" * 6]
    L += [f"| {r['method']} | {r['kept'][0]} | {r['kept'][1]:.2f} | {pct(r['kept'][2])} | {pct(r['kept'][3])} | {pct(r['kept'][4])} |" for r in K]
L += ["", f"Assumptions: LLM ${a.llm_price}/1M tokens (blended, edit `--llm-price`); GPU ${a.gpu_hour}/hr (edit `--gpu-hour`; a local GPU is $0 marginal). "
      "Kev GPU time per question = its end-to-end latency: questions run one at a time and hold the GPU throughout, whereas summing the "
      "wall time of each Kev request (`kev_gpu_sec`) counts concurrent requests several times over. "
      "Latency = end-to-end per question, excluding indexing; cached LLM calls use the latency recorded when first made. 95% CIs are bootstrap over questions."]
(HERE / "results/report.md").write_text("\n".join(L)); print("\n".join(L))

def pareto(pts):  # non-dominated (x, y): nothing both faster/cheaper and at least as accurate
    out = []
    for p in sorted(pts):
        if not out or p[1] > out[-1][1]: out.append(p)
    return out

fig, ax = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
for k, (key, lbl, floor) in enumerate([("p50", "median latency / question (s, log; < 1 ms plotted at 1 ms)", 1e-3), ("usd_per_1k", "$ per 1k questions (log; $0 plotted at $0.0001)", 1e-4)]):
    pts = [(max(r[key], floor), 100 * r["hit3"]) for r in table]
    for i, (r, (x, y)) in enumerate(zip(table, pts)):
        ax[k].errorbar(x, y, yerr=[[y - 100 * r["hit3_ci"][0]], [100 * r["hit3_ci"][1] - y]], fmt="osD^vP*Xh<>"[i % 11], color=f"C{i % 10}",
                       ms=7, capsize=3, elinewidth=.8, alpha=.85, label=r["method"] if k == 0 else None)
    ax[k].step(*zip(*pareto(pts)), where="post", ls="--", lw=1, color="k", alpha=.6, label="Pareto frontier" if k == 0 else None)
    ax[k].set_xscale("log"); ax[k].set_xlabel(lbl, fontsize=9); ax[k].grid(alpha=.3, which="both")
ax[0].set_ylabel("hit@3 (%), bars = 95% CI")
rows = -(-(len(table) + 1) // 4)
fig.legend(loc="lower center", ncol=4, fontsize=8, frameon=False); plt.tight_layout(rect=(0, .045 * rows + .02, 1, 1))
plt.savefig(HERE / "results/frontier.png", dpi=130)
