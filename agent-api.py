"""
AgentOS with File Upload and Project-based RAG
- Upload documents (PDF, TXT, DOCX, etc.) per-message or per-project
- Projects: upload files as a knowledge source, then ask questions (AGNO Knowledge + PgVector)
- Per-user project isolation
- General Q&A with team of agents

Usage:
# Ask question with uploaded file
curl -X POST "http://localhost:7777/agents/doc-agent/runs" \
  -F "message=What is this document about?" \
  -F "files=@document.pdf"

# Create a project
curl -X POST "http://localhost:7777/projects" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user1","name":"My Project","description":"Research docs"}'

# Upload files to project
curl -X POST "http://localhost:7777/projects/{id}/files" -F "files=@doc.pdf"

# Query project knowledge
curl -X POST "http://localhost:7777/projects/{id}/query" \
  -F "message=Summarize the key findings"
"""

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
import uuid
from base64 import b64decode, b64encode
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

import jwt as pyjwt
import PyPDF2
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.embedder.huggingface import HuggingfaceCustomEmbedder
from agno.knowledge.embedder.ollama import OllamaEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.media import File
from agno.models.azure import AzureOpenAI
from agno.os import AgentOS
from agno.os.middleware.jwt import JWTMiddleware
from agno.team import Team
from agno.tools import Toolkit
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector, SearchType
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from pydantic import BaseModel

# ============================================================================
# Document Processing Tool
# ============================================================================
load_dotenv()


class DocumentTools(Toolkit):
    """Simple document processing toolkit."""

    def __init__(self):
        super().__init__(name="document_tools", tools=[self.read_document])

    def read_document(self, files: Optional[Sequence[File]] = None) -> str:
        """
        Read and extract text from uploaded documents.
        Supports PDF, TXT, and other text-based files.

        Args:
            files: Files uploaded by user (auto-injected by AGNO)

        Returns:
            Extracted text content that will persist in conversation history
        """
        if not files:
            return "No files uploaded."

        results = []
        for i, file in enumerate(files, 1):
            # Debug: show all available attributes
            print(f"[DEBUG] File {i} attributes: {dir(file)}")

            if not file.content:
                results.append(f"File {i} is empty.")
                continue

            # Get file attributes safely with defaults
            file_name = (
                getattr(file, "name", None)
                or getattr(file, "filename", None)
                or f"file_{i}"
            )
            file_type = (
                getattr(file, "type", None)
                or getattr(file, "content_type", None)
                or "unknown"
            )

            print(
                f"[DEBUG] File {i}: name={file_name}, type={file_type}, size={len(file.content)}"
            )

            try:
                # Check if it's a PDF file
                is_pdf = (
                    isinstance(file_name, str) and file_name.lower().endswith(".pdf")
                ) or (isinstance(file_type, str) and "pdf" in file_type.lower())

                if is_pdf:
                    print(f"[PDF] Processing {file_name} ({len(file.content)} bytes)")

                    # Extract text from PDF using PyPDF2
                    pdf_reader = PyPDF2.PdfReader(BytesIO(file.content))
                    num_pages = len(pdf_reader.pages)
                    print(f"[PDF] Found {num_pages} pages in {file_name}")

                    text_parts = []
                    for page_num, page in enumerate(pdf_reader.pages, 1):
                        try:
                            page_text = page.extract_text()
                            if page_text and page_text.strip():
                                text_parts.append(f"[Page {page_num}]\n{page_text}")
                                print(
                                    f"[PDF] Extracted {len(page_text)} characters from page {page_num}"
                                )
                            else:
                                print(
                                    f"[PDF] Warning: Page {page_num} has no extractable text"
                                )
                        except Exception as page_error:
                            print(f"[PDF] Error on page {page_num}: {page_error}")
                            text_parts.append(
                                f"[Page {page_num}]\n(Error extracting this page: {page_error})"
                            )

                    if text_parts:
                        extracted_text = "\n\n".join(text_parts)
                        print(
                            f"[PDF] Successfully extracted text from {len(text_parts)} pages"
                        )
                        results.append(
                            f"=== Document: {file_name} ===\n"
                            f"Type: PDF\n"
                            f"Pages: {num_pages}\n"
                            f"Extracted: {len(text_parts)} pages with text\n\n"
                            f"{extracted_text}\n"
                            f"=== End of {file_name} ==="
                        )
                    else:
                        print(f"[PDF] Warning: No readable text found in {file_name}")
                        results.append(
                            f"=== Document: {file_name} ===\n"
                            f"Type: PDF\n"
                            f"Pages: {num_pages}\n"
                            f"Warning: This PDF has {num_pages} pages but no extractable text. "
                            f"It may contain only images or scanned content.\n"
                            f"=== End of {file_name} ==="
                        )
                else:
                    # Try to decode as plain text
                    print(f"[TEXT] Processing {file_name} as text file")
                    text = file.content.decode("utf-8", errors="ignore")
                    print(f"[TEXT] Extracted {len(text)} characters")
                    results.append(
                        f"=== Document: {file_name} ===\n"
                        f"Type: Text\n"
                        f"Size: {len(file.content)} bytes\n\n"
                        f"{text}\n"
                        f"=== End of {file_name} ==="
                    )
            except Exception as e:
                import traceback

                error_details = traceback.format_exc()
                print(f"[ERROR] Failed to process {file_name}:")
                print(error_details)
                results.append(
                    f"=== Document: {file_name} ===\n"
                    f"Error: Failed to extract text\n"
                    f"Details: {str(e)}\n"
                    f"Type: {file_type}\n"
                    f"Size: {len(file.content)} bytes\n"
                    f"=== End of {file_name} ==="
                )

        # Return a comprehensive result that will be stored in session history
        full_result = "\n\n".join(results)
        return (
            "I have successfully extracted and stored the document content in this conversation.\n"
            f"You can now ask me questions about the following document(s):\n\n"
            f"{full_result}\n\n"
            f"The document content is now available in our conversation context. "
            f"Ask me anything about it!"
        )


# ============================================================================
# Sandbox Setup
# ============================================================================

SANDBOX_DOMAIN = os.getenv("SANDBOX_DOMAIN", "localhost:8080")
SANDBOX_API_KEY = os.getenv("SANDBOX_API_KEY")
SANDBOX_IMAGE = os.getenv(
    "SANDBOX_IMAGE",
    "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1",
)

SANDBOX_OUTPUT_DIR = Path.home() / "sandbox_outputs"
SANDBOX_OUTPUT_DIR.mkdir(exist_ok=True)

_sandbox_instance: Optional[Sandbox] = None


async def get_sandbox() -> Sandbox:
    global _sandbox_instance, sandbox_agent
    if _sandbox_instance is not None:
        try:
            await _sandbox_instance.is_running()
        except Exception:
            print("[SANDBOX] Existing sandbox is dead, recreating...")
            try:
                await _sandbox_instance.close()
            except Exception:
                pass
            _sandbox_instance = None
            sandbox_agent = None
    if _sandbox_instance is None:
        config = ConnectionConfig(
            domain=SANDBOX_DOMAIN,
            api_key=SANDBOX_API_KEY,
            request_timeout=timedelta(seconds=120),
        )
        _sandbox_instance = await Sandbox.create(
            SANDBOX_IMAGE,
            connection_config=config,
            timeout=timedelta(hours=24),
        )
        print(f"[SANDBOX] Created sandbox: {_sandbox_instance.id}")
    return _sandbox_instance


async def close_sandbox():
    global _sandbox_instance
    if _sandbox_instance:
        await _sandbox_instance.kill()
        await _sandbox_instance.close()
        _sandbox_instance = None
        print("[SANDBOX] Closed sandbox")


class SandboxTools(Toolkit):
    def __init__(self, sandbox: Sandbox, **kwargs):
        self.sandbox = sandbox
        tools = [
            self.run_python,
            self.run_script,
            self.install_packages,
            self.download_file,
            self.read_file,
            self.list_files,
        ]
        super().__init__(name="sandbox_tools", tools=tools, **kwargs)

    async def run_python(self, code: str) -> str:
        execution = await self.sandbox.commands.run(f"python3 -c {repr(code)}")
        stdout = "\n".join(msg.text for msg in execution.logs.stdout).strip()
        stderr = "\n".join(msg.text for msg in execution.logs.stderr).strip()

        if execution.error:
            error_line = f"{execution.error.name}: {execution.error.value}"
            stderr = "\n".join(filter(None, [stderr, f"[error] {error_line}"]))

        if stderr:
            return f"{stdout}\n[stderr]\n{stderr}".strip()
        return stdout or "(no output)"

    async def run_script(self, filename: str, code: str) -> str:
        await self.sandbox.files.write_file(filename, code)
        execution = await self.sandbox.commands.run(f"python3 {filename}")
        stdout = "\n".join(msg.text for msg in execution.logs.stdout).strip()
        stderr = "\n".join(msg.text for msg in execution.logs.stderr).strip()

        if execution.error:
            error_line = f"{execution.error.name}: {execution.error.value}"
            stderr = "\n".join(filter(None, [stderr, f"[error] {error_line}"]))

        if stderr:
            return f"{stdout}\n[stderr]\n{stderr}".strip()
        return stdout or "(no output)"

    async def install_packages(self, packages: str) -> str:
        execution = await self.sandbox.commands.run(f"pip install {packages} -q")
        stdout = "\n".join(msg.text for msg in execution.logs.stdout).strip()
        stderr = "\n".join(msg.text for msg in execution.logs.stderr).strip()
        if execution.error:
            return f"Install failed: {execution.error.name}: {execution.error.value}\n{stderr}"
        return stdout or "Installed successfully"

    async def download_file(self, sandbox_path: str, local_filename: str = "") -> str:
        name = local_filename or Path(sandbox_path).name
        local_path = SANDBOX_OUTPUT_DIR / name
        data = await self.sandbox.files.read_bytes(sandbox_path)
        local_path.write_bytes(data)
        return f"Saved to {local_path} ({len(data):,} bytes)"

    async def read_file(self, sandbox_path: str) -> str:
        """Read the contents of a file in the sandbox."""
        try:
            data = await self.sandbox.files.read_bytes(sandbox_path)
            return data.decode("utf-8", errors="replace")
        except Exception as e:
            return f"Error reading {sandbox_path}: {e}"

    async def list_files(self, directory: str = "/workspace") -> str:
        """List files in a sandbox directory."""
        execution = await self.sandbox.commands.run(f"ls -la {directory}")
        stdout = "\n".join(msg.text for msg in execution.logs.stdout).strip()
        return stdout or "(empty directory)"


# ============================================================================
# Database Setup
# ============================================================================

# SQLite database for session storage
db = SqliteDb(
    db_file="agent_sessions.db",  # Database file in current directory
    id="doc-agent-db",
)

# ============================================================================
# Project Database Setup (SQLite for metadata, PgVector for embeddings)
# ============================================================================

PROJECTS_DB = "agent_sessions.db"
PGVECTOR_DB_URL = os.getenv(
    "PGVECTOR_DB_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/rag_db",
)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text-v2-moe")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
HF_EMBEDDING_DIMENSIONS = int(os.getenv("HF_EMBEDDING_DIMENSIONS", "384"))


def init_project_tables():
    """Create project metadata tables in SQLite."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);

        CREATE TABLE IF NOT EXISTS project_files (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT DEFAULT '',
            size INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS project_sessions (
            session_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            session_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_sessions_project ON project_sessions(project_id);
    """)
    conn.close()


init_project_tables()


# ============================================================================
# Auth Setup (users table + JWT helpers using stdlib only)
# ============================================================================

AUTH_SECRET = os.getenv("SECRET_KEY", "")
if not AUTH_SECRET:
    raise ValueError("SECRET_KEY env var is required for auth")

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 8


def init_auth_tables():
    """Create users table in SQLite."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
    """)
    conn.close()


init_auth_tables()


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 (stdlib, no bcrypt needed)."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return b64encode(salt + key).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    decoded = b64decode(stored_hash)
    salt = decoded[:32]
    stored_key = decoded[32:]
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(key, stored_key)


def create_jwt(user_id: str, email: str) -> str:
    """Create a JWT using pyjwt (same library the middleware uses for validation)."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "scopes": [
            "agents:read",
            "agents:run",
            "teams:read",
            "teams:run",
            "sessions:read",
            "sessions:write",
            "sessions:delete",
        ],
        "iat": now,
        "exp": now + JWT_EXPIRY_HOURS * 3600,
    }
    return pyjwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGORITHM)


http_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> str:
    """
    Extract user_id from JWT token in Authorization header.
    Raises 401 if missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = pyjwt.decode(
            credentials.credentials,
            AUTH_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub")
        return user_id
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


def verify_project_ownership(project_id: str, user_id: str) -> bool:
    """Verify that a project belongs to the given user. Returns True if owned, False otherwise."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    project = conn.execute(
        "SELECT user_id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    conn.close()
    if not project:
        return False
    return project["user_id"] == user_id


def get_project_knowledge(project_id: str) -> Knowledge:
    """Create an AGNO Knowledge object backed by PgVector for a specific project."""
    return Knowledge(
        vector_db=PgVector(
            table_name=f"project_{project_id.replace('-', '_')}",
            db_url=PGVECTOR_DB_URL,
            search_type=SearchType.hybrid,
            embedder=HuggingfaceCustomEmbedder(
                id=HF_EMBEDDING_MODEL,
                dimensions=HF_EMBEDDING_DIMENSIONS,
                api_key=os.getenv("HUGGINGFACE_API_KEY"),
            ),
        ),
        max_results=30,
    )


def extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Extract text from file bytes (PDF or plain text)."""
    is_pdf = filename.lower().endswith(".pdf")
    if is_pdf:
        pdf_reader = PyPDF2.PdfReader(BytesIO(content))
        parts = []
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text and text.strip():
                parts.append(text)
        return "\n\n".join(parts) if parts else ""
    else:
        return content.decode("utf-8", errors="ignore")


# ============================================================================
# LLM Setup
# ============================================================================

llm = AzureOpenAI(
    id=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_5", "gpt-4.1-mini"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT_5"),
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME_5"),
)

# ============================================================================
# Agent Setup
# ============================================================================

doc_agent = Agent(
    id="doc-agent",
    name="Document Q&A Agent",
    model=llm,
    tools=[DocumentTools()],
    instructions=[
        "You can answer questions about uploaded documents or general questions.",
        "IMPORTANT: When files are uploaded, use the read_document tool IMMEDIATELY to extract their content.",
        "The extracted document content will be stored in the conversation history automatically.",
        "After extraction, the document stays in context for all future questions in this session.",
        "Users do NOT need to re-upload the document for follow-up questions.",
        "If asked about a document that was already processed, refer to the document content from the conversation history.",
        "If no files are uploaded, answer using your general knowledge.",
        "Be concise, helpful, and reference specific parts of the document when answering.",
    ],
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=10,
    send_media_to_model=False,
    store_media=True,
    markdown=True,
    debug_mode=True,
)

duckduckgo_agent = Agent(
    id="duckduckgo-agent",
    name="DuckDuckGo Agent",
    model=llm,
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are a helpful assistant that can answer questions and help with tasks.",
        "You can use the DuckDuckGoTools to search the web for information.",
        "You can use the history to remember previous conversations and use that information to answer questions.",
        "You can use the user memories to remember user preferences and use that information to answer questions.",
        "You can use the session summaries to remember the summary of the session and use that information to answer questions.",
        "You can use the agentic memory to remember the memory of the agent and use that information to answer questions.",
        "If the user asks a question that is not related to the documents or the web, you can use the session summaries to remember the summary of the session and use that information to answer questions.",
        "If the user asks a question that is not related to the documents or the web, you can use the agentic memory to remember the memory of the agent and use that information to answer questions.",
        "If the user asks a questions that is not related to the document or the web asnwer it to the best of your knowledge, say I do no know if you can not answer it.",
    ],
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    enable_agentic_memory=True,
    add_history_to_context=True,
    num_history_runs=10,
    send_media_to_model=False,
    store_media=True,
    markdown=True,
    debug_mode=True,
)

# ============================================================================
# Team Setup
# ============================================================================

general_team = Team(
    id="general-team",
    name="General Team",
    members=[doc_agent, duckduckgo_agent],
    model=llm,
    instructions=[
        "Coordinate with team members to provide comprehensive information. Delegate tasks based on the user's request.",
        "IMPORTANT: When files are uploaded, IMMEDIATELY delegate to doc-agent to read and process them using the read_document tool.",
        "You can use the doc_agent to read documents and answer questions about them.",
        "You can use the duckduckgo_agent to search the web for information.",
        "You can use the history to remember previous conversations and use that information to answer questions.",
        "You can use the user memories to remember user preferences and use that information to answer questions.",
        "You can use the session summaries to remember the summary of the session and use that information to answer questions.",
        "You can use the agentic memory to remember the memory of the agent and use that information to answer questions.",
        "If the user asks a question that is not related to the documents or the web, you can use the session summaries to remember the summary of the session and use that information to answer questions.",
        "If the user asks a question that is not related to the documents or the web, you can use the agentic memory to remember the memory of the agent and use that information to answer questions.",
        "If the user asks a questions that is not related to the document or the web asnwer it to the best of your knowledge, say I do no know if you can not answer it.",
    ],
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    enable_agentic_memory=True,
    add_history_to_context=True,
    num_history_runs=10,
    send_media_to_model=False,  # Don't send files directly to coordinator model
    store_media=True,
    markdown=True,
    debug_mode=True,
)

sandbox_agent: Optional[Agent] = None


async def get_sandbox_agent() -> Agent:
    global sandbox_agent
    if sandbox_agent is None:
        sandbox = await get_sandbox()
        sandbox_agent = Agent(
            id="sandbox-agent",
            name="Sandbox Execution Agent",
            model=llm,
            tools=[SandboxTools(sandbox)],
            instructions=[
                "You are a helpful assistant with access to a Python code execution environment (sandbox).",
                "When asked to compute, analyze, or demonstrate something, write and run Python code using the sandbox tools.",
                "The sandbox persists across the conversation - variables, imports, and files you create remain available.",
                "Always show the code you run and explain the output.",
                "When you produce output files (images, spreadsheets, etc.), use the download_file tool to save them to the user's machine.",
                "You can install packages using install_packages if needed.",
                "Use run_python for quick one-liners and run_script for multi-line scripts.",
            ],
            db=db,
            add_history_to_context=True,
            num_history_runs=10,
            markdown=True,
            debug_mode=True,
        )
    return sandbox_agent


# ============================================================================
# AgentOS Setup
# ============================================================================

agent_os = AgentOS(
    id="simple-doc-agentos",
    name="Simple Document Q&A",
    agents=[doc_agent, duckduckgo_agent],
    teams=[general_team],
)

app = agent_os.get_app()

# Add JWT middleware manually so we can use HS256 and exclude auth routes
app.add_middleware(
    JWTMiddleware,
    verification_keys=[AUTH_SECRET],
    algorithm="HS256",
    authorization=True,
    excluded_route_paths=[
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        "/v1/auth/signup",
        "/v1/auth/login",
        "/info",
    ],
)

# ============================================================================
# Custom Endpoints
# ============================================================================

custom_router = APIRouter()


# ============================================================================
# Health & Info Endpoints
# ============================================================================


@custom_router.get("/health")
async def health_check():
    """Health check."""
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "Document Q&A with Projects + Sandbox",
            "agents": ["doc-agent", "duckduckgo-agent", "sandbox-agent"],
            "database": "SQLite (agent_sessions.db) + PgVector",
            "session_storage": "enabled",
            "sandbox": {
                "domain": SANDBOX_DOMAIN,
                "image": SANDBOX_IMAGE,
            },
        }
    )


@custom_router.get("/info")
async def api_info():
    """API information."""
    return JSONResponse(
        content={
            "name": "Document Q&A API with Projects + Sandbox",
            "description": "Upload documents, create projects with knowledge bases, ask questions, and execute Python code in sandbox",
            "endpoints": {
                "agent_runs": "POST /agents/doc-agent/runs",
                "projects_create": "POST /projects",
                "projects_list": "GET /projects?user_id=...",
                "projects_get": "GET /projects/{id}",
                "projects_delete": "DELETE /projects/{id}",
                "projects_upload": "POST /projects/{id}/files",
                "projects_remove_file": "DELETE /projects/{id}/files/{file_id}",
                "projects_query": "POST /projects/{id}/query",
                "sandbox_query": "POST /sandbox/query",
                "sandbox_close": "POST /sandbox/close",
                "health": "GET /health",
                "docs": "GET /docs",
            },
        }
    )


# ============================================================================
# Auth Endpoints
# ============================================================================


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


@custom_router.post("/v1/auth/signup")
async def signup(req: SignupRequest):
    """Create a new user account and return a JWT."""
    if len(req.password) < 8:
        return JSONResponse(
            status_code=400,
            content={"detail": "Password must be at least 8 characters"},
        )

    conn = sqlite3.connect(PROJECTS_DB)
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (req.email,)
    ).fetchone()
    if existing:
        conn.close()
        return JSONResponse(
            status_code=409,
            content={"detail": "An account with this email already exists"},
        )

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(req.password)
    conn.execute(
        "INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, ?, ?)",
        (user_id, req.email, pw_hash, req.name),
    )
    conn.commit()
    conn.close()

    token = create_jwt(user_id, req.email)
    return JSONResponse(content={"access_token": token, "user_id": user_id})


@custom_router.post("/v1/auth/login")
async def login(req: LoginRequest):
    """Authenticate a user and return a JWT."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM users WHERE email = ?", (req.email,)).fetchone()
    conn.close()

    if not user or not verify_password(req.password, user["password_hash"]):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid email or password"},
        )

    token = create_jwt(user["id"], user["email"])
    return JSONResponse(content={"access_token": token, "user_id": user["id"]})


# ============================================================================
# Project CRUD Endpoints
# ============================================================================


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


@custom_router.post("/projects")
async def create_project(req: CreateProjectRequest, user_id: str = Depends(get_current_user_id)):
    """Create a new project for the authenticated user."""
    project_id = str(uuid.uuid4())
    conn = sqlite3.connect(PROJECTS_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO projects (id, user_id, name, description) VALUES (?, ?, ?, ?)",
        (project_id, user_id, req.name, req.description),
    )
    conn.commit()
    conn.close()
    return JSONResponse(
        content={
            "id": project_id,
            "user_id": user_id,
            "name": req.name,
            "description": req.description,
        }
    )


@custom_router.get("/projects")
async def list_projects(user_id: str = Depends(get_current_user_id)):
    """List all projects for the authenticated user."""
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM projects WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()

    projects = []
    for row in rows:
        file_count = conn.execute(
            "SELECT COUNT(*) FROM project_files WHERE project_id = ?",
            (row["id"],),
        ).fetchone()[0]
        projects.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "name": row["name"],
                "description": row["description"],
                "created_at": row["created_at"],
                "file_count": file_count,
            }
        )
    conn.close()
    return JSONResponse(content=projects)


@custom_router.get("/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    """Get project details with file list. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        conn.close()
        return JSONResponse(status_code=404, content={"error": "Project not found"})

    files = conn.execute(
        "SELECT * FROM project_files WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()

    return JSONResponse(
        content={
            "id": project["id"],
            "user_id": project["user_id"],
            "name": project["name"],
            "description": project["description"],
            "created_at": project["created_at"],
            "files": [
                {
                    "id": f["id"],
                    "filename": f["filename"],
                    "file_type": f["file_type"],
                    "size": f["size"],
                    "created_at": f["created_at"],
                }
                for f in files
            ],
        }
    )


@custom_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    """Delete a project and its PgVector table. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    conn = sqlite3.connect(PROJECTS_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()

    # Drop the PgVector table for this project
    try:
        table_name = f"project_{project_id.replace('-', '_')}"
        from sqlalchemy import create_engine, text

        engine = create_engine(PGVECTOR_DB_URL)
        with engine.connect() as pg_conn:
            pg_conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            pg_conn.commit()
        engine.dispose()
    except Exception as e:
        print(f"[WARN] Failed to drop PgVector table: {e}")

    return JSONResponse(content={"status": "deleted"})


# ============================================================================
# Project File Upload & Management
# ============================================================================


@custom_router.post("/projects/{project_id}/files")
async def upload_project_files(
    project_id: str,
    files: list[UploadFile] = FastAPIFile(...),
    user_id: str = Depends(get_current_user_id),
):
    """Upload files to a project and ingest into the knowledge base. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        conn.close()
        return JSONResponse(status_code=404, content={"error": "Project not found"})

    knowledge = get_project_knowledge(project_id)
    uploaded = []
    ingested = 0

    for upload_file in files:
        content = await upload_file.read()
        if not content:
            continue

        file_id = str(uuid.uuid4())
        filename = upload_file.filename or f"file_{file_id}"
        file_type = upload_file.content_type or ""

        # Save metadata to SQLite
        conn.execute(
            "INSERT INTO project_files (id, project_id, filename, file_type, size) VALUES (?, ?, ?, ?, ?)",
            (file_id, project_id, filename, file_type, len(content)),
        )

        # Save to temp file and ingest via knowledge.insert()
        suffix = Path(filename).suffix or ".txt"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            is_pdf = suffix.lower() == ".pdf"
            pdf_chunking = DocumentChunking(chunk_size=2000, overlap=200)
            if is_pdf:
                await knowledge.add_content_async(
                    path=tmp_path,
                    name=filename,
                    reader=PDFReader(chunking_strategy=pdf_chunking),
                )
            else:
                await knowledge.add_content_async(path=tmp_path, name=filename)

            ingested += 1
            print(
                f"[PROJECT] Ingested {filename} ({len(content)} bytes) into knowledge base"
            )
        except Exception as e:
            print(f"[PROJECT] Error ingesting {filename}: {e}")
            import traceback

            traceback.print_exc()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        uploaded.append(
            {
                "id": file_id,
                "filename": filename,
                "file_type": file_type,
                "size": len(content),
            }
        )

    conn.commit()
    conn.close()

    print(
        f"[PROJECT] Uploaded {len(uploaded)} files, ingested {ingested} into PgVector for project {project_id}"
    )
    return JSONResponse(content={"uploaded": uploaded, "ingested": ingested})


@custom_router.delete("/projects/{project_id}/files/{file_id}")
async def delete_project_file(
    project_id: str,
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Remove a file from a project. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    conn = sqlite3.connect(PROJECTS_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "DELETE FROM project_files WHERE id = ? AND project_id = ?",
        (file_id, project_id),
    )
    conn.commit()
    conn.close()
    return JSONResponse(content={"status": "deleted"})


# ============================================================================
# Project Session Endpoints
# ============================================================================


@custom_router.get("/projects/{project_id}/sessions")
async def list_project_sessions(project_id: str, user_id: str = Depends(get_current_user_id)):
    """List all sessions for a project. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM project_sessions WHERE project_id = ? ORDER BY updated_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return JSONResponse(
        content=[
            {
                "session_id": r["session_id"],
                "project_id": r["project_id"],
                "session_name": r["session_name"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    )


@custom_router.get("/projects/{project_id}/sessions/{session_id}/runs")
async def get_project_session_runs(
    project_id: str,
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get all runs (messages) for a project session. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    try:
        conn = sqlite3.connect(PROJECTS_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()

        if not row or not row["runs"]:
            return JSONResponse(content=[])

        # AGNO stores runs as double-encoded JSON
        raw = row["runs"]
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        runs = []
        for run in parsed:
            run_input = ""
            inp = run.get("input")
            if isinstance(inp, dict):
                run_input = inp.get("input_content", "")
            elif isinstance(inp, str):
                run_input = inp
            # Fallback: check messages for user role
            if not run_input:
                for m in run.get("messages", []):
                    if isinstance(m, dict) and m.get("role") == "user":
                        run_input = m.get("content", "")
                        break

            runs.append(
                {
                    "run_id": run.get("run_id", str(uuid.uuid4())),
                    "run_input": run_input,
                    "content": run.get("content", ""),
                    "created_at": run.get("created_at", ""),
                }
            )
        return JSONResponse(content=runs)
    except Exception as e:
        print(f"[PROJECT SESSIONS] Error fetching runs: {e}")
        import traceback

        traceback.print_exc()
        return JSONResponse(content=[])


# ============================================================================
# Project Query Endpoint (Agentic RAG via AGNO Knowledge)
# ============================================================================


@custom_router.post("/projects/{project_id}/query")
async def query_project(
    project_id: str,
    message: str = Form(...),
    session_id: str = Form(None),
    stream: str = Form("true"),
    user_id: str = Depends(get_current_user_id),
):
    """Query a project's knowledge base using agentic RAG. Must be project owner."""
    if not verify_project_ownership(project_id, user_id):
        return JSONResponse(status_code=403, content={"error": "Access denied: not the project owner"})
    
    # Generate session_id server-side if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
    
    # Verify project exists
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        conn.close()
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    conn.close()

    knowledge = get_project_knowledge(project_id)

    # Ensure session is linked to this project
    if session_id:
        s_conn = sqlite3.connect(PROJECTS_DB)
        s_conn.execute("PRAGMA foreign_keys = ON")
        existing = s_conn.execute(
            "SELECT session_id FROM project_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not existing:
            s_conn.execute(
                "INSERT INTO project_sessions (session_id, project_id, session_name) VALUES (?, ?, ?)",
                (session_id, project_id, f"Chat {session_id[-6:]}"),
            )
        else:
            s_conn.execute(
                "UPDATE project_sessions SET updated_at = datetime('now') WHERE session_id = ?",
                (session_id,),
            )
        s_conn.commit()
        s_conn.close()

    # Create a project-specific agent with this knowledge base
    project_agent = Agent(
        id=f"project-agent-{project_id}",
        name=f"Project Agent ({project['name']})",
        model=llm,
        knowledge=knowledge,
        search_knowledge=True,
        instructions=[
            f"You are answering questions about the project '{project['name']}'.",
            "Always search the knowledge base thoroughly before answering. Run multiple searches with varied queries to ensure you cover ALL documents in the knowledge base.",
            "When asked to list files, search with broad generic terms like 'fraud', 'detection', 'analysis', 'review' to retrieve results from every document.",
            "Reference specific parts of the documents when possible, including the document name.",
            "If the knowledge base doesn't contain relevant information, say so clearly.",
            "You have full access to all uploaded project documents. Analyze them without limits.",
            "Be concise and helpful.",
        ],
        db=db,
        add_history_to_context=True,
        num_history_runs=10,
        markdown=True,
    )

    if stream.lower() == "true":

        async def event_stream():
            try:
                run_response = project_agent.arun(
                    message,
                    session_id=session_id,
                    stream=True,
                )
                async for chunk in run_response:
                    if hasattr(chunk, "content") and chunk.content:
                        event_data = json.dumps({"content": chunk.content})
                        yield f"event: RunContent\ndata: {event_data}\n\n"
                    if hasattr(chunk, "event") and chunk.event:
                        event_data = json.dumps({"event": str(chunk.event)})
                        yield f"event: RunEvent\ndata: {event_data}\n\n"
            except Exception as e:
                error_data = json.dumps({"error": str(e)})
                yield f"event: RunError\ndata: {error_data}\n\n"
                print(f"[PROJECT QUERY] Error: {e}")
                import traceback

                traceback.print_exc()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        run_response = project_agent.run(message, session_id=session_id)
        return JSONResponse(
            content={
                "content": run_response.content
                if hasattr(run_response, "content")
                else str(run_response),
                "session_id": session_id,
            }
        )


# ============================================================================
# Sandbox Endpoints
# ============================================================================


@custom_router.post("/sandbox/query")
async def query_sandbox(
    message: str = Form(...),
    session_id: str = Form(None),
    stream: str = Form("true"),
    files: list[UploadFile] = FastAPIFile(None),
    user_id: str = Depends(get_current_user_id),
):
    """Query the sandbox agent with Python code execution capabilities."""
    # Generate session_id server-side if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
    
    try:
        sandbox_agent_instance = await get_sandbox_agent()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": f"Failed to initialize sandbox: {str(e)}"},
        )

    # Upload files into the sandbox container
    uploaded_names = []
    if files:
        sandbox = await get_sandbox()
        for f in files:
            if f.filename:
                content = await f.read()
                sandbox_path = f"/workspace/{f.filename}"
                await sandbox.files.write_file(sandbox_path, content)
                uploaded_names.append(f.filename)
                print(
                    f"[SANDBOX] Uploaded {f.filename} ({len(content):,} bytes) to {sandbox_path}"
                )

    # Prepend file context to the message so the agent knows about them
    if uploaded_names:
        file_list = ", ".join(uploaded_names)
        message = f"[Files uploaded to /workspace/: {file_list}]\n\n{message}"

    if stream.lower() == "true":

        async def event_stream():
            try:
                run_response = sandbox_agent_instance.arun(
                    message,
                    session_id=session_id,
                    stream=True,
                )
                async for chunk in run_response:
                    if hasattr(chunk, "content") and chunk.content:
                        event_data = json.dumps({"content": chunk.content})
                        yield f"event: RunContent\ndata: {event_data}\n\n"
                    if hasattr(chunk, "event") and chunk.event:
                        event_data = json.dumps({"event": str(chunk.event)})
                        yield f"event: RunEvent\ndata: {event_data}\n\n"
            except Exception as e:
                error_data = json.dumps({"error": str(e)})
                yield f"event: RunError\ndata: {error_data}\n\n"
                print(f"[SANDBOX QUERY] Error: {e}")
                import traceback

                traceback.print_exc()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        run_response = sandbox_agent_instance.run(message, session_id=session_id)
        return JSONResponse(
            content={
                "content": run_response.content
                if hasattr(run_response, "content")
                else str(run_response),
                "session_id": session_id,
            }
        )


@custom_router.post("/sandbox/close")
async def close_sandbox_endpoint(user_id: str = Depends(get_current_user_id)):
    """Close the sandbox instance."""
    await close_sandbox()
    return JSONResponse(content={"status": "sandbox closed"})


app.include_router(custom_router)

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    agent_os.serve(
        app="agent-api:app",
        host="0.0.0.0",
        port=7777,
        reload=True,
    )
