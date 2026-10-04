"""Retrieval methods. Each: index(doc) once, search(question) -> dict(ranked=[pages], conf, + cost counters).

  bm25 / dense / hybrid   classic RAG baselines (page-level; no LLM, no GPU server)
  llm_tree                PageIndex-style tree search by a big LLM over HF Inference Providers
  kev_rerank              hybrid top-30 pages -> Kev Choice (pick page) -> Kev Noul (verify top 3)
  kev_tree                jev-doc-search style: Kev Choice beam search down the outline tree, page Choice, Noul verify
"""
import concurrent.futures as cf, hashlib, json, math, os, re, threading, time
from collections import Counter

import httpx

from common import HERE, children, load_doc

STOP = set("the and for are was what were that this with from which has have had its their how much does did into per fiscal year company".split())
def toks(s): return [w for w in re.findall(r"[a-z0-9]{2,}", s.lower()) if w not in STOP]

def snippet(text, q, words=100):
    """Window of the page densest in question terms (the page 'description' every model sees)."""
    qt, w = set(toks(q)), text.split()
    if len(w) <= words: return " ".join(w)
    best = max(range(0, len(w) - words + 1, 20), key=lambda i: sum(x.lower().strip(".,:;()$") in qt for x in w[i:i + words]))
    return " ".join(w[best:best + words])

def new_cost(): return {"api_tokens": 0, "api_sec": 0.0, "api_wall": 0.0, "kev_tokens": 0, "kev_gpu_sec": 0.0, "calls": 0}

# ---------- lexical + dense ----------
class BM25:
    def __init__(self, texts, k1=1.5, b=0.75):
        self.tf = [Counter(toks(t)) for t in texts]; self.len = [sum(c.values()) for c in self.tf]
        self.avg, self.k1, self.b, n = sum(self.len) / len(texts), k1, b, len(texts)
        df = Counter(w for c in self.tf for w in c); self.idf = {w: math.log(1 + (n - d + .5) / (d + .5)) for w, d in df.items()}
    def scores(self, q):
        qt = set(toks(q))
        return [sum(self.idf[w] * c[w] * (self.k1 + 1) / (c[w] + self.k1 * (1 - self.b + self.b * L / self.avg)) for w in qt if w in c)
                for c, L in zip(self.tf, self.len)]

_embedder = None
def embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(HERE / "cache/fastembed"))
    return _embedder

def order(scores): return sorted(range(len(scores)), key=lambda i: -scores[i])

class Base:
    name = "base"
    def __init__(self, **kw): self.kw = kw
    def index(self, doc):
        self.doc = doc; self.texts, self.nodes = load_doc(doc)
        if self.kw.get("summaries"):
            from summaries import read_summaries
            self.nodes = read_summaries(self.kw["summaries"], doc, self.texts, self.nodes)

class Bm25(Base):
    name = "bm25"
    def index(self, doc): super().index(doc); self.bm = BM25(self.texts)
    def search(self, q):
        s = self.bm.scores(q); return {"ranked": order(s)[:10], "conf": None, "cost": new_cost()}

class Dense(Base):
    name = "dense"
    def index(self, doc):
        super().index(doc); chunks, self.owner = [], []
        for p, t in enumerate(self.texts):
            for i in range(0, max(len(t), 1), 1500): chunks.append(t[i:i + 1500]); self.owner.append(p)
        import numpy as np
        self.emb = np.array(list(embedder().embed(chunks)))
    def scores(self, q):
        import numpy as np
        qe = next(iter(embedder().embed(["Represent this sentence for searching relevant passages: " + q])))
        sim, s = self.emb @ qe, [-1.0] * len(self.texts)
        for o, v in zip(self.owner, sim): s[o] = max(s[o], float(v))
        return s
    def search(self, q): return {"ranked": order(self.scores(q))[:10], "conf": None, "cost": new_cost()}

def rrf(*rankings, k=60):
    sc = Counter()
    for r in rankings:
        for i, p in enumerate(r): sc[p] += 1 / (k + i + 1)
    return [p for p, _ in sc.most_common()]

class Hybrid(Dense):
    name = "hybrid"
    def index(self, doc): super().index(doc); self.bm = BM25(self.texts)
    def candidates(self, q, n=30): return rrf(order(self.bm.scores(q))[:100], order(self.scores(q))[:100])[:n]
    def search(self, q): return {"ranked": self.candidates(q, 10), "conf": None, "cost": new_cost()}

# ---------- HF Inference Providers LLM (disk-cached) ----------
_clients = {}
def llm(model, prompt, cost, max_tokens=1500):
    key = hashlib.sha256(json.dumps([model, prompt, max_tokens, 0, "json_object"]).encode()).hexdigest(); f = HERE / f"cache/{key}.json"
    t0 = time.perf_counter()
    if f.exists(): out = json.load(open(f))
    else:
        from huggingface_hub import InferenceClient, get_token
        token = os.environ.get("HF_TOKEN") or get_token()
        if not token: raise RuntimeError("Export HF_TOKEN or log in with the Hugging Face CLI")
        c = _clients.setdefault(model, InferenceClient(model=model, token=token))
        for attempt in range(6):
            try:
                t = time.perf_counter()
                r = c.chat_completion([{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0, response_format={"type": "json_object"})
                out = {"text": r.choices[0].message.content or "", "tokens": r.usage.total_tokens, "sec": time.perf_counter() - t}
                json.dump(out, open(f, "w")); break
            except Exception:
                if attempt == 5: raise
                time.sleep(5 * 2 ** attempt)
    cost["api_wall"] += time.perf_counter() - t0   # replaced by the recorded API latency when the call was cached
    cost["api_tokens"] += out["tokens"]; cost["api_sec"] += out["sec"]; cost["calls"] += 1
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", out["text"]):
        try: parsed, _ = decoder.raw_decode(out["text"][match.start():])
        except json.JSONDecodeError: continue
        if isinstance(parsed, dict): return parsed
    raise ValueError(f"{model} did not return a JSON object")

class LlmTree(Base):
    """Whole outline in one prompt -> top sections; then page choice among keyword-ranked candidate pages."""
    name = "llm_tree"
    def __init__(self, model="zai-org/GLM-5.3-Flash", **kw): super().__init__(**kw); self.model = model
    def index(self, doc): super().index(doc)
    def search(self, q):
        cost, nodes, texts = new_cost(), self.nodes, self.texts
        toc = "\n".join(f'{"  " * n["level"]}[{n["id"]}] {n["title"]} (p{n["start"]}-{n["end"]}) {n.get("summary", "")}' for n in nodes)
        r = llm(self.model, f"Document outline:\n{toc}\n\nQuestion: {q}\n\nPick the 3 sections most likely to contain the evidence needed to answer. "
                f'Reply only JSON: {{"nodes":[ids]}}', cost)
        ids = [i for i in r.get("nodes", []) if isinstance(i, int) and 0 <= i < len(nodes)][:3]
        pages = sorted({p for i in ids for p in range(nodes[i]["start"], nodes[i]["end"] + 1)})
        qt = set(toks(q)); pages = sorted(sorted(pages, key=lambda p: -len(qt & set(toks(texts[p]))))[:12])
        body = "\n".join(f"[page {p}] {snippet(texts[p], q, 80)}" for p in pages)
        r = llm(self.model, f"Question: {q}\n\nCandidate pages:\n{body}\n\nRank up to 3 pages most likely to contain the evidence that answers the question. "
                'Reply only JSON: {"pages":[ints, best first],"answerable":true/false (do these pages really contain the answer?),"confidence":0.0-1.0}', cost)
        ranked = [p for p in r.get("pages", []) if p in pages]
        try: conf = float(r.get("confidence", 0))
        except (TypeError, ValueError): conf = 0.0
        if r.get("answerable") is False or not ranked: conf = 0.0
        return {"ranked": ranked + [p for p in pages if p not in ranked], "conf": conf, "cost": cost,
                "sections": [(nodes[i]["start"], nodes[i]["end"]) for i in ids]}

# ---------- Kev (decision model, local server: POST /v1/systemone) ----------
class KevClient:
    """At most one request in flight per server slot (so none waits in the server queue and the timeout measures real work),
    retries with backoff on timeouts / connection errors / 5xx, and raises when they run out: the caller records the question as failed."""
    CTX, TIMEOUT, RETRIES = 8192, 60, 4   # Kev-4B is validated to 8,192 tokens; one full 8k request takes ~1 s alone, a few s when slots are shared
    def __init__(self, url, tokenizer=None):
        """llama.cpp server: slots from /props, tokens from /tokenize. Otherwise (IFM K2-Type `jev.serve`, one GPU worker): 2 requests
        in flight, tokens from the local tokenizer.json, and 1,024 of the 8,192 tokens reserved for the template + questions."""
        self.http = httpx.Client(base_url=url, timeout=httpx.Timeout(self.TIMEOUT, connect=5), limits=httpx.Limits(max_connections=64))
        self.model, self.option_limit, self.state_limit = None, None, self.CTX - 1024
        try: slots, self.reserve, self.tok = self._post("/props", None, get=True).json()["total_slots"], 256, None
        except Exception:
            from tokenizers import Tokenizer
            if not tokenizer: raise ValueError("Pass --tokenizer for a non-llama.cpp server")
            slots, self.reserve, self.tok = 2, 1024, Tokenizer.from_file(tokenizer)
            health = self._post("/health", None, get=True).json()
            self.model = health.get("model")
            if "k2-type" in str(self.model).lower(): self.option_limit = 128
        self.gate, self.lock, self.ntoks = threading.BoundedSemaphore(slots), threading.Lock(), {}
    def _post(self, path, body, get=False):
        for attempt in range(self.RETRIES + 1):
            try:
                r = self.http.get(path) if get else self.http.post(path, json=body)
                if r.status_code < 400: return r
                err = httpx.HTTPStatusError(f"{r.status_code}: {r.text[:300]}", request=r.request, response=r)
                if r.status_code < 500: raise err   # 4xx is a bug in the request: no retry
            except httpx.TransportError as e: err = e   # timeouts, refused / dropped connections
            if attempt == self.RETRIES: raise RuntimeError(f"kev {path} failed after {attempt + 1} tries: {err!r}") from err
            time.sleep(2 ** attempt)
    def ntok(self, text):
        """Tokens of a text in Kev's own tokenizer (o200k undercounts it by ~5%, enough to overflow 8k windows)."""
        if text not in self.ntoks:
            self.ntoks[text] = len(self.tok.encode(text, add_special_tokens=False).ids) if self.tok else len(self._post("/tokenize", {"content": text}).json()["tokens"])
        return self.ntoks[text]
    def render(self, value, indent=0):
        """K2's JSON state rendering, before its max_state slice."""
        pad = "  " * indent
        if isinstance(value, dict):
            return "\n".join(f"{pad}{k}:\n{self.render(v, indent + 1)}" if isinstance(v, (dict, list)) else f"{pad}{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return "\n".join(f"{pad}- {self.render(v, indent + 1).strip() if isinstance(v, (dict, list)) else v}" for v in value)
        return f"{pad}{value}"
    def ask(self, state, questions, cost):
        if self.option_limit:
            if self.ntok(self.render(state)) > self.state_limit:
                raise ValueError("K2 would silently truncate this state; split its evidence into chunks")
            for question in questions.values():
                if question["type"] == "choice":
                    for key, desc in question["criteria"].items():
                        if self.ntok(f"{key}: {desc}" if desc else str(key)) > self.option_limit:
                            raise ValueError("K2 silently truncates Choice options to 128 tokens; use --choice-mode snippet or kev_noul")
        with self.gate:
            t = time.perf_counter(); j = self._post("/v1/systemone", {"state": state, "questions": questions}).json(); dt = time.perf_counter() - t
        n = j["usage"]["input_tokens"] if "usage" in j else j["input_tokens"]
        if n > self.CTX: raise RuntimeError(f"kev request of {n} tokens exceeds the validated {self.CTX}")
        with self.lock:  # llama.cpp returns no latency_ms: use request wall time (an upper bound on GPU time when slots share a batch)
            cost["kev_tokens"] += n; cost["kev_gpu_sec"] += j.get("latency_ms", dt * 1000) / 1000; cost["calls"] += 1
        return j["answers"]
    def choice(self, state, instructions, options, cost):
        a = self.ask(state, {"q": {"type": "choice", "instructions": instructions, "criteria": options}}, cost)["q"]
        probs = a["probabilities"]
        if set(probs) != set(options) or any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()) or abs(sum(probs.values()) - 1) > .03:
            raise ValueError("Invalid Choice probabilities returned by server")
        return probs
    def noul(self, state, instructions, cost):
        p = self.ask(state, {"q": {"type": "noul", "instructions": instructions}}, cost)["q"]["noul"]
        if not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1: raise ValueError("Invalid Noul probability")
        return p

POOL = cf.ThreadPoolExecutor(16)   # threads only; KevClient.gate bounds what reaches the server

class KevBase(Base):
    """Stages 2-3 of VectifyAI/jev-doc-search tree_search.py: page Choice over full page text (windowed), then Noul check."""
    BEAM, PAGES_PER_WINDOW, MAX_CANDIDATES, VERIFY_MIN, MAX_OPTIONS = 3, 3, 16, 0.5, 255
    # Jev: 30k of 32k tokens, 60k chars/page. Kev: 8,192 validated; keep 256 for template + instructions + question,
    # and count each option's key/markers (~6 tokens measured) on top of its text, all in Kev's tokenizer
    OPTION_OVERHEAD, MAX_PAGE_CHARS = 8, 20000

    def __init__(self, kev_url="http://127.0.0.1:8009", tokenizer=None, **kw):
        super().__init__(**kw); self.kev = KevClient(kev_url, tokenizer); self.MAX_TOKENS = 8192 - self.kev.reserve
        self.choice_mode = kw.get("choice_mode", "full")
    def index(self, doc): super().index(doc); list(POOL.map(lambda p: self.kev.ntok(self.page(p)), range(len(self.texts))))  # token counts for windows()
    def page(self, p): return self.texts[p][:self.MAX_PAGE_CHARS]
    def option(self, q, key, text):
        if self.choice_mode == "full": return text
        limit = self.kev.option_limit or 128
        words = snippet(text, q, 100).split()
        while words and self.kev.ntok(f"{key}: {' '.join(words)}") > limit: words.pop()
        return " ".join(words)

    def windows(self, pages, q=""):
        out, run, used = [], [], 0
        for p in pages:
            c = self.kev.ntok(self.option(q, f"p{p}", self.page(p))) + self.OPTION_OVERHEAD
            if c > self.MAX_TOKENS: raise ValueError(f"Page {p} cannot fit in a Choice request")
            if run and (len(run) == self.MAX_OPTIONS or used + c > self.MAX_TOKENS): out.append(run); run, used = [], 0
            run.append(p); used += c
        return out + [run] if run else out

    def page_stage(self, q, sections, cost):
        """sections: [(score, [pages])]. One Choice per window; best 3 per window; ranked by section score x page probability."""
        jobs = [(sc, run) for sc, pages in sections for run in self.windows(pages, q)]
        def ask(job):
            sc, run = job
            if len(run) == 1: return [(sc, run[0])]   # ask_choice's single-option shortcut: probability 1, no request
            probs = self.kev.choice({"question": q}, "Which page contains the answer to the question?", {f"p{p}": self.option(q, f"p{p}", self.page(p)) for p in run}, cost)
            return [(sc * probs[k], int(k[1:])) for k in sorted(probs, key=probs.get, reverse=True)[:self.PAGES_PER_WINDOW]]
        ranked, seen = [], set()
        for _, p in sorted((h for hs in POOL.map(ask, jobs) for h in hs), reverse=True):
            if p not in seen: seen.add(p); ranked.append(p)
        return ranked[:self.MAX_CANDIDATES]

    def check(self, q, cands, cost):
        def one(p): return p, self.kev.noul({"question": q, "page": self.page(p)}, "Does this page state information that answers the question?", cost)
        scored = sorted(POOL.map(one, cands), key=lambda s: -s[1])
        kept = [p for p, s in scored if s >= self.VERIFY_MIN] or [p for p, _ in scored[:2]]
        ranked = kept + [p for p, _ in scored if p not in kept]   # kept pages by Noul score, then the rest of the candidates
        return {"ranked": ranked, "kept": kept, "conf": scored[0][1] if scored else 0.0, "cost": cost}

class KevNoul(KevBase):
    """Hybrid top-30 -> independent Noul with evidence in state. No Choice option truncation or window softmax comparison."""
    name = "kev_noul"
    def index(self, doc): super().index(doc); self.h = Hybrid(); self.h.index(doc)
    def search(self, q):
        return self.check(q, self.h.candidates(q, 30), new_cost())

class KevRerank(KevBase):
    """Hybrid (BM25+dense) top-30 pages as one pseudo-section -> page Choice -> Noul check."""
    name = "kev_rerank"
    def index(self, doc): super().index(doc); self.h = Hybrid(); self.h.index(doc)
    def search(self, q):
        cost = new_cost(); cands = self.h.candidates(q, 30)
        return self.check(q, self.page_stage(q, [(1.0, cands)], cost), cost)

class KevTree(KevBase):
    """Port of tree_search.py: Choice beam search over the outline (geometric-mean path score), page Choice, Noul check."""
    name = "kev_tree"
    def index(self, doc):
        super().index(doc); n = self.nodes
        self.kids, self.top = children(n), [k for k in n if k["level"] == 0]
        self.desc = {k["id"]: f'{k["title"]}. {k.get("summary") or self._lead(k)}' for k in n}
    def _lead(self, node):
        t = " ".join(self.texts[node["start"]].split()); i = t.find(node["title"][:30])
        return " ".join(t[(i + len(node["title"]) if i >= 0 else 0):].split()[:30])

    def menu(self, node, kids):
        """section_options: each child as "title. summary", plus the node's own opening pages (before its first child) if any."""
        opts, tg = {}, {}
        for k in kids: opts[f"s{k['id']}"] = self.desc[k["id"]]; tg[f"s{k['id']}"] = (k, k["start"], k["end"])
        if node is not None and kids[0]["start"] > node["start"]:
            key = f"s{node['id']}:opening"
            opts[key] = f'The opening pages of "{node["title"]}", before its subsections. {self._lead(node)}'.strip()
            tg[key] = (None, node["start"], kids[0]["start"] - 1)
        return opts, tg

    def sections(self, q, cost):
        """search_sections: beam search until every path ends in a section with no subsections."""
        paths = [{"score": 1.0, "prod": 1.0, "steps": 0, "node": None, "children": self.top, "range": None}]
        while any(p["range"] is None for p in paths):
            open_ = [p for p in paths if p["range"] is None]
            menus = [self.menu(p["node"], p["children"]) for p in open_]
            def ask(m):
                opts = {k: self.option(q, k, v) for k, v in m[0].items()}
                if not opts: raise ValueError("Document has no selectable sections")
                if len(opts) > self.MAX_OPTIONS: raise ValueError("Section menu exceeds 255 options")
                if sum(self.kev.ntok(v) + self.OPTION_OVERHEAD for v in opts.values()) > self.MAX_TOKENS:
                    raise ValueError("Section menu exceeds token budget; subdivide the index")
                return {k: 1.0 for k in opts} if len(opts) == 1 else self.kev.choice({"question": q}, "Which part of the document most likely contains the answer to the question?", opts, cost)
            grown = [p for p in paths if p["range"] is not None]
            for p, (opts, tg), probs in zip(open_, menus, POOL.map(ask, menus)):
                decided = len(probs) > 1
                for key, pr in probs.items():
                    child, st, en = tg[key]; prod = p["prod"] * (max(pr, 1e-9) if decided else 1.0); steps = p["steps"] + decided
                    kids = self.kids[child["id"]] if child else []
                    grown.append({"score": prod ** (1 / steps) if steps else 1.0, "prod": prod, "steps": steps, "node": child, "children": kids, "range": None if kids else (st, en)})
            paths = sorted(grown, key=lambda p: -p["score"])[:self.BEAM]
        return [(p["score"], list(range(p["range"][0], p["range"][1] + 1))) for p in paths]

    def search(self, q):
        cost = new_cost()
        secs = self.sections(q, cost); out = self.check(q, self.page_stage(q, secs, cost), cost)
        out["sections"] = [(p[0], p[-1]) for _, p in secs]; return out

REGISTRY = {"bm25": Bm25, "dense": Dense, "hybrid": Hybrid, "llm_tree": LlmTree, "kev_rerank": KevRerank, "kev_tree": KevTree, "kev_noul": KevNoul}
