"""
Benchmark evaluation script for Purple Agent using LangSmith aevaluate.
Validates if the agent calls the expected tools for given scenarios.
"""

import os
import sys
import asyncio
import uuid
from typing import Dict, Any, List, Set
from dotenv import load_dotenv

# Add src to path to import purple_agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langsmith import Client, aevaluate
from langsmith.schemas import Example, Run

try:
    from src.purple_agent.langgraph_agent import LangGraphAgent
except ImportError:
    # Fallback to direct import if running from src root
    from purple_agent.langgraph_agent import LangGraphAgent

load_dotenv()

# -----------------------
# Configuration
# -----------------------
DATASET_NAME = "purple-agent-benchmark-v1"
# Ensure we use the base URL for discovery (remove /mcp suffix if present)
_endpoint = os.getenv("MCP_ENDPOINT", "http://localhost:8091")
if _endpoint.endswith("/mcp"):
    _endpoint = _endpoint[:-4]
MCP_ENDPOINT = _endpoint

# Model selection: Set USE_LOCAL_MODEL=true to use Qwen instead of OpenAI
USE_LOCAL_MODEL = os.getenv("USE_LOCAL_MODEL", "false").lower() == "true"
MODEL_NAME = os.getenv("MODEL", "gpt-4o-mini")

# -----------------------
# Setup Agent (Singleton-ish for test)
# -----------------------
agent_instance = None
_init_lock = asyncio.Lock()

async def get_agent():
    global agent_instance
    async with _init_lock:
        if agent_instance is None:
            if USE_LOCAL_MODEL:
                print(f"🔄 Initializing Agent with LocalModel (Qwen)...")
                print(f"💰 Cost savings: ~95% vs OpenAI")
                
                # Import LocalModel
                try:
                    from custom_qwen import LocalModel
                    model = LocalModel(temperature=0.0, max_tokens=4096)
                    model_provider = "custom"
                except ImportError as e:
                    print(f"⚠️ LocalModel not available: {e}")
                    print(f"   Falling back to OpenAI")
                    model = MODEL_NAME
                    model_provider = "openai"
            else:
                print(f"🔄 Initializing Agent with OpenAI ({MODEL_NAME})...")
                model = MODEL_NAME
                model_provider = "openai"
            
            print(f"🔗 MCP Endpoint: {MCP_ENDPOINT}")
            
            # Create agent
            agent = LangGraphAgent(
                mcp_endpoint=MCP_ENDPOINT,
                model=model,
                model_provider=model_provider
            )
            print(f"🔍 Agent instance created")
            
            try:
                await agent.initialize()
                
                if agent.graph is None:
                    raise ValueError("Graph compilation failed during init")
                agent_instance = agent
                print(f"✅ Agent initialized successfully with {len(agent.tools)} tools")
            except Exception as e:
                print(f"❌ Initialization failed: {e}")
                import traceback
                traceback.print_exc()
                return None
        return agent_instance

# -----------------------
# Target Function
# -----------------------
async def target(inputs: dict) -> dict:
    """
    Invokes the agent graph with the input question.
    """
    agent = await get_agent()
    
    # Check if graph exists
    if not agent or not agent.graph:
        return {"error": "Graph not initialized", "messages": []}

    # Extract question from inputs
    question = inputs.get("text") or inputs.get("question") or inputs.get("input")
    
    if not question:
         # Fallback: take the first string value found
         for k, v in inputs.items():
             if isinstance(v, str):
                 question = v
                 break
    
    if not question:
        return {"error": "No question found in inputs", "messages": []}

    # Prepare state
    initial_state = {
        "messages": [HumanMessage(content=str(question))],
    }
    
    # Run graph
    try:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = await agent.graph.ainvoke(initial_state, config=config)
        return result
    except Exception as e:
        print(f"Error executing target: {e}")
        return {"error": str(e), "messages": []}

# -----------------------
# Evaluators
# -----------------------
def tool_usage_evaluator(run: Run, example: Example) -> Dict[str, Any]:
    """
    Checks if the expected tools were called during the run.
    """
    # Extract expected tools from dataset example outputs
    expected_tools: List[str] = example.outputs.get("expected_tools", [])
    if not expected_tools:
        # If no tools expected, we can skip or pass
        return {"key": "tool_usage", "score": None}

    # Extract actual tools called from run outputs (the result of target function)
    # The target returns a dict which is the state of the graph.
    # It usually contains "messages".
    outputs = run.outputs or {}
    messages = outputs.get("messages", [])
    
    called_tools = set()
    for msg in messages:
        # Handle both object and dict representation (serialization)
        tool_calls = []
        if hasattr(msg, "tool_calls"):
            tool_calls = msg.tool_calls
        elif isinstance(msg, dict) and "tool_calls" in msg:
             tool_calls = msg["tool_calls"]
        elif isinstance(msg, dict) and "kwargs" in msg and "tool_calls" in msg["kwargs"]:
             # Sometimes serialized as kwargs
             tool_calls = msg["kwargs"]["tool_calls"]
        
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                called_tools.add(tool_call.get("name"))
            elif hasattr(tool_call, "name"):
                called_tools.add(tool_call.name)
    
    # Calculate score
    # Simple logic: Recall (how many expected tools were actually called)
    # or Jaccard similarity. Let's do a strict subset check or recall.
    
    missing_tools = [t for t in expected_tools if t not in called_tools]
    unexpected_tools = [t for t in called_tools if t not in expected_tools]
    
    score = 1.0 if not missing_tools else 0.0
    
    # If partial match is okay, we can adjust score
    if expected_tools and len(missing_tools) < len(expected_tools):
         score = (len(expected_tools) - len(missing_tools)) / len(expected_tools)

    return {
        "key": "tool_usage_recall",
        "score": score,
        "comment": f"Expected: {expected_tools}. Called: {list(called_tools)}. Missing: {missing_tools}"
    }

def correctness_evaluator(run: Run, example: Example) -> Dict[str, Any]:
    # Placeholder for LLM-based correctness check if needed
    # For now, we focus on tool usage
    return {"key": "correctness", "score": None}

# -----------------------
# Main Execution
# -----------------------
if __name__ == "__main__":
    print(f"🚀 Starting evaluation on dataset: {DATASET_NAME}")
    
    # Check if dataset exists (optional, aevaluate handles it but good for debug)
    client = Client()
    try:
        if not client.has_dataset(dataset_name=DATASET_NAME):
            print(f"⚠️ Dataset '{DATASET_NAME}' not found. Please run 'create_dataset.py' first.")
            sys.exit(1)
    except Exception as e:
        print(f"⚠️ Warning checking dataset: {e}")

    # Run evaluation
    async def main():
        results = await aevaluate(
            target,
            data=DATASET_NAME,
            evaluators=[tool_usage_evaluator],
            experiment_prefix="purple-agent-benchmark",
            max_concurrency=1  # Sequential to avoid rate limits or race conditions
        )
        print("\n📊 Evaluation Complete!")
        print(f"View results at: {results.url}")

    asyncio.run(main())
