# Changelog

## [1.1.0] - 2026-02-07

### Added
- **Token refresh**: Automatic token refresh via `/auth/refresh` with 60s expiry buffer — no more session timeouts
- **API key auth**: Support `QJ_MCP_API_KEY` as alternative to email/password
- **`.env` file support**: Automatically loads `.env` via `python-dotenv`
- **JSONL stdio**: Auto-detects both JSONL (newline-delimited) and Content-Length formats for Claude Desktop compatibility
- **`protocolVersion`**: Echoes client protocol version in `initialize` response (required by Claude Desktop 2024+)
- **Tool name sanitization**: Converts dotted names (e.g. `fmp.quote`) to underscore format (`fmp_quote`) for MCP compliance, with reverse mapping for API calls
- **401 retry**: Automatic token refresh + retry on 401 responses during tool calls
- **`pyproject.toml`**: Installable via `pip install .`
- **Lazy tool loading**: Tools loaded on first `tools/list` call, not at startup — faster Claude Desktop launch

### Fixed
- **Response format**: Changed from `{"type": "json", "json": ...}` to MCP-standard `{"type": "text", "text": ...}`
- **Logging**: All log output goes to stderr (stdout reserved for MCP protocol)

### Removed
- **`http_server.py`**: Was broken (imported non-existent `quantjourney.mcp` module)
- **SSE transport**: External users connect to QuantJourney's hosted SSE, not run their own
- **Unused dependencies**: Removed `mcp`, `pyyaml`, `uvicorn`, `starlette` from requirements

## [1.0.0] - 2025-12-01

### Added
- Initial release
- STDIO transport for Claude Desktop
- Email/password authentication
- Dynamic tool loading from `/mcp/manifest` API endpoint
- SSE transport (experimental)
