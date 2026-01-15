"""
MCP HTTP Server - Custom Tools

Exposes custom MCP tools (Notion, Gmail, Search, etc.) via HTTP.
Purple Agent connects here to discover and call tools.

NO tau2-bench dependency - uses your MCP servers directly.
"""
import os
import json
import asyncio
from typing import Any

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
import uvicorn

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

# Load environment variables from .env
load_dotenv()


# ============== Configuration ==============

PORT = int(os.getenv("MCP_PORT", "8091"))
DEFAULT_SERVERS = os.getenv("MCP_SERVERS", "notion,gmail,search,youtube,google-drive").split(",")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")


# MCP Server configurations - reads API keys from .env
MCP_SERVERS = {
    "youtube": {
        "transport": "stdio",
        "command": "uvx",
        "args": [
            "--from",
            "git+https://github.com/jkawamoto/mcp-youtube-transcript",
            "python",
            "-m",
            "mcp_youtube_transcript",
        ],
    },
    "gmail": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
    },
    "notion": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env": {"NOTION_TOKEN": os.getenv("NOTION_TOKEN", "")},
    },
    # Serper Search (requires API key) - use if SERPER_API_KEY is set
    "search": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "serper-search-scrape-mcp-server"],
        "env": {"SERPER_API_KEY": os.getenv("SERPER_API_KEY", "")},
    },
    "google-drive": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@piotr-agier/google-drive-mcp"],
        "env": {
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS": os.getenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", "")
        }
    }
}


# ============== Global State ==============

# MCP Server instance
mcp_server = Server("agentx-custom-tools")

# Loaded tools from MCP clients
_loaded_tools: list[Any] = []
_tool_map: dict[str, Any] = {}  # name -> tool object
_mcp_client: Any = None
_active_servers: list[str] = []

# Tool call tracking (for scoring)
_tool_calls: list[dict[str, Any]] = []
_current_state: dict[str, Any] = {}
_current_task: dict[str, Any] = {}  # Current task definition


# ============== Mock State Management ==============

def set_current_task(task: dict[str, Any]) -> None:
    """Set current task and initialize mock state from initial_state."""
    global _current_task
    _current_task = task
    
    if MOCK_MODE:
        from src.tools.mock_tools import init_mock_state
        initial_state = task.get("initial_state", {})
        init_mock_state(initial_state)
        print(f"📦 Mock state initialized from task: {task.get('task_id', 'unknown')}")


def get_mock_final_state() -> dict[str, Any]:
    """Get final state from mock state manager."""
    if MOCK_MODE:
        from src.tools.mock_tools import get_mock_final_state as _get_mock_final_state
        return _get_mock_final_state()
    return _current_state


# ============== MCP Client Management ==============

async def initialize_mcp_client(servers: list[str] | None = None) -> bool:
    """Initialize MCP client with specified servers."""
    global _mcp_client, _loaded_tools, _tool_map, _active_servers
    
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("❌ langchain_mcp_adapters not installed")
        return False
    
    servers = servers or DEFAULT_SERVERS
    
    # Filter to only configured servers
    server_config = {k: v for k, v in MCP_SERVERS.items() if k in servers}
    
    if not server_config:
        print(f"⚠️ No valid servers found in: {servers}")
        return False
    
    print(f"🔌 Connecting to MCP servers: {list(server_config.keys())}")
    
    try:
        # New API (langchain-mcp-adapters >= 0.1.0)
        # No context manager - just create and get_tools()
        _mcp_client = MultiServerMCPClient(server_config)
        _loaded_tools = await _mcp_client.get_tools()
        _tool_map = {tool.name: tool for tool in _loaded_tools}
        _active_servers = list(server_config.keys())
        
        print(f"✅ Loaded {len(_loaded_tools)} tools from {_active_servers}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to initialize MCP client: {e}")
        import traceback
        traceback.print_exc()
        return False


async def shutdown_mcp_client():
    """Shutdown MCP client."""
    global _mcp_client
    # New API doesn't need explicit cleanup
    _mcp_client = None


def _create_mock_tools() -> list[Any]:
    """Create mock tool objects from mock response definitions."""
    from src.tools.mock_tools import ALL_MOCK_RESPONSES
    
    class MockTool:
        """Simple tool wrapper for mock mode."""
        def __init__(self, name: str):
            self.name = name
            self.description = f"Execute {name}"
            self.args = {}  # Empty args - schema not needed for mock mode
        
        def invoke(self, arguments: dict) -> dict:
            return {}
    
    return [MockTool(name) for name in ALL_MOCK_RESPONSES.keys()]


def reset_tracking():
    """Reset tool call tracking and mock state."""
    global _tool_calls, _current_state, _current_task
    _tool_calls = []
    _current_state = {}
    
    # Reset mock state if in mock mode
    if MOCK_MODE:
        from src.tools.mock_tools import reset_mock_state
        reset_mock_state()
        
        # Re-initialize from current task if available
        if _current_task:
            from src.tools.mock_tools import init_mock_state
            initial_state = _current_task.get("initial_state", {})
            init_mock_state(initial_state)


# ============== MCP Protocol Handlers ==============

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools from MCP servers."""
    tools = []
    
    for i, tool in enumerate(_loaded_tools):
        # DEBUG: Show full tool structure for first tool
        if i == 0 and MOCK_MODE:
            print(f"\n🔍 DEBUG: First tool structure:")
            print(f"   Name: {tool.name}")
            print(f"   Type: {type(tool)}")
            print(f"   Attributes: {[a for a in dir(tool) if not a.startswith('_')]}")
            
            # Check all possible schema locations
            if hasattr(tool, "args_schema"):
                print(f"   ✓ Has args_schema: {type(tool.args_schema)}")
                if tool.args_schema:
                    print(f"     - Schema type: {type(tool.args_schema)}")
                    print(f"     - Schema attrs: {[a for a in dir(tool.args_schema) if not a.startswith('_')]}")
            
            if hasattr(tool, "input_schema"):
                print(f"   ✓ Has input_schema: {tool.input_schema}")
            
            if hasattr(tool, "args"):
                print(f"   ✓ Has args: {tool.args}")
            
            if hasattr(tool, "schema"):
                print(f"   ✓ Has schema: {tool.schema}")
            
            print(f"")
        
        # LangChain tool'dan schema al
        schema = {"type": "object", "properties": {}}
        
        # BEST: Use .args property (clean dict ready for OpenAI)
        if hasattr(tool, "args") and tool.args and isinstance(tool.args, dict):
            properties = tool.args
            required_fields = []
            
            # Infer required fields from properties
            for prop_name, prop_def in properties.items():
                if isinstance(prop_def, dict):
                    # Check if optional or has default
                    is_optional = "optional" in str(prop_def.get("description", "")).lower()
                    has_default = "default" in prop_def or "enum" in prop_def
                    
                    # If not optional and no default, it's required
                    if not is_optional and not has_default:
                        required_fields.append(prop_name)
            
            schema = {
                "type": "object",
                "properties": properties,
                "required": required_fields
            }
        
        # FALLBACK 1: Try input_schema (Pydantic model)
        elif hasattr(tool, "input_schema") and tool.input_schema:
            try:
                # Get model_fields directly (Pydantic v2)
                if hasattr(tool.input_schema, "model_fields"):
                    fields = tool.input_schema.model_fields
                    properties = {}
                    required_fields = []
                    
                    for name, field in fields.items():
                        # Build property schema
                        prop = {"type": "string"}  # default type
                        if hasattr(field, "description") and field.description:
                            prop["description"] = field.description
                        
                        properties[name] = prop
                        
                        # Check if required
                        if field.is_required():
                            required_fields.append(name)
                    
                    schema = {
                        "type": "object",
                        "properties": properties,
                        "required": required_fields
                    }
            except Exception as e:
                print(f"⚠️ Could not parse input_schema for {tool.name}: {e}")
        
        # FALLBACK 2: args_schema (if it's a dict)
        elif hasattr(tool, "args_schema") and isinstance(tool.args_schema, dict):
            schema = tool.args_schema
        
        # Fallback: Check if tool has input_schema directly
        elif hasattr(tool, "input_schema"):
            schema = tool.input_schema
        
        # Debug: Log tools with empty schemas in MOCK_MODE
        if MOCK_MODE and not schema.get("properties"):
            print(f"⚠️ Tool '{tool.name}' has empty schema - LLM may not send arguments")
        
        tools.append(Tool(
            name=tool.name,
            description=getattr(tool, "description", f"Execute {tool.name}"),
            inputSchema=schema,
        ))
    
    return tools


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool and return result."""
    global _tool_calls, _current_state
    
    # Mock mode - return simulated responses
    if MOCK_MODE:
        from src.tools.mock_tools import get_mock_response
        result = get_mock_response(name, arguments)
        
        # Track tool call
        _tool_calls.append({
            "name": name,
            "arguments": arguments,
            "result": result,
            "mock": True,
        })
        
        # Update state tracking
        _update_state(name, arguments, result)
        
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    
    # Real mode - call actual tools
    if name not in _tool_map:
        return [TextContent(type="text", text=json.dumps({"error": f"Tool {name} not found"}))]
    
    tool = _tool_map[name]
    
    try:
        # Call the tool
        if asyncio.iscoroutinefunction(tool.invoke):
            result = await tool.invoke(arguments)
        else:
            result = tool.invoke(arguments)
        
        # Track tool call
        _tool_calls.append({
            "name": name,
            "arguments": arguments,
            "result": result,
        })
        
        # Update state tracking
        _update_state(name, arguments, result)
        
        # Return result
        if isinstance(result, str):
            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text=json.dumps(result, default=str))]
            
    except Exception as e:
        error_result = {"error": str(e), "tool": name}
        return [TextContent(type="text", text=json.dumps(error_result))]


def _update_state(tool_name: str, args: dict, result: Any):
    """Update internal state tracking based on tool call."""
    global _current_state
    
    # Determine domain from tool name
    if tool_name.startswith("API-") or "notion" in tool_name.lower():
        domain = "notion"
    elif "email" in tool_name.lower() or "gmail" in tool_name.lower() or "mail" in tool_name.lower():
        domain = "gmail"
    elif "search" in tool_name.lower() or "scrape" in tool_name.lower():
        domain = "search"
    elif "youtube" in tool_name.lower() or "transcript" in tool_name.lower():
        domain = "youtube"
    elif "drive" in tool_name.lower() or "doc" in tool_name.lower() or "sheet" in tool_name.lower():
        domain = "google-drive"
    else:
        domain = "general"
    
    # Initialize domain state
    if domain not in _current_state:
        _current_state[domain] = {"tool_calls": [], "items": []}
    
    # Track the call
    _current_state[domain]["tool_calls"].append({
        "tool": tool_name,
        "args": args,
    })
    
    # Track created items if result contains IDs
    if isinstance(result, dict):
        if "id" in result:
            _current_state[domain]["items"].append({
                "id": result["id"],
                "type": tool_name,
            })


# ============== HTTP Endpoints ==============

async def health(request):
    """Health check."""
    return JSONResponse({
        "status": "ok",
        "service": "agentx-mcp-custom",
        "tools_loaded": len(_loaded_tools),
        "active_servers": _active_servers,
        "mock_mode": MOCK_MODE,
    })


async def info(request):
    """Server info."""
    return JSONResponse({
        "name": "agentx-custom-tools",
        "version": "2.0.0",
        "mode": "mock" if MOCK_MODE else "live",
        "mock_mode": MOCK_MODE,
        "active_servers": _active_servers,
        "tools_count": len(_loaded_tools),
        "protocol": "mcp",
        "transport": "sse",
    })


async def list_tools_http(request):
    """List tools via HTTP."""
    tools = await list_tools()
    return JSONResponse({
        "tools_count": len(tools),
        "servers": _active_servers,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema,
            }
            for t in tools
        ],
    })


async def call_tool_http(request):
    """Call tool via HTTP."""
    data = await request.json()
    name = data.get("name")
    arguments = data.get("arguments", {})
    
    if not name:
        return JSONResponse({"error": "Missing tool name"}, status_code=400)
    
    result = await call_tool(name, arguments)
    
    try:
        return JSONResponse(json.loads(result[0].text))
    except:
        return JSONResponse({"result": result[0].text})


async def get_state_http(request):
    """Get current state (for scoring)."""
    final_state = get_mock_final_state() if MOCK_MODE else _current_state
    return JSONResponse({
        "state": final_state,
        "tool_calls": _tool_calls,
        "mock_mode": MOCK_MODE,
    })


async def set_task_http(request):
    """Set current task and initialize mock state."""
    data = await request.json()
    set_current_task(data)
    return JSONResponse({
        "status": "ok",
        "task_id": data.get("task_id", "unknown"),
        "mock_mode": MOCK_MODE,
        "initial_state_keys": list(data.get("initial_state", {}).keys()),
    })


async def reset_http(request):
    """Reset state tracking."""
    reset_tracking()
    return JSONResponse({"status": "ok", "message": "State reset", "mock_mode": MOCK_MODE})


async def set_servers_http(request):
    """Change active MCP servers."""
    data = await request.json()
    servers = data.get("servers", DEFAULT_SERVERS)
    
    # Shutdown existing client
    await shutdown_mcp_client()
    
    # Initialize with new servers
    success = await initialize_mcp_client(servers)
    
    return JSONResponse({
        "status": "ok" if success else "error",
        "active_servers": _active_servers,
        "tools_count": len(_loaded_tools),
    })


async def get_tool_calls_http(request):
    """Get recorded tool calls (for scoring)."""
    return JSONResponse({
        "tool_calls": _tool_calls,
        "count": len(_tool_calls),
    })


# ============== SSE Transport ==============

sse_transport = SseServerTransport("/mcp/sse")


async def mcp_sse_handler(request):
    """Handle MCP SSE connections."""
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


# ============== App Lifecycle ==============

async def startup():
    """Initialize on startup."""
    global _loaded_tools, _tool_map, _active_servers
    
    # if MOCK_MODE:
    #     print("\n🚀 Starting in MOCK_MODE - loading mock tools...")
    #     # In mock mode, we don't need real MCP clients
    #     # Just register the mock tools directly
    #     _loaded_tools = _create_mock_tools()
    #     _tool_map = {tool.name: tool for tool in _loaded_tools}
    #     _active_servers = ["mock"]
    #     print(f"✅ Loaded {len(_loaded_tools)} mock tools")
    # else:
        print("\n🚀 Initializing MCP servers...")
        await initialize_mcp_client(DEFAULT_SERVERS)


async def shutdown():
    """Cleanup on shutdown."""
    print("\n🛑 Shutting down MCP client...")
    await shutdown_mcp_client()


# ============== Routes ==============

routes = [
    Route("/health", health, methods=["GET"]),
    Route("/info", info, methods=["GET"]),
    Route("/tools", list_tools_http, methods=["GET"]),
    Route("/tools/call", call_tool_http, methods=["POST"]),
    Route("/state", get_state_http, methods=["GET"]),
    Route("/task", set_task_http, methods=["POST"]),  # Set current task with initial_state
    Route("/reset", reset_http, methods=["POST"]),
    Route("/servers", set_servers_http, methods=["POST"]),
    Route("/tool_calls", get_tool_calls_http, methods=["GET"]),
    # MCP SSE transport
    Mount("/mcp", routes=[
        Route("/sse", mcp_sse_handler, methods=["GET"]),
        Route("/sse", sse_transport.handle_post_message, methods=["POST"]),
    ]),
]

app = Starlette(
    routes=routes, 
    debug=True,
    on_startup=[startup],
    on_shutdown=[shutdown],
)


# ============== Main ==============

if __name__ == "__main__":
    print(f"\n🔧 MCP HTTP Server (Custom Tools)")
    print(f"=" * 50)
    print(f"Port: {PORT}")
    print(f"Mock Mode: {MOCK_MODE}")
    print(f"Default Servers: {DEFAULT_SERVERS}")
    print(f"\nEndpoints:")
    print(f"  GET  /health      - Health check")
    print(f"  GET  /info        - Server info")
    print(f"  GET  /tools       - List tools")
    print(f"  POST /tools/call  - Call tool")
    print(f"  GET  /state       - Get state (for scoring)")
    print(f"  POST /task        - Set task (init mock state)")
    print(f"  POST /reset       - Reset state")
    print(f"  POST /servers     - Change servers")
    print(f"  GET  /mcp/sse     - MCP SSE transport")
    print(f"\n")
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)
