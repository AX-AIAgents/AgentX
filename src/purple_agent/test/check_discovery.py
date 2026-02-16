"""
Check Agent Card Script
"""

import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv

# Add src to path just in case
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

load_dotenv()

async def check_agent_card():
    # Green agent endpoint
    endpoint = "http://localhost:8090" 
    
    print(f"🔍 Discovery: Checking {endpoint} ...")
    
    async with httpx.AsyncClient() as client:
        # 1. Try /.well-known/agent.json
        try:
            url = f"{endpoint}/.well-known/agent.json"
            print(f"   Getting: {url}")
            resp = await client.get(url)
            if resp.status_code == 200:
                print("✅ Found Agent Card:")
                print(resp.json())
            else:
                print(f"❌ Not found (HTTP {resp.status_code})")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

        # 2. Try root /
        # Sometimes key info is at root
        try:
            url = f"{endpoint}/"
            print(f"\n   Getting Root: {url}")
            resp = await client.post(url, json={"jsonrpc": "2.0", "method": "agent.info", "id": 1})
            # Or maybe just GET / for metadata?
            # Let's try simple GET first just to see server response
            resp_root = await client.get(url)
            print(f"   Root default response: {resp_root.status_code}")
        except Exception as e:
           pass

if __name__ == "__main__":
    asyncio.run(check_agent_card())
