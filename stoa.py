"""Stoa (stoadex.com) client for Robinhood Chain.

Uses Stoa's public REST API for quotes and token lists, and Stoa's hosted
MCP server for the token safety check. No API key needed.

Docs: https://stoadex.com/docs/api and https://stoadex.com/docs/mcp
"""

import json
import urllib.request
import urllib.error

API_BASE = "https://stoadex.com/api/v1"
MCP_URL = "https://stoadex.com/mcp"
CHAIN = "robinhood"
CHAIN_ID = 4663
NATIVE = "native"  # ETH on Robinhood Chain

# Well-known tokens on Robinhood Chain (fallbacks if the list call fails)
USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"


class StoaError(Exception):
    pass


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "stoa-trade-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            msg = body.get("error", str(e))
        except Exception:
            msg = str(e)
        raise StoaError(msg)
    except Exception as e:
        raise StoaError(str(e))


def list_tokens(chain=CHAIN):
    """Tokens Stoa lists on the chain: [{address, symbol, name, decimals}]."""
    data = _get_json(f"{API_BASE}/tokens?chain={chain}")
    if isinstance(data, dict):
        return data.get("tokens", []), data.get("router")
    return data, None


def resolve_token(query, chain=CHAIN):
    """Resolve a ticker symbol or contract address to (address, symbol, decimals).

    Accepts a 0x address directly, or a symbol like FOREVER / BULL / TSLA.
    Symbol lookup: Stoa's token list first, then DexScreener (highest
    liquidity pair on Robinhood Chain wins).
    """
    q = query.strip()
    if q.lower().startswith("0x") and len(q) == 42:
        return q, None, 18
    if q.upper() in ("ETH", "NATIVE"):
        return NATIVE, "ETH", 18

    symbol = q.upper().lstrip("$")
    try:
        tokens, _ = list_tokens(chain)
        for t in tokens:
            if (t.get("symbol") or "").upper() == symbol:
                return t["address"], t["symbol"], int(t.get("decimals", 18))
    except StoaError:
        pass  # fall through to DexScreener

    # DexScreener fallback (covers unlisted / launchpad tokens)
    data = _get_json(f"https://api.dexscreener.com/latest/dex/search?q={symbol}")
    best = None
    for pair in data.get("pairs", []):
        if pair.get("chainId") != "robinhood":
            continue
        base = pair.get("baseToken", {})
        if (base.get("symbol") or "").upper() != symbol:
            continue
        liq = (pair.get("liquidity") or {}).get("usd", 0) or 0
        if best is None or liq > best[0]:
            best = (liq, base.get("address"), base.get("symbol"))
    if best:
        return best[1], best[2], 18
    raise StoaError(f"Token '{query}' not found on Robinhood Chain")


def token_meta(address, chain=CHAIN):
    """Best-effort (symbol, decimals) for an address from Stoa's list."""
    try:
        tokens, _ = list_tokens(chain)
        for t in tokens:
            if t.get("address", "").lower() == address.lower():
                return t.get("symbol"), int(t.get("decimals", 18))
    except StoaError:
        pass
    return None, 18


def quote(sell_token, buy_token, amount_wei, referrer=None, taker=None,
          slippage_bps=50, chain=CHAIN):
    """GET /quote on Stoa. amount_wei is an int in the sell token's smallest unit."""
    params = {
        "chain": chain,
        "sellToken": sell_token,
        "buyToken": buy_token,
        "amount": str(amount_wei),
        "slippageBps": str(slippage_bps),
    }
    if referrer:
        params["referrer"] = referrer
    if taker:
        params["taker"] = taker
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return _get_json(f"{API_BASE}/quote?{qs}")


def _mcp_call(tool, arguments, timeout=60):
    """Call a tool on Stoa's hosted MCP server (Streamable HTTP, stateless)."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "stoa-trade-bot/1.0",
    }

    def post(payload):
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        # Response may be plain JSON or SSE ("data: {...}" lines)
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if line.startswith("{"):
                return json.loads(line)
        return json.loads(raw)

    post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "stoa-trade-bot", "version": "1.0"},
    }})
    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    except Exception:
        pass
    result = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": tool, "arguments": arguments}})
    if "error" in result:
        raise StoaError(str(result["error"]))
    content = result.get("result", {}).get("content", [])
    for item in content:
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except Exception:
                return {"text": item["text"]}
    return result.get("result", {})


def safety_check(token_address, chain=CHAIN):
    """Stoa safety check: simulated buy + sell-back, taxes, holder concentration."""
    return _mcp_call("safety_check", {"chain": chain, "token": token_address})


def trade_url(buy_token_address, referrer=None, chain=CHAIN):
    """Deep link into Stoa Trade with the buy token and referrer prefilled."""
    url = f"https://stoadex.com/trade?chain={chain}&sell=native&buy={buy_token_address}"
    if referrer:
        url += f"&referrer={referrer}"
    return url
