# QuantJourney MCP Server

Connect AI assistants (Claude Desktop, Cursor, ChatGPT) to QuantJourney financial data using the Model Context Protocol (MCP).

## Features

- **500+ Financial Tools** - Access data from 16+ providers
- **Real-time Data** - Stocks, crypto, forex, commodities
- **Fundamentals** - Financial statements, ratios, valuations
- **Macro Data** - Economic indicators from FRED, IMF, OECD
- **Market Sentiment** - CNN Fear & Greed, insider trading

## Quick Start

### 1. Prerequisites

- Python 3.10+
- QuantJourney account ([Sign up](https://users.quantjourney.cloud))
- Claude Desktop or Cursor IDE

### 2. Installation

```bash
git clone https://github.com/QuantJourneyOrg/mcp-server.git
cd mcp-server
pip install -r requirements.txt
```

### 3. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "quantjourney": {
      "command": "python",
      "args": ["/path/to/mcp-server/server.py"],
      "env": {
        "QJ_MCP_EMAIL": "your@email.com",
        "QJ_MCP_PASSWORD": "your-password"
      }
    }
  }
}
```

### 4. Restart Claude Desktop

Restart Claude Desktop and you'll see the MCP tools icon. Start asking financial questions!

## Configuration Options

| Environment Variable | Description | Required |
|---------------------|-------------|----------|
| `QJ_MCP_EMAIL` | Your QuantJourney email | Yes* |
| `QJ_MCP_PASSWORD` | Your QuantJourney password | Yes* |
| `QJ_MCP_BEARER` | API token (alternative to email/password) | Yes* |
| `QJ_MCP_BASE_URL` | API URL (default: https://api.quantjourney.cloud) | No |

*Either email/password OR bearer token is required.

## Example Prompts

Once configured, try these prompts in Claude:

- *"What's the current P/E ratio for Apple and how does it compare to Microsoft?"*
- *"Show me Tesla's revenue growth over the last 5 years"*
- *"What are the top performing tech stocks this quarter?"*
- *"Analyze the current Fear & Greed index and what it means for the market"*

## Supported Data Providers

| Provider | Tools | Description |
|----------|-------|-------------|
| FMP | 81 | Financial Modeling Prep - comprehensive fundamentals |
| FRED | 80 | Federal Reserve Economic Data |
| Yahoo Finance | 73 | Real-time quotes and historical data |
| EOD | 61 | EOD Historical Data |
| MULTPL | 38 | Market multiples and valuations |
| CNN | 32 | Fear & Greed Index |
| SEC | 22 | SEC EDGAR filings |
| CCXT | 21 | Crypto exchanges |

## Running Modes

### STDIO Mode (Default - for Claude Desktop)

```bash
python server.py
```

### SSE Mode (for web clients)

```bash
python server.py --sse --port 8002
```

## Troubleshooting

### "No tools available"
- Check your API credentials are correct
- Ensure you have an active QuantJourney subscription

### "Authentication failed"
- Verify email/password in config
- Try using a bearer token instead

### Tools not appearing in Claude
- Restart Claude Desktop completely
- Check the config.json path is correct
- Verify Python path in config

## License

MIT License - see [LICENSE](LICENSE)

## Links

- [QuantJourney API](https://api.quantjourney.cloud)
- [Documentation](https://api.quantjourney.cloud/mcp)
- [Sign Up](https://users.quantjourney.cloud)
- [Discord](https://discord.gg/Qkvktf7fRv)
