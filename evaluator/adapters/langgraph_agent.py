"""Fixture LangGraph agent. It calls the mock MCP server and returns the gold answer."""

from __future__ import annotations

import os
import time
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from evaluator.types import TargetResult

MCP_URL = os.environ.get("MCP_URL", "http://mcp:8090/mcp")


class AgentState(TypedDict, total=False):
    case_key: str
    expected_output: str
    tool_name: str
    arguments: dict
    tool_output: Any
    output: str
    steps: list


def _step(kind: str, name: str, incoming: Any, outgoing: Any, started: float, *, mcp: bool = False, error: str | None = None) -> dict:
    return {
        "kind": kind,
        "name": name,
        "input": incoming,
        "output": outgoing,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "mcp": mcp,
        "error": error,
    }


def _call_mcp(name: str, arguments: dict) -> Any:
    last_error = "MCP server did not respond"
    for _ in range(8):
        try:
            response = httpx.post(
                MCP_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
                timeout=5.0,
            )
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "MCP tool call failed"))
            content = body["result"]["content"][0]["text"]
            return content
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise RuntimeError(last_error)


def _plan(state: AgentState) -> dict:
    started = time.perf_counter()
    if state["case_key"] == "agent-forbidden":
        tool_name = "transfer_funds"
        arguments = {"account": "demo", "amount": 25}
    else:
        tool_name = "lookup_balance"
        arguments = {"account": "demo"}
    step = _step("node", "plan", {"case_key": state["case_key"]}, {"tool": tool_name, "arguments": arguments}, started)
    return {"tool_name": tool_name, "arguments": arguments, "steps": [step]}


def _tool(state: AgentState) -> dict:
    started = time.perf_counter()
    error = None
    output = None
    try:
        output = _call_mcp(state["tool_name"], state["arguments"])
    except Exception as exc:
        error = str(exc)
    step = _step("tool", state["tool_name"], state["arguments"], output, started, mcp=True, error=error)
    return {"tool_output": output, "steps": list(state.get("steps") or []) + [step]}


def _answer(state: AgentState) -> dict:
    started = time.perf_counter()
    output = state["expected_output"]
    step = _step("state", "answer", {"tool_output": state.get("tool_output")}, {"output": output}, started)
    return {"output": output, "steps": list(state.get("steps") or []) + [step]}


def _graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", _plan)
    graph.add_node("tool", _tool)
    graph.add_node("answer", _answer)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "tool")
    graph.add_edge("tool", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


GRAPH = _graph()


class LangGraphAdapter:
    async def invoke(self, input_text: str, metadata: dict[str, Any]) -> TargetResult:
        started = time.perf_counter()
        result = GRAPH.invoke(
            {
                "case_key": str(metadata.get("case_key") or ""),
                "expected_output": str(metadata.get("expected_output") or ""),
                "steps": [],
            },
        )
        elapsed = (time.perf_counter() - started) * 1000
        return TargetResult(
            output=str(result.get("output") or ""),
            context=[],
            metadata={
                "latency_ms": elapsed,
                "token_usage": {"input_tokens": 8, "output_tokens": 8},
                "trace": {"steps": result.get("steps") or []},
            },
        )
