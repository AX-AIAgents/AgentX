#!/usr/bin/env python3
"""
Example External A2A Agent

This is a minimal example showing how ANY agent can connect to AgentX
without importing any AgentX code - just pure HTTP/JSON.

Usage:
    # Terminal 1: Start this agent
    python example_external_agent.py
    
    # Terminal 2: Start AgentX evaluation
    cd agentx
    python run.py --task-file tasks.jsonl --external-agent http://localhost:9000 --task 0
"""
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import httpx

app = FastAPI(title="Example External A2A Agent")

# State
conversation_history = []
mcp_endpoint = "http://localhost:8091"


# ============================================================
# 1. AGENT CARD - Required for A2A discovery
# ============================================================
@app.get("/.well-known/agent.json")
def agent_card():
    """Return agent capabilities and metadata."""
    return {
        "name": "Example External Agent",
        "description": "A minimal A2A-compatible agent for testing AgentX evaluation",
        "url": "http://localhost:9000/",
        "version": "1.0.0",
        "default_input_modes": ["text"],
        "default_output_modes": ["text"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "skills": [
            {
                "id": "task_execution",
                "name": "Execute Productivity Tasks",
                "description": "Can search, read documents, and create content",
                "tags": ["productivity", "search", "documents"],
            }
        ],
        "extensions": {
            "mcp_endpoint": mcp_endpoint,
        },
    }


# ============================================================
# 2. MESSAGE HANDLER - Main A2A communication endpoint
# ============================================================
class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str
    params: dict


class A2AResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    result: dict


@app.post("/a2a/message")
async def handle_message(request: A2ARequest) -> dict:
    """
    Handle incoming A2A messages.
    
    This is where your agent logic goes!
    """
    message = request.params.get("message", {})
    role = message.get("role", "user")
    parts = message.get("parts", [])
    
    # Extract text content
    text = ""
    tool_results = []
    
    for part in parts:
        if part.get("type") == "text":
            text += part.get("text", "")
        elif part.get("type") == "tool_result":
            tool_results.append({
                "id": part.get("toolCallId"),
                "result": part.get("result"),
            })
    
    # Store in conversation history
    conversation_history.append({"role": role, "content": text, "tool_results": tool_results})
    
    # Decide what to do based on conversation state
    return await decide_action(text, tool_results)


async def decide_action(text: str, tool_results: list) -> dict:
    """
    Simple decision logic - replace with your LLM or custom logic!
    
    This example uses a simple state machine:
    1. First turn: Search for documents
    2. After search: Read a document
    3. After reading: Complete task
    """
    turn = len(conversation_history)
    text_lower = text.lower()
    
    # If we received tool results, decide next step
    if tool_results:
        last_result = tool_results[-1].get("result", "")
        
        # If we just searched, read a document
        if "files" in last_result or "results" in last_result:
            return make_tool_call_response(
                text="Found some files. Let me read the first document.",
                tool_name="getGoogleDocContent",
                tool_args={"documentId": "doc-001"},
            )
        
        # If we just read, complete the task
        if "content" in last_result or "title" in last_result:
            return make_completion_response(
                "Task completed! I found and read the relevant documents."
            )
    
    # First turn or task assignment - start with search
    if "search" in text_lower or "find" in text_lower or turn <= 2:
        query = "project reports" if "project" in text_lower else "documents"
        return make_tool_call_response(
            text=f"I'll search for {query}.",
            tool_name="search",
            tool_args={"query": query},
        )
    
    # Default: Complete
    return make_completion_response("Task completed!")


def make_tool_call_response(text: str, tool_name: str, tool_args: dict) -> dict:
    """Helper to create A2A response with tool call."""
    return {
        "jsonrpc": "2.0",
        "result": {
            "message": {
                "role": "assistant",
                "parts": [
                    {"type": "text", "text": text},
                    {
                        "type": "tool_call",
                        "id": f"tc-{len(conversation_history)}",
                        "name": tool_name,
                        "arguments": tool_args,
                    },
                ],
            },
        },
    }


def make_completion_response(text: str) -> dict:
    """Helper to create A2A response signaling task completion."""
    return {
        "jsonrpc": "2.0",
        "result": {
            "status": "completed",
            "message": {
                "role": "assistant",
                "parts": [{"type": "text", "text": text}],
            },
        },
    }


# ============================================================
# 3. OPTIONAL: Health check endpoint
# ============================================================
@app.get("/health")
def health():
    return {"status": "ok", "agent": "example_external_agent"}


@app.post("/reset")
def reset():
    """Reset conversation state."""
    global conversation_history
    conversation_history = []
    return {"status": "reset"}


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🤖 Example External A2A Agent")
    print("=" * 60)
    print("This agent demonstrates A2A protocol compliance.")
    print("It does NOT import any AgentX code!")
    print()
    print("Endpoints:")
    print("  GET  /.well-known/agent.json  - Agent Card")
    print("  POST /a2a/message             - Message Handler")
    print("  GET  /health                  - Health Check")
    print()
    print("To evaluate this agent:")
    print("  python run.py --task-file tasks.jsonl --external-agent http://localhost:9000")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=9000)
