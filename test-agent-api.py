"""
AgentOS API for Distributed PgVector RAG System
Features:
- Session Management (create, retrieve, update sessions)
- Knowledge Upload (PDFs, URLs, text content)
- Team Execution with streaming responses
- User isolation and memory persistence
- Automatic API documentation (FastAPI/OpenAPI)
- JWT Authentication (optional - currently disabled)

Endpoints:
- POST /teams/{team_id}/runs - Execute RAG queries
- GET /sessions - List user sessions
- GET /sessions/{session_id} - Get session details
- GET /sessions/{session_id}/runs - Get session run history
- PATCH /sessions/{session_id} - Update session
- POST /knowledge/content - Upload content
- GET /health - Health check

Setup:
1. Set environment variables:
   - AZURE_OPENAI_API_KEY
   - AZURE_OPENAI_ENDPOINT
   - AZURE_OPENAI_DEPLOYMENT_NAME

2. Run PostgreSQL with pgvector:
   docker run -d --name agno-postgres \
     -e POSTGRES_DB=ai -e POSTGRES_USER=ai -e POSTGRES_PASSWORD=ai \
     -p 5533:5432 pgvector/pgvector:pg17

3. Run Ollama for embeddings:
   ollama pull nomic-embed-text

4. Start the API:
   python agent-api.py

Usage:
   curl -X POST "http://localhost:7777/teams/distributed-pgvector-rag-team/runs" \
     -H "Content-Type: multipart/form-data" \
     -F "message=How do I make Tom Kha Gai?" \
     -F "stream=true"
"""

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.ollama import OllamaEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.azure import AzureOpenAI
from agno.os import AgentOS

# JWT middleware imports removed - can be re-added later for production authentication
# from agno.os.middleware import JWTMiddleware
# from agno.os.middleware.jwt import TokenSource
from agno.team.team import Team
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Configuration
# ============================================================================

# Database configuration
DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5533/ai")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

# JWT Configuration - commented out, can be re-enabled later
# JWT_SECRET_KEY = os.getenv(
#     "JWT_SECRET_KEY", "your-super-secret-key-change-in-production"
# )
# JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Server configuration
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "7777"))
API_RELOAD = os.getenv("API_RELOAD", "true").lower() == "true"

# ============================================================================
# Database Setup
# ============================================================================

# Initialize PostgreSQL database for agent sessions and memory
db = PostgresDb(
    id="rag-db",
    db_url=DB_URL,
)

# ============================================================================
# LLM Configuration
# ============================================================================

# Azure OpenAI model for main conversations
llm = AzureOpenAI(
    id=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
)

# ============================================================================
# Knowledge Base Setup
# ============================================================================

# Vector-focused knowledge base for semantic similarity search
vector_knowledge = Knowledge(
    name="Vector Knowledge Base",
    description="Semantic search using pgvector for Thai recipes",
    vector_db=PgVector(
        table_name="recipes_vector",
        db_url=DB_URL,
        search_type=SearchType.vector,
        embedder=OllamaEmbedder(
            id=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
            host=OLLAMA_HOST,
        ),
    ),
)

# Hybrid knowledge base combining vector and text search
hybrid_knowledge = Knowledge(
    name="Hybrid Knowledge Base",
    description="Combined vector and text search for comprehensive results",
    vector_db=PgVector(
        table_name="recipes_hybrid",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OllamaEmbedder(
            id=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
            host=OLLAMA_HOST,
        ),
    ),
)

# ============================================================================
# Agent Definitions
# ============================================================================

# Vector Retriever Agent - Specialized in vector similarity search
vector_retriever = Agent(
    name="Vector Retriever",
    model=llm,
    role="Retrieve information using vector similarity search in PostgreSQL",
    knowledge=vector_knowledge,
    search_knowledge=True,
    instructions=[
        "Use vector similarity search to find semantically related content.",
        "Focus on finding information that matches the semantic meaning of queries.",
        "Leverage pgvector's efficient similarity search capabilities.",
        "Retrieve content that has high semantic relevance to the user's query.",
        "Return relevant recipe information with proper context.",
    ],
    markdown=True,
)

# Hybrid Searcher Agent - Specialized in hybrid search
hybrid_searcher = Agent(
    name="Hybrid Searcher",
    model=llm,
    role="Perform hybrid search combining vector and text search",
    knowledge=hybrid_knowledge,
    search_knowledge=True,
    instructions=[
        "Combine vector similarity and text search for comprehensive results.",
        "Find information that matches both semantic and lexical criteria.",
        "Use PostgreSQL's hybrid search capabilities for best coverage.",
        "Ensure retrieval of both conceptually and textually relevant content.",
        "Complement vector search results with keyword-based findings.",
    ],
    markdown=True,
)

# Data Validator Agent - Specialized in data quality validation
data_validator = Agent(
    name="Data Validator",
    model=llm,
    role="Validate retrieved data quality and relevance",
    instructions=[
        "Assess the quality and relevance of retrieved information.",
        "Check for consistency across different search results.",
        "Identify the most reliable and accurate information.",
        "Filter out any irrelevant or low-quality content.",
        "Ensure data integrity and relevance to the user's query.",
        "Cross-reference information from multiple sources when available.",
    ],
    markdown=True,
)

# Response Composer Agent - Specialized in response composition
response_composer = Agent(
    name="Response Composer",
    model=llm,
    role="Compose comprehensive responses with proper source attribution",
    instructions=[
        "Combine validated information from all team members.",
        "Create well-structured, comprehensive responses.",
        "Include proper source attribution and data provenance.",
        "Ensure clarity and coherence in the final response.",
        "Format responses for optimal user experience.",
        "Use markdown formatting for better readability.",
        "Cite specific recipes or sources when applicable.",
    ],
    markdown=True,
)

# ============================================================================
# Team Configuration
# ============================================================================

# Create distributed PgVector RAG team with memory and session support
distributed_pgvector_team = Team(
    id="distributed-pgvector-rag-team",
    name="Distributed PgVector RAG Team",
    model=llm,
    members=[vector_retriever, hybrid_searcher, data_validator, response_composer],
    instructions=[
        "Work together to provide comprehensive RAG responses using PostgreSQL pgvector.",
        "Vector Retriever: First perform vector similarity search to find semantically relevant recipes.",
        "Hybrid Searcher: Then perform hybrid search for comprehensive coverage including keyword matches.",
        "Data Validator: Validate and filter the retrieved information quality, checking for consistency.",
        "Response Composer: Compose the final response with proper attribution and formatting.",
        "Leverage PostgreSQL's scalability and pgvector's performance for efficient retrieval.",
        "Ensure enterprise-grade reliability and accuracy in all responses.",
        "Remember user preferences and previous queries when available.",
    ],
    show_members_responses=True,
    db=db,
    enable_agentic_memory=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# AgentOS Application Setup
# ============================================================================

# Create AgentOS application
agent_os = AgentOS(
    name="Distributed RAG API",
    description="Production-ready API for distributed multi-agent RAG using PostgreSQL pgvector",
    teams=[distributed_pgvector_team],
    knowledge=[vector_knowledge, hybrid_knowledge],
)

# Get FastAPI app instance
app = agent_os.get_app()

# ============================================================================
# Middleware Configuration
# ============================================================================

# JWT authentication middleware - DISABLED for now
# Uncomment and configure when you need authentication in production
#
# app.add_middleware(
#     JWTMiddleware,
#     secret_key=JWT_SECRET_KEY,
#     algorithm=JWT_ALGORITHM,
#     token_source=TokenSource.BOTH,  # Accept both header and cookie
#     user_id_claim="sub",  # Extract user_id from 'sub' claim
#     session_id_claim="session_id",  # Extract session_id from claim
#     dependencies_claims=["email", "name", "roles"],  # Additional claims to inject
#     validate=True,  # Enable token validation
#     excluded_route_paths=[
#         "/health",
#         "/docs",
#         "/redoc",
#         "/openapi.json",
#     ],  # Routes that don't require auth
# )

# ============================================================================
# Custom Endpoints
# ============================================================================

from fastapi import APIRouter
from fastapi.responses import JSONResponse

custom_router = APIRouter()


@custom_router.get("/health")
async def health_check():
    """
    Health check endpoint to verify API is running.

    Returns:
        JSON with status and service information
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "Distributed RAG API",
            "version": "1.0.0",
            "database": "connected" if db else "disconnected",
            "teams": [distributed_pgvector_team.id],
            "knowledge_bases": [
                vector_knowledge.name,
                hybrid_knowledge.name,
            ],
        }
    )


@custom_router.get("/info")
async def api_info():
    """
    Get API information and available endpoints.

    Returns:
        JSON with API capabilities and team information
    """
    return JSONResponse(
        content={
            "api_name": "Distributed RAG API",
            "description": "Multi-agent RAG system using PostgreSQL pgvector",
            "teams": [
                {
                    "id": distributed_pgvector_team.id,
                    "name": distributed_pgvector_team.name,
                    "members": [
                        agent.name for agent in distributed_pgvector_team.members
                    ],
                }
            ],
            "knowledge_bases": [
                {
                    "name": vector_knowledge.name,
                    "description": vector_knowledge.description,
                    "type": "vector_search",
                },
                {
                    "name": hybrid_knowledge.name,
                    "description": hybrid_knowledge.description,
                    "type": "hybrid_search",
                },
            ],
            "features": [
                "JWT Authentication",
                "Session Management",
                "User Memory Persistence",
                "Knowledge Upload",
                "Streaming Responses",
                "Multi-Agent Collaboration",
            ],
            "endpoints": {
                "team_runs": "POST /teams/{team_id}/runs",
                "sessions": "GET /sessions",
                "session_detail": "GET /sessions/{session_id}",
                "session_runs": "GET /sessions/{session_id}/runs",
                "update_session": "PATCH /sessions/{session_id}",
                "upload_content": "POST /knowledge/content",
                "health": "GET /health",
                "docs": "GET /docs",
            },
        }
    )


# Include custom router
app.include_router(custom_router)

# ============================================================================
# Startup Event
# ============================================================================


@app.on_event("startup")
async def startup_event():
    """
    Initialize resources on API startup.
    """
    print("=" * 80)
    print("Starting Distributed RAG API")
    print("=" * 80)
    print(f"Database: {DB_URL}")
    print(f"JWT Auth: Disabled")
    print(f"Teams: {len([distributed_pgvector_team])}")
    print(f"Knowledge Bases: {len([vector_knowledge, hybrid_knowledge])}")
    print(f"API Docs: http://{API_HOST}:{API_PORT}/docs")
    print(f"Health Check: http://{API_HOST}:{API_PORT}/health")
    print("=" * 80)

    # Load initial knowledge if URLs are provided
    initial_content_url = os.getenv("INITIAL_CONTENT_URL")
    if initial_content_url:
        print(f"Loading initial content from: {initial_content_url}")
        try:
            vector_knowledge.add_contents(urls=[initial_content_url])
            hybrid_knowledge.add_contents(urls=[initial_content_url])
            print("Initial content loaded successfully")
        except Exception as e:
            print(f"Failed to load initial content: {e}")

    print("API is ready to accept requests")
    print("=" * 80)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Cleanup resources on API shutdown.
    """
    print("=" * 80)
    print("Shutting down Distributed RAG API")
    print("=" * 80)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    """
    Run the AgentOS API server.

    The server will:
    - Start on the configured host and port
    - Serve the FastAPI application
    - Provide automatic API documentation at /docs
    - Enable hot-reload in development mode
    """
    agent_os.serve(
        app="agent-api:app",
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
    )
