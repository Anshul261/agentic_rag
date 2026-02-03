# UI-Illuminati + Document Agent Integration Guide

This guide explains how the UI-Illuminati frontend is integrated with the simple document agent API.

## Overview

The UI-Illuminati chat interface is now connected to your document agent API. When you're in **General Chat mode** (not in a project), all questions are automatically sent to the document agent running on `http://localhost:7777`.

## Key Features

### General Chat Mode
- **Direct API Integration**: All messages in general chat mode are sent to the document agent
- **File Upload Support**: Upload documents (PDF, TXT, etc.) with your questions
- **Session Management**: Each chat maintains its own session ID for conversation history
- **Error Handling**: Clear error messages if the API is not running

### Project Mode
- **Separate from Agent**: Project mode is NOT connected to the agent API
- **Mock Responses**: Currently uses placeholder responses
- **File Management**: Projects have their own file management system

## How It Works

### 1. General Chat Flow
```
User asks question in General Chat
    ↓
Frontend sends to: POST http://localhost:7777/agents/doc-agent/runs
    ↓
Document Agent processes (with LLM knowledge or uploaded files)
    ↓
Response displayed in chat interface
```

### 2. File Upload in General Chat
```
User attaches file(s) in General Chat
    ↓
Files stored temporarily in component state
    ↓
On message send: Files sent as multipart/form-data
    ↓
Document Agent extracts text and answers based on content
    ↓
Files cleared after successful send
```

## Setup Instructions

### 1. Start the Document Agent API

First, make sure your document agent is running:

```bash
cd /home/anshul/Projects/AI-Search-MCP/Agents/Agentic-Rag

# Make sure .env is configured with Azure OpenAI credentials
python simple-doc-agent.py
```

The API should start on: `http://localhost:7777`

### 2. Start the UI-Illuminati Frontend

In a separate terminal:

```bash
cd /home/anshul/Projects/AI-Search-MCP/Agents/Agentic-Rag/UI-Iluminati

# Install dependencies (if not already done)
npm install

# Start the development server
npm run dev
```

The UI should start on: `http://localhost:3000`

### 3. Test the Integration

1. **Open the UI**: Go to `http://localhost:3000`
2. **Ensure you're in General Chat mode**:
   - If you see a project selected, click the "New Chat" button
   - You should see "AI Assistant" in the header
3. **Ask a question**: Type any question and press Enter
4. **Upload a document (optional)**:
   - Click the paperclip icon
   - Select a file (PDF, TXT, etc.)
   - Ask a question about the file
   - The agent will process the file and answer

## File Structure

```
UI-Iluminati/
├── components/
│   └── chat-interface.tsx        # Main chat component (UPDATED)
├── lib/
│   └── api.ts                     # API integration (NEW)
└── INTEGRATION-GUIDE.md          # This file (NEW)

Agentic-Rag/
└── simple-doc-agent.py           # Document agent API
```

## Code Changes

### New Files
- `lib/api.ts`: API client for communicating with the document agent
  - `sendMessageToAgent()`: Sends messages and files to the agent
  - `checkAPIHealth()`: Checks if API is running
  - `getAPIInfo()`: Gets API information

### Modified Files
- `components/chat-interface.tsx`:
  - Import `sendMessageToAgent` from `lib/api.ts`
  - Added `sessionId` state for conversation tracking
  - Added `uploadedFiles` state for general chat file uploads
  - **Updated `handleSubmit()`**: Calls real API in general chat mode
  - **Updated file upload handler**: Stores files for API upload

## Configuration

### Environment Variables (Frontend)

Create `.env.local` in the UI-Illuminati directory:

```bash
NEXT_PUBLIC_API_URL=http://localhost:7777
```

If not set, defaults to `http://localhost:7777`.

### Environment Variables (Backend)

The document agent requires these in `.env`:

```bash
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=your_endpoint
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini
OPENAI_API_VERSION=2024-02-15-preview
```

## Troubleshooting

### "Error: Failed to get response from agent"
- **Check**: Is the document agent running on port 7777?
- **Solution**: Run `python simple-doc-agent.py` in the Agentic-Rag directory

### "API Error: 500"
- **Check**: Are Azure OpenAI credentials configured correctly?
- **Solution**: Verify `.env` file in Agentic-Rag directory has correct values

### Files not uploading
- **Check**: Are you in General Chat mode (not Project mode)?
- **Solution**: Click "New Chat" button to exit project mode

### CORS errors in browser console
- **Check**: Is the API URL correct?
- **Solution**: Make sure NEXT_PUBLIC_API_URL matches where the agent is running

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/agents/doc-agent/runs` | POST | Send messages and files to agent |
| `/health` | GET | Check if API is running |
| `/info` | GET | Get API information |

## Testing Checklist

- [ ] Document agent API starts successfully
- [ ] Frontend starts and loads
- [ ] Can send messages in general chat mode
- [ ] Receive responses from the agent
- [ ] Can upload files in general chat
- [ ] Agent processes uploaded files correctly
- [ ] Error messages display when API is down
- [ ] Project mode still works (with mock responses)

## Next Steps

### Optional Enhancements

1. **Add streaming responses**: Update API call to use `stream=true`
2. **Show file badges**: Display uploaded files before sending
3. **Connect project mode**: Link projects to specific agent sessions
4. **Add retry logic**: Automatically retry failed API calls
5. **Session persistence**: Save and load previous conversations

## Support

If you encounter issues:

1. Check both terminal outputs (frontend and backend)
2. Open browser DevTools → Network tab to see API calls
3. Check browser Console for JavaScript errors
4. Verify all environment variables are set correctly
