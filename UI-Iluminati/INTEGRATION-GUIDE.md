# UI-Illuminati Integration Guide

## Overview

The UI-Illuminati frontend connects to the `agent-api.py` backend running on `http://localhost:7777`. All API calls go through a Next.js BFF (Backend-for-Frontend) proxy at `/api/agentOS/*` which attaches auth credentials automatically.

## Three Operating Modes

### 1. General Chat (Team Mode)

User talks to a team of agents (`doc-agent` for document reading, `duckduckgo-agent` for web search).

```
User sends message
  → Frontend POST /api/agentOS/teams/{teamId}/runs (FormData + optional files)
  → BFF proxy forwards to backend with JWT
  → Backend streams SSE events (RunContent, ToolCallStarted, ToolCallCompleted, RunStarted)
  → Frontend renders streaming markdown + agent trace
```

**File uploads**: Attach files via the paperclip icon. Files are sent as `multipart/form-data` alongside the message. The agent extracts text and answers based on content.

### 2. Project Mode (RAG)

Upload files to a project, then ask questions against the entire knowledge base.

```
Upload files
  → POST /api/agentOS/projects/{projectId}/files (multipart)
  → Backend extracts text (PDF via PyPDF2, or UTF-8)
  → Chunks at 2000 chars with 200 char overlap
  → Embeds via HuggingFace BAAI/bge-small-en-v1.5 (384 dims)
  → Stores in PgVector table: ai.project_{id}

Query project
  → POST /api/agentOS/projects/{projectId}/query (FormData: message + session_id)
  → Backend creates Agent with Knowledge(PgVector), search_knowledge=True, max_results=30
  → Hybrid search (vector + keyword) retrieves relevant chunks
  → SSE streamed response
```

### 3. Sandbox Mode

Execute Python code via OpenSandbox.

```
User sends code
  → POST /api/agentOS/sandbox/query
  → Backend executes in sandboxed Python environment
  → SSE streamed response with output
```

## Setup

### Prerequisites

- **PostgreSQL with pgvector**: Docker container `agno_pgvector` on port 5533
- **Python 3.11+** with `uv` package manager
- **Node.js 18+** with npm
- **Azure OpenAI** credentials in `.env`
- **HuggingFace API key** in `.env` as `HUGGINGFACE_API_KEY`

### Start Backend

```bash
cd /home/anshul/projects/agentic_rag
uv run agent-api.py
# Runs on http://0.0.0.0:7777
```

### Start Frontend

```bash
cd /home/anshul/projects/agentic_rag/UI-Iluminati
npm run dev
# Runs on http://localhost:3000
```

## API Endpoints

### Auth (Next.js API routes)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login` | POST | Login, sets session cookie |
| `/api/auth/signup` | POST | Register new user |
| `/api/auth/logout` | POST | Clear session |
| `/api/auth/session` | GET | Check session status |

### Teams & Chat (proxied to backend)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agentOS/teams` | GET | List available teams |
| `/api/agentOS/teams/{id}/runs` | POST | Send message to team (SSE) |
| `/api/agentOS/sessions` | GET | List chat sessions |
| `/api/agentOS/sessions/{id}/runs` | GET | Get session run history |

### Projects (proxied to backend)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agentOS/projects` | GET/POST | List or create projects |
| `/api/agentOS/projects/{id}` | GET/DELETE | Get details or delete project |
| `/api/agentOS/projects/{id}/files` | POST | Upload files to project |
| `/api/agentOS/projects/{id}/files/{fid}` | DELETE | Remove file from project |
| `/api/agentOS/projects/{id}/query` | POST | Query project knowledge base (SSE) |
| `/api/agentOS/projects/{id}/sessions` | GET | List project chat sessions |

### Sandbox (proxied to backend)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agentOS/sandbox/query` | POST | Execute Python code (SSE) |

## SSE Event Format

All streaming endpoints return Server-Sent Events:

```
event: RunStarted
data: {"agent": {"name": "Team", "id": "..."}}

event: ToolCallStarted
data: {"tool": {"tool_name": "search_knowledge"}, "agent": {"name": "doc-agent"}}

event: RunContent
data: {"content": "partial markdown text..."}

event: ToolCallCompleted
data: {"tool": {"tool_name": "search_knowledge", "metrics": {"duration": 1.23}}}

event: RunError
data: {"error": "error message"}
```

## Frontend File Structure

```
UI-Iluminati/
├── app/
│   ├── globals.css              # Design tokens (dark theme, orange accent)
│   ├── layout.tsx               # Root layout (JetBrains Mono + Inter fonts)
│   ├── page.tsx                 # Home → ChatInterface
│   ├── (auth)/                  # Public auth routes
│   │   ├── login/page.tsx
│   │   └── signup/page.tsx
│   └── api/agentOS/             # BFF proxy routes to backend
├── components/
│   ├── chat-interface.tsx       # Main UI (sidebar, chat, projects, sandbox)
│   ├── agent-trace.tsx          # Agent activity visualization
│   ├── auth/                    # Login/signup forms
│   ├── providers/               # AuthProvider
│   └── ui/                      # 50+ Shadcn/Radix components
├── lib/
│   ├── api.ts                   # API client functions
│   ├── utils.ts                 # cn() utility
│   ├── auth/                    # Session management
│   └── store/                   # Zustand stores (auth, chat)
├── middleware.ts                # Route protection
└── package.json
```

## Design System

Terminal-inspired dark theme ("dark-product-ui"):

- **Backgrounds**: `#0A0A0A` (primary), `#111111` (sidebar), `#0F0F0F` (cards)
- **Accent**: `#E07A3A` (orange) — used for dots, icons, active states
- **Text**: `#EDEDED` (primary), `#999999` (secondary), `#666666` (muted)
- **Borders**: `#2A2A2A` (standard), `#1A1A1A` (subtle)
- **Fonts**: JetBrains Mono (body), Inter (headings)
- **Texture**: Diagonal pinstripe at 2% white opacity on content areas

## Troubleshooting

### Backend won't start
- Check port 7777 is free: `ss -tlnp | grep 7777`
- Kill existing: `kill $(lsof -ti:7777)`

### File upload fails in project mode
- Verify PostgreSQL is running: `ss -tlnp | grep 5533`
- Check `PGVECTOR_DB_URL` in `.env` uses port **5533**
- Check `HUGGINGFACE_API_KEY` is valid (test: `curl -H "Authorization: Bearer $KEY" https://huggingface.co/api/whoami`)

### Project queries return partial results
- `Knowledge(max_results=30)` in `agent-api.py` controls how many chunks are retrieved
- Check the vector table: `docker exec agno_pgvector psql -U ai -d ai -c "SELECT name, COUNT(*) FROM ai.project_{id} GROUP BY name;"`

### Auth issues
- Session cookie: `__iluminati_session`
- Secret key: `SECRET_KEY` in `.env`
- Middleware protects all routes except `/login`, `/signup`, `/api/auth`
