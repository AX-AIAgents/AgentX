"""
Green Agent Orchestrator - A2A Client Mode

This module handles the conversation loop between Green Agent and 
an external Purple Agent. Green Agent acts as both:
1. A2A Server (receives kickoff from run.py)
2. A2A Client (connects to Purple Agent)

This is the proper A2A architecture:
- run.py → Green Agent: "Start evaluating Purple at http://..."
- Green Agent → Purple Agent: Send tasks, receive responses
- Green Agent: Execute MCP tools, calculate scores, report results

NO MORE CODE IMPORTS - Pure A2A protocol!
"""
import json
from typing import Any, Optional

import httpx


class PurpleAgentClient:
    """
    A2A Client to communicate with Purple Agent.
    
    Green Agent uses this to:
    1. Send task instructions
    2. Receive tool call requests
    3. Execute tools via MCP
    4. Send tool results back
    """
    
    def __init__(self, purple_url: str, mcp_endpoint: str, timeout: float = 60.0):
        """
        Initialize Purple Agent client.
        
        Args:
            purple_url: Purple Agent's A2A URL (e.g., http://localhost:9000)
            mcp_endpoint: MCP server URL for tool execution
            timeout: HTTP timeout
        """
        self.purple_url = purple_url.rstrip('/')
        self.mcp_endpoint = mcp_endpoint.rstrip('/')
        self.timeout = timeout
        
        # Agent info (from Agent Card)
        self.agent_name = "Unknown"
        self.agent_description = ""
        self.capabilities = {}
        self.skills = []
        
        # State
        self.connected = False
        self.conversation_history: list[dict] = []
        
    async def connect(self) -> dict[str, Any]:
        """
        Connect to Purple Agent and fetch its Agent Card.
        
        Returns:
            Agent Card data
        """
        print(f"\n🔌 Green → Purple: Connecting to {self.purple_url}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Fetch Agent Card
            card_url = f"{self.purple_url}/.well-known/agent.json"
            response = await client.get(card_url)
            response.raise_for_status()
            card_data = response.json()
        
        # Parse Agent Card
        self.agent_name = card_data.get("name", "Unknown Agent")
        self.agent_description = card_data.get("description", "")
        self.capabilities = card_data.get("capabilities", {})
        self.skills = card_data.get("skills", [])
        
        self.connected = True
        
        print(f"✅ Connected to: {self.agent_name}")
        print(f"   Description: {self.agent_description[:100]}...")
        print(f"   Capabilities: {self.capabilities}")
        
        return card_data
    
    async def send_message(self, message: str) -> dict[str, Any]:
        """
        Send A2A message to Purple Agent.
        
        Args:
            message: Message content
            
        Returns:
            Purple Agent's response
        """
        if not self.connected:
            raise RuntimeError("Not connected to Purple Agent")
        
        # Build A2A message
        a2a_message = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": f"msg-{len(self.conversation_history)}",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": message}],
                    "messageId": f"mid-{len(self.conversation_history)}",
                },
                "configuration": {
                    "acceptedOutputModes": ["text"],
                },
            },
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.purple_url}/a2a/message",
                json=a2a_message,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
        
        # Extract response
        parsed = self._parse_a2a_response(result)
        
        # Track conversation
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": parsed})
        
        return parsed
    
    def _parse_a2a_response(self, response: dict) -> dict[str, Any]:
        """Parse A2A response format."""
        # Check for errors
        if "error" in response:
            return {
                "content": "",
                "error": response["error"],
                "done": False,
            }
        
        # Extract result
        result = response.get("result", {})
        message = result.get("message", {})
        parts = message.get("parts", [])
        
        content = ""
        tool_calls = []
        done = False
        
        for part in parts:
            if isinstance(part, dict):
                if "text" in part:
                    content += part["text"]
                elif "toolCall" in part:
                    # Format 1: {"toolCall": {...}}
                    tool_calls.append(part["toolCall"])
                elif part.get("type") == "tool_call":
                    # Format 2: {"type": "tool_call", "name": ..., "arguments": ...}
                    tool_calls.append({
                        "id": part.get("id", f"tc-{len(tool_calls)}"),
                        "name": part.get("name"),
                        "arguments": part.get("arguments", {}),
                    })
                elif part.get("type") == "text":
                    content += part.get("text", "")
        
        # Check for completion signals
        if any(kw in content.lower() for kw in ["task complete", "[done]", "finished"]):
            done = True
            print(f"   🏁 Completion signal detected in content: {content[:100]}...")
        
        return {
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
            "done": done,
        }
    
    async def execute_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Execute MCP tool and return result.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Tool execution result
        """
        print(f"   🔧 Executing: {tool_name}")
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(
                f"{self.mcp_endpoint}/tools/call",
                json={
                    "name": tool_name,
                    "arguments": arguments,
                },
            )
            response.raise_for_status()
            result = response.json()
        
        if "error" in result:
            return {"error": result["error"]}
        
        return result.get("result", {})
    
    async def send_tool_results(self, tool_results: list[dict]) -> dict[str, Any]:
        """
        Send tool execution results back to Purple Agent.
        
        Args:
            tool_results: List of {id, name, result} dicts
            
        Returns:
            Purple Agent's follow-up response
        """
        # Build A2A message with tool results in parts
        parts = []
        for r in tool_results:
            parts.append({
                "type": "tool_result",
                "toolCallId": r["id"],
                "toolName": r["name"],
                "result": r["result"],
            })
        
        # Send as A2A message
        message_data = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": f"msg-results-{len(self.conversation_history)}",
            "params": {
                "message": {
                    "role": "user",
                    "parts": parts,
                    "messageId": f"mid-results-{len(self.conversation_history)}",
                },
            },
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.purple_url}/a2a/message",
                json=message_data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
        
        self.conversation_history.append(("tool_results", parts))
        return self._parse_a2a_response(result)


async def run_evaluation_loop(
    purple_client: PurpleAgentClient,
    task_def: dict,
    scorer: Any,  # MCPScorer
    max_turns: int = 30,
) -> dict[str, Any]:
    """
    Run the multi-turn evaluation loop.
    
    This is the main orchestration logic, now inside Green Agent.
    
    Flow:
    1. Send task instruction to Purple
    2. Loop:
       - Purple responds with tool calls or text
       - Green executes tools via MCP
       - Green sends results back to Purple
       - Green provides guidance if needed
    3. Calculate and return score
    
    Args:
        purple_client: Connected PurpleAgentClient
        task_def: Task definition dict
        scorer: MCPScorer instance
        max_turns: Maximum conversation turns
        
    Returns:
        Evaluation result with score
    """
    from src.green_agent_guide import _generate_conversational_response
    
    task_id = task_def.get("task_id", "unknown")
    instruction = task_def.get("instruction", "")
    required_tools = task_def.get("expected_actions", [])
    required_tool_names = list(set(a.get("tool", "") for a in required_tools if a.get("tool")))
    
    print(f"\n{'='*60}")
    print(f"📋 Starting evaluation: {task_id}")
    print(f"   Instruction: {instruction[:80]}...")
    print(f"   Required tools: {required_tool_names}")
    print(f"{'='*60}")
    
    # Step 1: Send initial task instruction
    print(f"\n📨 Green → Purple: Sending task...")
    
    exam_paper = f"""TASK: {task_id}
DOMAIN: {task_def.get('domain', 'general')}

CUSTOMER REQUEST:
{instruction}

You have access to MCP tools. Use them to fulfill the request.
Report your actions with [TOOL:name](args) format.
When done, say [TASK_COMPLETE].
"""
    
    response = await purple_client.send_message(exam_paper)
    
    # Step 2: Multi-turn loop
    called_tools = []
    previous_signature = None
    
    for turn in range(max_turns):
        print(f"\n🔄 Turn {turn + 1}/{max_turns}")
        
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])
        done = response.get("done", False)
        
        if content:
            print(f"   💜 Purple: {content[:150]}...")
        
        # Check for completion
        if done or "[TASK_COMPLETE]" in content:
            print(f"   ✅ Purple signaled completion")
            break
        
        # Handle tool calls
        if tool_calls:
            tool_results = []
            tool_names_this_turn = []
            
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", {})
                
                print(f"   🔧 Purple calls: {tool_name}")
                
                # Record for scoring
                scorer.record_tool_call(tool_name, tool_args)
                called_tools.append(tool_name)
                tool_names_this_turn.append(tool_name)
                
                # Execute tool
                result = await purple_client.execute_tool(tool_name, tool_args)
                tool_results.append({
                    "id": tc.get("id", tool_name),
                    "name": tool_name,
                    "result": result,
                })
            
            # Detect duplicate patterns
            current_signature = "|".join(tool_names_this_turn)
            if current_signature == previous_signature:
                print(f"   ⚠️ Duplicate tool pattern - breaking loop")
                break
            previous_signature = current_signature
            
            # Send results back to Purple
            response = await purple_client.send_tool_results(tool_results)
        else:
            # No tool calls - Purple is either done or stuck
            print(f"   ⚠️ No tool calls from Purple - ending evaluation")
            break
    
    # Step 3: Calculate score
    print(f"\n📊 Calculating score...")
    score = scorer.calculate_score()
    score_dict = score.to_dict()
    
    print(f"   Total: {score_dict.get('total_score', 0):.2%}")
    print(f"   Action: {score_dict.get('scores', {}).get('action', 0):.2%}")
    print(f"   Argument: {score_dict.get('scores', {}).get('argument', 0):.2%}")
    
    return {
        "task_id": task_id,
        "status": "completed" if turn < max_turns - 1 else "max_turns",
        "turns": turn + 1,
        "score": score_dict,
        "tool_calls": list(set(called_tools)),
        "tool_call_count": len(called_tools),
    }


class GreenAgentOrchestrator:
    """
    Main orchestrator for Green Agent.
    
    Handles:
    1. Receiving kickoff from run.py
    2. Connecting to Purple Agent
    3. Running evaluation loop
    4. Reporting results
    """
    
    def __init__(
        self,
        task_file: str,
        mcp_endpoint: str = "http://localhost:8091",
    ):
        """
        Initialize orchestrator.
        
        Args:
            task_file: Path to task definitions JSONL
            mcp_endpoint: MCP server URL
        """
        self.task_file = task_file
        self.mcp_endpoint = mcp_endpoint
        self.task_loader = None
        
    def _load_tasks(self):
        """Load task definitions."""
        from src.tools.task_loader import TaskLoader
        self.task_loader = TaskLoader(self.task_file)
        self.task_loader.load_all()
    
    async def evaluate_agent(
        self,
        purple_agent_url: str,
        task_ids: list[int] | None = None,
        max_turns: int = 30,
    ) -> dict[str, Any]:
        """
        Main entry point: Evaluate a Purple Agent.
        
        This is called by Green Agent's kickoff handler.
        
        Args:
            purple_agent_url: Purple Agent's A2A URL
            task_ids: List of task indices to run
            max_turns: Max turns per task
            
        Returns:
            Evaluation results
        """
        from src.tools.mcp_scorer import MCPScorer
        
        # Load tasks
        if not self.task_loader:
            self._load_tasks()
        
        # Get tasks to run
        all_tasks = self.task_loader.load_all()
        if task_ids:
            selected = [(i, all_tasks[i]) for i in task_ids if i < len(all_tasks)]
        else:
            selected = [(i, t) for i, t in enumerate(all_tasks[:5])]
        
        print(f"\n🎯 Evaluating agent: {purple_agent_url}")
        print(f"   Tasks: {len(selected)}")
        
        # Connect to Purple Agent
        purple_client = PurpleAgentClient(
            purple_url=purple_agent_url,
            mcp_endpoint=self.mcp_endpoint,
        )
        await purple_client.connect()
        
        # Run evaluations
        results = []
        
        for task_idx, task_def in selected:
            print(f"\n{'='*60}")
            print(f"📋 Task {task_idx}: {task_def.task_id}")
            print(f"   Domain: {task_def.domain} | Difficulty: {task_def.difficulty}")
            print(f"{'='*60}")
            
            # Send task to MCP for state reset
            await self._reset_mcp_state(task_def.to_dict())
            
            # Create scorer
            scorer = MCPScorer(task_def.to_dict())
            
            # Run evaluation loop
            try:
                result = await run_evaluation_loop(
                    purple_client=purple_client,
                    task_def=task_def.to_dict(),
                    scorer=scorer,
                    max_turns=max_turns,
                )
                result["task_index"] = task_idx
                results.append(result)
                
            except Exception as e:
                import traceback
                print(f"❌ Error: {e}")
                traceback.print_exc()
                results.append({
                    "task_id": task_def.task_id,
                    "task_index": task_idx,
                    "status": "error",
                    "error": str(e),
                })
        
        return {
            "tasks": results,
            "purple_agent": purple_agent_url,
            "total_tasks": len(selected),
            "completed": sum(1 for r in results if r.get("status") == "completed"),
        }
    
    async def _reset_mcp_state(self, task: dict) -> bool:
        """Reset MCP server state for task."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.mcp_endpoint}/task",
                    json=task,
                )
                return response.status_code == 200
        except Exception as e:
            print(f"⚠️ Failed to reset MCP state: {e}")
            return False
