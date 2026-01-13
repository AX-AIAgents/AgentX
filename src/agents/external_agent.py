#!/usr/bin/env python3
"""
Example External A2A Agent with OpenAI GPT-4o-mini

This is an A2A-compatible agent that uses OpenAI for decision making.

Usage:
    # Terminal 1: Start this agent
    python -m src.agents.external_agent
    
    # Terminal 2: Start AgentX evaluation
    python run.py --task-file tasks.jsonl --external-agent http://localhost:9000 --task 0
"""
import json
import os
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import httpx
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

app = FastAPI(title="OpenAI A2A Agent")

# OpenAI client - lazy initialization
_client = None

def get_openai_client():
    """Get or create OpenAI client."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _client = OpenAI(api_key=api_key)
    return _client

# State
conversation_history = []
mcp_endpoint = "http://localhost:8091"
available_tools = []


# ============================================================
# 1. AGENT CARD - Required for A2A discovery
# ============================================================
@app.get("/.well-known/agent.json")
def agent_card():
    """Return agent capabilities and metadata."""
    port = int(os.getenv("PORT", 9000))
    return {
        "name": "OpenAI GPT-4o-mini Agent",
        "description": "An A2A-compatible agent powered by OpenAI GPT-4o-mini",
        "url": f"http://localhost:{port}/",
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "skills": [
            {
                "id": "task_execution",
                "name": "Execute Productivity Tasks",
                "description": "Can search, read documents, and create content using MCP tools",
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
    try:
        # Check if OpenAI client can be initialized
        get_openai_client()
    except ValueError as e:
        # Return error response if API key is missing
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {
                "code": -32000,
                "message": f"Server configuration error: {str(e)}",
                "data": {
                    "details": "OPENAI_API_KEY environment variable must be set on the server"
                }
            }
        }
    
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
    
    # Check if this is a new task (kickoff message)
    if "<task_config>" in text:
        print("🔄 New task detected - resetting conversation history")
        conversation_history.clear()
    
    print(f"📨 Incoming message - role: {role}, has_text: {bool(text.strip())}, has_tool_results: {bool(tool_results)}")
    
    # CRITICAL FIX: Check if last entry was assistant with tool_calls but no tool_results followed
    # If user sends new message without tool_results, we need to handle incomplete tool_calls
    if conversation_history and not tool_results and role == "user":
        last_entry = conversation_history[-1]
        # If last message was assistant with tool_calls, we need tool_results
        if last_entry.get("assistant_message") and last_entry["assistant_message"].get("tool_calls"):
            print(f"⚠️ WARNING: Last assistant had tool_calls but new user message without tool_results")
            print(f"   → Cleaning up conversation history to avoid OpenAI API error")
            # Remove the assistant message with pending tool_calls
            conversation_history.pop()
    
    # Store in conversation history
    # If this message contains ONLY tool_results, don't add as user message
    # Tool results will be added separately when building OpenAI messages
    if not (tool_results and not text.strip()):
        conversation_history.append({"role": role, "content": text, "tool_results": tool_results})
        print(f"   → Added to history as: role={role}, content_len={len(text)}, tool_results={len(tool_results)}")
    elif tool_results:
        # Only tool results, no text - store separately
        conversation_history.append({"tool_results": tool_results})
        print(f"   → Added to history as: tool_results only ({len(tool_results)} results)")
    
    # Decide what to do using OpenAI
    try:
        return await decide_action_with_llm(text, tool_results)
    except RuntimeError as e:
        # Return JSON-RPC error for initialization issues
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {
                "code": -32000,
                "message": str(e),
                "data": {
                    "details": "Server configuration error - check environment variables"
                }
            }
        }
    except Exception as e:
        # Return JSON-RPC error for other issues
        import traceback
        traceback.print_exc()
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}",
                "data": {
                    "type": type(e).__name__
                }
            }
        }


async def fetch_tools_from_mcp():
    """Fetch available tools from MCP server."""
    global available_tools
    if available_tools:
        return available_tools
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(f"{mcp_endpoint}/tools")
            if response.status_code == 200:
                available_tools = response.json().get("tools", [])
                print(f"📦 Fetched {len(available_tools)} tools from MCP")
    except Exception as e:
        print(f"⚠️ Failed to fetch tools: {e}")
    return available_tools


def build_openai_tools(mcp_tools: list) -> list:
    """Convert MCP tools to OpenAI function format."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
        })
    return openai_tools


async def decide_action_with_llm(text: str, tool_results: list) -> dict:
    """
    Use OpenAI GPT-4o-mini to decide next action.
    """
    try:
        # Ensure OpenAI client is initialized
        client = get_openai_client()
    except ValueError as e:
        # Return error if client can't be initialized
        raise RuntimeError(f"Client not initialized: {str(e)}")
    
    # Fetch tools from MCP
    mcp_tools = await fetch_tools_from_mcp()
    openai_tools = build_openai_tools(mcp_tools)
    
    # Build messages for OpenAI
    messages = [
        {
            "role": "system",
            "content": """You are a task execution agent. Your job is to FULLY complete the user's request using the available tools.

CRITICAL RULES:
1. DO NOT say "TASK COMPLETED" until you have actually performed ALL required actions
2. After each tool call, analyze the result and decide if more actions are needed
3. A typical task requires MULTIPLE tool calls (search → read → create → send)
4. Only say "TASK COMPLETED" when you have:
   - Searched for relevant information
   - Read/retrieved the necessary content
   - Created or modified the required documents
   - Sent any required emails or notifications

WORKFLOW:
1. Understand what the user wants
2. Search for relevant information first
3. Read/get the content you found
4. Create new documents or update existing ones
5. Send emails or notifications if required
6. ONLY THEN say "TASK COMPLETED"

You have access to tools for: Notion, Gmail, Google Drive, YouTube, and Search.
USE THEM ALL as needed to complete the task fully."""
        }
    ]
    
    # Add conversation history
    print(f"📚 Building messages from {len(conversation_history)} history entries")
    
    # Track the last assistant message's tool_call IDs
    last_tool_call_ids = []
    
    for i, entry in enumerate(conversation_history):
        if entry.get("tool_results"):
            # Add tool results as tool messages
            # Match with previous assistant's tool_call IDs
            for idx, tr in enumerate(entry["tool_results"]):
                # Use the corresponding tool_call_id from last assistant message
                tool_call_id = last_tool_call_ids[idx] if idx < len(last_tool_call_ids) else tr.get("id", "unknown")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tr.get("result", {}))
                })
            print(f"   Entry {i}: Added {len(entry['tool_results'])} tool results")
        elif entry.get("assistant_message"):
            # Add assistant's previous response with tool calls
            assistant_msg = entry["assistant_message"]
            messages.append(assistant_msg)
            
            # Save tool_call IDs for matching with results
            if assistant_msg.get("tool_calls"):
                last_tool_call_ids = [tc["id"] for tc in assistant_msg["tool_calls"]]
            
            print(f"   Entry {i}: Added assistant message with tool_calls")
        elif entry.get("content"):
            messages.append({
                "role": entry.get("role", "user"),
                "content": entry.get("content", "")
            })
            print(f"   Entry {i}: Added {entry.get('role', 'user')} message (content_len={len(entry.get('content', ''))})")
    
    # Call OpenAI
    try:
        print(f"🤖 Calling OpenAI with {len(openai_tools)} tools, {len(messages)} messages")
        print(f"   Last message roles: {[m.get('role') for m in messages[-3:]]}")
        
        response = get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=openai_tools if openai_tools else None,
            tool_choice="auto" if openai_tools else None,
        )
        
        print(f"   ✅ OpenAI response received")
        choice = response.choices[0]
        message = choice.message
        print(f"   Response: tool_calls={bool(message.tool_calls)}, content={message.content[:50] if message.content else 'None'}...")
        
        # Check for tool calls
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            print(f"   🔧 Tool call: {tool_call.function.name}")
            print(f"   📋 Arguments: {tool_call.function.arguments}")
            
            # Save assistant message with tool calls to history
            conversation_history.append({
                "assistant_message": {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in message.tool_calls
                    ]
                }
            })
            
            return make_tool_call_response(
                text=message.content or f"Calling {tool_call.function.name}...",
                tool_name=tool_call.function.name,
                tool_args=json.loads(tool_call.function.arguments),
            )
        
        # Check for completion
        content = message.content or ""
        print(f"   📝 Text response (no tool calls): {content[:150]}...")
        
        if "TASK COMPLETED" in content.upper() or "completed" in content.lower():
            print(f"   ✅ Detected completion signal")
            return make_completion_response(content)
        
        print(f"   ⚠️ No tool calls, no completion - returning text")
        # Continue conversation
        return {
            "jsonrpc": "2.0",
            "result": {
                "message": {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": content}],
                },
            },
        }
        
    except Exception as e:
        print(f"   ❌ Exception in decide_action_with_llm: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return make_completion_response(f"Error: {str(e)}")


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
    return {"status": "ok", "agent": "openai_gpt4o_mini_agent"}


@app.post("/reset")
def reset():
    """Reset conversation state."""
    global conversation_history, available_tools
    conversation_history = []
    available_tools = []
    return {"status": "reset"}


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🤖 OpenAI GPT-4o-mini A2A Agent")
    print("=" * 60)
    print("This agent uses OpenAI GPT-4o-mini for decision making.")
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
