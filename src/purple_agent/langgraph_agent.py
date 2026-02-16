"""
AgentX LangGraph Agent - Simplified Single Node Architecture
============================================================
Clean, minimal agent with single execution node.

Architecture:
- One unified agent node with tools
- Simple state management
- Direct execution, no routing overhead
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path

import httpx
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, END, MessagesState
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware, ContextEditingMiddleware, ClearToolUsesEdit

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


# =============================================================================
# Simple State
# =============================================================================


class AgentState(MessagesState):
    """Minimal state tracking."""

    tool_results: List[Dict[str, Any]] = []
    final_answer: str = ""


# =============================================================================
# MCP Tool Loading
# =============================================================================


class MCPToolLoader:
    """Load MCP tools and convert to LangChain format using Agent Discovery."""

    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[Tool] = []
        self.agent_card: Dict[str, Any] = {}
        self.tools_endpoint: Optional[str] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def discover_capabilities(self) -> bool:
        """
        Check /.well-known/agent.json to discover capabilities and tool endpoints.
        Returns True if tools should be loaded.
        """
        print(f"🔍 Discovering agent capabilities at {self.mcp_endpoint}...")
        client = await self.get_client()

        try:
            # 1. Try Agent Card
            response = await client.get(f"{self.mcp_endpoint}/.well-known/agent.json")
            if response.status_code == 200:
                self.agent_card = response.json()
                print(f"✅ Found Agent Card: {self.agent_card.get('name', 'Unknown')}")

                # Analyze for tool endpoints
                # Strategy 1: Look for explicit 'tools_url' or similiar fields (future standard)
                if self.agent_card.get("tools_url"):
                    self.tools_endpoint = self.agent_card["tools_url"]
                    print(f"   Tools endpoint found in card: {self.tools_endpoint}")
                    return True

                # Strategy 2: Scan description/skills for URIs
                import re

                description = str(self.agent_card)
                # Matches http(s)://.../tools
                url_match = re.search(r'https?://[^\s"]+/tools', description)
                if url_match:
                    self.tools_endpoint = url_match.group(0)
                    print(
                        f"   Tools endpoint extracted from description: {self.tools_endpoint}"
                    )
                    return True

                # Strategy 3: Check keywords indicating MCP/tools support
                keywords = ["mcp", "tool", "function", "skill"]
                if any(k in description.lower() for k in keywords):
                    print(
                        "   Agent mentions tools/MCP, assuming default /tools endpoint."
                    )
                    self.tools_endpoint = f"{self.mcp_endpoint}/tools"
                    return True
            else:
                print(
                    f"⚠️ No Agent Card found (HTTP {response.status_code}). Assumption: Standard MCP."
                )

        except Exception as e:
            print(f"⚠️ Discovery error: {e}")

        # Fallback: Assume standard MCP /tools if nothing else found but we were told this IS an MCP endpoint
        if not self.tools_endpoint:
            self.tools_endpoint = f"{self.mcp_endpoint}/tools"

        return True

    async def load_tools(self) -> List[Tool]:
        """Fetch and convert MCP tools."""
        if self._tools_cache:
            return self._tools_cache

        # Ensure discovery happened
        if not self.tools_endpoint:
            should_load = await self.discover_capabilities()
            if not should_load:
                print("ℹ️ Agent does not appear to support tools.")
                return []

        try:
            print(f"📥 Loading tools from: {self.tools_endpoint}")
            client = await self.get_client()
            # If we extracted a full URL, use it. Otherwise append to base.
            url = (
                self.tools_endpoint
                if "://" in self.tools_endpoint
                else f"{self.mcp_endpoint}/{self.tools_endpoint.lstrip('/')}"
            )

            response = await client.get(url)

            if response.status_code != 200:
                print(f"⚠️ Failed to load tools from {url}: HTTP {response.status_code}")
                return []

            data = response.json()
            mcp_tools = data.get("tools", [])

            print(f"✅ Loaded {len(mcp_tools)} MCP tools")

            # Convert to LangChain Tools
            langchain_tools = []
            for mcp_tool in mcp_tools:
                name = mcp_tool.get("name", "")
                description = mcp_tool.get("description", f"Execute {name}")

                # Create closure with proper binding
                def make_tool_func(t_name, t_endpoint, t_schema):
                    async def execute_tool(*args, **kwargs) -> str:
                        try:
                            # Handle positional arguments (LangChain sometimes passes single string arg)
                            # If we have args and the schema has exactly one required property, map it.
                            final_args = kwargs.copy()
                            if args:
                                # Simple heuristic: if 1 arg and it's a string, and schema has 1 property
                                # or we just take the first property.
                                # For now, let's just update kwargs if empty.
                                if not final_args and len(args) == 1:
                                    # Try to guess key from schema
                                    props = (
                                        t_schema.get("inputSchema", {})
                                        .get("properties", {})
                                        .keys()
                                    )
                                    if props:
                                        first_key = list(props)[0]
                                        final_args[first_key] = args[0]
                                    else:
                                        # Fallback, maybe 'input' or 'query'
                                        final_args["input"] = args[0]

                            # Construct call URL
                            # If endpoint is http://host/tools -> call is http://host/tools/call
                            call_url = f"{t_endpoint}/call"

                            nonlocal self
                            client = await self.get_client()

                            response = await client.post(
                                call_url, json={"name": t_name, "arguments": final_args}
                            )
                            result = response.json()
                            return json.dumps(result, default=str)
                        except Exception as e:
                            return json.dumps({"error": str(e)})

                    def sync_wrapper(*args, **kwargs) -> str:
                        return asyncio.run(execute_tool(*args, **kwargs))

                    return sync_wrapper, execute_tool

                sync_func, async_func = make_tool_func(name, url, mcp_tool)

                # Note: We stick to plain Tool for now, relying on LLM to pass kwargs correctly.
                # Ideally we would use StructuredTool with a dynamic Pydantic model.

                tool = Tool(
                    name=name,
                    description=description,
                    func=sync_func,
                    coroutine=async_func,
                )
                langchain_tools.append(tool)

            self._tools_cache = langchain_tools
            return langchain_tools

        except Exception as e:
            print(f"❌ Error loading tools: {e}")
            return []


# =============================================================================
# Agent Configuration
# =============================================================================

SYSTEM_PROMPT = """You are a highly capable AI assistant with access to a wide range of tools.

Your Goal: Complete the user's request accurately by chaining the necessary tools in the correct order.

Instructions:
1. **PLAN:** Before taking action, analyze the request. Break it down into logical steps.
   - Example: "Search Drive for file" -> "Read file content" -> "Send email".
2. **SEARCH:** If you need to find a resource (file, email, video), use the appropriate search tool first. Do not hallucinate IDs or paths.
3. **EXECUTE:** Call the tools one by one. Check the output of each tool before proceeding to the next step.
   - If a tool fails or returns empty results, try a different query or approach.
4. **ARGUMENTS:** precise with tool arguments. If a tool requires a specific ID (like a video ID or file ID), ensure you have obtained it from a previous step.

Tools available: {tool_names}

Be persistent and thorough. Do not give up easily."""


# =============================================================================
# Graph Builder
# =============================================================================


def build_agent_graph(model: any, tools: List[Tool]):
    """Build simple single-node graph using create_agent."""

    # Format system prompt with tool names
    tool_names = ", ".join([t.name for t in tools])
    formatted_prompt = SYSTEM_PROMPT.replace("{tool_names}", tool_names)

    # Create agent directly
    purple_agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=formatted_prompt,
        middleware=[
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
            ContextEditingMiddleware(
                edits=[
                    ClearToolUsesEdit(
                        trigger=100000,
                        keep=3,
                    ),
                ],
            ),
        ],
    )

    # Agent node
    def agent_node(state: AgentState) -> Dict:
        """Agent execution node."""
        messages = state.get("messages", [])

        # Invoke agent
        result = purple_agent.invoke({"messages": messages})

        # Extract messages and tool calls
        result_messages = result.get("messages", [])

        # Track tool usage
        tool_results = []
        final_answer = ""

        for msg in result_messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_results.append(
                        {
                            "name": tc.get("name", "unknown"),
                            "arguments": tc.get("args", {}),
                        }
                    )
            if hasattr(msg, "content") and msg.content:
                final_answer = msg.content

        return {
            "messages": result_messages,
            "tool_results": state.get("tool_results", []) + tool_results,
            "final_answer": final_answer or "Task completed",
        }

    # Build graph
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)

    return graph.compile()


# =============================================================================
# Main Agent Class
# =============================================================================


class LangGraphAgent:
    """
    Simplified LangGraph agent with single execution node.

    Features:
    - Clean single-node architecture
    - Direct tool execution
    - Minimal state management
    - Works with ANY MCP server
    """

    def __init__(
        self,
        mcp_endpoint: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ):
        self.mcp_endpoint = mcp_endpoint
        self.model_name = model
        self.temperature = temperature

        self.tool_loader = MCPToolLoader(mcp_endpoint)
        self.graph = None
        self.tools = []
        self.model = None

        # Metrics
        self.total_tasks = 0
        self.successful_tasks = 0

    async def initialize(self):
        """Load tools and build graph."""
        print(f"🔧 Initializing LangGraph Agent...")
        print(f"   Model: {self.model_name}")
        print(f"   MCP: {self.mcp_endpoint}")

        # Load tools
        self.tools = await self.tool_loader.load_tools()
        print(f"✅ Loaded {len(self.tools)} tools")

        # Create model
        self.model = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
        ).with_config({"configurable": {"system_message": SYSTEM_PROMPT}})

        # Build graph
        self.graph = build_agent_graph(self.model, self.tools)
        print(f"✅ Agent ready")

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent (A2A interface)."""
        if self.graph is None:
            await self.initialize()

        self.total_tasks += 1
        task_text = get_message_text(message)

        await updater.update_status(
            TaskState.working, new_agent_text_message("Processing...")
        )

        try:
            # Execute graph
            result = await asyncio.to_thread(
                self.graph.invoke,
                {"messages": [HumanMessage(content=task_text)]},
                {"configurable": {"thread_id": str(self.total_tasks)}},
            )

            # Extract results
            final_answer = result.get("final_answer", "Task completed")
            tool_results = result.get("tool_results", [])

            # Build response
            response_data = {
                "response": final_answer,
                "tool_calls": tool_results,
                "tool_call_count": len(tool_results),
                "metrics": {
                    "total_tasks": self.total_tasks,
                    "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
                },
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

    async def close(self):
        """Cleanup."""
        await self.tool_loader.close()

    def get_metrics(self) -> Dict:
        """Get metrics."""
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
        }

    def reset(self):
        """Reset metrics."""
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports
# =============================================================================

__all__ = ["LangGraphAgent", "MCPToolLoader", "AgentState", "graph"]


# =============================================================================
# Graph Instance for LangGraph Server
# =============================================================================

# Create default agent instance for langgraph.json
agent = LangGraphAgent(
    mcp_endpoint="http://localhost:8091",
    model="gpt-4o-mini",
    temperature=0.0,
)

# Initialize and expose graph safely
graph = None
import sys
import os

# Check if we are being imported by a test script or if explicit skip is set
is_test_run = any("test" in arg for arg in sys.argv)
if os.getenv("SKIP_AGENT_INIT") != "true" and not is_test_run:
    import asyncio

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            pass
        else:
            asyncio.run(agent.initialize())
            graph = agent.graph
    except Exception as e:
        print(f"⚠️ Agent initialization skipped or failed: {e}")
