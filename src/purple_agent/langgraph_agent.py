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
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

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
    """Load MCP tools and convert to LangChain format."""
    
    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[Tool] = []
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def load_tools(self) -> List[Tool]:
        """Fetch and convert MCP tools."""
        if self._tools_cache:
            return self._tools_cache
        
        try:
            client = await self.get_client()
            response = await client.get(f"{self.mcp_endpoint}/tools")
            
            if response.status_code != 200:
                print(f"⚠️ Failed to load tools: HTTP {response.status_code}")
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
                def make_tool_func(tool_name: str):
                    async def execute_tool(**kwargs) -> str:
                        try:
                            client = await self.get_client()
                            response = await client.post(
                                f"{self.mcp_endpoint}/tools/call",
                                json={"name": tool_name, "arguments": kwargs}
                            )
                            result = response.json()
                            return json.dumps(result, default=str)
                        except Exception as e:
                            return json.dumps({"error": str(e)})
                    
                    def sync_wrapper(**kwargs) -> str:
                        return asyncio.run(execute_tool(**kwargs))
                    
                    return sync_wrapper, execute_tool
                
                sync_func, async_func = make_tool_func(name)
                
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

SYSTEM_PROMPT = """You are a helpful AI assistant with access to tools.

When given a task:
1. Analyze what needs to be done
2. Use available tools to gather information
3. Chain multiple tools if needed
4. Provide clear, accurate responses

Be thorough and efficient."""


# =============================================================================
# Graph Builder
# =============================================================================

def build_agent_graph(model: ChatOpenAI, tools: List[Tool]):
    """Build simple single-node graph using create_agent."""
    # Create agent directly
    agent_executor = create_agent(
        llm=model,
        tools=tools,
        system_message=SYSTEM_PROMPT,
    )
    
    # Agent node
    def agent_node(state: AgentState) -> Dict:
        """Agent execution node."""
        messages = state.get("messages", [])
        
        # Invoke agent
        result = agent_executor.invoke({"messages": messages})
        
        # Extract messages and tool calls
        result_messages = result.get("messages", [])
        
        # Track tool usage
        tool_results = []
        final_answer = ""
        
        for msg in result_messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_results.append({
                        "name": tc.get("name", "unknown"),
                        "arguments": tc.get("args", {}),
                    })
            if hasattr(msg, 'content') and msg.content:
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
    
    return graph.compile(checkpointer=MemorySaver())


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
        model = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
        ).with_config({"configurable": {"system_message": SYSTEM_PROMPT}})
        
        # Build graph
        self.graph = build_agent_graph(model, self.tools)
        print(f"✅ Agent ready")
    
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent (A2A interface)."""
        if self.graph is None:
            await self.initialize()
        
        self.total_tasks += 1
        task_text = get_message_text(message)
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing...")
        )
        
        try:
            # Execute graph
            result = await asyncio.to_thread(
                self.graph.invoke,
                {"messages": [HumanMessage(content=task_text)]},
                {"configurable": {"thread_id": str(self.total_tasks)}}
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
                }
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
                TaskState.failed,
                new_agent_text_message(f"Error: {e}")
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

__all__ = ["LangGraphAgent", "MCPToolLoader", "AgentState"]
