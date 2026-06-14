from __future__ import annotations

import json
import sys


def respond(request: dict) -> dict:
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-feishu-project-mcp", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {"name": "search_by_mql", "description": "fake search"},
                {"name": "add_comment", "description": "fake comment"},
            ]
        }
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "search_by_mql":
            result = {
                "items": [
                    {
                        "id": "story_1",
                        "workitem_type": "story",
                        "space_key": "z9b9t3",
                        "title": "fake story",
                        "url": "https://project.feishu.cn/z9b9t3/story/detail/story_1",
                        "arguments": arguments,
                    }
                ]
            }
        elif name == "add_comment":
            result = {"comment_id": "comment_1", "arguments": arguments}
        else:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32601, "message": f"unknown tool: {name}"},
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        sys.stdout.write(json.dumps(respond(json.loads(line))) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
