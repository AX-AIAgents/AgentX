"""
Dataset Creator for Purple Agent Benchmarking.

This script creates a robust dataset in LangSmith designed to test
architectural changes in the agent. It focuses on multi-step,
cross-tool execution using the Green Agent's capabilities:
- YouTube
- Gmail
- Notion
- Search (Serper)
- Google Drive

Total Examples: 20
Categories:
1. Multi-Step Research (Search -> Notion)
2. Content Repurposing (YouTube -> Notion/Gmail)
3. Office Administration (Drive -> Gmail)
4. Complex Coordination (Search + Drive + Notion)
"""

import os
import uuid
from langsmith import Client
from dotenv import load_dotenv

load_dotenv()

DATASET_NAME = "purple-agent-benchmark-v1"
DESCRIPTION = "Benchmark for testing agentic architecture changes. Focuses on multi-tool consistency with gpt-4o-mini."

# -----------------------------------------------------------------------------
# Scenarios
# -----------------------------------------------------------------------------

examples = [
    # --- Category 1: Research & Documentation (Search -> Notion) ---
    {
        "inputs": {"text": "Search for the latest release features of LangChain v0.3. Create a new Notion page titled 'LangChain Updates' and list these features as bullet points."},
        "outputs": {"expected_tools": ["google_search", "API-post-page", "API-patch-block-children"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "notion"]}
    },
    {
        "inputs": {"text": "Find the current stock price of NVIDIA and its P/E ratio. Create a summary note in Notion titled 'Market Watch' with this data."},
        "outputs": {"expected_tools": ["google_search", "API-post-page"]},
        "metadata": {"difficulty": "easy", "domains": ["search", "notion"]}
    },
    {
        "inputs": {"text": "Research top 3 competitors to 'Perplexity AI'. Create a Notion page named 'Competitor Analysis' and write a brief comparison paragraph for each."},
        "outputs": {"expected_tools": ["google_search", "API-post-page"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "notion"]}
    },
    {
        "inputs": {"text": "Find upcoming AI conferences in San Francisco for Q3 2024. Save the list with dates and locations against a Notion page called 'Events'."},
        "outputs": {"expected_tools": ["google_search", "API-post-page"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "notion"]}
    },

    # --- Category 2: Content Repurposing (YouTube -> Notion/Gmail) ---
    {
        "inputs": {"text": "Get the transcript for the YouTube video with ID 'dQw4w9WgXcQ' (or search for 'Rick Astley Never Gonna Give You Up'). Summarize the lyrics in a Notion page titled 'Song Analysis'."},
        "outputs": {"expected_tools": ["get_transcript", "API-post-page"]},
        "metadata": {"difficulty": "medium", "domains": ["youtube", "notion"]}
    },
    {
        "inputs": {"text": "Search for 'Andrej Karpathy state of GPT' on YouTube. Get the transcript of his latest talk and email a 3-bullet point summary to 'boss@company.com' with subject 'Karpathy Summary'."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "send_email"]},
        "metadata": {"difficulty": "hard", "domains": ["search", "youtube", "gmail"]}
    },
    {
        "inputs": {"text": "Find a tutorial video on 'How to make sourdough bread' on YouTube. Create a Notion page 'Recipes' and paste the step-by-step transcript there."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "API-post-page"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "youtube", "notion"]}
    },
    {
        "inputs": {"text": "Analyze the sentiment of the YouTube video 'MKBHD iPhone Review'. If positive, email 'marketing@apple.com' saying 'Good review'; otherwise say 'Needs improvement'."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "send_email"]},
        "metadata": {"difficulty": "hard", "domains": ["youtube", "gmail"]}
    },

    # --- Category 3: Office Org (Drive -> Gmail/Notion) ---
    {
        "inputs": {"text": "List the files in my Google Drive to find 'Q1_Report.pdf'. Read its content (mock assumption) and email a summary to 'team@agentx.com'."},
        "outputs": {"expected_tools": ["listFolder", "getGoogleDocContent", "send_email"]},
        "metadata": {"difficulty": "medium", "domains": ["drive", "gmail"]}
    },
    {
        "inputs": {"text": "Search my Drive for 'Meeting Notes'. Find the most recent one, extract the action items, and create a new Notion task list page called 'Action Items'."},
        "outputs": {"expected_tools": ["listFolder", "getGoogleDocContent", "API-post-page"]},
        "metadata": {"difficulty": "hard", "domains": ["drive", "notion"]}
    },
    {
        "inputs": {"text": "Check my unread emails in Gmail. If there is an email from 'huseyin@example.com', create a Notion page with its content titled 'Urgent from Huseyin'."},
        "outputs": {"expected_tools": ["search_emails", "API-post-page"]},
        "metadata": {"difficulty": "medium", "domains": ["gmail", "notion"]}
    },
    {
        "inputs": {"text": "Find the document 'Project_Alpha_Specs' in Drive. Read the requirements section and search Google to see if any new technologies mentioned exist. Save results to Notion."},
        "outputs": {"expected_tools": ["listFolder", "getGoogleDocContent", "google_search", "API-post-page"]},
        "metadata": {"difficulty": "expert", "domains": ["drive", "search", "notion"]}
    },

    # --- Category 4: Complex Multi-Step (All Tools) ---
    {
        "inputs": {"text": "I need to plan a trip to Tokyo. Search for top 5 attractions. Find a YouTube video guide for the #1 attraction. Create a Notion page 'Tokyo Trip' with the list and the video summary. Finally, email the Notion page link to 'travel_buddy@email.com'."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "API-post-page", "send_email"]},
        "metadata": {"difficulty": "expert", "domains": ["search", "youtube", "notion", "gmail"]}
    },
    {
        "inputs": {"text": "Search Google for 'Python 3.13 release date'. Check my Gmail to see if I received any newsletters about 'Python updates'. If not, create a draft email to 'newsletter@python.org' asking to subscribe."},
        "outputs": {"expected_tools": ["google_search", "search_emails", "draft_email"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "gmail"]}
    },
    {
        "inputs": {"text": "Find the 'Budget_2024' sheet in Drive. Assume it says we are over budget. Search Google for 'cost cutting strategies for startups'. Create a Notion page 'Strategy' with 5 tips."},
        "outputs": {"expected_tools": ["listFolder", "getGoogleSheetContent", "google_search", "API-post-page"]},
        "metadata": {"difficulty": "hard", "domains": ["drive", "search", "notion"]}
    },
    {
        "inputs": {"text": "Who is currently the CEO of OpenAI? Search Google. Then search YouTube for their latest interview. Create a Notion page with their Bio and a key quote from the interview."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "API-post-page"]},
        "metadata": {"difficulty": "hard", "domains": ["search", "youtube", "notion"]}
    },
    {
        "inputs": {"text": "Search for 'Agentic patterns'. Create a Notion page. Then search for 'LangGraph' and append a summary of it to the SAME Notion page."},
        "outputs": {"expected_tools": ["google_search", "API-post-page", "API-patch-block-children"]},
        "metadata": {"difficulty": "medium", "domains": ["search", "notion"]}
    },
    {
        "inputs": {"text": "I lost the link to the 'Quarterly Review' doc. Search my Drive for it. Copy the content. Create an email to 'manager@corp.com' with the content as body and subject 'Here is the review'."},
        "outputs": {"expected_tools": ["listFolder", "getGoogleDocContent", "send_email"]},
        "metadata": {"difficulty": "medium", "domains": ["drive", "gmail"]}
    },
    {
        "inputs": {"text": "Search Google for the weather in London today. If it's raining (simulate logic), search YouTube for 'indoor activities London'. Save 3 ideas to Notion."},
        "outputs": {"expected_tools": ["google_search", "get_transcript", "API-post-page"]},
        "metadata": {"difficulty": "hard", "domains": ["search", "youtube", "notion"]}
    },
    {
        "inputs": {"text": "Full audit: Check last 3 emails from Gmail. List last 3 files in Drive. Create a Notion page 'Daily Audit' listing the subjects of emails and names of files."},
        "outputs": {"expected_tools": ["search_emails", "listFolder", "API-post-page"]},
        "metadata": {"difficulty": "hard", "domains": ["gmail", "drive", "notion"]}
    }
]

def create_dataset():
    client = Client()
    
    print(f"🚀 Creating/Updating dataset: {DATASET_NAME}")
    
    # Create or get dataset
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"   Dataset exists. Fetching...")
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        print(f"   Creating new dataset...")
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description=DESCRIPTION
        )

    # Prepare examples
    inputs = [e["inputs"] for e in examples]
    outputs = [e["outputs"] for e in examples]
    metadatas = [e["metadata"] for e in examples]

    # Add examples (LangSmith handles deduplication/versions usually, 
    # but for clean slate usually best to create new name or delete old examples if iterating)
    client.create_examples(
        inputs=inputs,
        outputs=outputs,
        metadata=metadatas,
        dataset_id=dataset.id
    )
    
    print(f"✅ Successfully added {len(examples)} examples to '{DATASET_NAME}'")
    print(f"   URL: {dataset.url}")

if __name__ == "__main__":
    create_dataset()
