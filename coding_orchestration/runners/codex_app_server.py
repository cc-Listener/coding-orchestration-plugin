from __future__ import annotations

from itertools import count


class CodexAppServerClient:
    def __init__(self, client_name: str = "hermes_coding_orchestration", client_version: str = "0.1.0"):
        self.client_name = client_name
        self.client_version = client_version

    def build_start_turn_messages(self, cwd: str, prompt: str, model: str) -> list[dict]:
        ids = count(1)
        thread_id_placeholder = "${thread_id_from_response}"
        return [
            {
                "method": "initialize",
                "id": next(ids),
                "params": {
                    "clientInfo": {
                        "name": self.client_name,
                        "title": "Hermes Coding Orchestration",
                        "version": self.client_version,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"method": "initialized", "params": {}},
            {
                "method": "thread/start",
                "id": next(ids),
                "params": {
                    "model": model,
                    "cwd": cwd,
                    "approvalPolicy": "never",
                    "sandbox": "workspaceWrite",
                    "serviceName": self.client_name,
                },
            },
            {
                "method": "turn/start",
                "id": next(ids),
                "params": {
                    "threadId": thread_id_placeholder,
                    "input": [{"type": "text", "text": prompt}],
                },
            },
        ]
