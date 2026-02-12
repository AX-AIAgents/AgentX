"""
AgentX LangGraph Agent V2 - Simplified & Fast
==============================================
Production-ready agent optimized for AgentBeats benchmarks.

Key Changes from V1:
- No router overhead - direct execution
- Streaming-friendly architecture
- Proper async/await throughout
- Green Agent compatible response format
"""
import asyncio
import json
import os
from typing import Dict, List, Any, Optional

import httpx
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END, MessagesState
from langgraph.prebuilt import ToolNode

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


# =============================================================================
# MCP Tool Loading (Simplified)
# =============================================================================

class MCPToolLoader:
    """Load and convert MCP tools to LangChain format."""
    
    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_cache: List[Tool] = []
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def load_tools(self) -> List[Tool]:
        """Fetch tools from MCP and convert to LangChain Tools."""
        if self._tools_cache:
            return self._tools_cache
        
        try:
            client = await self.get_client()
            response = await client.get(f"{self.mcp_endpoint}/tools")
            
            if response.status_code != 200:
                print(f"⚠️ MCP tools endpoint returned {response.status_code}")
                return []
            
            data = response.json()
            mcp_tools = data.get("tools", [])
            
            # Convert to LangChain Tools
            langchain_tools = []
            for mcp_tool in mcp_tools:
                tool_name = mcp_tool.get("name", "")
                if not tool_name:
                    continue
                
                # Create async function for this tool
                async def tool_func(tool_name=tool_name, **kwargs):
                    return await self.call_tool(tool_name, kwargs)
                
                # Wrap in Tool
                langchain_tools.append(Tool(
                    name=tool_name,
                    description=mcp_tool.get("description", ""),
                    func=lambda **kw: asyncio.run(tool_func(**kw)),
                    coroutine=tool_func,  # For async support
                ))
            
            self._tools_cache = langchain_tools
            return langchain_tools
            
        except Exception as e:
            print(f"❌ Failed to load MCP tools: {e}")
            return []
    
    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool via MCP endpoint."""
        try:
            client = await self.get_client()
            response = await client.post(
                f"{self.mcp_endpoint}/tools/call",
                json={"name": tool_name, "arguments": arguments},
                timeout=60.0
            )
            
            result = response.json()
            # Return as string for LLM consumption
            return json.dumps(result)
            
        except Exception as e:
            return json.dumps({"error": str(e)})


# =============================================================================
# Agent State
# =============================================================================

class AgentState(MessagesState):
    """Simple state extending MessagesState."""
    tool_calls_made: List[Dict[str, Any]] = []


# =============================================================================
# Graph Builder (Simplified)
# =============================================================================

def should_continue(state: AgentState) -> str:
    """Determine if we should continue to tools or end."""
    messages = state["messages"]
    last_message = messages[-1]
    
    # If LLM makes a tool call, go to tools node
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    # Otherwise end
    return END


def call_model(state: AgentState, model: ChatOpenAI):
    """Call the LLM."""
    messages = state["messages"]
    response = model.invoke(messages)
    return {"messages": [response]}


def build_graph(model: ChatOpenAI, tools: List[Tool]):
    """Build simplified agent graph with tools."""
    
    # Create graph
    workflow = StateGraph(AgentState)
    
    # Define nodes
    workflow.add_node("agent", lambda s: call_model(s, model))
    
    # Add tool node if tools exist
    if tools:
        tool_node = ToolNode(tools)
        workflow.add_node("tools", tool_node)
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional edges
    if tools:
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                END: END
            }
        )
        # After tools, go back to agent
        workflow.add_edge("tools", "agent")
    else:
        workflow.add_edge("agent", END)
    
    # Compile without checkpointer (stateless execution)
    return workflow.compile()


# =============================================================================
# Main Agent Class
# =============================================================================

SYSTEM_PROMPT = """You are an elite AI assistant that helps complete tasks using available tools.

When given a task:
1. Analyze what needs to be done
2. Use the available tools to complete the task efficiently
3. Chain tool outputs together when needed
4. Provide a clear summary of what you did

Be direct and efficient. Use tools when needed, but don't over-complicate simple tasks.
"""


class LangGraphAgentV2:
    """
    Simplified LangGraph Agent for AgentBeats.
    
    Features:
    - Fast initialization
    - Proper async/await
    - Green Agent compatible output
    - Streaming support
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
        if self.graph is not None:
            return  # Already initialized
        
        print(f"🔧 Initializing LangGraph Agent V2...")
        print(f"   Model: {self.model_name}")
        print(f"   MCP: {self.mcp_endpoint}")
        
        # Load tools
        self.tools = await self.tool_loader.load_tools()
        print(f"✅ Loaded {len(self.tools)} tools")
        
        # Create model with tool binding
        self.model = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            streaming=True
        )
        
        if self.tools:
            self.model = self.model.bind_tools(self.tools)
        
        # Build graph
        self.graph = build_graph(self.model, self.tools)
        print(f"✅ Agent graph compiled")
    
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Execute agent (A2A interface)."""
        # Initialize on first run
        if self.graph is None:
            await self.initialize()
        
        self.total_tasks += 1
        task_text = get_message_text(message)
        
        print(f"\n{'='*60}")
        print(f"📋 Task #{self.total_tasks}: {task_text[:100]}...")
        print(f"{'='*60}")
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing request...")
        )
        
        try:
            # Prepare input with system prompt
            input_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task_text}
            ]
            
            # Invoke graph (stateless execution)
            print(f"🚀 Starting execution...")
            start_time = asyncio.get_event_loop().time()
            
            # Run in thread pool to avoid blocking
            result = await asyncio.to_thread(
                self.graph.invoke,
                {"messages": input_messages},
                {"recursion_limit": 20}  # Max 20 steps
            )
            
            elapsed = asyncio.get_event_loop().time() - start_time
            
            # Extract results
            messages = result.get("messages", [])
            print(f"📨 Received {len(messages)} messages")
            
            final_message = messages[-1] if messages else None
            
            # Extract tool calls
            tool_calls_made = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_name = tc.get("name", "unknown")
                        tool_calls_made.append({
                            "name": tool_name,
                            "arguments": tc.get("args", {})
                        })
                        print(f"  🔧 Tool: {tool_name}")
            
            # Get final answer
            if final_message and hasattr(final_message, "content"):
                final_answer = final_message.content
            else:
                final_answer = "Task completed"
            
            print(f"✅ Task complete in {elapsed:.2f}s ({len(tool_calls_made)} tools)")
            print(f"📝 Response: {final_answer[:200]}...")
            
            # Build response in Green Agent format
            response_data = {
                "response": final_answer,
                "tool_calls": tool_calls_made,
            }
            
            # Send as artifact
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(response_data)))],
                name="Response",
            )
            
            self.successful_tasks += 1
            
        except Exception as e:
            print(f"❌ Agent error: {e}")
            import traceback
            traceback.print_exc()
            
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}")
            )
            raise
    
    async def close(self):
        """Cleanup resources."""
        await self.tool_loader.close()
    
    def get_metrics(self) -> Dict:
        """Get agent metrics."""
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": f"{(self.successful_tasks / max(self.total_tasks, 1)) * 100:.1f}%",
        }
    
    def reset(self):
        """Reset agent state."""
        self.total_tasks = 0
        self.successful_tasks = 0


# =============================================================================
# Exports
# =============================================================================

__all__ = ["LangGraphAgentV2", "MCPToolLoader"]
