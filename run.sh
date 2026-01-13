#!/bin/bash

# AgentBeats Runner for AgentX - PRODUCTION MODE
# ===============================================
# Phase 1 Teslimat: Green Agent (Assessor) + MCP Server
#
#   1. MCP Server (port 8091) - 76 tools (background)
#   2. Green Agent/A2A Server (port 8090) - Main process (FOREGROUND)
#
# NOTE: Purple Agent runs externally - AgentBeats Controller coordinates it.
# For local testing, use run_local.sh or run.py instead.

# NOTE: Don't use `set -e` - it causes script to exit on any error

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "🚀 Starting AgentX Green Agent (Production Mode)..."
echo "📂 Working directory: $SCRIPT_DIR"
echo ""

# Export environment variables
# AgentBeats Controller sets AGENT_PORT env var (not PORT!)
export PORT=${AGENT_PORT:-${PORT:-8090}}
export MCP_PORT=8091
export AGENT_PUBLIC_URL="http://localhost:8091"
export PYTHONPATH="$SCRIPT_DIR"

echo "🔧 Configuration:"
echo "   AGENT_PORT (from AgentBeats): ${AGENT_PORT:-not set}"
echo "   PORT (resolved): $PORT"
echo "   MCP_PORT: $MCP_PORT"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    if [ -n "$MCP_PID" ]; then
        kill $MCP_PID 2>/dev/null
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Start MCP Server in background
echo "1️⃣ Starting MCP Server (port 8091)..."
python src/mcp_http_server.py > mcp_server.log 2>&1 &
MCP_PID=$!
echo "   ✅ MCP Server starting... (PID: $MCP_PID)"
echo "   📝 Logs: mcp_server.log"
sleep 3  # Wait for MCP to initialize

# Check if MCP is running
if ! kill -0 $MCP_PID 2>/dev/null; then
    echo "   ❌ MCP Server failed to start! Check mcp_server.log"
    cat mcp_server.log
    exit 1
fi

# Start Green Agent (A2A Server) in FOREGROUND
# This is the main process that AgentBeats monitors!
echo "2️⃣ Starting Green Agent/A2A Server (port $PORT)..."
echo "   📍 This is the main process AgentBeats monitors"
echo ""
echo "✅ Green Agent ready to receive evaluation requests"
echo "   Use: http://localhost:$PORT/ for A2A messages"
echo ""

# Run A2A server in foreground (keeps container alive)
python src/a2a_server.py
