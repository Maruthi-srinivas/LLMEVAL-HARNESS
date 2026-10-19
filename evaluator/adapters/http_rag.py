"""HTTP RAG target. The request and response shapes are fixed."""

from __future__ import annotations

import time
from typing import Any

import httpx

from evaluator.net import UnsafeTargetUrl, ensure_safe_url, redirected
from evaluator.types import TargetResult


class HttpRagAdapter:
    def __init__(self, endpoint: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0):
        self.endpoint = endpoint
        self.transport = transport
        self.timeout = timeout

    async def invoke(self, input_text: str, metadata: dict[str, Any]) -> TargetResult:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout, follow_redirects=False) as client:
                response = await self._post(client, self.endpoint, input_text)
        except UnsafeTargetUrl as exc:
            return _failure("provider_error", str(exc))
        except httpx.TimeoutException:
            return _failure("timeout", "RAG endpoint timed out")
        except httpx.HTTPError as exc:
            return _failure("provider_error", f"RAG endpoint request failed: {exc.__class__.__name__}")
        if response.status_code >= 400:
            return _failure("provider_error", f"RAG endpoint returned {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            return _failure("provider_error", "RAG endpoint did not return JSON")
        parsed = _parse(body)
        if isinstance(parsed, TargetResult):
            return parsed
        answer, documents, usage = parsed
        elapsed = (time.perf_counter() - started) * 1000
        return TargetResult(
            output=answer,
            context=[],
            metadata={"latency_ms": elapsed, "token_usage": usage},
            documents=documents,
        )

    async def _post(self, client: httpx.AsyncClient, url: str, input_text: str) -> httpx.Response:
        current = url
        for _ in range(5):
            if self.transport is None:
                ensure_safe_url(current)
            response = await client.post(current, json={"question": input_text})
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current = redirected(current, location) if self.transport is None else location
        raise UnsafeTargetUrl("Target URL redirected too many times")


def _parse(body: Any) -> TargetResult | tuple[str, list[dict[str, str]], dict]:
    if not isinstance(body, dict) or not isinstance(body.get("answer"), str) or not isinstance(body.get("documents"), list):
        return _failure("provider_error", "RAG response must include answer and documents")
    documents = []
    for item in body["documents"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            return _failure("provider_error", "RAG documents require string id and text")
        documents.append({"id": item["id"], "text": item["text"]})
    usage = body.get("token_usage")
    if not isinstance(usage, dict):
        return _failure("provider_error", "RAG response must include token_usage")
    return body["answer"], documents, usage


def _failure(category: str, detail: str) -> TargetResult:
    return TargetResult(
        output="",
        context=[],
        metadata={"latency_ms": None, "token_usage": {}},
        error_category=category,
        error_detail=detail,
    )
