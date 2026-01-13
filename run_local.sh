#!/bin/bash

# AgentX LOCAL DEVELOPMENT Runner
# ================================
# Starts ALL services for local testing:
#   1. MCP Server (port 8091) - 76 tools
#   2. Green Agent/A2A Server (port 8090) - Evaluation orchestrator
#   3. Purple Agent (port 9000) - Baseline agent for testing
#
# Usage:
#   ./run_local.sh                    # Start all services
#   ./run_local.sh --no-purple        # Start without Purple Agent

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "🚀 Starting AgentX Services (Local Development)..."
echo "📂 Working directory: $SCRIPT_DIR"
echo ""

# Export environment variables
export A2A_PORT=8090
export MCP_PORT=8091
export AGENT_PUBLIC_URL="http://localhost:8091"
export PYTHONPATH="$SCRIPT_DIR"

# Track PIDs for cleanup
PIDS=()

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Shutting down all services..."
    for pid in "${PIDS[@]}"; do
        kill $pid 2>/dev/null
    done
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Start MCP Server in background
echo "1️⃣ Starting MCP Server (port 8091)..."
python src/mcp_http_server.py > mcp_server.log 2>&1 &
MCP_PID=$!
PIDS+=($MCP_PID)
echo "   ✅ MCP Server starting... (PID: $MCP_PID)"
echo "   📝 Logs: mcp_server.log"
sleep 3

if ! kill -0 $MCP_PID 2>/dev/null; then
    echo "   ❌ MCP Server failed to start!"
    cat mcp_server.log
    exit 1
fi

# Start Green Agent (A2A Server) in background
echo "2️⃣ Starting Green Agent/A2A Server (port 8090)..."
python src/a2a_server.py > a2a_server.log 2>&1 &
A2A_PID=$!
PIDS+=($A2A_PID)
echo "   ✅ A2A Server starting... (PID: $A2A_PID)"
echo "   📝 Logs: a2a_server.log"
sleep 3

if ! kill -0 $A2A_PID 2>/dev/null; then
    echo "   ❌ A2A Server failed to start!"
    cat a2a_server.log
    exit 1
fi

# Start Purple Agent unless --no-purple flag
if [[ "$1" != "--no-purple" ]]; then
    echo "3️⃣ Starting Purple Agent (port 9000)..."
    python -m src.agents.external_agent > purple_agent.log 2>&1 &
    PURPLE_PID=$!
    PIDS+=($PURPLE_PID)
    echo "   ✅ Purple Agent starting... (PID: $PURPLE_PID)"
    echo "   📝 Logs: purple_agent.log"
    sleep 2
    
    if ! kill -0 $PURPLE_PID 2>/dev/null; then
        echo "   ❌ Purple Agent failed to start!"
        cat purple_agent.log
        exit 1
    fi
fi

echo ""
echo "✅ All services running!"
echo ""
echo "📍 Endpoints:"
echo "   Green Agent (A2A): http://localhost:8090/"
echo "   MCP Server:        http://localhost:8091/"
if [[ "$1" != "--no-purple" ]]; then
    echo "   Purple Agent:      http://localhost:9000/"
fi
echo ""
echo "🧪 To run evaluation:"
echo "   python run.py --task-file tasks.jsonl --external-agent http://localhost:9000"
echo ""
echo "⏳ Press Ctrl+C to stop all services..."

# Wait forever
while true; do
    sleep 1
    # Check if any service died
    for pid in "${PIDS[@]}"; do
        if ! kill -0 $pid 2>/dev/null; then
            echo "⚠️ A service has stopped! Check logs."
        fi
    done
done
