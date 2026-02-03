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
