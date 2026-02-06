"""
QuantJourney MCP Server
=======================
Connect AI assistants (Claude Desktop, Cursor) to QuantJourney financial data
using the Model Context Protocol (MCP).

Usage:
  STDIO mode (default, for Claude Desktop):
    python server.py

  SSE mode (for web clients):
    python server.py --sse --port 8002
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.requests import Request

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("qj-mcp-server")

# Configuration from environment
BASE_URL = os.getenv("QJ_MCP_BASE_URL", "https://api.quantjourney.cloud").rstrip("/")
EMAIL = os.getenv("QJ_MCP_EMAIL", "").strip()
PASSWORD = os.getenv("QJ_MCP_PASSWORD", "").strip()
BEARER = os.getenv("QJ_MCP_BEARER", "").strip()


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    endpoint: str


# Global state
TOOLS: Dict[str, Tool] = {}
AUTH_TOKEN: Optional[str] = None


def _authenticate() -> Optional[str]:
    """Authenticate with QuantJourney API and get bearer token."""
    global AUTH_TOKEN
    
    # If we have a bearer token, use it
    if BEARER:
        AUTH_TOKEN = BEARER if BEARER.startswith("Bearer ") else f"Bearer {BEARER}"
        return AUTH_TOKEN
    
    # Otherwise, authenticate with email/password
    if not (EMAIL and PASSWORD):
        logger.warning("No authentication credentials provided. Set QJ_MCP_EMAIL/QJ_MCP_PASSWORD or QJ_MCP_BEARER")
        return None
    
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token") or data.get("token")
        if token:
            AUTH_TOKEN = f"Bearer {token}"
            logger.info("Successfully authenticated with QuantJourney API")
            return AUTH_TOKEN
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
    return None


def _load_tools_from_api() -> Dict[str, Tool]:
    """Fetch available tools from the QuantJourney API."""
    tools: Dict[str, Tool] = {}
    
    if not AUTH_TOKEN:
        _authenticate()
    
    if not AUTH_TOKEN:
        logger.warning("Cannot load tools: not authenticated")
        return tools
    
    try:
        # Fetch MCP tools manifest
        resp = requests.get(
            f"{BASE_URL}/mcp/tools",
            headers={"Authorization": AUTH_TOKEN, "Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        
        for t in data.get("tools", []):
            name = t.get("name")
            if not name:
                continue
            
            desc = t.get("description_short") or t.get("description_long") or t.get("description") or name
            schema = t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}}
            
            # Determine endpoint
            exec_spec = t.get("execution") or {}
            endpoint = exec_spec.get("preferred") or exec_spec.get("fallback") or t.get("endpoint") or f"/mcp/call/{name}"
            
            tools[name] = Tool(
                name=name,
                description=desc,
                input_schema=schema,
                endpoint=endpoint
            )
        
        logger.info(f"Loaded {len(tools)} tools from API")
    except Exception as e:
        logger.error(f"Failed to load tools from API: {e}")
    
    return tools


def _init_tools():
    """Initialize tools on startup."""
    global TOOLS
    TOOLS = _load_tools_from_api()


# ---------------------------------------------------------------------------
# JSON-RPC Logic (Transport Agnostic)
# ---------------------------------------------------------------------------

def _result(id_val: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_val, "result": result}


def _error(id_val: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_val, "error": err}


def handle_initialize(id_val, params):
    return _result(id_val, {
        "serverInfo": {"name": "QuantJourney MCP Server", "version": "1.0.0"},
        "capabilities": {
            "tools": {}
        }
    })


def handle_tools_list(id_val, params):
    items = []
    for t in TOOLS.values():
        items.append({
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema or {"type": "object", "properties": {}},
        })
    return _result(id_val, {"tools": items})


def _get_headers() -> Dict[str, str]:
    """Get HTTP headers for API calls."""
    headers = {"Content-Type": "application/json"}
    if AUTH_TOKEN:
        headers["Authorization"] = AUTH_TOKEN
    return headers


def _call_api(path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Call QuantJourney API endpoint."""
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, json=args, headers=_get_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def handle_tools_call(id_val, params):
    name = (params or {}).get("name")
    arguments = (params or {}).get("arguments") or {}
    
    if not name or name not in TOOLS:
        return _error(id_val, -32602, f"Unknown tool: {name}")
    
    t = TOOLS[name]
    try:
        data = _call_api(t.endpoint, arguments)
        return _result(id_val, {"content": [{"type": "json", "json": data}]})
    except requests.HTTPError as e:
        return _error(id_val, -32000, f"API error: {e.response.status_code}", {"error": str(e)})
    except Exception as exc:
        return _error(id_val, -32000, "Tool execution failed", {"error": str(exc)})


def process_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC message and return the response."""
    method = msg.get("method")
    id_val = msg.get("id")
    params = msg.get("params")
    
    if method == "initialize":
        return handle_initialize(id_val, params)
    elif method == "tools/list":
        return handle_tools_list(id_val, params)
    elif method == "tools/call":
        return handle_tools_call(id_val, params)
    elif method == "notifications/initialized":
        return None
    else:
        return _error(id_val, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# STDIO Transport (for Claude Desktop)
# ---------------------------------------------------------------------------

def _read_message_stdio(stdin) -> Optional[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="ignore")
        if line in ("\r\n", "\n"):
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = stdin.read(length)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _write_message_stdio(msg: Dict[str, Any]) -> None:
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def run_stdio() -> int:
    stdin = sys.stdin.buffer
    while True:
        msg = _read_message_stdio(stdin)
        if msg is None:
            break
        resp = process_message(msg)
        if resp:
            _write_message_stdio(resp)
    return 0


# ---------------------------------------------------------------------------
# SSE Transport (for web clients)
# ---------------------------------------------------------------------------

class SseSession:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.id = str(uuid.uuid4())

    async def send(self, message: Dict[str, Any]):
        await self.queue.put(message)

    async def event_generator(self):
        yield f"event: endpoint\ndata: /messages?session_id={self.id}\n\n"
        while True:
            message = await self.queue.get()
            data = json.dumps(message)
            yield f"event: message\ndata: {data}\n\n"


sessions: Dict[str, SseSession] = {}


async def handle_sse(request: Request):
    session = SseSession()
    sessions[session.id] = session
    logger.info(f"New SSE session: {session.id}")
    return StreamingResponse(session.event_generator(), media_type="text/event-stream")


async def handle_messages(request: Request):
    session_id = request.query_params.get("session_id")
    if not session_id or session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    
    try:
        body = await request.json()
        response = process_message(body)
        if response:
            await sessions[session_id].send(response)
        return JSONResponse({"status": "accepted"}, status_code=202)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_health(request: Request):
    return JSONResponse({
        "status": "healthy",
        "service": "quantjourney-mcp-server",
        "tools_loaded": len(TOOLS),
        "authenticated": AUTH_TOKEN is not None
    })


def create_app() -> Starlette:
    routes = [
        Route("/health", handle_health, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Route("/messages", handle_messages, methods=["POST"]),
    ]
    return Starlette(routes=routes)


def run_sse(host: str = "0.0.0.0", port: int = 8002):
    uvicorn.run(create_app(), host=host, port=port)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> int:
    # Initialize authentication and load tools
    _authenticate()
    _init_tools()
    
    if not TOOLS:
        logger.warning("No tools loaded. Check your credentials and API connectivity.")
    
    # Check for SSE mode
    mode = os.getenv("QJ_MCP_MODE", "stdio").lower()
    
    if "--sse" in sys.argv:
        mode = "sse"
    
    port = 8002
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    
    if mode == "sse":
        print(f"Starting QuantJourney MCP Server in SSE mode on port {port}...", file=sys.stderr)
        run_sse(port=port)
        return 0
    else:
        return run_stdio()


if __name__ == "__main__":
    sys.exit(main())
