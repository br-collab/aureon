#!/usr/bin/env python3
"""
aureon-agents-mcp — MCP server exposing RANGER_AGENTS task-registry methods.

Transport: JSON-RPC 2.0 over stdio (matches Cato eFICC MCP pattern).
Tool registration is dynamic from the RANGER_AGENTS registry.
"""

import inspect
import json
import sys
import threading
import traceback
from datetime import datetime, timezone


def _discover_registries() -> dict:
    """Discover all *_AGENTS registries from aureon.agents tier subpackages."""
    registries = {}
    try:
        from aureon.agents.ranger import RANGER_AGENTS
        registries.update(RANGER_AGENTS)
    except ImportError:
        pass
    try:
        from aureon.agents.jtac import JTAC_AGENTS
        registries.update(JTAC_AGENTS)
    except ImportError:
        pass
    try:
        from aureon.agents.hunter_killer import HUNTER_KILLER_AGENTS
        registries.update(HUNTER_KILLER_AGENTS)
    except ImportError:
        pass
    return registries


def _get_task_methods(cls) -> list:
    """Get task-registry methods for a role class."""
    from aureon.agents.base import Agent

    base_methods = set(dir(Agent)) | set(dir(object))
    # Always include get_status (overridden by every role)
    base_methods.discard("get_status")
    # Exclude backward-compat alias
    always_exclude = {"prepare_settlement_package", "confirm_handoff", "emit_execution_confirmation"}

    methods = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        if name in always_exclude:
            continue
        if name in base_methods:
            continue
        attr = getattr(cls, name, None)
        if attr is not None and callable(attr) and not isinstance(attr, (type, property)):
            methods.append(name)

    if "get_status" not in methods:
        methods.insert(0, "get_status")

    return methods


def _build_tool_schema(method) -> dict:
    """Build a JSON Schema for a method's parameters from its signature."""
    sig = inspect.signature(method)
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        properties[name] = {"type": "object", "description": f"Parameter: {name}"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _instantiate(cls):
    """Instantiate an agent with minimal aureon_state."""
    state = {"doctrine_version": "1.0", "halt_active": False, "authority_log": []}
    return cls(state, threading.Lock())


class AgentsMCPServer:
    """JSON-RPC 2.0 MCP server over stdio for aureon agents."""

    def __init__(self):
        self._registries = _discover_registries()
        self._tools = {}
        self._register_tools()

    def _register_tools(self):
        for role_id, cls in self._registries.items():
            methods = _get_task_methods(cls)
            for method_name in methods:
                tool_name = f"{role_id}_{method_name}"
                method = getattr(cls, method_name)
                doc = (method.__doc__ or "").strip().split("\n")[0]
                self._tools[tool_name] = {
                    "role_id": role_id,
                    "cls": cls,
                    "method_name": method_name,
                    "description": f"[{role_id}] {getattr(cls, 'role_name', '?')}: {doc}",
                    "schema": _build_tool_schema(method),
                }

        role_count = len(self._registries)
        tool_count = len(self._tools)
        self._log(f"aureon-agents-mcp: registered {tool_count} tools across {role_count} roles")

    def _log(self, msg: str):
        print(msg, file=sys.stderr)

    def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return self._response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "aureon-agents-mcp",
                    "version": "1.0",
                },
            })

        if method == "tools/list":
            tools = []
            for tool_name, info in sorted(self._tools.items()):
                tools.append({
                    "name": tool_name,
                    "description": info["description"],
                    "inputSchema": info["schema"],
                })
            return self._response(req_id, {"tools": tools})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            return self._call_tool(req_id, tool_name, arguments)

        if method == "notifications/initialized":
            return None

        return self._error(req_id, -32601, f"Method not found: {method}")

    def _call_tool(self, req_id, tool_name: str, arguments: dict) -> dict:
        if tool_name not in self._tools:
            return self._error(req_id, -32602, f"Tool not found: {tool_name}")

        info = self._tools[tool_name]
        try:
            state = {"doctrine_version": "1.0", "halt_active": False, "authority_log": []}
            lock = threading.Lock()
            agent = info["cls"](state, lock)
            method = getattr(agent, info["method_name"])

            sig = inspect.signature(method)
            kwargs = {}
            for name in sig.parameters:
                if name == "self":
                    continue
                if name in arguments:
                    kwargs[name] = arguments[name]

            # Auto-provide C2 for methods that need it
            if "c2" in sig.parameters and "c2" not in kwargs:
                from aureon.agents.c2.coordinator import ThifurC2
                c2 = ThifurC2(state, lock)
                decision = arguments.get("decision", {})
                task_id = c2.issue_task(decision, agents=["THIFUR_J", "THIFUR_R"])
                handoff = c2.handoff(task_id, from_agent="THIFUR_J", to_agent="THIFUR_R", object_state=decision)
                agent.confirm_handoff(handoff)
                kwargs["c2"] = c2
                if "task_id" in sig.parameters and "task_id" not in kwargs:
                    kwargs["task_id"] = task_id

            result = method(**kwargs)

            def _serialize(obj):
                if hasattr(obj, "__dataclass_fields__"):
                    from dataclasses import asdict
                    return asdict(obj)
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return str(obj)

            text = json.dumps(result, indent=2, default=_serialize)
            return self._response(req_id, {
                "content": [{"type": "text", "text": text}],
            })
        except Exception:
            tb = traceback.format_exc()
            self._log(f"Tool error: {tool_name}\n{tb}")
            return self._error(req_id, -32000, f"Tool execution error: {tb}")

    def _response(self, req_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def run_stdio(self):
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        self._log("aureon-agents-mcp: listening on stdio")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                resp = self._error(None, -32700, f"Parse error: {e}")
                print(json.dumps(resp), flush=True)
                continue

            resp = self._handle_request(request)
            if resp is not None:
                print(json.dumps(resp), flush=True)


def list_tools():
    """Utility: print all registered tools to stdout (for testing)."""
    server = AgentsMCPServer()
    for name, info in sorted(server._tools.items()):
        print(f"  {name}")
        print(f"    {info['description']}")
    print(f"\nTotal: {len(server._tools)} tools across {len(server._registries)} roles")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
        list_tools()
        return
    server = AgentsMCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
