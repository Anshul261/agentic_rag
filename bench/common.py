"""Data loading (HF bucket -> subset -> PDFs), outline trees, and retrieval metrics."""
import collections, hashlib, inspect, json, math, os, pathlib, pickle, re, tempfile, urllib.request

import pymupdf

HERE = pathlib.Path(__file__).parent
# Credentials must be supplied by the caller's environment. Never read .env.
BUCKET, BUCKET_FILE = "AnshulRaj/financebench-bucket", "financebench_merged.jsonl"
for d in ("data", "pdfs", "cache", "results"): (HERE / d).mkdir(exist_ok=True)

# ---------- data ----------
def load_subset(n_docs=10, n_questions=None):
    """Questions from the user's HF bucket; the n_docs docs with the most questions. PDFs come from the FinanceBench GitHub repo."""
    f = HERE / "data/fb.jsonl"
    if not f.exists():
        from huggingface_hub import HfApi
        HfApi(token=os.environ["HF_TOKEN"]).download_bucket_files(BUCKET, [(BUCKET_FILE, str(f))])
    rows = [json.loads(l) for l in open(f)]
    docs = [d for d, _ in collections.Counter(r["doc_name"] for r in rows).most_common(n_docs)]
    qs = sorted((r for r in rows if r["doc_name"] in docs), key=lambda r: (docs.index(r["doc_name"]), r["financebench_id"]))[:n_questions]
    for d in {r["doc_name"] for r in qs}:
        p = HERE / f"pdfs/{d}.pdf"
        if not p.exists(): urllib.request.urlretrieve(f"https://raw.githubusercontent.com/patronus-ai/financebench/main/pdfs/{d}.pdf", p)
    return [{"id": r["financebench_id"], "doc": r["doc_name"], "question": r["question"],
             "gold": sorted({e["evidence_page_num"] for e in r["evidence"]}), "answer": r["answer"]} for r in qs]

# ---------- outline tree (no LLM) ----------
PART = re.compile(r"^PART\s+(IV|I{1,3})\b(?!\s+of\b)", re.I)
ITEM = re.compile(r"^ITEMS?\s+(\d{1,2})([A-C]?)(?:\s*\(\w\)\S*)?\s*(?:[.:,\-–—]|$)", re.I)
FS = re.compile(r"^((condensed\s+)?consolidated\s+(statements?\s+of|balance\s+sheets?|financial\s+statements)|notes\s+to\s+(the\s+)?(condensed\s+)?consolidated\s+financial"
                r"|report\s+of\s+independent\s+registered|management['’]s\s+(report|discussion))", re.I)
NOTE = re.compile(r"^(?:NOTE\s+(\d{1,2})\b\s*[.:\-–—]?|(\d{1,2})\.\s+(?=[A-Z]{2}))", re.I)
STOPS = re.compile(r"^(signatures?|exhibit\s+\d|index\s+to\s+exhibits|exhibit\s+index)\b", re.I)

def _lines(doc):
    """[(page, text, size, bold, isolated)]: one per visual line; isolated = nothing else printed on the same row (not a table cell)."""
    out = []
    for i in range(len(doc)):
        ls = []
        for b in doc[i].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                sp = [s for s in l["spans"] if s["text"].strip()]
                if sp: ls.append((l["bbox"], " ".join(" ".join(s["text"].split()) for s in sp), max(s["size"] for s in sp), all(s["flags"] & 16 for s in sp)))
        for k, (bb, t, sz, bold) in enumerate(ls):
            iso = not any(j != k and min(bb[3], o[3]) - max(bb[1], o[1]) > .5 * (bb[3] - bb[1]) for j, (o, *_) in enumerate(ls))
            out.append((i, t, sz, bold, iso))
    return out

def build_tree(doc):
    """Flat nodes [{id,title,level,start,end}], pages 0-indexed, no LLM. PDF outline when it has one; else filing structure from layout:
    PART (0) > ITEM (1) > financial-statement titles / bold section headings (2) > Notes / minor headings (3) > headings inside a note (4).
    Item and note numbers must increase (drops TOC entries, cross-references and running headers); exhibits after SIGNATURES are one leaf."""
    n = len(doc)
    heads = [(lvl - 1, t.strip(), p - 1) for lvl, t, p in doc.get_toc() if p > 0 and t.strip()]
    if len(heads) < 5:
        L = _lines(doc); heads = []
        sizes = collections.Counter()
        for _, t, sz, _, _ in L: sizes[round(sz, 1)] += len(t)
        body = sizes.most_common(1)[0][0]
        norm = lambda t: re.sub(r"[\d\W_]+", " ", t.lower()).strip()
        pages_of = collections.defaultdict(set)
        for p, t, *_ in L: pages_of[norm(t)].add(p)
        toc = collections.defaultdict(list)   # table-of-contents pages: >= 4 Item lines, mostly plain, or >= 3 Part lines
        for p, t, sz, bold, _ in L:
            if ITEM.match(t) or PART.match(t): toc[p].append((bool(PART.match(t)), bold or sz >= body + 1.5))
        toc = {p for p, v in toc.items() if (len(v) >= 4 and sum(s for _, s in v) < len(v) / 2) or sum(pt for pt, _ in v) >= 3}
        fs_index = {p for p, c in collections.Counter(p for p, t, *_ in L if FS.match(t)).items() if c >= 3}   # lists of statements, not the statements
        last_item, last_note, in_notes, in_fs, stop, seen = (), 0, False, False, False, set()
        for k, (p, t, sz, bold, iso) in enumerate(L):
            if p in toc or len(t) > 160 or not re.search("[A-Za-z]{2}", t): continue
            strong = bold or sz >= body + 1.5
            nxt = L[k + 1] if k + 1 < len(L) and L[k + 1][0] == p else (p, "", 0, False, False)
            if (ITEM.match(t) or NOTE.match(t)) and len(re.sub(r"^\W*\w+\s+\w+\W*", "", t)) < 3 and not (PART.match(nxt[1]) or ITEM.match(nxt[1])):
                t = f"{t} {nxt[1]}".strip()   # 'NOTE 1' / 'Item 7.' with the title on the next line
            if not strong: continue
            if (m := PART.match(t)) and len(t) < 60:
                last_item, in_notes, in_fs, stop = (), False, False, False; heads.append((0, t, p)); continue
            if m := ITEM.match(t):
                key = (int(m[1]), m[2].upper())
                if key > last_item: last_item, in_notes, in_fs = key, False, False; stop = key >= (15, ""); heads.append((1, t, p))
                continue
            if stop: continue
            if STOPS.match(t) and iso: stop = True; heads.append((2, t, p)); continue
            if FS.match(t) and len(t) < 110:
                if norm(t) in seen or p in fs_index or "continued" in t.lower(): continue
                seen.add(norm(t)); in_notes = t.lower().startswith("notes"); in_fs = bool(re.search(r"statements?\s+of|balance\s+sheet", t, re.I))
                heads.append((2, t, p)); last_note = 0; continue
            if (m := NOTE.match(t)) and iso and (in_notes or t.lower().startswith("note")):
                num = int(m[1] or m[2])
                if num > last_note:
                    if not in_notes: in_notes = True; heads.append((2, "Notes to the financial statements", p))
                    last_note, in_fs = num, False; heads.append((3, t, p))
                continue
            if in_fs or p in fs_index or not iso or len(t) > 100 or len(t) < 4 or not t[0].isupper() or len(pages_of[norm(t)]) > 3: continue
            if sum(c.isalpha() for c in t) < .6 * len(t.replace(" ", "")) or t.endswith((",", ";")) or t[-1].isdigit() or t.count("(") != t.count(")"): continue
            if nxt[3] or re.search(r"\b(of|to|and|the|in|for|per|on|by|with|from|that|are)$", t, re.I): continue   # table column-header cells, wrapped labels
            if norm(t) in norm(heads[-1][1]) if heads else False: continue   # note title repeated as a heading
            major = sz >= body + 1.5 or (t.isupper() and len(t) > 6)
            heads.append((4 if in_notes and last_note else 2 if major else 3, t.rstrip(":"), p))
        cuts = [i for i, h in enumerate(heads) if h[0] <= 1] + [len(heads)]
        for a, b in zip([0] + cuts, cuts):   # a lone major heading in an Item is a sibling of its minor headings, not their parent
            two = [h for h in heads[a:b] if h[0] == 2]
            if len(two) == 1 and not FS.match(two[0][1]) and not two[0][1].startswith("Notes"): heads[a:b] = [(3 if h[0] == 2 else h[0], *h[1:]) for h in heads[a:b]]
    if heads and heads[0][2] > 0: heads.insert(0, (heads[0][0], "Cover page and front matter", 0))
    if not heads: heads = [(0, "Document", 0)]
    depth, stack = [], []  # parent = nearest earlier heading of a lower raw level; every child exactly one level under its parent
    for lvl, _, _ in heads:
        while stack and stack[-1] >= lvl: stack.pop()
        depth.append(len(stack)); stack.append(lvl)
    heads = [(d, t, p) for d, (_, t, p) in zip(depth, heads)]
    return [{"id": i, "title": t[:80], "level": lvl, "start": p,
             "end": max(p, min(n - 1, next((q for l2, _, q in heads[i + 1:] if l2 <= lvl), n)))} for i, (lvl, t, p) in enumerate(heads)]

def children(nodes):
    """kids[i] = direct children of node i: the following level+1 nodes up to the next node at level <= its own.
    (Matching kids by page range instead also catches the next sibling's children that start on a shared boundary page.)"""
    kids, stack = [[] for _ in nodes], []
    for x in nodes:
        while stack and stack[-1]["level"] >= x["level"]: stack.pop()
        if stack: kids[stack[-1]["id"]].append(x)
        stack.append(x)
    return kids

def leaf_sizes(nodes, page, kids=None):
    """Sizes of the leaf sections containing `page` (a leaf: no child, or the opening pages of a node before its first child)."""
    out = []
    for x, ks in zip(nodes, kids or children(nodes)):
        lo, hi = x["start"], (ks[0]["start"] - 1 if ks else x["end"])
        if lo <= page <= hi: out.append(hi - lo + 1)
    return out

def tree_report(trees, qs, max_leaf=15):
    """Per doc: nodes, gold-page leaf sizes; overall: share of questions with a gold page in a leaf of <= max_leaf pages."""
    best_all, leaves_all = [], []
    for doc, nodes in trees.items():
        kids = children(nodes); n_pages = max(x["end"] for x in nodes) + 1
        best = [min(s for g in q["gold"] for s in leaf_sizes(nodes, g, kids) or [n_pages]) for q in qs if q["doc"] == doc]
        leaves = [(ks[0]["start"] if ks else x["end"] + 1) - x["start"] for x, ks in zip(nodes, kids) if not ks or ks[0]["start"] > x["start"]]
        best_all += best; leaves_all += leaves
        print(f"  {doc:28s} nodes={len(nodes):4d} depth={max(x['level'] for x in nodes)} max fan-out={max(len(k) for k in kids):3d} "
              f"mean leaf={sum(leaves) / len(leaves):5.1f}p  gold leaf sizes={best}")
    ok = sum(b <= max_leaf for b in best_all)
    print(f"  => gold page in a leaf of <= {max_leaf} pages: {ok}/{len(best_all)} = {100 * ok / len(best_all):.1f}%   "
          f"mean gold-leaf size {sum(best_all) / len(best_all):.1f}p   mean leaf size {sum(leaves_all) / len(leaves_all):.1f}p")

def load_doc(name):
    """-> (page_texts, tree_nodes); cached on disk."""
    pdf = HERE / f"pdfs/{name}.pdf"
    fingerprint = hashlib.sha256(pdf.read_bytes() + inspect.getsource(build_tree).encode()).hexdigest()[:16]
    c = HERE / f"cache/doc_{name}_{fingerprint}.pkl"
    if c.exists():
        try:
            with c.open("rb") as file: return pickle.load(file)
        except (EOFError, pickle.UnpicklingError): pass
    with pymupdf.open(pdf) as d:
        out = ([d[i].get_text() for i in range(len(d))], build_tree(d))
    # Multiple evaluation threads can load the same document concurrently.
    # Publish a complete cache entry atomically, never a partially written pickle.
    with tempfile.NamedTemporaryFile(dir=c.parent, delete=False) as file:
        temp_path = pathlib.Path(file.name); pickle.dump(out, file)
    os.replace(temp_path, c)
    return out

# ---------- metrics ----------
def hit(ranked, gold, k): return float(bool(set(ranked[:k]) & set(gold)))
def recall(ranked, gold, k): return len(set(ranked[:k]) & set(gold)) / len(gold)
def mrr(ranked, gold, k=10): return next((1 / (i + 1) for i, p in enumerate(ranked[:k]) if p in gold), 0.0)
def ndcg(ranked, gold, k=5):
    dcg = sum(1 / math.log2(i + 2) for i, p in enumerate(ranked[:k]) if p in gold)
    return dcg / sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))

def auroc(conf, y):
    """P(confidence of a hit > confidence of a miss); ties count half."""
    pos, neg = [c for c, v in zip(conf, y) if v], [c for c, v in zip(conf, y) if not v]
    if not pos or not neg: return float("nan")
    return sum((p > q) + .5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))

def ece(conf, y, bins=5):
    e = 0.0
    for b in range(bins):
        idx = [i for i, c in enumerate(conf) if b / bins <= c < (b + 1) / bins or (b == bins - 1 and c == 1)]
        if idx: e += len(idx) / len(conf) * abs(sum(conf[i] for i in idx) / len(idx) - sum(y[i] for i in idx) / len(idx))
    return e

def bootstrap_ci(vals, n=2000, seed=0):
    import random; r = random.Random(seed); m = len(vals)
    means = sorted(sum(r.choices(vals, k=m)) / m for _ in range(n))
    return means[int(.025 * n)], means[int(.975 * n)]

if __name__ == "__main__":   # uv run common.py [--print]: tree diagnostics, cached trees (before) vs the current builder (after)
    import sys
    qs = load_subset(); docs = sorted({q["doc"] for q in qs})
    cached = {d: pickle.load(open(HERE / f"cache/doc_{d}.pkl", "rb"))[1] for d in docs if (HERE / f"cache/doc_{d}.pkl").exists()}
    if cached: print("cached trees (cache/doc_*.pkl):"); tree_report(cached, [q for q in qs if q["doc"] in cached])
    fresh = {d: build_tree(pymupdf.open(HERE / f"pdfs/{d}.pdf")) for d in docs}
    print("current build_tree:"); tree_report(fresh, qs)
    if "--print" in sys.argv:
        for d, nodes in fresh.items():
            print(f"\n=== {d}"); [print(f'{"  " * x["level"]}[{x["id"]}] {x["title"]} ({x["start"]}-{x["end"]})') for x in nodes]
