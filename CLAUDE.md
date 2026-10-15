# PageIndex RAG

Reasoning-based (vectorless) RAG: documents become section trees; a LangGraph agent
navigates them. See README.md for the architecture.

## Running

- Everything: `./scripts/run_demo.sh` (Postgres container, deps, index, API on 7777, UI on 3000).
- API only: `uv run uvicorn pageindex_rag.server:app --port 7777`
- UI only: `cd UI-Iluminati && npm run dev` (talks to `NEXT_PUBLIC_PAGEINDEX_API`).
- Always use `uv` for Python, never bare `python3` or `pip`.
- Never read, edit or print `.env`. Code loads it via python-dotenv; the OpenRouter key is `OPENROUTER_KEY`.

## Database

Dedicated container `pageindex_pg` (pgvector/pgvector:pg17) on `127.0.0.1:5534`,
user/password/db `pageindex`. Do not touch other containers.
`docker exec pageindex_pg psql -U pageindex -d pageindex`
Tables: `documents` (tree JSONB), `nodes` (flat, full-text `tsv`), LangGraph checkpoint tables.

## Layout

| Path | Purpose |
|---|---|
| `pageindex_rag/parsing.py` | Docling → DocTree; heading levels rebuilt from numbering; runs in a subprocess (Docling can segfault) |
| `pageindex_rag/summarize.py` | cheap-model titles, section/table summaries, figure descriptions |
| `pageindex_rag/pipeline.py` | parse → titles → dedupe → enrich → store (shared by CLI and upload API) |
| `pageindex_rag/tools.py` | framework-free retrieval tools |
| `pageindex_rag/agent.py` | LangChain v1 `create_agent`; prompts v1/v2; tools via `ToolRuntime` |
| `pageindex_rag/runner.py` | one question → `RunReport` (answer, billed cost, tokens, tool calls) |
| `pageindex_rag/api.py`, `server.py` | FastAPI router + app; SSE query; upload jobs; replay |
| `pageindex_rag/auth.py` | auth hook (currently a fixed local user) |
| `pageindex_rag/trace.py` | tool calls → UI trace events |
| `UI-Iluminati/app/page.tsx` | the whole UI; components in `components/pageindex/` |
| `bench/` | benchmark questions, runner, fixtures |

## Gotchas

- OpenRouter with Chat Completions: the billed cost is in `response_metadata.token_usage.cost`.
- Keep the system prompt (catalog) stable: it is what makes prompt caching work.
- The provider can block requests with a content filter; the runner turns that into a refusal.
- OpenRouter keys have spend limits; a 402/403 mid-benchmark means the limit was hit.
