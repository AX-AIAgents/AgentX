#!/usr/bin/env python3
"""Quick import test for Purple Agent V2"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

print("🧪 Testing imports...")

try:
    from src.purple_agent.langgraph_agent import LangGraphAgentV2
    print("✅ LangGraphAgentV2 imported successfully")
except Exception as e:
    print(f"❌ Failed to import LangGraphAgentV2: {e}")
    sys.exit(1)

try:
    from src.purple_agent.executor import AdvancedPurpleExecutor
    print("✅ AdvancedPurpleExecutor imported successfully")
except Exception as e:
    print(f"❌ Failed to import AdvancedPurpleExecutor: {e}")
    sys.exit(1)

try:
    from src.purple_agent.agent import ModelConfig, RetryConfig, MemoryConfig
    print("✅ Config classes imported successfully")
except Exception as e:
    print(f"❌ Failed to import config classes: {e}")
    sys.exit(1)

print("\n✅ All imports successful!")
print("\n📊 Agent Configuration:")
print(f"   - LangGraph V2: Available")
print(f"   - Default timeout: 60s")
print(f"   - Temperature: 0.0")
print(f"   - Max retries: 2")
print("\n🚀 Ready for benchmarking!")
