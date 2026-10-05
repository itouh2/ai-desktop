import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_project_mcp_json_registers_only_ai_desktop():
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert config == {
        "mcpServers": {
            "ai-desktop": {
                "command": "uv",
                "args": ["run", "--no-sync", "--directory", "C:/Works/2026/ai-desktop", "ai-desktop"],
            }
        }
    }
