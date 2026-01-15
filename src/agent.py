"""
AgentX Green Agent - Agent Logic
================================
Handles assessment requests from AgentBeats platform.

Request Format (from AgentBeats):
{
    "participants": {"purple_agent": "http://..."},
    "config": {"task_ids": [0,1,2], "max_turns": 30}
}
"""
import json
from typing import Any

from pydantic import BaseModel, HttpUrl, ValidationError
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message

from src.messenger import Messenger


class EvalRequest(BaseModel):
    """AgentBeats assessment request format."""
    participants: dict[str, HttpUrl]  # role -> agent URL
    config: dict[str, Any]


class TaskScore(BaseModel):
    """Score for a single task."""
    task_id: str
    action_score: float
    argument_score: float
    efficiency_score: float
    total_score: float
    status: str
    details: dict[str, Any] = {}


class EvalResult(BaseModel):
    """Final evaluation result."""
    assessment_id: str
    agent: str
    tasks: list[TaskScore]
    summary: dict[str, Any]


class Agent:
    """
    AgentX Green Agent - MCP Task Evaluator
    
    Evaluates Purple agents on MCP-based tasks with 3D scoring:
    - Action Score (50%): Did agent call required tools?
    - Argument Score (40%): Were tool arguments correct?
    - Efficiency Score (10%): Did agent complete optimally?
    """
    
    # Required participants for this assessment
    required_roles: list[str] = ["agent"]
    
    # Required config keys
    required_config_keys: list[str] = []  # task_ids and max_turns are optional
    
    def __init__(self):
        self.messenger = Messenger()
        # These will be set from executor
        self.task_loader = None
        self.scorer = None
        self.mcp_endpoint = None
    
    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        """Validate AgentBeats assessment request."""
        # Check required roles
        missing_roles = set(self.required_roles) - set(request.participants.keys())
        if missing_roles:
            return False, f"Missing participant roles: {missing_roles}"
        
        # Check required config keys
        missing_config = set(self.required_config_keys) - set(request.config.keys())
        if missing_config:
            return False, f"Missing config keys: {missing_config}"
        
        return True, "ok"
    
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """
        Main agent logic - handle assessment request.
        
        This is called by the Executor when a message arrives.
        
        Args:
            message: Incoming A2A message (contains EvalRequest JSON)
            updater: TaskUpdater for reporting progress and results
        """
        input_text = get_message_text(message)
        
        # Parse and validate request
        try:
            request = EvalRequest.model_validate_json(input_text)
            ok, msg = self.validate_request(request)
            if not ok:
                await updater.reject(new_agent_text_message(msg))
                return
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return
        
        # Extract configuration
        purple_agent_url = str(request.participants["agent"])
        task_ids = request.config.get("task_ids", [])
        max_turns = request.config.get("max_turns", 30)
        
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(
                f"Starting assessment.\n"
                f"Purple Agent: {purple_agent_url}\n"
                f"Tasks: {task_ids or 'all'}\n"
                f"Max Turns: {max_turns}"
            )
        )
        
        try:
            # Run evaluation
            results = await self.evaluate_purple_agent(
                purple_agent_url=purple_agent_url,
                task_ids=task_ids,
                max_turns=max_turns,
                updater=updater,
            )
            
            # Save results to historical_trajectories/
            await self._save_results(results)
            
            # Produce artifact with results
            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=f"Evaluation complete. Average score: {results.summary.get('average_score', 0):.2%}")),
                    Part(root=DataPart(data=results.model_dump())),
                ],
                name="EvaluationResult",
            )
            
        except Exception as e:
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Evaluation failed: {e}")
            )
            raise
        finally:
            self.messenger.reset()
    
    async def _save_results(self, results: EvalResult) -> None:
        """Save evaluation results to historical_trajectories/"""
        import os
        from datetime import datetime
        from pathlib import Path
        
        # Create directory if not exists
        trajectories_dir = Path("historical_trajectories")
        trajectories_dir.mkdir(exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"eval_{results.assessment_id}_{timestamp}.json"
        filepath = trajectories_dir / filename
        
        # Save as JSON
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(results.model_dump_json(indent=2))
        
        print(f"📁 Results saved to: {filepath}")
    
    async def evaluate_purple_agent(
        self,
        purple_agent_url: str,
        task_ids: list[int],
        max_turns: int,
        updater: TaskUpdater,
    ) -> EvalResult:
        """
        Run evaluation loop for Purple Agent.
        
        For each task:
        1. Setup environment (reset MCP state)
        2. Send task instruction to Purple Agent
        3. Receive tool calls, execute on MCP
        4. Score results
        """
        import uuid
        
        assessment_id = str(uuid.uuid4())[:8]
        task_scores: list[TaskScore] = []
        
        # Determine which tasks to run
        if not task_ids and self.task_loader:
            # Run first 5 tasks if not specified
            task_ids = list(range(min(5, len(self.task_loader.tasks))))
        
        for task_idx in task_ids:
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"Running task {task_idx}...")
            )
            
            try:
                score = await self.run_single_task(
                    task_idx=task_idx,
                    purple_agent_url=purple_agent_url,
                    max_turns=max_turns,
                    updater=updater,
                )
                task_scores.append(score)
                
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(
                        f"Task {task_idx} complete: {score.total_score:.2%}"
                    )
                )
                
            except Exception as e:
                task_scores.append(TaskScore(
                    task_id=f"task-{task_idx}",
                    action_score=0.0,
                    argument_score=0.0,
                    efficiency_score=0.0,
                    total_score=0.0,
                    status="failed",
                    details={"error": str(e)}
                ))
        
        # Calculate summary
        total = len(task_scores)
        completed = sum(1 for t in task_scores if t.status == "completed")
        avg_score = sum(t.total_score for t in task_scores) / max(total, 1)
        
        return EvalResult(
            assessment_id=assessment_id,
            agent=purple_agent_url,
            tasks=task_scores,
            summary={
                "total_tasks": total,
                "completed_tasks": completed,
                "average_score": avg_score,
                "action_avg": sum(t.action_score for t in task_scores) / max(total, 1),
                "argument_avg": sum(t.argument_score for t in task_scores) / max(total, 1),
                "efficiency_avg": sum(t.efficiency_score for t in task_scores) / max(total, 1),
            }
        )
    
    async def run_single_task(
        self,
        task_idx: int,
        purple_agent_url: str,
        max_turns: int,
        updater: TaskUpdater,
    ) -> TaskScore:
        """
        Run a single evaluation task.
        
        1. Load task definition
        2. Reset MCP state
        3. Send instruction to Purple Agent
        4. Execute tool calls
        5. Score results
        """
        from src.tools.mcp_scorer import MCPScorer
        
        # Get task definition
        if not self.task_loader:
            return TaskScore(
                task_id=f"task-{task_idx}",
                action_score=0.0,
                argument_score=0.0,
                efficiency_score=0.0,
                total_score=0.0,
                status="error",
                details={"error": "Task loader not initialized"}
            )
        
        try:
            task_def = self.task_loader.get_task(task_idx)
        except IndexError:
            return TaskScore(
                task_id=f"task-{task_idx}",
                action_score=0.0,
                argument_score=0.0,
                efficiency_score=0.0,
                total_score=0.0,
                status="error",
                details={"error": f"Task {task_idx} not found"}
            )
        
        # Initialize scorer for this task
        scorer = MCPScorer(task_def.to_dict())
        
        # Reset MCP state and set task via endpoint if available
        if self.mcp_endpoint:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    # Set current task (includes initial_state)
                    await client.post(
                        f"{self.mcp_endpoint}/task",
                        json=task_def.to_dict()
                    )
                    # Reset state
                    await client.post(
                        f"{self.mcp_endpoint}/reset",
                        json={}
                    )
            except Exception as e:
                # State reset failed, continue anyway
                pass
        
        # Conversation loop with Purple Agent
        turn = 0
        conversation_done = False
        last_response = ""
        
        # Send initial instruction
        instruction = task_def.instruction
        if self.mcp_endpoint:
            instruction += f"\n\nYou have access to MCP tools at: {self.mcp_endpoint}/mcp"
        
        try:
            while turn < max_turns and not conversation_done:
                turn += 1
                
                # Send message to Purple Agent
                response = await self.messenger.talk_to_agent(
                    message=instruction if turn == 1 else last_response,
                    url=purple_agent_url,
                    new_conversation=(turn == 1),
                    timeout=60,
                )
                
                last_response = response
                
                # Parse response for tool calls
                tool_calls = self._extract_tool_calls(response)
                
                if tool_calls:
                    # Execute each tool call and record for scoring
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name", "")
                        tool_args = tool_call.get("arguments", {})
                        
                        # Execute on MCP if available
                        result = None
                        if self.mcp_endpoint:
                            result = await self._execute_mcp_tool(tool_name, tool_args)
                        
                        # Record for scoring
                        scorer.record_tool_call(tool_name, tool_args, result)
                        tool_results.append({
                            "tool": tool_name,
                            "result": result
                        })
                    
                    # Send results back to agent
                    last_response = json.dumps({"tool_results": tool_results})
                else:
                    # No tool calls - check if agent is done
                    if self._is_task_complete(response):
                        conversation_done = True
                
        except Exception as e:
            return TaskScore(
                task_id=task_def.task_id,
                action_score=0.0,
                argument_score=0.0,
                efficiency_score=0.0,
                total_score=0.0,
                status="error",
                details={"error": str(e), "turn": turn}
            )
        
        # Calculate final score
        score_result = scorer.calculate_score()
        
        return TaskScore(
            task_id=task_def.task_id,
            action_score=score_result.action_score,
            argument_score=score_result.argument_score,
            efficiency_score=score_result.efficiency_score,
            total_score=score_result.total_score,
            status="completed",
            details=score_result.to_dict()
        )
    
    def _extract_tool_calls(self, response: str) -> list[dict]:
        """Extract tool calls from agent response."""
        tool_calls = []
        
        # First, check for <tool_calls>...</tool_calls> format (Purple Agent format)
        import re
        tool_calls_pattern = r'<tool_calls>\s*(.*?)\s*</tool_calls>'
        match = re.search(tool_calls_pattern, response, re.DOTALL)
        if match:
            try:
                tool_calls_json = match.group(1).strip()
                parsed = json.loads(tool_calls_json)
                if isinstance(parsed, list):
                    # Convert from Purple format to standard format
                    for tc in parsed:
                        tool_calls.append({
                            "name": tc.get("tool", tc.get("name", "")),
                            "arguments": tc.get("arguments", tc.get("parameters", {})),
                            "result": tc.get("result")
                        })
                    return tool_calls
            except json.JSONDecodeError:
                pass
        
        # Try to parse as JSON
        try:
            data = json.loads(response)
            if isinstance(data, dict):
                # Check for OpenAI-style tool calls
                if "tool_calls" in data:
                    return data["tool_calls"]
                # Check for direct tool call
                if "name" in data and ("arguments" in data or "parameters" in data):
                    return [data]
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON blocks in response
        json_pattern = r'\{[^{}]*"name"[^{}]*\}'
        matches = re.findall(json_pattern, response)
        for match in matches:
            try:
                tool_call = json.loads(match)
                if "name" in tool_call:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError:
                pass
        
        return tool_calls
    
    def _is_task_complete(self, response: str) -> bool:
        """Check if agent indicates task completion."""
        completion_phrases = [
            "task complete",
            "done",
            "finished",
            "completed",
            "that's all",
            "nothing more",
        ]
        response_lower = response.lower()
        return any(phrase in response_lower for phrase in completion_phrases)
    
    async def _execute_mcp_tool(self, tool_name: str, arguments: dict) -> dict | None:
        """Execute a tool call on the MCP server."""
        if not self.mcp_endpoint:
            return None
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.mcp_endpoint}/tools/call",
                    json={
                        "name": tool_name,
                        "arguments": arguments
                    }
                )
                if response.status_code == 200:
                    return response.json()
                return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
