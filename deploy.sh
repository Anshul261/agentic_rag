#!/bin/bash
# =============================================================================
# Agentic RAG - Deployment Script
# Usage: ./deploy.sh [up|down|restart|logs|status]
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}=== Agentic RAG Deployment Script ===${NC}"

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Copy .env.example to .env and configure it first:"
    echo "  cp .env.example .env"
    exit 1
fi

# Container names
CONTAINER_PREFIX="agentic_rag"

# Docker Compose command
DC="docker compose -f docker-compose.yml"

# Functions
start_services() {
    echo -e "${CYAN}Starting services...${NC}"
    
    # Build if needed
    echo -e "${CYAN}Building containers (if needed)...${NC}"
    $DC build
    
    echo -e "${CYAN}Starting all services...${NC}"
    $DC up -d
    
    echo -e "${GREEN}Waiting for services to be healthy...${NC}"
    sleep 10
    
    # Show status
    $DC ps
    echo ""
    echo -e "${GREEN}Services started!${NC}"
    echo "  Backend:  http://localhost:7777"
    echo "  Frontend: http://localhost:3000"
}

stop_services() {
    echo -e "${CYAN}Stopping services...${NC}"
    $DC down
    echo -e "${GREEN}Services stopped!${NC}"
}

restart_services() {
    stop_services
    start_services
}

show_logs() {
    SERVICE="${2:-}"
    if [ -n "$SERVICE" ]; then
        $DC logs -f --tail=100 "$SERVICE"
    else
        $DC logs -f --tail=50
    fi
}

show_status() {
    echo -e "${CYAN}Container Status:${NC}"
    $DC ps
    
    echo ""
    echo -e "${CYAN}Resource Usage:${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
        $($DC ps -q) 2>/dev/null || true
    
    echo ""
    echo -e "${CYAN}Health Status:${NC}"
    for container in $($DC ps --format "{{.Name}}"); do
        health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")
        echo "  $container: $health"
    done
}

show_help() {
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  up       - Start all services"
    echo "  down     - Stop all services"
    echo "  restart  - Restart all services"
    echo "  logs     - Show logs (optional: <service-name>)"
    echo "  status   - Show container status and health"
    echo "  build    - Build/rebuild containers"
}

# Main
case "${1:-}" in
    up)
        start_services
        ;;
    down)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs "$@"
        ;;
    status)
        show_status
        ;;
    build)
        $DC build
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac