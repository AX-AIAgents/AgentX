#!/usr/bin/env python3
"""
AgentX Purple Agent Server
==========================
AgentBeats Compatible A2A Server with ENTRYPOINT support.

This is a baseline Purple Agent powered by OpenAI GPT-4o-mini.

Usage:
    python src/agents/server.py --host 0.0.0.0 --port 9000
    python src/agents/server.py --host 0.0.0.0 --port 9000 --card-url https://my-agent.example.com/

Arguments (AgentBeats required):
    --host: Host to bind the server (default: 127.0.0.1)
    --port: Port to listen on (default: 9000)
    --card-url: URL to advertise in agent card (optional)
"""
import argparse
import os
import sys
from pathlib import Path

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.agents.executor import PurpleExecutor


def main():
    parser = argparse.ArgumentParser(
        description="AgentX Purple Agent - OpenAI GPT-4o-mini A2A Agent"
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
        default=9000, 
        help="Port to bind the server"
    )
    parser.add_argument(
        "--card-url", 
        type=str, 
        help="URL to advertise in the agent card"
    )
    
    # Additional options
    parser.add_argument(
        "--mcp-endpoint",
        type=str,
        default=os.getenv("MCP_ENDPOINT"),
        help="MCP endpoint URL for tool discovery"
    )
    
    args = parser.parse_args()
    
    # Set environment variables
    os.environ["PORT"] = str(args.port)
    
    # MCP Endpoint resolution (support both MCP_ENDPOINT and MCP_PORT)
    mcp_endpoint = args.mcp_endpoint
    if not mcp_endpoint:
        mcp_port = os.getenv("MCP_PORT", "8091")
        # In Docker, green-agent is the container name
        green_host = os.getenv("GREEN_AGENT_HOST", "green-agent")
        mcp_endpoint = f"http://{green_host}:{mcp_port}"
        print(f"🔍 MCP endpoint constructed from MCP_PORT: {mcp_endpoint}")
    
    args.mcp_endpoint = mcp_endpoint
    os.environ["MCP_ENDPOINT"] = mcp_endpoint
    
    # Build Agent Card
    agent_url = args.card_url or f"http://{args.host}:{args.port}/"
    
    skill = AgentSkill(
        id="task_execution",
        name="Execute Productivity Tasks",
        description=(
            "AI agent that can search, read documents, and create content "
            "using MCP tools. Powered by OpenAI GPT-4o-mini."
        ),
        tags=["productivity", "search", "documents", "mcp"],
        examples=[
            "Search for information and summarize",
            "Read and analyze documents",
            "Create content based on research"
        ]
    )
    
    agent_card = AgentCard(
        name="AgentX Purple Agent",
        description=(
            "Purple Agent (Participant) for AgentBeats platform. "
            "Powered by OpenAI GPT-4o-mini. Uses MCP tools for task execution."
        ),
        url=agent_url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    
    # Create executor
    executor = PurpleExecutor(mcp_endpoint=args.mcp_endpoint)
    
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
    print("🟣 AgentX Purple Agent (AgentBeats Compatible)")
    print("=" * 60)
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Card URL: {agent_url}")
    print(f"   MCP Endpoint: {args.mcp_endpoint or 'Will discover from Green Agent'}")
    print(f"   Model: gpt-4o-mini")
    print("")
    print("   Endpoints:")
    print(f"     GET  /.well-known/agent.json")
    print(f"     POST / (A2A JSON-RPC)")
    print(f"     GET  /health")
    print("=" * 60 + "\n")
    
    # Run server
    uvicorn.run(server.build(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
