# Project Goal

Building a general-purpose agent able to READ docs, search online and in the futurer PPT creation, Excel analysis, and perfroming command execution and moving and managing the device files. All using local llms only. The idea is to push the agents to be able to work within files and folders locally while only using simple tools like:

Capabilities;
- read uploaded documents and answer questions in chat mode
- projects mode to upload files and answer questions using RAG
Future:
- Doc creation, PPT creation and Excel analysis modes to be added.

# Code and Doc details
I am using agno to create an agent that is able to access a files do research and create assests as files differet providers will be used currently azure but fireworks AI and openrouter will be considered.
I am using agno to leanr more search the https://docs.agno.com/llms.txt and read it to understand the latest details if you want to leanr more about anything start by searching online and finding docs or other people who have done the same things.

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
