# PageIndex RAG

Reasoning-based retrieval over your documents. Instead of chunking text into a vector
database, each document becomes a **table-of-contents tree** (sections, figures, tables,
with summaries). An agent reads the catalog, opens the trees it needs and reads only the
relevant sections, then answers with page-level citations. The UI shows the path it took.

```bash
./scripts/run_demo.sh          # database, deps, index, API and UI; Ctrl+C stops everything
```

Then open http://localhost:3000. Test questions: [docs/TEST_QUESTIONS.md](docs/TEST_QUESTIONS.md).

## How it works

```
documents ──Docling──▶ section/figure/table tree ──cheap LLM──▶ summaries, figure descriptions
                                                                   │
                                            Postgres (trees as JSONB + full-text index)
                                                                   │
question ──▶ LangGraph agent ──tools──▶ catalog → search_nodes → get_tree → read_nodes / look_at_figure
                    │                                                        │
                    └──── structured answer + citations ◀────────────────────┘
```

| Stage | What happens | Code |
|---|---|---|
| Parse | Docling (CPU or GPU) in an isolated subprocess; headings → tree, figures cropped, tables kept | `pageindex_rag/parsing.py` |
| Enrich | Cheap model fixes titles, summarizes sections/tables, describes figures | `summarize.py` |
| Store | One row per document (tree JSONB) + one row per node (full-text search) | `store.py` |
| Ask | LangChain v1 `create_agent` (LangGraph); catalog in the cached system prompt | `agent.py`, `runner.py` |
| Serve | FastAPI: browse, ask (SSE), upload, replay; Postgres checkpointer for chat memory | `api.py`, `server.py` |
| Trace | Tool calls → structured events for the UI's search-path view; OpenTelemetry spans | `trace.py`, `telemetry.py` |

Supported uploads: PDF, DOCX, PPTX, XLSX, HTML, Markdown, images.

## Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `OPENROUTER_KEY` | required | LLM access via OpenRouter |
| `PAGEINDEX_REASONING_MODEL` | `openai/gpt-6.1-sol` | navigates trees and answers |
| `PAGEINDEX_CHEAP_MODEL` | `openai/gpt-6-luna` | indexing summaries, figures, titles |
| `PAGEINDEX_PROMPT` | `v2` | `v2` adds scope, untrusted-content and dual-use rules |
| `PAGEINDEX_READ_MODE` | `full` | `extract`: cheap model condenses sections first |
| `PAGEINDEX_DB_URL` | `postgresql://pageindex:pageindex@127.0.0.1:5534/pageindex` | the `pageindex_pg` container |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | export OpenTelemetry traces to any collector |

The UI reads `NEXT_PUBLIC_PAGEINDEX_API` (default `http://localhost:7777`).

## Command line

```bash
uv run -m pageindex_rag.cli index ~/papers --collection mypapers   # parse + enrich + store
uv run -m pageindex_rag.cli ask --collection mypapers "question"   # one question, with cost
uv run -m pageindex_rag.cli show <doc_id>                          # print a document tree
PYTHONPATH=. uv run python bench/run_bench.py --label run1         # 40-question benchmark
```

## Auth

There is none yet: every request is the local user. `pageindex_rag/auth.py` is the single
hook where an auth service plugs in; all API routes already depend on it.

## Benchmark

`bench/` holds 40 graded questions from single facts to adversarial probes (prompt
injection, secret extraction, jailbreaks, over-refusal), with gold answers checked against
the source text. Deterministic checks plus a cross-family LLM judge; reports land in
`bench/results/`.
