# Agentic-Rag Projects Feature — Implementation Log

## Plan

Add a "Projects" feature where users upload files that get ingested into a per-project AGNO `Knowledge` base backed by PgVector. Users then ask questions using AGNO's native agentic RAG (`search_knowledge=True`). User isolation via `user_id` stored in browser localStorage. Session metadata in SQLite (`agent_sessions.db`), vector embeddings in PostgreSQL with pgvector.

### Architecture

```
User uploads files to Project
  -> Backend saves file metadata to SQLite (agent_sessions.db)
  -> Backend ingests file content into AGNO Knowledge(PgVector) with table_name="project_{id}"
  -> User asks question
  -> Backend creates Agent with knowledge=Knowledge(PgVector(table="project_{id}")), search_knowledge=True
  -> AGNO's agentic RAG searches the vector DB automatically
  -> SSE streamed response back to UI
```

### Key Design Decisions

1. **AGNO-native RAG**: `agno.knowledge.knowledge.Knowledge` + `agno.vectordb.pgvector.PgVector` per project
2. **Per-project vector table**: Each project gets `project_{project_id}` table in PgVector (schema `ai`)
3. **Embedder**: `OllamaEmbedder` with `nomic-embed-text-v2-moe` (768 dims, fully local)
4. **File ingestion**: Save uploaded bytes to temp file, call `await knowledge.add_content_async(path=..., name=..., reader=PDFReader())` — AGNO handles chunking, embedding, and upserting natively
5. **Session DB**: SQLite `agent_sessions.db` for project + file metadata
6. **No new pyproject.toml**: Uses existing root `/home/anshul/projects/MCP-Tools/pyproject.toml` with `uv`

---

## Completed Work

### 1. `agent-api.py` — Backend (MODIFIED)

**New imports added:**
- `sqlite3`, `uuid`, `json`, `asyncio`, `tempfile`, `pathlib.Path`
- `agno.knowledge.knowledge.Knowledge`
- `agno.knowledge.embedder.ollama.OllamaEmbedder`
- `agno.knowledge.reader.pdf_reader.PDFReader`
- `agno.vectordb.pgvector.PgVector`, `SearchType`
- `fastapi.UploadFile`, `File`, `Form`, `Query`
- `fastapi.responses.StreamingResponse`
- `pydantic.BaseModel`

**Project database setup:**
- SQLite tables `projects` and `project_files` created in `agent_sessions.db`
- `projects`: id, user_id, name, description, created_at
- `project_files`: id, project_id, filename, file_type, size, created_at
- Foreign key with CASCADE delete

**Helper functions:**
- `init_project_tables()` — creates SQLite tables at startup
- `get_project_knowledge(project_id)` — returns AGNO Knowledge object with PgVector (hybrid search, OllamaEmbedder nomic-embed-text-v2-moe, 768 dims)
- `extract_text_from_bytes(content, filename)` — PDF via PyPDF2 or UTF-8 text

**7 new API endpoints on `custom_router`:**

| Endpoint | Method | Description |
|---|---|---|
| `/projects` | POST | Create project (JSON body: user_id, name, description) |
| `/projects` | GET | List projects by user_id query param |
| `/projects/{id}` | GET | Get project details + file list |
| `/projects/{id}` | DELETE | Delete project + drop PgVector table |
| `/projects/{id}/files` | POST | Upload files (multipart), extract text, ingest into PgVector |
| `/projects/{id}/files/{file_id}` | DELETE | Remove file metadata |
| `/projects/{id}/query` | POST | Query project knowledge base with SSE streaming |

**Query endpoint details:**
- Creates a per-request `Agent` with the project's `Knowledge` and `search_knowledge=True`
- Streams SSE events (`RunContent`, `RunEvent`, `RunError`) via `StreamingResponse`
- Uses `project_agent.arun(message, session_id=session_id, stream=True)` as async iterator (no await)
- Non-streaming fallback via `project_agent.run()`

**Config variables (with env overrides):**
- `PGVECTOR_DB_URL` — default: `postgresql+psycopg://postgres:postgres@localhost:5432/rag_db`
- `OLLAMA_HOST` — default: `http://localhost:11434`
- `EMBEDDING_MODEL` — default: `nomic-embed-text-v2-moe`
- `EMBEDDING_DIMENSIONS` — default: `768`

---

### 2. `UI-Iluminati/lib/api.ts` — API Client (MODIFIED)

**New exports:**
- `getUserId()` — generates/caches UUID in localStorage (`agno_user_id` key)
- `createProject(userId, name, description)` — POST `/projects`
- `listProjects(userId)` — GET `/projects?user_id=X`
- `getProject(projectId)` — GET `/projects/{id}` (returns files list)
- `deleteProject(projectId)` — DELETE `/projects/{id}`
- `uploadProjectFiles(projectId, files)` — POST `/projects/{id}/files` (FormData)
- `deleteProjectFile(projectId, fileId)` — DELETE `/projects/{id}/files/{file_id}`
- `queryProject(projectId, message, sessionId)` — POST `/projects/{id}/query` (returns raw Response for SSE)

**New TypeScript interfaces:**
- `ProjectInfo` (id, user_id, name, description, created_at, file_count)
- `ProjectFileInfo` (id, filename, file_type, size, created_at)
- `ProjectDetail extends ProjectInfo` (with files array)

---

### 3. `UI-Iluminati/components/chat-interface.tsx` — Frontend (MODIFIED)

**State changes:**
- Removed mock project data (3 hardcoded projects)
- Added `userId` state from `getUserId()`
- Added `uploadingFiles` loading state
- Changed `Project.chatCount` to `Project.file_count`

**New functions:**
- `loadProjects()` — fetches projects from API on mount
- `loadProjectDetails(projectId)` — fetches project with file list, sets as selected
- `handleDeleteProject(projectId)` — calls API delete, removes from state

**Modified functions:**
- `handleCreateProject` — now async, calls `apiCreateProject()`, adds result to state
- `handleProjectFileUpload` — now async, calls `uploadProjectFiles()`, updates state with returned file metadata, shows uploading indicator
- `handleRemoveFile` — now async, calls `deleteProjectFile()` API
- `handleSubmit` (project mode) — replaced mock setTimeout with real SSE streaming via `queryProject()`, parses `RunContent` and `RunError` events identically to team chat mode

**UI changes:**
- Project list items: now `<div>` with nested `<button>` for click + separate delete button (trash icon, visible on hover)
- Project click loads details from API and clears messages
- Upload button shows "Uploading..." with disabled state during upload
- Projects sidebar shows `file_count` instead of `chatCount`

---

## Bug Fixes

1. **AsyncIterator not awaitable**: Changed `await project_agent.arun(..., stream=True)` to `project_agent.arun(...)` — with `stream=True`, AGNO returns an `AsyncIterator` directly, not an awaitable
2. **Default port**: Fixed `PGVECTOR_DB_URL` default from port `5433` to `5432`
3. **`Knowledge` has no `load_documents()`**: The `Document` class approach doesn't work. AGNO Knowledge doesn't expose a `load_documents()` method. Switched to saving uploaded bytes to a temp file and using `knowledge.add_content(path=..., reader=PDFReader())`
4. **`Knowledge` has no `insert()`**: Despite some docs referencing `insert()`, agno v2.4.7 does not have it. The correct method is `add_content()` / `add_content_async()`
5. **`asyncio.run()` cannot be called from a running event loop**: The sync `knowledge.add_content()` internally calls `asyncio.run()`, which fails inside FastAPI's async handler. Fixed by using `await knowledge.add_content_async()` instead

## AGNO API Reference Notes (v2.4.7)

These are the correct APIs discovered during implementation. Documenting here since the online docs sometimes reference different method names.

### Knowledge class (`agno.knowledge.knowledge.Knowledge`)

**Available public methods** (verified via `dir()`):
- `add_content(path=, url=, text_content=, name=, reader=, metadata=, ...)` — sync, calls `asyncio.run()` internally
- `add_content_async(...)` — async version, **use this inside FastAPI/async contexts**
- `add_contents(paths=, urls=, ...)` / `add_contents_async(...)` — batch versions
- `search(query)` / `async_search(query)` — search the knowledge base
- `remove_all_content()` / `aremove_all_content()`
- `remove_content_by_id()` / `aremove_content_by_id()`
- `remove_vectors_by_name()` / `remove_vectors_by_metadata()`

**Methods that do NOT exist** (despite some docs/examples):
- ~~`insert()`~~ — does not exist in v2.4.7
- ~~`load_documents()`~~ — does not exist
- ~~`load()`~~ — does not exist on the base `Knowledge` class

**Constructor:**
```python
Knowledge(
    vector_db=PgVector(
        table_name="my_table",
        db_url="postgresql+psycopg://user:pass@host:port/db",
        search_type=SearchType.hybrid,  # or .vector, .keyword
        embedder=OllamaEmbedder(id="nomic-embed-text-v2-moe", dimensions=768, host="http://localhost:11434"),
    ),
)
```

**File ingestion (async, for use in FastAPI):**
```python
from agno.knowledge.reader.pdf_reader import PDFReader

await knowledge.add_content_async(
    path="/path/to/file.pdf",
    name="my_document.pdf",
    reader=PDFReader(),   # required for PDFs, optional for text files
)
```

**`WARNING Contents DB not found`** — This is harmless. It means no `contents_db` was set for tracking content status metadata. Not needed for basic ingestion/search.

### Agent streaming (`agno.agent.Agent`)

- `agent.arun(message, stream=True)` — returns `AsyncIterator` directly, do NOT `await` it
- `agent.arun(message, stream=False)` — returns awaitable `RunResponse`
- `agent.run(message)` — sync version

### Docs links

| Topic | URL |
|---|---|
| Knowledge bases overview | https://docs.agno.com/knowledge/vector-stores/pgvector/usage/pgvector-db |
| PDF Reader | https://docs.agno.com/knowledge/concepts/readers/pdf-reader |
| Document Readers | https://docs.agno.com/cookbook/knowledge/readers |
| Agent with Knowledge | https://docs.agno.com/agents/usage/agent-with-knowledge |
| PgVector integration | https://docs.agno.com/integrations/vectordb/pgvector/overview |
| AgentOS API | https://docs.agno.com/agent-os/api |
| Azure OpenAI Embedder | https://docs.agno.com/basics/knowledge/embedder/azure-openai/overview |
| Chunking strategies | https://docs.agno.com/basics/knowledge/chunking/agentic-chunking |

## Files Changed

| File | Action |
|---|---|
| `Agents/Agentic-Rag/agent-api.py` | Modified — added project DB, endpoints, Knowledge/PgVector integration |
| `Agents/Agentic-Rag/UI-Iluminati/lib/api.ts` | Modified — added project API functions + getUserId |
| `Agents/Agentic-Rag/UI-Iluminati/components/chat-interface.tsx` | Modified — connected projects to backend, SSE streaming for project queries |

---

## 31 March 2026 — AgentOS Alignment & PgVector User Separation Refactor

### Problem Statement

After auditing `agent-api.py` against AgentOS best practices, we found the codebase was **working around AgentOS instead of with it**:

1. **Unregistered agents**: Only `doc_agent` and `duckduckgo_agent` are registered. The project agent (created per-request) and sandbox agent (lazy-loaded) are invisible to AgentOS — no auto-routes, no session management, no RBAC, no tracing.
2. **Duplicate code**: Custom SSE streaming, health endpoints, and session management reimplemented despite AgentOS providing all of these out-of-the-box.
3. **Per-project PgVector tables**: Current design creates `project_{uuid}` table per project. With many users/projects, this creates table sprawl and prevents cross-project search for a user.
4. **`include_router` bolted on**: Custom endpoints added after `get_app()` instead of using the `base_app` pattern with proper route conflict resolution.

### Research Sources

| Topic | Source |
|---|---|
| AgentOS auto-generated routes | Source: `agno/os/routers/agents/router.py`, `teams/router.py`, `session/session.py`, `knowledge/knowledge.py` |
| AgentOS `base_app` pattern | Source: `agno/os/app.py` — `base_app` param + `on_route_conflict` |
| AgentOS JWT middleware | Source: `agno/os/middleware/jwt.py` — `excluded_route_paths`, HS256 support |
| PgVector metadata filtering | Source: `agno/vectordb/pgvector/pgvector.py` — `meta_data` JSONB column, `@>` containment queries |
| Knowledge `isolate_vector_search` | Source: `agno/knowledge/knowledge.py` — `linked_to` metadata + auto-filter |
| Knowledge `knowledge_filters` | Source: `agno/agent/agent.py` — per-agent or per-run filter dicts |
| AgentOS API reference | https://docs.agno.com/reference-api/schema/agents/create-agent-run |
| AgentOS security | https://docs.agno.com/agent-os/security |
| Knowledge filter expressions | `agno/vectordb/pgvector/pgvector.py` — `EQ`, `IN`, `GT`, `AND`, `OR` DSL |
| AgentOS run endpoint params | `POST /agents/{id}/runs`: message, stream, session_id, user_id, files, version, background, dependencies, metadata |
| AgentOS session management | `GET/POST/DELETE /sessions` — auto user_id scoping, pagination, CRUD |
| AgentOS knowledge routes | `POST /knowledge/content`, `POST /knowledge/search`, `GET /knowledge/content/{id}/status` |
| AGNO docs index | https://docs.agno.com/llms.txt |

### What AgentOS Auto-Generates (that we were duplicating)

| Our Custom Endpoint | AgentOS Built-in |
|---|---|
| `GET /health` | Auto-generated `GET /health` |
| `GET /info` | Auto-generated `GET /config` (full OS config) |
| `GET /projects/{id}/sessions` | `GET /sessions?type=agent&component_id={agent_id}&user_id={user_id}` |
| `GET /projects/{id}/sessions/{sid}/runs` | `GET /sessions/{session_id}/runs` |
| Custom SSE streaming (project + sandbox) | Built-in SSE on `POST /agents/{id}/runs` with richer event types |

### What Remains Custom (AgentOS has no equivalent)

| Endpoint | Reason |
|---|---|
| `POST /v1/auth/signup`, `/login` | AgentOS has no user registration |
| `POST /projects` (CRUD) | AgentOS has no "project" concept — domain-specific |
| `POST /projects/{id}/files` | File upload + per-project knowledge ingestion with metadata tagging |
| `POST /projects/{id}/query` | AgentOS run routes don't expose `knowledge_filters` param — we need per-request project scoping |
| `POST /sandbox/query` | Lazy sandbox init + file upload to sandbox container |
| `POST /sandbox/close` | Sandbox lifecycle management |

### PgVector User Separation Architecture

**Current (per-project tables):**
```
ai.project_abc123  ← all chunks for project abc123
ai.project_def456  ← all chunks for project def456
ai.project_ghi789  ← all chunks for project ghi789
... (N tables for N projects across all users)
```

**New (per-user tables with metadata filtering):**
```
ai.user_<user_id>  ← single table per user
  └── meta_data JSONB contains: {"project_id": "abc123", "filename": "doc.pdf"}
  └── meta_data JSONB contains: {"project_id": "def456", "filename": "report.pdf"}
  └── GIN index on meta_data for fast JSONB @> queries
```

**How filtering works:**
- AGNO's `PgVector.search()` accepts `filters={"project_id": "abc123"}`
- Translates to SQL: `WHERE meta_data @> '{"project_id": "abc123"}'::jsonb`
- Agent uses `knowledge_filters={"project_id": project_id}` on each run
- `Knowledge(isolate_vector_search=True)` adds `linked_to` auto-filter for extra safety

**Benefits:**
- Hard user isolation (separate tables per user) — good for compliance
- Soft project isolation within a user's table (metadata filters)
- Fewer tables: N_users vs N_projects (typically 10-100x fewer)
- Enables cross-project search for a user if needed later
- AGNO-native: uses `knowledge_filters` + `meta_data` JSONB — no custom SQL
- Clean deletion: drop user table on account delete, `remove_vectors_by_metadata` on project delete

**GIN index needed for performance:**
```sql
CREATE INDEX idx_user_{id}_meta_gin ON ai.user_{id} USING GIN (meta_data);
```

### Refactor Plan

#### Phase 1: AgentOS Alignment (agent-api.py)

1. **Switch to `base_app` pattern**: Create custom `FastAPI` app first, pass to `AgentOS(base_app=custom_app, on_route_conflict="preserve_base_app")`
2. **Remove duplicate endpoints**: Delete custom `/health` and `/info` (use AgentOS built-in)
3. **Remove custom project session endpoints**: Use AgentOS built-in `GET /sessions` with `component_id` filter
4. **Cache project agents**: Dict of `project_id -> Agent` instead of creating per-request
5. **Add project scopes to JWT**: Add `projects:read`, `projects:write`, `projects:delete`, `knowledge:read`, `knowledge:write` to JWT scopes

#### Phase 2: PgVector Migration

1. **Change `get_project_knowledge()`** → `get_user_knowledge(user_id)`: Returns Knowledge with `PgVector(table_name=f"user_{user_id}")`
2. **Add metadata on ingest**: Pass `metadata={"project_id": project_id, "filename": filename}` to `knowledge.add_content_async()`
3. **Filter on query**: Use `knowledge_filters={"project_id": project_id}` in project agent
4. **Add GIN index**: On table creation, add `CREATE INDEX ... USING GIN (meta_data)` for fast metadata queries
5. **Update delete logic**: Project delete → `knowledge.remove_vectors_by_metadata({"project_id": project_id})` instead of `DROP TABLE`
6. **Migration script**: Move existing per-project tables to per-user tables (optional, can start fresh)

#### Phase 3: Frontend BFF Updates

1. **Update proxy routes** to match new backend endpoints where changed
2. **Use AgentOS session endpoints** via BFF proxy instead of custom project session endpoints
3. **Update `api.ts`** to call correct paths

### AGNO PgVector Internals Reference (from source code audit)

**Table schema (v1):**
| Column | Type | Notes |
|---|---|---|
| `id` | String (PK) | MD5 of `{doc_id}_{content_hash}` |
| `name` | String | Document/chunk name |
| `meta_data` | JSONB | **All metadata + filters merged here** |
| `filters` | JSONB | Raw filter dict (bookkeeping only) |
| `content` | TEXT | Chunk text |
| `embedding` | Vector(dims) | Vector embedding |
| `usage` | JSONB | Token usage stats |
| `content_hash` | String | Hash of source content |
| `content_id` | String | Parent Content object ID |
| `created_at` | DateTime | Auto-set |
| `updated_at` | DateTime | Auto-set on update |

**How metadata merges on insert (`_get_document_record()`):**
```python
meta_data = doc.meta_data or {}
if filters:
    meta_data.update(filters)  # user metadata merged into meta_data JSONB
```

**How search filters work (`_search_vector()`, `_search_keyword()`, `_search_hybrid()`):**
```python
# Dict filters → JSONB containment:
stmt = stmt.where(table.c.meta_data.contains(filters))
# SQL: WHERE meta_data @> '{"project_id": "xxx"}'::jsonb

# FilterExpr DSL:
# EQ("project_id", "xxx") → meta_data->>'project_id' = 'xxx'
# IN("status", ["a","b"]) → meta_data->>'status' IN ('a','b')
```

**Knowledge `isolate_vector_search` behavior:**
- Always sets `meta_data["linked_to"] = self.name` on every chunk at insert time
- When `isolate_vector_search=True`, auto-injects `{"linked_to": self.name}` filter on every search
- Useful for multiple Knowledge instances sharing one PgVector table

---

## Security Updates (April 2026)

### Problem Identified

The original implementation had a **critical security vulnerability**: project endpoints relied on client-provided `user_id` from query parameters instead of extracting it from the JWT token. This allowed users to:

1. List other users' projects by guessing IDs
2. Delete other users' projects
3. Upload files to other users' projects
4. Query other users' project knowledge bases

### Solution Implemented

**1. JWT user_id extraction:**
- Added `get_current_user_id()` dependency that extracts `sub` claim from Authorization header
- Uses `HTTPBearer` security scheme
- Raises 401 if missing/invalid/expired

**2. Ownership verification:**
- Added `verify_project_ownership(project_id, user_id)` function
- Queries `projects` table to check `project.user_id == JWT user_id`
- Returns True only if match

**3. Server-side session_id:**
- Generate `session_id` server-side if not provided
- Prevents session hijacking

### Updated Endpoints

All project and sandbox endpoints now require JWT and ownership verification:

| Endpoint | Auth | Ownership Check |
|----------|------|-----------------|
| `POST /projects` | JWT | Uses JWT user_id |
| `GET /projects` | JWT | Own projects only |
| `GET /projects/{id}` | JWT | Must own |
| `DELETE /projects/{id}` | JWT | Must own |
| `POST /projects/{id}/files` | JWT | Must own |
| `DELETE /projects/{id}/files/{file_id}` | JWT | Must own |
| `GET /projects/{id}/sessions` | JWT | Must own |
| `GET /projects/{id}/sessions/{session_id}/runs` | JWT | Must own |
| `POST /projects/{id}/query` | JWT | Must own |
| `POST /sandbox/query` | JWT | Valid token |
| `POST /sandbox/close` | JWT | Valid token |

### Test Results

```
=== Testing Ownership Enforcement ===

1. User A → GET proj-b-1 (User B project)
   Status: 403 ✓ BLOCKED!

2. User B → GET proj-a-1 (User A project)
   Status: 403 ✓ BLOCKED!

3. User A → DELETE proj-b-1 (User B project)
   Status: 403 ✓ BLOCKED!

5. User A → GET proj-a-1 (own project)
   Status: 200 ✓ ALLOWED!
```

### Code Changes in `agent-api.py`

**New imports:**
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
```

**New helper functions:**
```python
http_bearer = HTTPBearer(auto_error=False)

def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> str:
    """Extract user_id from JWT token in Authorization header."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(credentials.credentials, AUTH_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub")
        return user_id
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

def verify_project_ownership(project_id: str, user_id: str) -> bool:
    """Verify that a project belongs to the given user."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT user_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not project:
        return False
    return project["user_id"] == user_id
```

**Example endpoint with ownership:**
```python
@custom_router.get("/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    """Get project details. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    # ... rest of handler
```
