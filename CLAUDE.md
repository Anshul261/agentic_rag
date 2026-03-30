# Agentic RAG — UI-Illuminati

## Project Overview

A general-purpose agentic AI platform with document reading, online search, and project-based RAG. Built with AGNO framework, Azure OpenAI, and a dark terminal-inspired Next.js frontend ("UI-Illuminati").

**Goal**: Push agents to work within files and folders locally using simple tools. Currently supports document Q&A in chat mode and project-based RAG with uploaded files.

## Architecture

```
┌──────────────────────┐     ┌─────────────────────────────────┐
│  UI-Illuminati       │     │  agent-api.py (FastAPI + AGNO)  │
│  Next.js 16 + React  │────>│  Port 7777                      │
│  Port 3000           │ BFF │                                  │
│  Tailwind + Shadcn   │proxy│  ┌─── General Chat (Team)       │
└──────────────────────┘     │  │    doc-agent + duckduckgo     │
                             │  ├─── Project Mode (RAG)         │
                             │  │    PgVector + HF Embeddings   │
                             │  └─── Sandbox Mode               │
                             │       OpenSandbox (Python exec)  │
                             └─────────────────────────────────┘
                                        │           │
                              ┌─────────┘           └──────────┐
                              ▼                                ▼
                    ┌──────────────────┐          ┌──────────────────┐
                    │  PostgreSQL      │          │  Azure OpenAI    │
                    │  PgVector        │          │  gpt-5 (default) │
                    │  Port 5533       │          │  gpt-4.1-mini    │
                    │  Container:      │          │  o4-mini          │
                    │  agno_pgvector   │          └──────────────────┘
                    └──────────────────┘
```

## Quick Start

```bash
# 1. Start PostgreSQL (Docker — already running as agno_pgvector on port 5533)
#    If not running: docker start agno_pgvector

# 2. Start Ollama (optional, for local embeddings)
#    ollama serve

# 3. Start the backend
cd /home/anshul/projects/agentic_rag
uv run agent-api.py

# 4. Start the frontend (separate terminal)
cd UI-Iluminati
npm run dev

# 5. Open http://localhost:3000
```

## Key Files

| File | Purpose |
|------|---------|
| `agent-api.py` | Main backend — AGNO agents, project CRUD, file upload, RAG query endpoints |
| `pyproject.toml` | Python dependencies (managed with `uv`) |
| `.env` | All secrets and config (Azure keys, DB URLs, HF token) |
| `UI-Iluminati/` | Next.js frontend app |
| `UI-Iluminati/app/globals.css` | Design tokens — dark terminal theme with orange accent |
| `UI-Iluminati/components/chat-interface.tsx` | Main UI — sidebar, chat, projects, sandbox tabs |
| `UI-Iluminati/components/agent-trace.tsx` | Agent activity visualization during streaming |
| `UI-Iluminati/lib/api.ts` | Frontend API client (BFF proxy to backend) |
| `UI-Iluminati/lib/store/auth-store.ts` | Zustand auth state management |
| `UI-Iluminati/middleware.ts` | Route protection (redirects to /login if unauthenticated) |
| `AGENTS.md` | Project goals and sandbox setup instructions |
| `log.md` | Implementation log with AGNO API reference notes |

## Running Commands

- **Always use `uv`** to run Python — never bare `python3` or `pip`. Example: `uv run agent-api.py`
- **Frontend**: `npm run dev` (from `UI-Iluminati/` directory)
- Never access read, edit or modify the .env
- **Build frontend**: `npm run build` (from `UI-Iluminati/` directory)
- PostgreSQL runs in Docker container `agno_pgvector` on port **5533** (maps to 5432 inside container)
- Access DB via: `docker exec agno_pgvector psql -U ai -d ai`

## Environment Variables (`.env`)

| Variable | Purpose |
|----------|---------|
| `PGVECTOR_DB_URL` | PostgreSQL connection string. **Port 5533**, user `ai`, db `ai` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT_5` | Azure endpoint for gpt-5 (default LLM) |
| `AZURE_OPENAI_DEPLOYMENT_NAME_5` | Deployment name for gpt-5 |
| `HUGGINGFACE_API_KEY` | HuggingFace Inference API key (used for project embeddings) |
| `SECRET_KEY` | JWT secret for auth sessions |
| `BRAVE_API_KEY` | Brave Search API key |

**Note**: `.env`.  Both must use port **5533**. The last one wins.

## Backend Architecture (`agent-api.py`)
Using the AGNO agent logs https://docs.agno.com/llms.txt

### Three Modes

1. **General Chat** — Team-based agent with `doc-agent` (document reader) and `duckduckgo-agent` (web search). Streams SSE responses. Endpoint: `POST /api/agentOS/teams/{teamId}/runs`

2. **Project Mode** — Per-project RAG. Files uploaded, chunked (2000 chars, 200 overlap), embedded via HuggingFace (`BAAI/bge-small-en-v1.5`, 384 dims), stored in PgVector. Queries use hybrid search with `max_results=30`. Endpoint: `POST /projects/{id}/query`

3. **Sandbox Mode** — Python code execution via OpenSandbox. Endpoint: `POST /sandbox/query`

### Embeddings

- **Project RAG**: `HuggingfaceCustomEmbedder` with `BAAI/bge-small-en-v1.5` (384 dimensions)
- **Chunking**: `DocumentChunking(chunk_size=2000, overlap=200)` — critical to stay within model context limits
- **Search**: Hybrid search (vector + keyword) via PgVector
- Each project gets its own PgVector table: `ai.project_{uuid_with_underscores}`

### Database

- **SQLite** (`agent_sessions.db`): Project metadata, file metadata, session tracking
- **PgVector** (PostgreSQL): Vector embeddings per project, agent session storage

### LLM

- Default: Azure OpenAI **gpt-5** (`AZURE_OPENAI_DEPLOYMENT_NAME_5`)
- Configured via `AZURE_OPENAI_ENDPOINT_5` environment variable

## Frontend Architecture (`UI-Iluminati/`)

### Stack
- Next.js 16 + React 19 + TypeScript
- Tailwind CSS 4 with CSS custom properties
- Shadcn/ui (50+ Radix components)
- Zustand for state management
- Iron-session + JWT for auth

### Design System
Dark terminal-inspired aesthetic ("dark-product-ui"):
- Near-black backgrounds (`#0A0A0A`)
- Orange accent (`#E07A3A`) for interactive elements and dots
- JetBrains Mono (primary) + Inter (headings)
- Diagonal pinstripe texture on content areas
- All text mono, uppercase labels with wide tracking
- Thin borders (`#2A2A2A`), minimal animations

### Auth Flow
1. Login/signup via `/api/auth/login` and `/api/auth/signup`
2. Backend sets HTTP-only `__iluminati_session` cookie
3. Middleware validates cookie on protected routes
4. BFF proxy at `/api/agentOS/*` attaches JWT from cookie to backend requests

### Key Components
- `chat-interface.tsx` — Main UI (sidebar + chat + project files panel)
- `agent-trace.tsx` — Shows agent tool calls and progress during streaming
- `auth/login-form.tsx` and `signup-form.tsx` — Auth pages

## Known Issues & Gotchas

1. **AGNO API quirks**: `agent.arun(message, stream=True)` returns `AsyncIterator` directly — do NOT `await` it. See `log.md` for full AGNO API reference.

2. **Embedding context limits**: The `nomic-embed-text-v2-moe` Ollama model has strict context limits. Large PDF chunks fail silently (return 0-dim vectors). Current fix: use HuggingFace embedder with smaller chunks (2000 chars).

3. **Duplicate `.env` entries**: `PGVECTOR_DB_URL` appears on lines 7 and 30. Last entry wins. Both must match (port 5533).

4. **Knowledge `max_results`**: Default is 10. Set to 30 for projects to ensure multi-file coverage on broad queries. The param is on `Knowledge()`, not `Agent()`.

5. **HuggingFace auth**: The embedder reads `HUGGINGFACE_API_KEY` env var (not `HUGGINGFACE_HUB_TOKEN`).

## Future Plans

- Document creation (DOCX/PDF generation)
- PowerPoint creation mode
- Excel analysis mode
- Local file management (move, copy, organize)
- Switch to fully local LLMs (Fireworks AI, OpenRouter)
- OpenSandbox for arbitrary code execution (partially implemented)

## AGNO Framework Reference

For AGNO-specific APIs, search https://docs.agno.com/llms.txt for the latest details. See `log.md` for verified API signatures and common pitfalls discovered during development.

## Sandbox Run
To start the sandbox server:
1. Pull the sandbox image (if not already)
docker pull sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1
2. Configure sandbox (copy example config)
cp $(uv python)/lib/python3.11/site-packages/example.config.toml ~/.sandbox.toml
3. Set environment variables in agentic_rag/.env:
SANDBOX_DOMAIN=localhost:8080
SANDBOX_API_KEY=    # only if you enabled api_key in ~/.sandbox.toml
4. Start the sandbox server:
source .venv/bin/activate
opensandbox-server
The server will bind to 127.0.0.1:8080. Verify:
curl http://localhost:8080/health
