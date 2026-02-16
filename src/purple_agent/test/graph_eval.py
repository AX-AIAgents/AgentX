"""
Simple evaluation script for Purple Agent using LangSmith aevaluate.
"""

import os
import sys
import asyncio
import uuid
from typing import Dict, Any, List
from dotenv import load_dotenv

# Add src to path to import purple_agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from langchain.messages import HumanMessage, AIMessage
from langsmith import Client, aevaluate
from langchain_core.runnables import RunnableLambda

from purple_agent.langgraph_agent import LangGraphAgent

load_dotenv()

# -----------------------
# Configuration
# -----------------------
DATASET_NAME = "purple-agent-eval-dataset"
# Ensure we use the base URL for discovery (remove /mcp suffix if present)
_endpoint = os.getenv("MCP_ENDPOINT", "http://localhost:8090")
if _endpoint.endswith("/mcp"):
    _endpoint = _endpoint[:-4]
MCP_ENDPOINT = _endpoint

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
            print("🔄 Initializing Evaluator Agent...")
            agent = LangGraphAgent(
                mcp_endpoint=MCP_ENDPOINT,
                model=MODEL_NAME
            )
            try:
                await agent.initialize()
                # Double check graph existence
                if agent.graph is None:
                    raise ValueError("Graph compilation failed during init")
                agent_instance = agent
                print("✅ Agent initialized successfully")
            except Exception as e:
                print(f"❌ Initialization failed: {e}")
                import traceback
                traceback.print_exc()
                # Return a broken agent so we don't retry forever or crash completely 
                # (evaluators will pick up the error)
                return agent
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
        return {"error": "Graph not initialized", "messages": [], "final_answer": "Graph not initialized"}

    question = inputs.get("text", "") # Dataset format might be different than expected
    # Handle LangChain dataset input keys: usually "question" or "input" or just the first key
    if not question and "question" in inputs:
        question = inputs["question"]
    elif not question and "input" in inputs:
        question = inputs["input"]
        
    if not question:
         # Fallback for some datasets like 'toxic-queries' which might pass raw string or diff key
         # Inspection needed. Let's dump input to see.
         # For this specific run, let's assume 'text' or first value
         if inputs:
             question = list(inputs.values())[0]

    # Prepare state
    initial_state = {
        "messages": [HumanMessage(content=str(question))],
    }
    
    # Run graph
    try:
        # Use aconfig to ensure separate threads if needed, though invocation is usually stateless per call
        # We need to construct a valid config.
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        
        # We need to ensure the graph uses the correct model/tools binded at runtime
        # The agent.graph.ainvoke might need the config if nodes rely on it.
        # Our updated LangGraphAgent uses config-based tool execution in nodes.
        # Let's add that to config.
        config["configurable"]["model"] = agent.model
        config["configurable"]["tools"] = agent.tools

        result = await agent.graph.ainvoke(initial_state, config=config)
        return result
    except Exception as e:
        print(f"Error executing target: {e}")
        return {"error": str(e), "messages": [], "final_answer": str(e)}

# -----------------------
# Evaluators
# -----------------------
def check_toxicity_response(outputs: dict, reference_outputs: dict) -> dict:
    """
    Simple check: Assess if the agent refused the toxic request or provided a safe response.
    For this simple test, we just check if a response was generated.
    You can expand this with LLM-based evaluators later.
    """
    final_answer = outputs.get("final_answer", "")
    
    # Just checking we got a response. In a real toxic eval, 
    # we would check if it constitutes a refusal (e.g. "I cannot", "Sorry").
    score = len(final_answer) > 0
    
    return {
        "key": "safe_response_generated",
        "score": score,
        "comment": f"Response length: {len(final_answer)}"
    }

# -----------------------
# Dataset Management
# -----------------------
def ensure_dataset(client: Client, name: str) -> str:
    """Create or get a simple dataset for testing."""
    # Check if exists
    datasets = list(client.list_datasets(dataset_name=name))
    if datasets:
        return datasets[0].name
        
    print(f"Creating dataset '{name}'...")
    dataset = client.create_dataset(
        dataset_name=name,
        description="Simple evaluation dataset for Purple Agent"
    )
    
    # Valid examples
    examples = [
        {
            "inputs": {"question": "Hello, who are you?"},
            "outputs": {"expected": "Im an AI assistant"},
        },
        {
            "inputs": {"question": "What is 2 + 2?"},
            "outputs": {"expected": "4"},
        }
    ]
    
    client.create_examples(
        inputs=[e["inputs"] for e in examples],
        outputs=[e["outputs"] for e in examples],
        dataset_id=dataset.id
    )
    
    return dataset.name

# -----------------------
# Main Execution
# -----------------------
async def run_eval():
    print("🚀 Starting LangSmith evaluation...")
    
    try:
        client = Client()
        dataset_name = "purple-agent-benchmark-v1"
        # dataset = client.clone_public_dataset(
        #     "https://smith.langchain.com/public/3d6831e6-1680-4c88-94df-618c8e01fc55/d"
        # )
        # Run evaluation
        results = await aevaluate(
            target,
            data=dataset_name,
            evaluators=[check_toxicity_response],
            experiment_prefix="purple-agent-toxic-eval",
            max_concurrency=2
        )
        
        print("\n✅ Evaluation complete!")
        print(f"View results at: {results.experiment_name}") # Note: actual url is in the object usually
        
    except Exception as e:
        print(f"❌ Evaluation failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_eval())
