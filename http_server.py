from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

# Reuse handlers from stdio MCP server
from quantjourney.mcp import server as mcp_stdio


app = FastAPI(title="QuantJourney MCP (WebSocket)", version="0.1.0")


def _ok(id_val, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_val, "result": result}


def _err(id_val, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": id_val, "error": e}


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"


def _normalize_bearer(value: str | None) -> str | None:
    if not value:
        return None
    val = value.strip()
    if not val:
        return None
    if not val.lower().startswith("bearer "):
        val = f"Bearer {val}"
    return val


@app.websocket("/mcp")
async def mcp_ws(ws: WebSocket):
    # Optional token check
    token_required = os.getenv("QJ_MCP_TOKEN")
    hdr_tok = ws.headers.get("x-mcp-auth")
    q_tok = ws.query_params.get("token")
    if token_required and (hdr_tok or q_tok) != token_required:
        await ws.close(code=4401)
        return
    await ws.accept()
    # Build per-connection forwarding headers from WS headers/query
    fwd_headers: Dict[str, str] = {}
    # Authorization: support 'authorization' or 'x-api-authorization'
    auth_hdr = ws.headers.get("authorization") or ws.headers.get("x-api-authorization")
    auth_q = ws.query_params.get("auth") or ws.query_params.get("bearer")
    bearer = _normalize_bearer(auth_hdr or auth_q)
    if bearer:
        fwd_headers["Authorization"] = bearer
    # Tenant/user context
    tenant = ws.headers.get("x-tenant-id") or ws.query_params.get("tenant")
    user = ws.headers.get("x-user-id") or ws.query_params.get("user")
    if tenant:
        fwd_headers["X-Tenant-Id"] = tenant
    if user:
        fwd_headers["X-User-Id"] = user
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await ws.send_text(json.dumps(_err(None, -32700, "Parse error")))
                continue
            method = msg.get("method")
            id_val = msg.get("id")
            params = msg.get("params")
            try:
                # Apply per-connection headers for downstream API calls
                mcp_stdio.set_call_headers(fwd_headers)
                if method == "initialize":
                    await ws.send_text(json.dumps(mcp_stdio.handle_initialize(id_val, params)))
                elif method == "tools/list":
                    await ws.send_text(json.dumps(mcp_stdio.handle_tools_list(id_val, params)))
                elif method == "tools/call":
                    await ws.send_text(json.dumps(mcp_stdio.handle_tools_call(id_val, params)))
                else:
                    await ws.send_text(json.dumps(_err(id_val, -32601, f"Method not found: {method}")))
            except Exception as exc:
                await ws.send_text(json.dumps(_err(id_val, -32000, "Internal error", {"error": str(exc)})))
            finally:
                mcp_stdio.clear_call_headers()
    except WebSocketDisconnect:
        return
