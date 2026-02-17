"""
AgentX LangGraph Agent
======================
Clean agent powered by LangChain's create_agent (which returns a LangGraph graph).

Architecture:
- create_agent provides the compiled LangGraph graph with built-in tool loop
- MCPToolLoader handles discovery and conversion of MCP tools
- LangGraphAgent orchestrates initialization, execution, and lifecycle
"""

import json
import asyncio
import os
import re
import sys
from typing import List, Dict, Any, Optional, Union, Literal

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ToolRetryMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
)

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


# =============================================================================
# MCP Tool Loading
# =============================================================================


class MCPToolLoader:
    """Discover and load MCP tools, converting them to LangChain Tool format.

    Uses Agent Discovery protocol (/.well-known/agent.json) to find tool endpoints,
    with fallback to standard /tools path.
    """

    _TOOL_KEYWORDS = frozenset(["mcp", "tool", "function", "skill"])
    _TOOLS_URL_PATTERN = re.compile(r'https?://[^\s"]+/tools')

    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[Tool] = []
        self.tools_endpoint: Optional[str] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ----- Discovery -----

    async def _discover_tools_endpoint(self) -> str:
        """Resolve the tools endpoint URL via agent card or fallback."""
        client = await self.get_client()

        try:
            resp = await client.get(f"{self.mcp_endpoint}/.well-known/agent.json")
            if resp.status_code == 200:
                card = resp.json()
                print(f"✅ Agent Card: {card.get('name', 'Unknown')}")

                # Explicit tools_url field
                if card.get("tools_url"):
                    return card["tools_url"]

                # Scan card text for tool URLs
                card_text = str(card)
                url_match = self._TOOLS_URL_PATTERN.search(card_text)
                if url_match:
                    return url_match.group(0)

                # Keyword heuristic
                if any(k in card_text.lower() for k in self._TOOL_KEYWORDS):
                    return f"{self.mcp_endpoint}/tools"
            else:
                print(f"⚠️ No Agent Card (HTTP {resp.status_code}), using default /tools")
        except Exception as e:
            print(f"⚠️ Discovery error: {e}")

        return f"{self.mcp_endpoint}/tools"

    # ----- Tool Loading -----

    async def load_tools(self) -> List[Tool]:
        """Fetch MCP tools and convert to LangChain Tools."""
        if self._tools_cache:
            return self._tools_cache

        if not self.tools_endpoint:
            self.tools_endpoint = await self._discover_tools_endpoint()

        url = (
            self.tools_endpoint
            if "://" in self.tools_endpoint
            else f"{self.mcp_endpoint}/{self.tools_endpoint.lstrip('/')}"
        )

        print(f"📥 Loading tools from: {url}")
        client = await self.get_client()

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"⚠️ Failed to load tools: HTTP {resp.status_code}")
                return []

            mcp_tools = resp.json().get("tools", [])
            print(f"✅ Loaded {len(mcp_tools)} MCP tools")

            self._tools_cache = [
                self._create_langchain_tool(t, url) for t in mcp_tools
            ]
            return self._tools_cache
        except Exception as e:
            print(f"❌ Error loading tools: {e}")
            return []

    def _create_langchain_tool(self, mcp_tool: Dict, endpoint_url: str) -> Tool:
        """Convert a single MCP tool definition to a LangChain Tool."""
        name = mcp_tool.get("name", "")
        description = mcp_tool.get("description", f"Execute {name}")
        schema = mcp_tool.get("inputSchema", {})
        call_url = f"{endpoint_url}/call"
        loader = self  # explicit reference, no nonlocal hack

        async def _execute_async(*args, **kwargs) -> str:
            try:
                final_args = _resolve_args(args, kwargs, schema)
                client = await loader.get_client()
                resp = await client.post(
                    call_url, json={"name": name, "arguments": final_args}
                )
                return json.dumps(resp.json(), default=str)
            except Exception as e:
                return json.dumps({"error": str(e)})

        def _execute_sync(*args, **kwargs) -> str:
            return asyncio.run(_execute_async(*args, **kwargs))

        return Tool(
            name=name,
            description=description,
            func=_execute_sync,
            coroutine=_execute_async,
        )


def _resolve_args(
    args: tuple, kwargs: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Any]:
    """Map positional args to named params using the tool's input schema."""
    final_args = kwargs.copy()
    if args and not final_args and len(args) == 1:
        props = list(schema.get("properties", {}).keys())
        key = props[0] if props else "input"
        final_args[key] = args[0]
    return final_args


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a highly capable AI assistant with access to a wide range of tools.

Your Goal: Complete the user's request accurately by chaining the necessary tools in the correct order.

Instructions:
1. **PLAN:** Before taking action, analyze the request. Break it down into logical steps.
   - Example: "Search Drive for file" -> "Read file content" -> "Send email".
2. **SEARCH:** If you need to find a resource (file, email, video), use the appropriate search tool first. Do not hallucinate IDs or paths.
3. **EXECUTE:** Call the tools one by one. Check the output of each tool before proceeding to the next step.
   - If a tool fails or returns empty results, try a different query or approach.
4. **ARGUMENTS:** Be precise with tool arguments. If a tool requires a specific ID (like a video ID or file ID), ensure you have obtained it from a previous step.

Tools available: {tool_names}

Be persistent and thorough. Do not give up easily."""


# =============================================================================
# Main Agent Class
# =============================================================================


class LangGraphAgent:
    """LangGraph agent backed by LangChain's create_agent.

    create_agent returns a compiled LangGraph graph with its own internal
    tool-calling loop. We use it *directly* — no extra StateGraph wrapper.

    Features:
    - Single compiled graph (no graph-in-graph nesting)
    - MCP tool discovery and loading
    - Supports OpenAI, local, and custom model backends
    - A2A protocol integration via ``run()``
    """

    def __init__(
        self,
        mcp_endpoint: str,
        model: Union[str, BaseChatModel] = "gpt-4o-mini",
        temperature: float = 0.0,
        model_provider: Literal["openai", "local"] = "openai",
    ):
        self.mcp_endpoint = mcp_endpoint
        self.temperature = temperature

        # Resolve model name & instance
        if isinstance(model, str):
            self.model_name = model
            self.model_instance = None
            self.model_provider = model_provider
        else:
            self.model_name = getattr(model, "model", "custom-model")
            self.model_instance = model
            self.model_provider = "custom"

        self.tool_loader = MCPToolLoader(mcp_endpoint)
        self.graph = None  # CompiledGraph from create_agent
        self.tools: List[Tool] = []

        # Metrics
        self.total_tasks = 0
        self.successful_tasks = 0

    # ----- Initialization -----

    async def initialize(self):
        """Load MCP tools, resolve model, and build the agent graph."""
        print(f"🔧 Initializing LangGraph Agent...")
        print(f"   Model: {self.model_name} ({self.model_provider})")
        print(f"   MCP: {self.mcp_endpoint}")

        self.tools = await self.tool_loader.load_tools()
        print(f"✅ Loaded {len(self.tools)} tools")

        model = self._resolve_model()
        self.graph = self._build_graph(model, self.tools)
        print("✅ Agent ready")

    def _resolve_model(self) -> BaseChatModel:
        """Return the chat model instance based on provider config."""
        if self.model_instance:
            return self.model_instance

        if self.model_provider == "local":
            return self._try_local_model()

        return ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
        )

    def _try_local_model(self) -> BaseChatModel:
        """Attempt to load LocalModel (Qwen), fallback to OpenAI."""
        try:
            from pathlib import Path

            project_root = Path(__file__).resolve().parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from custom_qwen import LocalModel

            print("   Using LocalModel (Qwen)")
            return LocalModel(temperature=self.temperature)
        except ImportError as e:
            print(f"⚠️ LocalModel not available, falling back to OpenAI: {e}")
            return ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
            )

    @staticmethod
    def _build_graph(model: BaseChatModel, tools: List[Tool]):
        """Create the compiled LangGraph graph via create_agent.

        create_agent already returns a compiled graph with an internal
        tool-calling loop — no need to wrap it in another StateGraph.
        """
        tool_names = ", ".join(t.name for t in tools)
        prompt = SYSTEM_PROMPT.replace("{tool_names}", tool_names)

        return create_agent(
            model=model,
            tools=tools,
            system_prompt=prompt,
            middleware=[
                ToolRetryMiddleware(
                    max_retries=3,
                    backoff_factor=2.0,
                    initial_delay=1.0,
                ),
                ContextEditingMiddleware(
                    edits=[
                        ClearToolUsesEdit(trigger=100000, keep=3),
                    ],
                ),
            ],
        )

    # ----- A2A Execution -----

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent task (A2A interface)."""
        if self.graph is None:
            await self.initialize()

        self.total_tasks += 1
        task_text = get_message_text(message)

        await updater.update_status(
            TaskState.working, new_agent_text_message("Processing...")
        )

        try:
            result = await asyncio.to_thread(
                self.graph.invoke,
                {"messages": [HumanMessage(content=task_text)]},
                {"configurable": {"thread_id": str(self.total_tasks)}},
            )

            final_answer, tool_results = self._extract_results(result)

            response_data = {
                "response": final_answer,
                "tool_calls": tool_results,
                "tool_call_count": len(tool_results),
                "metrics": self.get_metrics(),
            }

            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(response_data)))],
                name="Response",
            )
            self.successful_tasks += 1

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await updater.update_status(
                TaskState.failed, new_agent_text_message(f"Error: {e}")
            )
            raise

    # ----- Result Extraction -----

    @staticmethod
    def _extract_results(result: Dict) -> tuple[str, List[Dict]]:
        """Extract final answer and tool call info from graph output."""
        messages = result.get("messages", [])
        tool_results: List[Dict] = []
        final_answer = ""

        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_results.append({
                        "name": tc.get("name", "unknown"),
                        "arguments": tc.get("args", {}),
                    })
            if hasattr(msg, "content") and msg.content:
                final_answer = msg.content

        return final_answer or "Task completed", tool_results

    # ----- Lifecycle -----

    async def close(self):
        """Release resources."""
        await self.tool_loader.close()

    def get_metrics(self) -> Dict:
        total = max(self.total_tasks, 1)
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / total) * 100:.1f}%",
        }

    def reset(self):
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports
# =============================================================================

__all__ = ["LangGraphAgent", "MCPToolLoader", "graph"]


# =============================================================================
# Graph Instance for LangGraph Server
# =============================================================================

graph = None

_is_test_run = any("test" in arg for arg in sys.argv)
if os.getenv("SKIP_AGENT_INIT") != "true" and not _is_test_run:
    try:
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None

        if _loop is None or not _loop.is_running():
            _agent = LangGraphAgent(
                mcp_endpoint="http://localhost:8091",
                model="gpt-4o-mini",
                temperature=0.0,
            )
            asyncio.run(_agent.initialize())
            graph = _agent.graph
    except Exception as e:
        print(f"⚠️ Agent initialization skipped or failed: {e}")
