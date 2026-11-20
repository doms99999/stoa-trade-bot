# STOA Trade BOT

A Telegram bot that answers `/quote` and `/check` for Robinhood Chain tokens
using [Stoa](https://stoadex.com)'s public API and MCP server — built for the
Stoa build bounty (option 1: Telegram bot).

- **`/quote <token> [amount]`** — live ETH → token quote from Stoa's router:
  amount out, minimum received (0.5% slippage), rate, route/venue, price
  impact, and a **Swap on Stoa** button. Every quote is requested with the
  bot owner's address as `referrer`, so swaps the bot sends earn the
  referrer share (10% of Stoa's 2 bps fee).
- **`/check <token>`** — Stoa token safety check (MCP `safety_check`):
  simulated buy + sell-back on-chain, verdict (`ok` / `caution` / `danger`),
  buy/sell taxes, round-trip cost, holder concentration when available.

`<token>` accepts a ticker (`FOREVER`, `BULL`, `TSLA`) or a contract address.
Quotes are read-only; the bot never holds keys or moves funds — swaps happen
on stoadex.com in the user's own wallet.

## Setup

1. Create the bot with [@BotFather](https://t.me/BotFather): `/newbot`, pick a
   name and username. Copy the token it gives you.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure:

   ```bash
   cp .env.example .env   # then edit: TELEGRAM_BOT_TOKEN, REFERRER_ADDRESS
   set -a; source .env; set +a
   ```

4. Run it (any always-on host works — a small VPS, Railway, Render, Fly.io):

   ```bash
   python bot.py
   ```

5. Add the bot to your public group and try `/quote FOREVER` and
   `/check FOREVER`.

## Files

- `bot.py` — Telegram handlers and message formatting.
- `stoa.py` — Stoa REST API (`/quote`, `/tokens`) + MCP (`safety_check`)
  client, standard library only.

## Notes

- Stoa API limit: 60 requests/minute per IP; the bot has a 3-second per-chat
  cooldown.
- Quotes stay valid ~30 seconds and move with the market.
- Not financial advice. A passed safety check describes the token today, not
  later.
