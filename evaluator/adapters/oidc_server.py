"""Fixture OpenID Connect server. A real provider is configured with environment variables and is not started here."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt

SECRET = os.environ.get("OIDC_CLIENT_SECRET", "fixture-secret")
ISSUER = os.environ.get("OIDC_ISSUER", "http://oidc:8091")
EMAIL = os.environ.get("OIDC_FIXTURE_EMAIL", "oidc-user@example.com")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/.well-known/openid-configuration":
            self._send(
                {
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                }
            )
            return
        if parsed.path == "/authorize":
            query = parse_qs(parsed.query)
            location = query.get("redirect_uri", ["http://localhost/callback"])[0]
            state = query.get("state", [""])[0]
            joiner = "&" if "?" in location else "?"
            target = f"{location}{joiner}{urlencode({'code': 'fixture-code', 'state': state})}"
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        self._send({"error": "not_found"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/token":
            self._send({"error": "not_found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        token = jwt.encode({"email": EMAIL, "sub": EMAIL}, SECRET, algorithm="HS256")
        self._send({"id_token": token, "access_token": token, "token_type": "Bearer"})

    def _send(self, body: dict, status: int = 200) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()


if __name__ == "__main__":
    main()
