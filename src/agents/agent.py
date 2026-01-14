"""
AgentX Purple Agent Logic
=========================
OpenAI GPT-4o-mini powered agent for task execution.
"""
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message


load_dotenv()


class PurpleAgent:
    """
    Purple Agent - OpenAI GPT-4o-mini Task Executor
    
    Receives tasks from Green Agent and executes them using:
    - LLM reasoning (OpenAI GPT-4o-mini)
    - MCP tools (discovered from Green Agent or configured)
    """
    
    def __init__(self, mcp_endpoint: str | None = None):
        self.mcp_endpoint = mcp_endpoint
        self.conversation_history: list[dict] = []
        self.available_tools: list[dict] = []
        self._openai_client: OpenAI | None = None
    
    @property
    def openai_client(self) -> OpenAI:
        """Lazy initialization of OpenAI client."""
        if self._openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client
    
    async def discover_tools(self) -> list[dict]:
        """Discover available tools from MCP endpoint."""
        if not self.mcp_endpoint:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.mcp_endpoint}/tools")
                if response.status_code == 200:
                    data = response.json()
                    tools = data.get("tools", [])
                    print(f"✅ Discovered {len(tools)} tools from MCP")
                    return tools
        except Exception as e:
            print(f"⚠️ Failed to discover tools: {e}")
        
        return []
    
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool via MCP endpoint."""
        if not self.mcp_endpoint:
            return {"error": "No MCP endpoint configured"}
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.mcp_endpoint}/tools/call",
                    json={"name": tool_name, "arguments": arguments}
                )
                return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def convert_tools_to_openai_format(self, tools: list[dict]) -> list[dict]:
        """Convert MCP tool format to OpenAI function format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                }
            })
        return openai_tools
    
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """
        Main agent logic - execute task.
        
        Args:
            message: Incoming A2A message with task instruction
            updater: TaskUpdater for reporting progress
        """
        input_text = get_message_text(message)
        
        # Check for new task indicator
        if "<task_config>" in input_text or not self.conversation_history:
            self.conversation_history.clear()
            # Discover tools if MCP endpoint available
            if self.mcp_endpoint:
                self.available_tools = await self.discover_tools()
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing request...")
        )
        
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": input_text
        })
        
        # Convert tools to OpenAI format
        openai_tools = self.convert_tools_to_openai_format(self.available_tools)
        
        # System prompt
        system_prompt = """You are an AI assistant that helps complete tasks using available tools.
When given a task:
1. Analyze what needs to be done
2. Use the available tools to complete the task
3. Report your progress and results clearly

If you need to use a tool, call it with the appropriate parameters.
After completing the task, summarize what you did and the results."""
        
        try:
            # Call OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    *self.conversation_history
                ],
                tools=openai_tools if openai_tools else None,
                tool_choice="auto" if openai_tools else None,
            )
            
            assistant_message = response.choices[0].message
            
            # Handle tool calls
            if assistant_message.tool_calls:
                tool_results = []
                
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(f"Calling tool: {tool_name}")
                    )
                    
                    result = await self.call_tool(tool_name, arguments)
                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "content": json.dumps(result)
                    })
                
                # Add assistant message with tool calls
                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })
                
                # Add tool results
                for tr in tool_results:
                    self.conversation_history.append(tr)
                
                # Get final response after tool execution
                final_response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *self.conversation_history
                    ],
                )
                
                final_text = final_response.choices[0].message.content or ""
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_text
                })
                
                # Build response with tool calls for Green Agent scoring
                tool_calls_for_scoring = [
                    {
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments)
                    }
                    for tc in assistant_message.tool_calls
                ]
                
                response_with_tools = {
                    "response": final_text,
                    "tool_calls": tool_calls_for_scoring,
                    "tool_results": [json.loads(tr["content"]) for tr in tool_results]
                }
                
                await updater.add_artifact(
                    parts=[Part(root=TextPart(text=json.dumps(response_with_tools)))],
                    name="Response",
                )
            else:
                # No tool calls, just text response
                response_text = assistant_message.content or ""
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                await updater.add_artifact(
                    parts=[Part(root=TextPart(text=response_text))],
                    name="Response",
                )
                
        except Exception as e:
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}")
            )
            raise
    
    def reset(self):
        """Reset agent state."""
        self.conversation_history.clear()
        self.available_tools.clear()
