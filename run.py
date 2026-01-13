#!/usr/bin/env python3
"""
AgentX Runner - KICKOFF SCRIPT ONLY

This is a minimal kickoff script that:
1. Starts the servers (A2A + MCP)
2. Sends ONE kickoff message to Green Agent
3. Waits for evaluation results

The actual orchestration happens INSIDE Green Agent:
- Green Agent connects to Purple Agent via A2A
- Green Agent sends tasks, receives responses
- Green Agent executes MCP tools
- Green Agent calculates scores

This follows the A2A protocol: near-zero code changes required
to evaluate ANY A2A-compatible agent.

Usage:
    # Evaluate an external agent
    python run.py --task-file tasks.jsonl --external-agent http://localhost:9000
    
    # Run specific task
    python run.py --task-file tasks.jsonl --external-agent http://localhost:9000 --task 0
    
    # Start servers only
    python run.py --task-file tasks.jsonl --servers-only
"""
import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import tomllib  # Python 3.11+ built-in


def load_config(config_path: str = "scenario.toml") -> dict:
    """Load configuration from TOML file."""
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def start_servers(config: dict, task_file: str | None = None) -> tuple[subprocess.Popen, subprocess.Popen]:
    """Start A2A and MCP servers."""
    a2a_port = config.get("server", {}).get("a2a_port", 8090)
    mcp_port = config.get("server", {}).get("mcp_port", 8091)
    
    env = os.environ.copy()
    env["A2A_PORT"] = str(a2a_port)
    env["MCP_PORT"] = str(mcp_port)
    env["AGENT_PUBLIC_URL"] = f"http://localhost:{mcp_port}"
    env["PYTHONPATH"] = str(Path.cwd())
    
    # Pass task file to Green Agent
    if task_file:
        task_path = Path(task_file)
        if not task_path.is_absolute():
            task_path = Path.cwd() / task_path
        env["TASK_DEFINITIONS_FILE"] = str(task_path.resolve())
    
    print(f"🚀 Starting servers...")
    print(f"   A2A (Green Agent): http://localhost:{a2a_port}")
    print(f"   MCP (Tools): http://localhost:{mcp_port}")
    
    # Start MCP server
    mcp_proc = subprocess.Popen(
        [sys.executable, "src/mcp_http_server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)
    
    # Start A2A server
    a2a_proc = subprocess.Popen(
        [sys.executable, "src/a2a_server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(3)  # Wait for server to start
    
    # Check if servers are running
    if mcp_proc.poll() is not None:
        output = mcp_proc.stdout.read().decode() if mcp_proc.stdout else "No output"
        raise RuntimeError(f"MCP server failed to start: {output}")
    if a2a_proc.poll() is not None:
        output = a2a_proc.stdout.read().decode() if a2a_proc.stdout else "No output"
        raise RuntimeError(f"A2A server failed to start: {output}")
    
    print(f"✅ Servers running")
    return a2a_proc, mcp_proc


def stop_servers(a2a_proc: subprocess.Popen, mcp_proc: subprocess.Popen):
    """Stop servers gracefully."""
    print("\n🛑 Stopping servers...")
    a2a_proc.terminate()
    mcp_proc.terminate()
    a2a_proc.wait(timeout=5)
    mcp_proc.wait(timeout=5)
    print("✅ Servers stopped")


async def send_kickoff_to_green_agent(
    green_agent_url: str,
    purple_agent_url: str,
    task_file: str,
    task_ids: list[int] | None = None,
    max_turns: int = 30,
) -> dict:
    """
    Send kickoff message to Green Agent and wait for results.
    
    This is ALL that run.py does - one message to Green Agent!
    
    Green Agent then:
    1. Connects to Purple Agent
    2. Runs evaluation loop
    3. Returns results
    
    Args:
        green_agent_url: Green Agent's A2A URL (e.g., http://localhost:8090)
        purple_agent_url: Purple Agent's URL to evaluate
        task_file: Path to task definitions
        task_ids: Optional list of task indices
        max_turns: Max turns per task
        
    Returns:
        Evaluation results from Green Agent
    """
    print(f"\n📨 Sending kickoff to Green Agent...")
    print(f"   Green Agent: {green_agent_url}")
    print(f"   Purple Agent: {purple_agent_url}")
    print(f"   Task file: {task_file}")
    print(f"   Tasks: {task_ids or 'all'}")
    
    # Build kickoff message
    kickoff_config = {
        "purple_agent_url": purple_agent_url,
        "task_file": str(task_file),
        "max_turns": max_turns,
    }
    
    if task_ids:
        kickoff_config["task_ids"] = task_ids
    
    kickoff_message = f"<task_config>{json.dumps(kickoff_config)}</task_config>"
    
    # Build A2A message
    a2a_message = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "kickoff-1",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": kickoff_message}],
                "messageId": "kickoff-msg-1",
            },
            "configuration": {
                "acceptedOutputModes": ["text"],
            },
        },
    }
    
    # Send to Green Agent
    # Note: Green Agent will handle the entire evaluation and return when done
    # A2A SDK uses root endpoint (/) for JSON-RPC messages
    async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout for full eval
        response = await client.post(
            f"{green_agent_url.rstrip('/')}/",
            json=a2a_message,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
    
    # Parse result
    if "error" in result:
        return {"status": "error", "error": result["error"]}
    
    # A2A SDK format: result.result IS the message (not result.result.message)
    # Format: {"id": "...", "jsonrpc": "2.0", "result": {"kind": "message", "parts": [...], ...}}
    response_obj = result.get("result", {})
    parts = response_obj.get("parts", [])
    
    for part in parts:
        if isinstance(part, dict):
            # A2A SDK format: {"kind": "text", "text": "..."}
            text = part.get("text", "")
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"status": "completed", "raw_response": text}
    
    return {"status": "unknown", "raw": result}


def save_results(results: dict, config: dict):
    """Save results to file."""
    output_config = config.get("output", {})
    results_dir = Path(output_config.get("results_dir", "historical_trajectories"))
    results_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = results_dir / f"eval_{timestamp}.json"
    
    with open(filename, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {filename}")
    return filename


def print_summary(results: dict):
    """Print evaluation summary."""
    print(f"\n{'='*60}")
    print(f"📊 Evaluation Summary")
    print(f"{'='*60}")
    
    tasks = results.get("tasks", [])
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    total = len(tasks)
    
    print(f"   Agent: {results.get('purple_agent', 'unknown')}")
    print(f"   Completed: {completed}/{total}")
    
    total_score = 0
    for task in tasks:
        status_icon = "✅" if task.get("status") == "completed" else "❌"
        score = task.get("score", {}).get("total_score", 0)
        total_score += score
        print(f"   {status_icon} {task.get('task_id', '?')}: {score:.0%}")
    
    if total > 0:
        avg_score = total_score / total
        print(f"\n   📈 Average Score: {avg_score:.0%}")


def main():
    parser = argparse.ArgumentParser(
        description="AgentX Kickoff Script - Evaluate any A2A-compatible agent"
    )
    parser.add_argument("--config", default="scenario.toml", help="Config file path")
    parser.add_argument("--task", type=int, help="Run specific task ID")
    parser.add_argument("--tasks", help="Comma-separated task IDs (e.g., 0,1,2)")
    parser.add_argument("--max-turns", type=int, default=30, help="Max turns per task")
    parser.add_argument("--servers-only", action="store_true", help="Start servers only")
    parser.add_argument("--no-servers", action="store_true", help="Don't start servers")
    
    # Required arguments
    parser.add_argument(
        "--task-file", 
        required=True, 
        help="Path to task definitions JSONL file"
    )
    parser.add_argument(
        "--external-agent",
        required=True,
        help="URL of external A2A agent to evaluate (e.g., http://localhost:9000)"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Get ports from config
    a2a_port = config.get("server", {}).get("a2a_port", 8090)
    green_agent_url = f"http://localhost:{a2a_port}"
    
    # Determine task IDs
    task_ids = None
    if args.task is not None:
        task_ids = [args.task]
    elif args.tasks:
        task_ids = [int(t.strip()) for t in args.tasks.split(",")]
    
    # Resolve task file path
    task_file = Path(args.task_file)
    if not task_file.is_absolute():
        task_file = Path.cwd() / task_file
    
    print(f"\n{'='*60}")
    print(f"🧪 AgentX - A2A Agent Evaluator")
    print(f"{'='*60}")
    print(f"   Config: {args.config}")
    print(f"   Task File: {task_file}")
    print(f"   External Agent: {args.external_agent}")
    print(f"   Tasks: {task_ids or 'first 5'}")
    
    a2a_proc = mcp_proc = None
    
    try:
        # Start servers if needed
        if not args.no_servers:
            a2a_proc, mcp_proc = start_servers(config, str(task_file))
            
            if args.servers_only:
                print("\n⏳ Servers running. Press Ctrl+C to stop.")
                signal.signal(signal.SIGINT, lambda s, f: None)
                while True:
                    time.sleep(1)
        
        # === THE ONLY THING RUN.PY DOES ===
        # Send ONE kickoff message to Green Agent
        # Green Agent handles EVERYTHING else
        results = asyncio.run(
            send_kickoff_to_green_agent(
                green_agent_url=green_agent_url,
                purple_agent_url=args.external_agent,
                task_file=str(task_file),
                task_ids=task_ids,
                max_turns=args.max_turns,
            )
        )
        
        # Print summary
        print_summary(results)
        
        # Save results
        if config.get("output", {}).get("save_conversations", True):
            save_results(results, config)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
    
    except httpx.HTTPError as e:
        print(f"\n❌ HTTP Error: {e}")
        print("   Make sure both Green Agent and Purple Agent are running.")
    
    finally:
        if a2a_proc and mcp_proc:
            stop_servers(a2a_proc, mcp_proc)


if __name__ == "__main__":
    main()
