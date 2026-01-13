"""
Mock Tools - Simulated tool responses for testing.

When MOCK_MODE=true, tool calls return simulated successful responses
without connecting to real APIs. This enables:
- Testing without API keys
- Faster evaluation runs
- Consistent reproducible results
- 100% success rate for validation

STATE-AWARE MOCK SYSTEM:
- Reads from initial_state in task definition
- Updates running_state as tools are called
- Enables proper state_match scoring
"""
import json
import uuid
import copy
from datetime import datetime
from typing import Any


# ============== State Manager ==============

class MockStateManager:
    """
    Manages state for mock tool execution.
    
    - Initialized with task's initial_state
    - Tool calls read from and update state
    - Final state used for scoring
    """
    
    _instance = None
    
    def __init__(self):
        self.initial_state: dict[str, Any] = {}
        self.running_state: dict[str, Any] = {}
        self.tool_history: list[dict[str, Any]] = []
    
    @classmethod
    def get_instance(cls) -> "MockStateManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def initialize(self, initial_state: dict[str, Any]) -> None:
        """Initialize state from task definition."""
        self.initial_state = copy.deepcopy(initial_state)
        self.running_state = copy.deepcopy(initial_state)
        self.tool_history = []
    
    def reset(self) -> None:
        """Reset to initial state."""
        self.running_state = copy.deepcopy(self.initial_state)
        self.tool_history = []
    
    def get_state(self, domain: str) -> dict[str, Any]:
        """Get state for a specific domain."""
        return self.running_state.get(domain, {})
    
    def update_state(self, domain: str, key: str, value: Any, operation: str = "append") -> None:
        """Update state for a domain."""
        if domain not in self.running_state:
            self.running_state[domain] = {}
        
        if operation == "append":
            if key not in self.running_state[domain]:
                self.running_state[domain][key] = []
            self.running_state[domain][key].append(value)
        elif operation == "set":
            self.running_state[domain][key] = value
        elif operation == "extend":
            if key not in self.running_state[domain]:
                self.running_state[domain][key] = []
            self.running_state[domain][key].extend(value)
    
    def record_tool_call(self, tool_name: str, args: dict, result: Any) -> None:
        """Record a tool call for history."""
        self.tool_history.append({
            "tool": tool_name,
            "arguments": args,
            "result": result,
            "timestamp": generate_mock_timestamp(),
        })
    
    def get_final_state(self) -> dict[str, Any]:
        """Get the current running state (for scoring)."""
        return copy.deepcopy(self.running_state)
    
    def get_tool_history(self) -> list[dict[str, Any]]:
        """Get tool call history."""
        return self.tool_history.copy()


# Global state manager instance
_state_manager = MockStateManager.get_instance()


def init_mock_state(initial_state: dict[str, Any]) -> None:
    """Initialize mock state from task's initial_state."""
    _state_manager.initialize(initial_state)


def reset_mock_state() -> None:
    """Reset mock state."""
    _state_manager.reset()


def get_mock_final_state() -> dict[str, Any]:
    """Get final state for scoring."""
    return _state_manager.get_final_state()


def get_mock_tool_history() -> list[dict[str, Any]]:
    """Get tool call history."""
    return _state_manager.get_tool_history()


# ============== Mock Response Generators ==============

def generate_mock_id() -> str:
    """Generate a realistic-looking ID."""
    return str(uuid.uuid4())[:8]


def generate_mock_timestamp() -> str:
    """Generate current timestamp."""
    return datetime.now().isoformat()


# ============== Notion Mock Responses ==============

NOTION_MOCK_RESPONSES = {
    "API-post-search": lambda args: {
        "object": "list",
        "results": [
            {
                "id": f"page-{generate_mock_id()}",
                "object": "page",
                "created_time": generate_mock_timestamp(),
                "last_edited_time": generate_mock_timestamp(),
                "properties": {
                    "title": {
                        "title": [{"text": {"content": args.get("query", "Search Result")}}]
                    }
                },
                "url": f"https://notion.so/page-{generate_mock_id()}"
            }
        ],
        "has_more": False,
        "next_cursor": None
    },
    
    "API-get-page": lambda args: {
        "id": args.get("page_id", f"page-{generate_mock_id()}"),
        "object": "page",
        "created_time": generate_mock_timestamp(),
        "last_edited_time": generate_mock_timestamp(),
        "properties": {
            "title": {
                "title": [{"text": {"content": "Mock Page Title"}}]
            }
        },
        "url": f"https://notion.so/{args.get('page_id', 'mock-page')}"
    },
    
    "API-patch-block-children": lambda args: {
        "object": "list",
        "results": [
            {
                "id": f"block-{generate_mock_id()}",
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": "Block added successfully"}}]
                }
            }
        ],
        "has_more": False
    },
    
    "API-get-self": lambda args: {
        "object": "user",
        "id": f"user-{generate_mock_id()}",
        "name": "Mock User",
        "type": "person",
        "person": {"email": "mockuser@example.com"}
    },
    
    "API-get-block": lambda args: {
        "id": args.get("block_id", f"block-{generate_mock_id()}"),
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"text": {"content": "Mock block content"}}]
        }
    },
    
    "API-get-block-children": lambda args: {
        "object": "list",
        "results": [
            {
                "id": f"block-{generate_mock_id()}",
                "object": "block",
                "type": "paragraph"
            }
        ],
        "has_more": False
    },
    
    "API-post-page": lambda args: {
        "id": f"page-{generate_mock_id()}",
        "object": "page",
        "created_time": generate_mock_timestamp(),
        "url": f"https://notion.so/page-{generate_mock_id()}"
    },
    
    "API-patch-page": lambda args: {
        "id": args.get("page_id", f"page-{generate_mock_id()}"),
        "object": "page",
        "last_edited_time": generate_mock_timestamp()
    },
    
    "API-delete-block": lambda args: {
        "id": args.get("block_id", f"block-{generate_mock_id()}"),
        "object": "block",
        "archived": True
    },
    
    "API-get-database": lambda args: {
        "id": args.get("database_id", f"db-{generate_mock_id()}"),
        "object": "database",
        "title": [{"text": {"content": "Mock Database"}}]
    },
    
    "API-post-database-query": lambda args: {
        "object": "list",
        "results": [
            {
                "id": f"page-{generate_mock_id()}",
                "object": "page",
                "properties": {}
            }
        ],
        "has_more": False
    },
    
    # Additional Notion tools
    "API-retrieve-a-block": lambda args: {
        "id": args.get("block_id", f"block-{generate_mock_id()}"),
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"text": {"content": "Mock block content"}}]}
    },
    
    "API-update-a-block": lambda args: {
        "id": args.get("block_id", f"block-{generate_mock_id()}"),
        "object": "block",
        "last_edited_time": generate_mock_timestamp()
    },
    
    "API-delete-a-block": lambda args: {
        "id": args.get("block_id", f"block-{generate_mock_id()}"),
        "archived": True
    },
    
    "API-retrieve-a-page": lambda args: {
        "id": args.get("page_id", f"page-{generate_mock_id()}"),
        "object": "page",
        "properties": {"title": {"title": [{"text": {"content": "Mock Page"}}]}}
    },
    
    "API-retrieve-a-page-property": lambda args: {
        "object": "property_item",
        "id": args.get("property_id", "prop-id"),
        "type": "title",
        "title": {"text": {"content": "Mock Property Value"}}
    },
    
    "API-move-page": lambda args: {
        "id": args.get("page_id", f"page-{generate_mock_id()}"),
        "object": "page",
        "parent": {"page_id": args.get("parent_id", f"parent-{generate_mock_id()}")}
    },
    
    "API-get-user": lambda args: {
        "object": "user",
        "id": args.get("user_id", f"user-{generate_mock_id()}"),
        "name": "Mock User",
        "type": "person"
    },
    
    "API-get-users": lambda args: {
        "object": "list",
        "results": [
            {"id": f"user-{generate_mock_id()}", "name": "User 1", "type": "person"},
            {"id": f"user-{generate_mock_id()}", "name": "User 2", "type": "person"}
        ]
    },
    
    "API-create-a-comment": lambda args: {
        "id": f"comment-{generate_mock_id()}",
        "object": "comment",
        "created_time": generate_mock_timestamp(),
        "rich_text": [{"text": {"content": args.get("text", "Mock comment")}}]
    },
    
    "API-retrieve-a-comment": lambda args: {
        "id": args.get("comment_id", f"comment-{generate_mock_id()}"),
        "object": "comment",
        "rich_text": [{"text": {"content": "Mock comment content"}}]
    },
    
    "API-create-a-data-source": lambda args: {
        "id": f"ds-{generate_mock_id()}",
        "object": "data_source",
        "name": args.get("name", "Mock Data Source")
    },
    
    "API-retrieve-a-data-source": lambda args: {
        "id": args.get("data_source_id", f"ds-{generate_mock_id()}"),
        "object": "data_source",
        "name": "Mock Data Source"
    },
    
    "API-update-a-data-source": lambda args: {
        "id": args.get("data_source_id", f"ds-{generate_mock_id()}"),
        "object": "data_source",
        "last_edited_time": generate_mock_timestamp()
    },
    
    "API-query-data-source": lambda args: {
        "object": "list",
        "results": [{"id": f"item-{generate_mock_id()}", "data": {"field": "value"}}]
    },
    
    "API-list-data-source-templates": lambda args: {
        "object": "list",
        "results": [
            {"id": "template-1", "name": "Template 1"},
            {"id": "template-2", "name": "Template 2"}
        ]
    },
}


# ============== Gmail Mock Responses ==============

GMAIL_MOCK_RESPONSES = {
    "send_email": lambda args: {
        "success": True,
        "message_id": f"msg-{generate_mock_id()}",
        "thread_id": f"thread-{generate_mock_id()}",
        "to": args.get("to", "recipient@example.com"),
        "subject": args.get("subject", "No Subject"),
        "status": "sent"
    },
    
    "draft_email": lambda args: {
        "success": True,
        "draft_id": f"draft-{generate_mock_id()}",
        "message": {
            "to": args.get("to", "recipient@example.com"),
            "subject": args.get("subject", "Draft Subject")
        }
    },
    
    "read_email": lambda args: {
        "id": args.get("message_id", f"msg-{generate_mock_id()}"),
        "thread_id": f"thread-{generate_mock_id()}",
        "from": "sender@example.com",
        "to": "you@example.com",
        "subject": "Mock Email Subject",
        "body": "This is a mock email body for testing purposes.",
        "date": generate_mock_timestamp()
    },
    
    "search_emails": lambda args: {
        "results": [
            {
                "id": f"msg-{generate_mock_id()}",
                "thread_id": f"thread-{generate_mock_id()}",
                "subject": f"Email matching: {args.get('query', 'search')}",
                "from": "sender@example.com",
                "date": generate_mock_timestamp(),
                "snippet": "This is a preview of the email content..."
            }
        ],
        "total": 1
    },
    
    "modify_email": lambda args: {
        "id": args.get("message_id", f"msg-{generate_mock_id()}"),
        "labels": args.get("labels", ["INBOX"]),
        "modified": True
    },
    
    "delete_email": lambda args: {
        "id": args.get("message_id", f"msg-{generate_mock_id()}"),
        "deleted": True
    },
    
    "list_email_labels": lambda args: {
        "labels": [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "SENT", "name": "SENT", "type": "system"},
            {"id": "DRAFT", "name": "DRAFT", "type": "system"},
            {"id": "STARRED", "name": "STARRED", "type": "system"},
        ]
    },
    
    # Additional Gmail tools
    "batch_delete_emails": lambda args: {
        "success": True,
        "deleted_count": len(args.get("message_ids", [])),
        "message_ids": args.get("message_ids", [])
    },
    
    "batch_modify_emails": lambda args: {
        "success": True,
        "modified_count": len(args.get("message_ids", [])),
        "labels_added": args.get("add_labels", []),
        "labels_removed": args.get("remove_labels", [])
    },
    
    "create_label": lambda args: {
        "id": f"label-{generate_mock_id()}",
        "name": args.get("name", "New Label"),
        "type": "user"
    },
    
    "update_label": lambda args: {
        "id": args.get("label_id", f"label-{generate_mock_id()}"),
        "name": args.get("name", "Updated Label"),
        "updated": True
    },
    
    "delete_label": lambda args: {
        "id": args.get("label_id", f"label-{generate_mock_id()}"),
        "deleted": True
    },
    
    "get_or_create_label": lambda args: {
        "id": f"label-{generate_mock_id()}",
        "name": args.get("name", "Label"),
        "created": True
    },
    
    "create_filter": lambda args: {
        "id": f"filter-{generate_mock_id()}",
        "criteria": args.get("criteria", {}),
        "action": args.get("action", {})
    },
    
    "create_filter_from_template": lambda args: {
        "id": f"filter-{generate_mock_id()}",
        "template": args.get("template", "default"),
        "created": True
    },
    
    "get_filter": lambda args: {
        "id": args.get("filter_id", f"filter-{generate_mock_id()}"),
        "criteria": {"from": "example@email.com"},
        "action": {"addLabelIds": ["IMPORTANT"]}
    },
    
    "list_filters": lambda args: {
        "filters": [
            {"id": f"filter-{generate_mock_id()}", "criteria": {"from": "a@b.com"}},
            {"id": f"filter-{generate_mock_id()}", "criteria": {"subject": "urgent"}}
        ]
    },
    
    "delete_filter": lambda args: {
        "id": args.get("filter_id", f"filter-{generate_mock_id()}"),
        "deleted": True
    },
    
    "download_attachment": lambda args: {
        "attachment_id": args.get("attachment_id", f"att-{generate_mock_id()}"),
        "filename": args.get("filename", "attachment.pdf"),
        "size": 1024,
        "downloaded": True,
        "path": f"/tmp/{args.get('filename', 'attachment.pdf')}"
    },
}


# ============== Search Mock Responses ==============

SEARCH_MOCK_RESPONSES = {
    "google_search": lambda args: {
        "searchParameters": {
            "q": args.get("query", args.get("q", "search query")),
            "type": "search"
        },
        "organic": [
            {
                "title": f"Result 1 for: {args.get('query', args.get('q', 'query'))}",
                "link": "https://example.com/result1",
                "snippet": "This is a relevant search result for your query...",
                "position": 1
            },
            {
                "title": f"Result 2 for: {args.get('query', args.get('q', 'query'))}",
                "link": "https://example.com/result2",
                "snippet": "Another relevant result with useful information...",
                "position": 2
            },
            {
                "title": f"Result 3 for: {args.get('query', args.get('q', 'query'))}",
                "link": "https://example.com/result3",
                "snippet": "Third result with additional details...",
                "position": 3
            }
        ],
        "credits": 1
    },
    
    "scrape": lambda args: {
        "url": args.get("url", "https://example.com"),
        "title": "Mock Page Title",
        "content": "This is the scraped content of the page. It contains relevant information about the topic.",
        "metadata": {
            "author": "Mock Author",
            "date": generate_mock_timestamp()
        }
    },
}


# ============== YouTube Mock Responses ==============

YOUTUBE_MOCK_RESPONSES = {
    "get_transcript": lambda args: {
        "video_id": args.get("video_id", args.get("url", "dQw4w9WgXcQ")),
        "transcript": "This is a mock transcript of the video. It contains the spoken content. The video discusses various topics relevant to the query.",
        "language": "en"
    },
    
    "get_timed_transcript": lambda args: {
        "video_id": args.get("video_id", args.get("url", "dQw4w9WgXcQ")),
        "segments": [
            {"start": 0.0, "duration": 5.0, "text": "Welcome to this video."},
            {"start": 5.0, "duration": 5.0, "text": "Today we'll discuss important topics."},
            {"start": 10.0, "duration": 5.0, "text": "Let's get started with the main content."},
        ],
        "language": "en"
    },
    
    "get_video_info": lambda args: {
        "video_id": args.get("video_id", args.get("url", "dQw4w9WgXcQ")),
        "title": "Mock Video Title",
        "channel": "Mock Channel",
        "description": "This is a mock video description for testing purposes.",
        "duration": "10:30",
        "views": 1000000,
        "likes": 50000,
        "published_at": generate_mock_timestamp()
    },
}


# ============== Google Drive Mock Responses ==============

DRIVE_MOCK_RESPONSES = {
    "list_files": lambda args: {
        "files": [
            {
                "id": f"file-{generate_mock_id()}",
                "name": "Document 1.docx",
                "mimeType": "application/vnd.google-apps.document"
            },
            {
                "id": f"file-{generate_mock_id()}",
                "name": "Spreadsheet 1.xlsx",
                "mimeType": "application/vnd.google-apps.spreadsheet"
            }
        ],
        "nextPageToken": None
    },
    
    "search": lambda args: {
        "files": [
            {
                "id": f"file-{generate_mock_id()}",
                "name": f"File matching: {args.get('query', 'search')}",
                "mimeType": "application/vnd.google-apps.document"
            }
        ]
    },
    
    "get_file": lambda args: {
        "id": args.get("file_id", f"file-{generate_mock_id()}"),
        "name": "Mock File.docx",
        "mimeType": "application/vnd.google-apps.document",
        "content": "This is the content of the mock file."
    },
    
    "create_file": lambda args: {
        "id": f"file-{generate_mock_id()}",
        "name": args.get("name", "New File"),
        "mimeType": args.get("mimeType", "application/vnd.google-apps.document"),
        "webViewLink": f"https://docs.google.com/document/d/{generate_mock_id()}"
    },
    
    "update_file": lambda args: {
        "id": args.get("file_id", f"file-{generate_mock_id()}"),
        "name": args.get("name", "Updated File"),
        "modifiedTime": generate_mock_timestamp()
    },
    
    "delete_file": lambda args: {
        "id": args.get("file_id", f"file-{generate_mock_id()}"),
        "deleted": True
    },
    
    # Additional Google Drive tools
    "createFolder": lambda args: {
        "id": f"folder-{generate_mock_id()}",
        "name": args.get("name", "New Folder"),
        "mimeType": "application/vnd.google-apps.folder",
        "webViewLink": f"https://drive.google.com/drive/folders/{generate_mock_id()}"
    },
    
    "listFolder": lambda args: {
        "files": [
            {"id": f"file-{generate_mock_id()}", "name": "File 1.docx"},
            {"id": f"file-{generate_mock_id()}", "name": "File 2.xlsx"},
        ],
        "folders": [
            {"id": f"folder-{generate_mock_id()}", "name": "Subfolder"}
        ]
    },
    
    "moveItem": lambda args: {
        "id": args.get("item_id", f"item-{generate_mock_id()}"),
        "newParent": args.get("destination", f"folder-{generate_mock_id()}"),
        "moved": True
    },
    
    "renameItem": lambda args: {
        "id": args.get("item_id", f"item-{generate_mock_id()}"),
        "name": args.get("new_name", "Renamed Item"),
        "renamed": True
    },
    
    "deleteItem": lambda args: {
        "id": args.get("item_id", f"item-{generate_mock_id()}"),
        "deleted": True
    },
    
    "createTextFile": lambda args: {
        "id": f"file-{generate_mock_id()}",
        "name": args.get("name", "text.txt"),
        "content": args.get("content", ""),
        "mimeType": "text/plain"
    },
    
    "updateTextFile": lambda args: {
        "id": args.get("file_id", f"file-{generate_mock_id()}"),
        "updated": True,
        "modifiedTime": generate_mock_timestamp()
    },
    
    # Google Docs
    "createGoogleDoc": lambda args: {
        "id": f"doc-{generate_mock_id()}",
        "name": args.get("name", "New Document"),
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": f"https://docs.google.com/document/d/{generate_mock_id()}"
    },
    
    "getGoogleDocContent": lambda args: {
        "id": args.get("doc_id", f"doc-{generate_mock_id()}"),
        "title": "Mock Document",
        "content": "This is the mock document content.",
        "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Mock text"}}]}}]}
    },
    
    "updateGoogleDoc": lambda args: {
        "id": args.get("doc_id", f"doc-{generate_mock_id()}"),
        "updated": True,
        "revisionId": generate_mock_id()
    },
    
    "formatGoogleDocText": lambda args: {
        "id": args.get("doc_id", f"doc-{generate_mock_id()}"),
        "formatted": True,
        "style": args.get("style", {})
    },
    
    "formatGoogleDocParagraph": lambda args: {
        "id": args.get("doc_id", f"doc-{generate_mock_id()}"),
        "formatted": True,
        "paragraphStyle": args.get("style", {})
    },
    
    # Google Sheets
    "createGoogleSheet": lambda args: {
        "id": f"sheet-{generate_mock_id()}",
        "name": args.get("name", "New Spreadsheet"),
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "webViewLink": f"https://docs.google.com/spreadsheets/d/{generate_mock_id()}"
    },
    
    "getGoogleSheetContent": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "sheets": [{"properties": {"title": "Sheet1"}, "data": []}],
        "values": [["A1", "B1"], ["A2", "B2"]]
    },
    
    "updateGoogleSheet": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "updatedCells": args.get("values", [[]]).__len__(),
        "updated": True
    },
    
    "formatGoogleSheetCells": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "formatted": True,
        "range": args.get("range", "A1:Z100")
    },
    
    "formatGoogleSheetText": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "formatted": True
    },
    
    "formatGoogleSheetNumbers": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "formatted": True,
        "numberFormat": args.get("format", "NUMBER")
    },
    
    "mergeGoogleSheetCells": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "merged": True,
        "range": args.get("range", "A1:B2")
    },
    
    "setGoogleSheetBorders": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "borders_set": True,
        "range": args.get("range", "A1:Z100")
    },
    
    "addGoogleSheetConditionalFormat": lambda args: {
        "id": args.get("spreadsheet_id", f"sheet-{generate_mock_id()}"),
        "rule_added": True,
        "rule_id": generate_mock_id()
    },
    
    # Google Slides
    "createGoogleSlides": lambda args: {
        "id": f"slides-{generate_mock_id()}",
        "name": args.get("name", "New Presentation"),
        "mimeType": "application/vnd.google-apps.presentation",
        "webViewLink": f"https://docs.google.com/presentation/d/{generate_mock_id()}"
    },
    
    "getGoogleSlidesContent": lambda args: {
        "id": args.get("presentation_id", f"slides-{generate_mock_id()}"),
        "title": "Mock Presentation",
        "slides": [{"objectId": f"slide-{generate_mock_id()}", "pageElements": []}]
    },
    
    "updateGoogleSlides": lambda args: {
        "id": args.get("presentation_id", f"slides-{generate_mock_id()}"),
        "updated": True,
        "replies": []
    },
    
    "createGoogleSlidesTextBox": lambda args: {
        "objectId": f"textbox-{generate_mock_id()}",
        "created": True,
        "text": args.get("text", "")
    },
    
    "createGoogleSlidesShape": lambda args: {
        "objectId": f"shape-{generate_mock_id()}",
        "created": True,
        "shapeType": args.get("shape_type", "RECTANGLE")
    },
    
    "formatGoogleSlidesText": lambda args: {
        "id": args.get("presentation_id", f"slides-{generate_mock_id()}"),
        "formatted": True
    },
    
    "formatGoogleSlidesParagraph": lambda args: {
        "id": args.get("presentation_id", f"slides-{generate_mock_id()}"),
        "formatted": True
    },
    
    "setGoogleSlidesBackground": lambda args: {
        "id": args.get("presentation_id", f"slides-{generate_mock_id()}"),
        "background_set": True,
        "color": args.get("color", "#FFFFFF")
    },
    
    "styleGoogleSlidesShape": lambda args: {
        "objectId": args.get("object_id", f"shape-{generate_mock_id()}"),
        "styled": True
    },
}


# ============== All Mock Responses ==============

ALL_MOCK_RESPONSES = {
    **NOTION_MOCK_RESPONSES,
    **GMAIL_MOCK_RESPONSES,
    **SEARCH_MOCK_RESPONSES,
    **YOUTUBE_MOCK_RESPONSES,
    **DRIVE_MOCK_RESPONSES,
}


# ============== State-Aware Tool Categories ==============

# Define which tools read from state vs which create new data
# COMPLETE LIST OF ALL 76 TOOLS categorized

STATE_READERS = {
    # ===== NOTION (27 tools) =====
    "API-get-users": ("notion", "users"),
    "API-get-user": ("notion", "users"),
    "API-get-self": ("notion", "current_user"),
    "API-get-page": ("notion", "pages"),
    "API-retrieve-a-page": ("notion", "pages"),
    "API-retrieve-a-page-property": ("notion", "pages"),
    "API-get-block": ("notion", "blocks"),
    "API-get-block-children": ("notion", "blocks"),
    "API-retrieve-a-block": ("notion", "blocks"),
    "API-get-database": ("notion", "databases"),
    "API-post-database-query": ("notion", "databases"),
    "API-post-search": ("notion", "search_results"),
    "API-retrieve-a-comment": ("notion", "comments"),
    "API-retrieve-a-data-source": ("notion", "data_sources"),
    "API-query-data-source": ("notion", "data_sources"),
    "API-list-data-source-templates": ("notion", "data_source_templates"),
    
    # ===== GMAIL (18 tools) =====
    "read_email": ("gmail", "emails"),
    "search_emails": ("gmail", "emails"),
    "list_email_labels": ("gmail", "labels"),
    "list_filters": ("gmail", "filters"),
    "get_filter": ("gmail", "filters"),
    "download_attachment": ("gmail", "attachments"),
    
    # ===== GOOGLE DRIVE (26 tools) =====
    "list_files": ("google-drive", "files"),
    "listFolder": ("google-drive", "folders"),
    "search": ("google-drive", "search_results"),
    "get_file": ("google-drive", "files"),
    "getGoogleDocContent": ("google-drive", "docs"),
    "getGoogleSheetContent": ("google-drive", "sheets"),
    "getGoogleSlidesContent": ("google-drive", "slides"),
    
    # ===== SEARCH (2 tools) =====
    "google_search": ("search", "results"),
    "scrape": ("search", "scraped_pages"),
    
    # ===== YOUTUBE (3 tools) =====
    "get_video_info": ("youtube", "video_info"),
    "get_transcript": ("youtube", "transcripts"),
    "get_timed_transcript": ("youtube", "timed_transcripts"),
}

STATE_WRITERS = {
    # ===== GMAIL - write operations =====
    "send_email": ("gmail", "sent"),
    "draft_email": ("gmail", "drafts"),
    "modify_email": ("gmail", "modified"),
    "delete_email": ("gmail", "deleted"),
    "batch_delete_emails": ("gmail", "deleted"),
    "batch_modify_emails": ("gmail", "modified"),
    "create_label": ("gmail", "labels"),
    "update_label": ("gmail", "labels"),
    "delete_label": ("gmail", "deleted_labels"),
    "get_or_create_label": ("gmail", "labels"),
    "create_filter": ("gmail", "filters"),
    "create_filter_from_template": ("gmail", "filters"),
    "delete_filter": ("gmail", "deleted_filters"),
    
    # ===== NOTION - write operations =====
    "API-post-page": ("notion", "pages"),
    "API-patch-page": ("notion", "pages"),
    "API-move-page": ("notion", "pages"),
    "API-patch-block-children": ("notion", "blocks"),
    "API-update-a-block": ("notion", "blocks"),
    "API-delete-block": ("notion", "deleted_blocks"),
    "API-delete-a-block": ("notion", "deleted_blocks"),
    "API-create-a-comment": ("notion", "comments"),
    "API-create-a-data-source": ("notion", "data_sources"),
    "API-update-a-data-source": ("notion", "data_sources"),
    
    # ===== GOOGLE DRIVE - write operations =====
    "create_file": ("google-drive", "files"),
    "createTextFile": ("google-drive", "files"),
    "update_file": ("google-drive", "files"),
    "updateTextFile": ("google-drive", "files"),
    "createFolder": ("google-drive", "folders"),
    "moveItem": ("google-drive", "moved"),
    "renameItem": ("google-drive", "renamed"),
    "delete_file": ("google-drive", "deleted"),
    "deleteItem": ("google-drive", "deleted"),
    "createGoogleDoc": ("google-drive", "docs"),
    "updateGoogleDoc": ("google-drive", "docs"),
    "formatGoogleDocText": ("google-drive", "docs"),
    "formatGoogleDocParagraph": ("google-drive", "docs"),
    "createGoogleSheet": ("google-drive", "sheets"),
    "updateGoogleSheet": ("google-drive", "sheets"),
    "formatGoogleSheetCells": ("google-drive", "sheets"),
    "formatGoogleSheetText": ("google-drive", "sheets"),
    "formatGoogleSheetNumbers": ("google-drive", "sheets"),
    "mergeGoogleSheetCells": ("google-drive", "sheets"),
    "setGoogleSheetBorders": ("google-drive", "sheets"),
    "addGoogleSheetConditionalFormat": ("google-drive", "sheets"),
    "createGoogleSlides": ("google-drive", "slides"),
    "updateGoogleSlides": ("google-drive", "slides"),
    "createGoogleSlidesTextBox": ("google-drive", "slides"),
    "createGoogleSlidesShape": ("google-drive", "slides"),
    "formatGoogleSlidesText": ("google-drive", "slides"),
    "formatGoogleSlidesParagraph": ("google-drive", "slides"),
    "setGoogleSlidesBackground": ("google-drive", "slides"),
    "styleGoogleSlidesShape": ("google-drive", "slides"),
}


# ============== Mock Tool Executor ==============

def get_mock_response(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Get a mock response for a tool call.
    
    Args:
        tool_name: Name of the tool
        arguments: Tool arguments
        
    Returns:
        Mock response dict
    """
    global _state_manager
    
    # Check if this tool reads from initial_state
    if tool_name in STATE_READERS:
        domain, key = STATE_READERS[tool_name]
        state_data = _state_manager.get_state(domain).get(key, [])
        
        # If we have data in initial_state, use it
        if state_data:
            result = _create_state_aware_response(tool_name, arguments, state_data)
            _state_manager.record_tool_call(tool_name, arguments, result)
            return result
    
    # Generate mock response
    if tool_name in ALL_MOCK_RESPONSES:
        generator = ALL_MOCK_RESPONSES[tool_name]
        result = generator(arguments)
    else:
        # Generic fallback for unknown tools
        result = {
            "success": True,
            "tool": tool_name,
            "arguments_received": arguments,
            "message": f"Mock response for {tool_name}",
            "id": generate_mock_id(),
            "timestamp": generate_mock_timestamp()
        }
    
    # Update state if this is a write operation
    if tool_name in STATE_WRITERS:
        domain, key = STATE_WRITERS[tool_name]
        _update_state_from_result(domain, key, tool_name, arguments, result)
    
    # Record tool call
    _state_manager.record_tool_call(tool_name, arguments, result)
    
    return result


def _create_state_aware_response(tool_name: str, args: dict, state_data: list | dict) -> dict:
    """Create response using data from initial_state."""
    
    if tool_name == "API-get-users":
        # Return users from initial_state
        return {
            "object": "list",
            "results": state_data if isinstance(state_data, list) else [state_data],
            "has_more": False
        }
    
    elif tool_name == "API-get-user":
        # Find specific user by ID or return first
        user_id = args.get("user_id")
        if user_id and isinstance(state_data, list):
            user = next((u for u in state_data if u.get("id") == user_id), state_data[0] if state_data else None)
        else:
            user = state_data[0] if isinstance(state_data, list) and state_data else state_data
        return user or {"object": "user", "id": generate_mock_id(), "name": "Unknown User"}
    
    elif tool_name in ("API-get-page", "API-retrieve-a-page"):
        page_id = args.get("page_id")
        if page_id and isinstance(state_data, list):
            page = next((p for p in state_data if p.get("id") == page_id), state_data[0] if state_data else None)
        else:
            page = state_data[0] if isinstance(state_data, list) and state_data else state_data
        return page or ALL_MOCK_RESPONSES.get(tool_name, lambda a: {})(args)
    
    elif tool_name == "search_emails":
        # Return emails from state
        return {
            "results": state_data if isinstance(state_data, list) else [state_data],
            "total": len(state_data) if isinstance(state_data, list) else 1
        }
    
    elif tool_name == "get_transcript":
        return {
            "video_id": args.get("video_id", "mock-video"),
            "transcript": state_data[0].get("transcript", "Mock transcript") if state_data else "Mock transcript",
            "language": "en"
        }
    
    # Default: return state data wrapped appropriately
    if isinstance(state_data, list):
        return {"results": state_data, "count": len(state_data)}
    return state_data


def _update_state_from_result(domain: str, key: str, tool_name: str, args: dict, result: dict) -> None:
    """Update running state based on tool result."""
    global _state_manager
    
    if tool_name == "send_email":
        email_record = {
            "id": result.get("message_id", generate_mock_id()),
            "to": args.get("to", args.get("recipient", "")),
            "subject": args.get("subject", ""),
            "body": args.get("body", args.get("content", "")),
            "timestamp": generate_mock_timestamp(),
        }
        _state_manager.update_state(domain, key, email_record, "append")
    
    elif tool_name == "draft_email":
        draft_record = {
            "id": result.get("draft_id", generate_mock_id()),
            "to": args.get("to", ""),
            "subject": args.get("subject", ""),
            "body": args.get("body", ""),
        }
        _state_manager.update_state(domain, key, draft_record, "append")
    
    elif tool_name in ("create_file", "createTextFile"):
        file_record = {
            "id": result.get("id", generate_mock_id()),
            "name": args.get("name", args.get("filename", "new_file.txt")),
            "content": args.get("content", ""),
        }
        _state_manager.update_state(domain, key, file_record, "append")
    
    elif tool_name == "createFolder":
        folder_record = {
            "id": result.get("id", generate_mock_id()),
            "name": args.get("name", args.get("folder_name", "New Folder")),
        }
        _state_manager.update_state(domain, key, folder_record, "append")
    
    elif tool_name in ("createGoogleDoc", "createGoogleSheet", "createGoogleSlides"):
        doc_record = {
            "id": result.get("id", generate_mock_id()),
            "name": args.get("name", args.get("title", "New Document")),
            "webViewLink": result.get("webViewLink", ""),
        }
        _state_manager.update_state(domain, key, doc_record, "append")
    
    elif tool_name == "API-patch-block-children":
        block_record = {
            "id": result.get("results", [{}])[0].get("id", generate_mock_id()),
            "parent_id": args.get("block_id", args.get("parent_id", "")),
            "content": args.get("content", args.get("children", [])),
        }
        _state_manager.update_state(domain, key, block_record, "append")
    
    elif tool_name == "get_transcript":
        transcript_record = {
            "video_id": args.get("video_id", args.get("url", "")),
            "transcript": result.get("transcript", ""),
        }
        _state_manager.update_state("youtube", "transcripts", transcript_record, "append")


def is_tool_mockable(tool_name: str) -> bool:
    """Check if a tool has a specific mock handler."""
    return tool_name in ALL_MOCK_RESPONSES
