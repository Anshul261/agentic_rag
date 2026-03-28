# Agentic RAG - Document Q&A System

A powerful document question-answering system with real-time agent activity tracking. Upload documents (PDF, TXT, DOCX) and ask questions using an intelligent AI agent with full conversation history and session management.

## Features

### Core Capabilities
- **Multi-Format Document Support**: PDF, TXT, DOCX, and more
- **Intelligent Q&A**: Ask questions about your documents or general knowledge
- **Session Management**: Persistent conversation history across sessions
- **Project Organization**: Group chats and files into projects
- **Modern UI**: Clean, responsive interface with dark mode support
- **Real-Time Streaming**: See responses as they're generated

### Agent Trace Logging
- **Activity Visibility**: See what the agent is doing in real-time
- **Tool Tracking**: Monitor when tools like `read_document` are used
- **Timing Information**: Track how long operations take
- **Compact Display**: Non-intrusive trace view in message history
- **Live Progress**: Real-time updates during agent processing

## Architecture

### Backend (FastAPI)
- **Framework**: AgentOS with FastAPI
- **Agent**: `doc-agent` - Document Q&A specialist
- **Database**: SQLite for session storage
- **LLM**: Azure OpenAI (configurable)
- **Tools**: Document processing (PyPDF2 for PDF extraction)

### Frontend (Next.js)
- **Framework**: Next.js 14+ with App Router
- **UI Library**: Shadcn/ui components
- **Styling**: Tailwind CSS
- **Markdown**: ReactMarkdown with GFM support
- **Icons**: Lucide React

## Installation

### Prerequisites
- Python 3.9+
- Node.js 18+
- Azure OpenAI API credentials

### Backend Setup

1. Navigate to the agent directory:
   ```bash
   cd Agents/Agentic-Rag
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   Create a `.env` file with:
   ```env
   AZURE_OPENAI_API_KEY=your_api_key
   AZURE_OPENAI_ENDPOINT=your_endpoint
   AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment
   OPENAI_API_VERSION=2024-02-15-preview
   ```

4. Start the backend:
   ```bash
   python agent-api.py
   ```
   Backend runs at `http://localhost:7777`

### Frontend Setup

1. Navigate to the UI directory:
   ```bash
   cd UI-Iluminati
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Configure environment variables:
   Create `.env.local`:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:7777
   ```

4. Start the development server:
   ```bash
   npm run dev
   ```
   Frontend runs at `http://localhost:3000`

## Usage

### Basic Document Q&A

1. **Start a New Chat**
   - Click "New Chat" in the sidebar
   - A new session is automatically created

2. **Upload a Document**
   - Click the paperclip icon in the message input
   - Select your document (PDF, TXT, DOCX)
   - The file will be queued for upload

3. **Ask Questions**
   - Type your question in the message box
   - Press Enter or click Send
   - Watch the agent trace to see real-time processing
   - Receive intelligent answers based on your document

4. **Continue the Conversation**
   - Follow-up questions use the same session
   - Document context is preserved
   - No need to re-upload the file

### Agent Trace Features

#### During Processing
- See live updates: "Using read_document", "Processing request"
- Monitor progress with animated indicators
- Track tool execution in real-time

#### After Response
- View compact trace showing last 3 steps
- See which tools were used
- Check execution timestamps
- Review agent activity history

### Session Management

#### Save and Resume
- Sessions auto-save to SQLite database
- Click any session in the sidebar to reload
- All messages and context restored
- Continue where you left off

#### Organize with Projects
- Create projects to group related chats
- Upload files specific to each project
- Track multiple workstreams separately

## API Endpoints

### Agent Endpoints
- `POST /agents/doc-agent/runs` - Send message to agent
  - Supports file upload
  - Streaming with `stream=true`
  - Agent monitoring with `monitor=true`

### Session Endpoints
- `GET /sessions` - List all sessions
- `GET /sessions/{session_id}` - Get session details
- `GET /sessions/{session_id}/runs` - Get session history
- `POST /sessions` - Create new session

### Utility Endpoints
- `GET /health` - Health check
- `GET /info` - API information
- `GET /docs` - Interactive API documentation

## Agent Trace Events

The system captures these agent events:

| Event | Trigger | Display |
|-------|---------|---------|
| `RunStarted` | Agent begins processing | "Agent started processing" |
| `ToolCallStarted` | Tool execution begins | "Using {tool_name}" |
| `ToolCallCompleted` | Tool finishes | "Completed {tool_name} in Xs" |
| `RunContent` | Response streaming | Accumulated in message |

## Configuration

### Backend Configuration

Edit `agent-api.py`:

```python
# Database location
db = SqliteDb(db_file="agent_sessions.db")

# Server settings
agent_os.serve(
    app="agent-api:app",
    host="0.0.0.0",
    port=7777,
    reload=True,
)

# Agent configuration
doc_agent = Agent(
    id="doc-agent",
    name="Document Q&A Agent",
    model=llm,
    tools=[DocumentTools()],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=10,  # Conversation history length
)
```

### Frontend Configuration

Customize UI in `components/chat-interface.tsx`:

```typescript
// Compact mode for traces
<AgentTrace steps={message.agentSteps} compact={true} />

// Full mode during loading
<AgentTrace 
  steps={currentAgentSteps} 
  currentProgress={currentProgress}
  isLoading={true}
  compact={false}
/>
```

## Database Schema

SQLite stores:
- **Sessions**: Conversation sessions with metadata
- **Runs**: Individual message exchanges
- **User Memories**: Preferences and context
- **Media**: Uploaded file references

## UI Components

### Core Components
- `chat-interface.tsx` - Main chat interface
- `agent-trace.tsx` - Agent activity display
- `ui/button.tsx` - Styled buttons
- `ui/input.tsx` - Text inputs
- `ui/dialog.tsx` - Modal dialogs

### Utilities
- `lib/api.ts` - API client functions
- `lib/utils.ts` - Utility functions

## Testing

### Test Document Upload
```bash
curl -X POST "http://localhost:7777/agents/doc-agent/runs" \
  -F "message=What is this document about?" \
  -F "files=@document.pdf" \
  -F "session_id=test123"
```

### Test General Question
```bash
curl -X POST "http://localhost:7777/agents/doc-agent/runs" \
  -F "message=What is Python?" \
  -F "session_id=test123"
```

### Test Streaming
```bash
curl -X POST "http://localhost:7777/agents/doc-agent/runs" \
  -F "message=Explain AI" \
  -F "stream=true" \
  -F "monitor=true" \
  -F "session_id=test123"
```

## Troubleshooting

### Backend Issues

**Problem**: API not starting
- Check Azure OpenAI credentials in `.env`
- Verify Python dependencies installed
- Check port 7777 is available

**Problem**: Document extraction fails
- Ensure PyPDF2 installed for PDF support
- Check file format is supported
- Verify file is not corrupted

### Frontend Issues

**Problem**: UI not loading
- Check `NEXT_PUBLIC_API_URL` in `.env.local`
- Verify backend is running
- Clear browser cache

**Problem**: No agent traces showing
- Ensure `stream=true` and `monitor=true` in API calls
- Check browser console for errors
- Verify backend supports streaming

### Session Issues

**Problem**: Sessions not persisting
- Check `agent_sessions.db` file exists
- Verify write permissions
- Check database connection

## Security Considerations

- **File Upload**: Validate file types and sizes
- **API Keys**: Never commit `.env` files
- **CORS**: Configure allowed origins in production
- **Rate Limiting**: Implement for production use
- **File Storage**: Clean up temporary files regularly

## Production Deployment

### Backend
1. Use production WSGI server (Gunicorn/Uvicorn)
2. Configure proper CORS origins
3. Set up SSL/TLS certificates
4. Use production database (PostgreSQL)
5. Implement rate limiting and authentication

### Frontend
1. Build optimized production bundle:
   ```bash
   npm run build
   npm start
   ```
2. Configure environment variables
3. Set up CDN for static assets
4. Implement proper error tracking

## Recent Updates

### Agent Trace Logging
- Added real-time agent activity tracking
- Compact trace display in message history
- Live progress indicators during processing
- Tool execution monitoring
- Timestamps for all agent actions
- Non-intrusive UI design

### Session Management
- SQLite database integration
- Persistent conversation history
- Session list in sidebar
- Click to resume sessions

## Key Files Modified

### New Files
- `UI-Iluminati/components/agent-trace.tsx` - Agent trace display component

### Modified Files
- `UI-Iluminati/components/chat-interface.tsx` - Added streaming and trace support
  - Extended Message interface with agentSteps
  - Replaced API call with streaming fetch
  - Added SSE event parsing
  - Integrated AgentTrace component

## Contributing

Contributions welcome. Areas for improvement:
- Additional document format support
- Enhanced trace filtering and search
- Multi-agent support
- Advanced analytics dashboard
- Performance optimizations

## Support

For issues and questions:
- Check troubleshooting section
- Review API documentation at `/docs`
- Check backend logs for errors
- Verify environment configuration

# Agent Sandbox

To start the sandbox server:
# 1. Pull the sandbox image (if not already)
docker pull sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1
# 2. Configure sandbox (copy example config)
cp $(uv python)/lib/python3.11/site-packages/example.config.toml ~/.sandbox.toml
# 3. Set environment variables in agentic_rag/.env:
SANDBOX_DOMAIN=localhost:8080
# SANDBOX_API_KEY=    # only if you enabled api_key in ~/.sandbox.toml
# 4. Start the sandbox server:
source .venv/bin/activate
opensandbox-server
The server will bind to 127.0.0.1:8080. Verify:
curl http://localhost:8080/health
