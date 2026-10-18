"""Mock MCP server. It exposes two tools and stores no credentials."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = {
    "lookup_balance": {
        "name": "lookup_balance",
        "description": "Read a demo account balance.",
        "inputSchema": {
            "type": "object",
            "properties": {"account": {"type": "string"}},
            "required": ["account"],
        },
    },
    "transfer_funds": {
        "name": "transfer_funds",
        "description": "Move money from a demo account.",
        "inputSchema": {
            "type": "object",
            "properties": {"account": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["account", "amount"],
        },
    },
}


def call_tool(name: str, arguments: dict) -> dict:
    if name == "lookup_balance":
        return {"balance": 120, "account": arguments.get("account")}
    if name == "transfer_funds":
        return {"status": "moved", "account": arguments.get("account"), "amount": arguments.get("amount")}
    raise KeyError(name)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw.decode("utf-8"))
            method = request.get("method")
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            if method == "tools/list":
                result = {"tools": list(TOOLS.values())}
            elif method == "tools/call":
                name = str(params.get("name") or "")
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                result = {"content": [{"type": "text", "text": json.dumps(call_tool(name, arguments))}]}
            else:
                self._send({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": "Method not found"}}, 400)
                return
            self._send({"jsonrpc": "2.0", "id": request.get("id"), "result": result}, 200)
        except Exception as exc:
            self._send({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(exc)}}, 400)

    def _send(self, body: dict, status: int) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
