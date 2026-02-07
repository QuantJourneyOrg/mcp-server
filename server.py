"""
QuantJourney MCP Server
=======================
Connect AI assistants (Claude Desktop, Cursor, Windsurf) to QuantJourney
financial data using the Model Context Protocol (MCP).

Usage:
  STDIO mode (default, for Claude Desktop / Cursor):
    python server.py

  With .env file:
    Create a .env file with QJ_MCP_EMAIL and QJ_MCP_PASSWORD, then:
    python server.py

Environment Variables:
  QJ_MCP_EMAIL      - Your QuantJourney email
  QJ_MCP_PASSWORD   - Your QuantJourney password
  QJ_MCP_API_KEY    - API key (alternative to email/password)
  QJ_MCP_BASE_URL   - API URL (default: https://api.quantjourney.cloud)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging to stderr (stdout is reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("qj-mcp")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("QJ_MCP_BASE_URL", "https://api.quantjourney.cloud").rstrip("/")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    endpoint: str


# ---------------------------------------------------------------------------
# Authentication — email/password with token refresh, or API key
# ---------------------------------------------------------------------------

_AUTH_TOKEN: Optional[str] = None
_REFRESH_TOKEN: Optional[str] = None
_TOKEN_EXPIRY: int = 0  # Unix timestamp


def _authenticate() -> Optional[str]:
    """Authenticate with QuantJourney API and return bearer token."""
    global _AUTH_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY

    # 1) API key — no refresh needed, long-lived
    api_key = os.getenv("QJ_MCP_API_KEY", "").strip()
    if api_key:
        _AUTH_TOKEN = api_key
        _TOKEN_EXPIRY = int(time.time()) + 86400 * 365  # effectively permanent
        logger.info("Using API key authentication")
        return _AUTH_TOKEN

    # 2) Raw bearer token
    bearer = os.getenv("QJ_MCP_BEARER", "").strip()
    if bearer:
        _AUTH_TOKEN = bearer
        _TOKEN_EXPIRY = int(time.time()) + 900  # assume 15 min
        logger.info("Using bearer token from environment")
        return _AUTH_TOKEN

    # 3) Email / password login
    email = os.getenv("QJ_MCP_EMAIL", "").strip()
    password = os.getenv("QJ_MCP_PASSWORD", "").strip()

    if not (email and password):
        logger.warning("No credentials. Set QJ_MCP_EMAIL/QJ_MCP_PASSWORD or QJ_MCP_API_KEY")
        return None

    logger.info("Authenticating as %s ...", email)
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token") or data.get("token", "")
        refresh = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 900)

        if token:
            _AUTH_TOKEN = token
            _REFRESH_TOKEN = refresh
            _TOKEN_EXPIRY = int(time.time()) + expires_in - 60  # 60s buffer
            logger.info("Authenticated (expires in %ds)", expires_in)
            return token
        else:
            logger.error("No token in login response")
            return None
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        return None


def _refresh_auth() -> Optional[str]:
    """Refresh access token using refresh token."""
    global _AUTH_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY

    if not _REFRESH_TOKEN:
        logger.info("No refresh token — re-authenticating")
        return _authenticate()

    logger.info("Refreshing token ...")
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/refresh",
            json={"refresh_token": _REFRESH_TOKEN},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token", "")
        refresh = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 900)

        if token:
            _AUTH_TOKEN = token
            if refresh:
                _REFRESH_TOKEN = refresh
            _TOKEN_EXPIRY = int(time.time()) + expires_in - 60
            logger.info("Token refreshed (expires in %ds)", expires_in)
            return token
        else:
            logger.warning("Refresh failed — re-authenticating")
            return _authenticate()
    except Exception as exc:
        logger.warning("Refresh failed: %s — re-authenticating", exc)
        return _authenticate()


def _ensure_auth() -> str:
    """Ensure we have a valid token — refresh if expired."""
    global _AUTH_TOKEN, _TOKEN_EXPIRY

    now = int(time.time())

    # Still valid
    if _AUTH_TOKEN and _TOKEN_EXPIRY > now:
        return _AUTH_TOKEN

    # Expired — try refresh
    if _AUTH_TOKEN and _REFRESH_TOKEN:
        token = _refresh_auth()
        if token:
            return token

    # Fresh login
    token = _authenticate()
    return token or ""


# ---------------------------------------------------------------------------
# Tool Loading — from API manifest
# ---------------------------------------------------------------------------

_TOOLS: Optional[Dict[str, Tool]] = None


def _load_tools_from_api() -> Dict[str, Tool]:
    """Fetch available tools from the QuantJourney API manifest endpoint."""
    tools: Dict[str, Tool] = {}

    token = _ensure_auth()
    if not token:
        logger.warning("Cannot load tools — not authenticated")
        return tools

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    # API keys are sent as-is; JWT tokens need Bearer prefix
    if token.startswith("QJ_"):
        headers["X-API-Key"] = token
    else:
        headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") else token

    try:
        resp = requests.get(
            f"{BASE_URL}/mcp/manifest",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("tools", []):
            name = t.get("name")
            if not name:
                continue

            desc = (
                t.get("description_short")
                or t.get("description_long")
                or t.get("description")
                or name
            )
            schema = (
                t.get("input_schema")
                or t.get("inputSchema")
                or {"type": "object", "properties": {}}
            )

            exec_spec = t.get("execution") or {}
            endpoint = (
                exec_spec.get("preferred")
                or exec_spec.get("fallback")
                or t.get("endpoint")
                or f"/mcp/call/{name}"
            )

            tools[name] = Tool(
                name=name,
                description=desc,
                input_schema=schema,
                endpoint=endpoint,
            )

        logger.info("Loaded %d tools from API", len(tools))
    except Exception as exc:
        logger.error("Failed to load tools: %s", exc)

    return tools


def _get_tools() -> Dict[str, Tool]:
    """Lazy-load tools on first access."""
    global _TOOLS
    if _TOOLS is None:
        logger.info("Loading tools ...")
        _TOOLS = _load_tools_from_api()
    return _TOOLS


def _reload_tools() -> Dict[str, Tool]:
    """Force reload tools (e.g. after re-authentication)."""
    global _TOOLS
    _TOOLS = None
    return _get_tools()


# ---------------------------------------------------------------------------
# Tool Name Sanitization (. → _ for MCP compatibility)
# ---------------------------------------------------------------------------

_TOOL_NAME_MAP: Dict[str, str] = {}


def _sanitize_tool_name(name: str) -> str:
    """Convert tool name to MCP-compatible format (replace . with _)."""
    return name.replace(".", "_")


def _build_tool_name_map() -> Dict[str, str]:
    """Build reverse mapping: sanitized_name → original_name."""
    global _TOOL_NAME_MAP
    if not _TOOL_NAME_MAP:
        for original in _get_tools():
            _TOOL_NAME_MAP[_sanitize_tool_name(original)] = original
    return _TOOL_NAME_MAP


def _unsanitize_tool_name(name: str) -> str:
    """Resolve MCP tool name back to original API name."""
    tools = _get_tools()
    if name in tools:
        return name
    name_map = _build_tool_name_map()
    return name_map.get(name, name)


# ---------------------------------------------------------------------------
# JSON-RPC Logic (Transport Agnostic)
# ---------------------------------------------------------------------------


def _result(id_val: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_val, "result": result}


def _error(id_val: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_val, "error": err}


def handle_initialize(id_val: Any, params: Optional[Dict]) -> Dict[str, Any]:
    protocol_version = (params or {}).get("protocolVersion", "2024-11-05")
    return _result(id_val, {
        "protocolVersion": protocol_version,
        "serverInfo": {"name": "QuantJourney MCP Server", "version": "1.1.0"},
        "capabilities": {
            "tools": {},
        },
    })


def handle_tools_list(id_val: Any, params: Optional[Dict]) -> Dict[str, Any]:
    items = []
    for t in _get_tools().values():
        items.append({
            "name": _sanitize_tool_name(t.name),
            "description": t.description,
            "inputSchema": t.input_schema or {"type": "object", "properties": {}},
        })
    return _result(id_val, {"tools": items})


def _get_headers() -> Dict[str, str]:
    """Build HTTP headers for API calls with valid auth."""
    token = _ensure_auth()
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if token:
        if token.startswith("QJ_"):
            headers["X-API-Key"] = token
        else:
            headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") else token
    return headers


def _call_api(path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Call QuantJourney API endpoint."""
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, json=args, headers=_get_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def handle_tools_call(id_val: Any, params: Optional[Dict]) -> Dict[str, Any]:
    raw_name = (params or {}).get("name")
    name = _unsanitize_tool_name(raw_name) if raw_name else None
    arguments = (params or {}).get("arguments") or {}

    if not name or name not in _get_tools():
        return _error(id_val, -32602, f"Unknown tool: {raw_name} (resolved to {name})")

    t = _get_tools()[name]
    try:
        data = _call_api(t.endpoint, arguments)
        return _result(id_val, {
            "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
        })
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        # Token expired mid-session — refresh and retry once
        if status == 401:
            logger.info("Got 401 — refreshing token and retrying")
            _ensure_auth()
            try:
                data = _call_api(t.endpoint, arguments)
                return _result(id_val, {
                    "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
                })
            except Exception as retry_exc:
                return _error(id_val, -32000, "Tool call failed after retry", {"error": str(retry_exc)})
        return _error(id_val, -32000, f"API error: {status}", {"error": str(exc)})
    except Exception as exc:
        return _error(id_val, -32000, "Tool execution failed", {"error": str(exc)})


def process_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC message and return the response (or None for notifications)."""
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
        return None  # ACK, no response
    else:
        return _error(id_val, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# STDIO Transport — supports both JSONL and Content-Length formats
# ---------------------------------------------------------------------------


def _read_message_stdio(stdin) -> Optional[Dict[str, Any]]:
    """Read a message from stdin — auto-detects JSONL vs Content-Length format."""
    first_line = stdin.readline()
    if not first_line:
        return None

    first_str = first_line.decode("utf-8", errors="ignore").strip()
    if not first_str:
        return None

    # Content-Length header → LSP-style framing
    if first_str.lower().startswith("content-length:"):
        length = int(first_str.split(":", 1)[1].strip())
        # Skip remaining headers until empty line
        while True:
            line = stdin.readline()
            if not line:
                return None
            if line.strip() == b"":
                break
        body = stdin.read(length)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", errors="ignore"))
        except Exception as exc:
            logger.error("JSON parse error (LSP): %s", exc)
            return None
    else:
        # JSONL — the line IS the JSON message
        try:
            return json.loads(first_str)
        except Exception as exc:
            logger.error("JSON parse error (JSONL): %s", exc)
            return None


def _write_message_stdio(msg: Dict[str, Any]) -> None:
    """Write message to stdout in JSONL format (newline-terminated)."""
    data = json.dumps(msg, separators=(",", ":"))
    sys.stdout.write(data + "\n")
    sys.stdout.flush()


def run_stdio() -> int:
    """Main stdio loop — reads JSON-RPC messages and writes responses."""
    logger.info("Server ready (stdio mode)")
    stdin = sys.stdin.buffer
    while True:
        msg = _read_message_stdio(stdin)
        if msg is None:
            logger.info("No more messages — exiting")
            break
        logger.debug("Received: %s", msg.get("method", "unknown"))
        resp = process_message(msg)
        if resp is not None:
            _write_message_stdio(resp)
    return 0


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def main() -> int:
    # Disable Python output buffering — critical for stdio MCP
    os.environ["PYTHONUNBUFFERED"] = "1"

    logger.info("QuantJourney MCP Server v1.1.0")
    logger.info("API: %s", BASE_URL)

    # Auth happens lazily on first API call (via _ensure_auth)
    # This avoids blocking stdio during Claude Desktop startup
    return run_stdio()


if __name__ == "__main__":
    sys.exit(main())
