#!/bin/bash
# =============================================================================
# Agentic RAG - Build Scripts
# Usage: ./build.sh [backend|frontend|all]
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Agentic RAG Build Script ===${NC}"

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Copy .env.example to .env and configure it first:"
    echo "  cp .env.example .env"
    exit 1
fi

# Build function
build_backend() {
    echo -e "${GREEN}Building backend...${NC}"
    docker build -t agentic-rag:backend -f Dockerfile.backend .
    echo -e "${GREEN}Backend built successfully!${NC}"
}

build_frontend() {
    echo -e "${GREEN}Building frontend...${NC}"
    docker build -t agentic-rag:frontend -f Dockerfile.frontend .
    echo -e "${GREEN}Frontend built successfully!${NC}"
}

# Main
case "${1:-all}" in
    backend)
        build_backend
        ;;
    frontend)
        build_frontend
        ;;
    all)
        build_backend
        build_frontend
        ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

echo -e "${GREEN}Build complete!${NC}"