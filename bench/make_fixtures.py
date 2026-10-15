"""Build replay fixtures for the UI from tool calls recorded in earlier live runs.

    PYTHONPATH=. uv run python bench/make_fixtures.py

Events come from the real TraceBuilder over the stored trees, so they match what
a live run streams. Fixture run ids start with "fixture-" so they are easy to
tell apart from real recorded runs.
"""

import json
from pathlib import Path

from pageindex_rag.api import RUNS_DIR
from pageindex_rag.store import Store
from pageindex_rag.tools import ToolContext
from pageindex_rag.trace import TraceBuilder

GNN = "20d48ed184a74ce7"

# Live run of 2026-10-15 (step 3 of the build): tool calls, answer and citations as printed.
GNN_ANSWER = """The systematic review groups GNN architectures used for financial fraud detection into **four main families**: [1]

| Architecture family | Representative models | Main idea |
|---|---|---|
| **Convolutional GNNs** | GCN and **GraphSAGE** | Aggregate information from a node's local neighborhood to learn its representation. [1][2] |
| **Attention-based GNNs** | GAT; specialized models such as **APAN** and **GraphMSE** | Learn which neighboring nodes or edges are most relevant and weight them. [1][2] |
| **Metapath-based GNNs** | **HMF-GNN** and other heterogeneous, path-based models | Use predefined sequences of node and edge types to capture relationships in heterogeneous graphs. [1][2] |
| **Transformer-based GNNs** | Graph Transformer Networks (**GTN**), including **S_HGTNs** | Learn useful graph connections and metapaths rather than relying only on predefined paths. [1][2] |

**GCN, GraphSAGE, and GAT are the most commonly employed architectures**. [3]

**Cryptocurrency is the most-studied financial area**, particularly Bitcoin and Ethereum: **51%** of studies, followed by online transactions (**25%**), credit cards (**15%**), insurance (**6%**), and taxation (**3%**). [4][5]"""

GNN_CITES = [("0024", "7–10"), ("0037", "11"), ("0033", "9–10"), ("0043", "12"), ("0036", "10–12")]

# Live run of 2026-10-15: SMOTE question. Its 36 citations are recorded (doc:node); the answer text is not.
SMOTE_READS = [
    "0e3d26556c97598f:0011", "0e3d26556c97598f:0016", "0e3d26556c97598f:0017",
    "2c21156b4336590c:0013", "2c21156b4336590c:0024",
    "a80259f53fc0db6a:0016", "a80259f53fc0db6a:0024",
    "55d2907dd0baf811:0024", "55d2907dd0baf811:0028", "55d2907dd0baf811:0030",
    "9c1e9e90e128c283:0008", "9c1e9e90e128c283:0016", "9c1e9e90e128c283:0020",
    "764d2ed2383e591f:0017", "764d2ed2383e591f:0044",
    "028ee87d9d7d84f7:0012", "028ee87d9d7d84f7:0020", "028ee87d9d7d84f7:0025",
    "1ee5ef4ed49fec8a:0013", "1ee5ef4ed49fec8a:0014", "1ee5ef4ed49fec8a:0037",
]
SMOTE_TREES = ["2c21156b4336590c", "55d2907dd0baf811", "764d2ed2383e591f", "9c1e9e90e128c283",
               "0e3d26556c97598f", "a80259f53fc0db6a", "1ee5ef4ed49fec8a", "028ee87d9d7d84f7"]


def build(builder: TraceBuilder, calls: list[tuple[float, str, dict]]) -> list[dict]:
    events = [dict(t=0.0, event="Trace", data=builder.start())]
    for t, name, args in calls:
        if ev := builder.from_tool_call(name, json.dumps(args)):
            events.append(dict(t=t, event="Trace", data=ev))
    return events


def main() -> None:
    store = Store()
    builder = TraceBuilder(ToolContext(store=store, collection="litreview", data_dir=Path("data/pageindex")))
    titles = {d: t for d, t, _, _ in store.list_documents("litreview")}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    q = "Which GNN architectures are used for financial fraud detection, and which financial area is most studied?"
    events = build(builder, [
        (4.2, "get_tree", {"doc_id": GNN}),
        (9.8, "read_nodes", {"refs": [f"{GNN}:{n}" for n in
                                      ("0024", "0027", "0029", "0031", "0032", "0033", "0036", "0037")]}),
        (14.5, "look_at_figure", {"doc_id": GNN, "node_id": "0043", "question": "Which areas and percentages?"}),
    ])
    events.append(dict(t=24.6, event="Answer", data=dict(answer=GNN_ANSWER, citations=[
        dict(doc_id=GNN, doc_title=titles[GNN], node_id=n, pages=p) for n, p in GNN_CITES])))
    events.append(dict(t=24.7, event="Stats", data=dict(seconds=24.7, cost_usd=0.024, model_calls=4, tool_calls=3,
                                                         run_id="fixture-gnn")))
    (RUNS_DIR / "fixture-gnn.json").write_text(json.dumps(dict(question=q, collection="litreview", events=events)))

    q = "Which papers handle class imbalance with SMOTE or resampling, and what results do they report?"
    calls = [(3.1, "search_nodes", {"query": "SMOTE resampling oversampling undersampling class imbalance results"}),
             (5.0, "search_nodes", {"query": "SMOTE ADASYN resampling experimental results accuracy F1"})]
    calls += [(8.0 + i * 1.2, "get_tree", {"doc_id": d}) for i, d in enumerate(SMOTE_TREES)]
    calls += [(24.0, "read_nodes", {"refs": SMOTE_READS[:12]}), (31.0, "read_nodes", {"refs": SMOTE_READS[12:]})]
    events = build(builder, calls)
    events.append(dict(t=40.0, event="Answer", data=dict(
        answer="_Replay fixture: this search path was rebuilt from a recorded live run's citations; "
               "that run's answer text was not saved. Ask the question live to get the full answer._",
        citations=[dict(doc_id=d, doc_title=titles[d], node_id=n, pages=builder._node_event(d, n)["pages"])
                   for d, n in (r.split(":") for r in SMOTE_READS[::3])])))
    events.append(dict(t=40.1, event="Stats", data=dict(seconds=96.0, cost_usd=0.20, model_calls=7, tool_calls=17,
                                                         run_id="fixture-smote")))
    (RUNS_DIR / "fixture-smote.json").write_text(json.dumps(dict(question=q, collection="litreview", events=events)))
    print("wrote", sorted(p.name for p in RUNS_DIR.glob("fixture-*.json")))


if __name__ == "__main__":
    main()
