#!/usr/bin/env python3
"""
AgentX Green Agent Server
=========================
AgentBeats Compatible A2A Server with ENTRYPOINT support.

Usage:
    python src/server.py --host 0.0.0.0 --port 8090
    python src/server.py --host 0.0.0.0 --port 8090 --card-url https://my-agent.example.com/

Arguments (AgentBeats required):
    --host: Host to bind the server (default: 127.0.0.1)
    --port: Port to listen on (default: 8090)
    --card-url: URL to advertise in agent card (optional)
"""
import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.executor import Executor


def start_mcp_server(mcp_port: int) -> subprocess.Popen | None:
    """Start MCP server in background."""
    mcp_script = Path(__file__).parent / "mcp_http_server.py"
    if not mcp_script.exists():
        print(f"⚠️ MCP server script not found: {mcp_script}")
        return None
    
    env = os.environ.copy()
    env["MCP_PORT"] = str(mcp_port)
    
    print(f"🔧 Starting MCP Server on port {mcp_port}...")
    proc = subprocess.Popen(
        [sys.executable, str(mcp_script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(3)  # Wait for MCP to initialize
    
    if proc.poll() is not None:
        print("❌ MCP Server failed to start")
        return None
    
    print(f"✅ MCP Server running (PID: {proc.pid})")
    return proc


def main():
    parser = argparse.ArgumentParser(
        description="AgentX Green Agent - A2A Evaluator Server"
    )
    # AgentBeats required arguments
    parser.add_argument(
        "--host", 
        type=str, 
        default="127.0.0.1", 
        help="Host to bind the server"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8090, 
        help="Port to bind the server"
    )
    parser.add_argument(
        "--card-url", 
        type=str, 
        help="URL to advertise in the agent card"
    )
    
    # Additional options
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8091")),
        help="MCP server port (default: 8091)"
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Don't start MCP server (assume it's running externally)"
    )
    parser.add_argument(
        "--task-file",
        type=str,
        default=os.getenv("TASK_DEFINITIONS_FILE", "src/data/task_definitions.jsonl"),
        help="Path to task definitions JSONL file"
    )
    
    args = parser.parse_args()
    
    # Set environment variables for downstream components
    os.environ["PORT"] = str(args.port)
    os.environ["MCP_PORT"] = str(args.mcp_port)
    os.environ["AGENT_PUBLIC_URL"] = f"http://localhost:{args.mcp_port}"
    
    mcp_proc = None
    
    try:
        # Start MCP Server if needed
        if not args.no_mcp:
            mcp_proc = start_mcp_server(args.mcp_port)
        
        # Build Agent Card
        agent_url = args.card_url or f"http://{args.host}:{args.port}/"
        
        skill = AgentSkill(
            id="evaluate_mcp_agent",
            name="MCP Agent Evaluation",
            description=(
                "Evaluate A2A agents on MCP-based tasks with 3D scoring: "
                f"Endpoint is /tools all tools list {os.environ['AGENT_PUBLIC_URL']}/tools. "
                "Action Match (50%), Argument Match (40%), Efficiency (10%). "
                "Supports 76 tools across Notion, Gmail, Google Drive, YouTube, Search."
            ),
            tags=["mcp", "evaluation", "assessment", "3d-scoring"],
            examples=[
                "Evaluate agent on Notion task",
                "Run productivity workflow evaluation",
                "Test multi-tool coordination"
            ]
        )
        
        agent_card = AgentCard(
            name="AgentX Green Agent",
            description=(
                "Green Agent (Assessor) for AgentBeats platform. "
                "Evaluates Purple agents using MCP tools with standardized 3D scoring."
            ),
            url=agent_url,
            version="1.0.0",
            default_input_modes=["text"],
            default_output_modes=["text"],
            capabilities=AgentCapabilities(streaming=True),
            skills=[skill],
        )
        
        # Create executor with task file and MCP port
        executor = Executor(task_file=args.task_file, mcp_port=args.mcp_port)
        
        # Create A2A server
        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
        )
        
        server = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler,
        )
        
        # Print startup info
        print("\n" + "=" * 60)
        print("🟢 AgentX Green Agent (AgentBeats Compatible)")
        print("=" * 60)
        print(f"   Host: {args.host}")
        print(f"   Port: {args.port}")
        print(f"   Card URL: {agent_url}")
        print(f"   MCP Port: {args.mcp_port}")
        print(f"   Task File: {args.task_file}")
        print("")
        print("   Endpoints:")
        print(f"     GET  /.well-known/agent.json")
        print(f"     POST / (A2A JSON-RPC)")
        print(f"     GET  /health")
        print("")
        print("   AgentBeats Assessment Request Format:")
        print('     {"participants": {"role": "url"}, "config": {...}}')
        print("=" * 60 + "\n")
        
        # Run server
        uvicorn.run(server.build(), host=args.host, port=args.port)
        
    finally:
        if mcp_proc:
            print("\n🛑 Stopping MCP Server...")
            mcp_proc.terminate()
            mcp_proc.wait(timeout=5)


if __name__ == "__main__":
    main()
