"""Grep stored node text: uv run python bench/grep_nodes.py <regex> [doc_id ...] — for verifying gold answers."""
import re, sys
from pageindex_rag.store import Store
pat = re.compile(sys.argv[1], re.I)
docs = sys.argv[2:]
rows = Store().conn.execute("select doc_id, node_id, kind, page_start, text, coalesce(summary,'') from nodes where collection='litreview'").fetchall()
n = 0
for d, nid, kind, p, text, summ in rows:
    if docs and d not in docs: continue
    for src, body in (("text", text), ("summary", summ)):
        for m in pat.finditer(body):
            s = re.sub(r"\s+", " ", body[max(0, m.start()-130): m.end()+130])
            print(f"{d}:{nid} ({kind} p{p}, {src}) …{s}…"); n += 1
            if n > 12: sys.exit()
