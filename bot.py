"""STOA Trade BOT — Telegram bot for Stoa on Robinhood Chain.

Commands:
  /quote <token> [amount]   Live swap quote: ETH -> token via Stoa's router
  /check <token>            Stoa token safety check (simulated buy/sell)

<token> is a ticker (FOREVER, BULL, TSLA) or a contract address.
Every quote is requested with REFERRER_ADDRESS set, so swaps the bot
sends earn the referrer share of Stoa's fee.

Setup: copy .env.example to .env, fill in your bot token from @BotFather,
then run:  python bot.py
"""

import html
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
)

import stoa

REFERRER = os.environ.get(
    "REFERRER_ADDRESS", "0xD294e1d6824ddC84172452EE88D57c014543F7D0")
DEFAULT_AMOUNT_ETH = 0.1
SLIPPAGE_BPS = 50  # 0.5%

_last_call = {}  # chat_id -> timestamp (simple flood control)


def _flood_ok(chat_id):
    now = time.time()
    if now - _last_call.get(chat_id, 0) < 3:
        return False
    _last_call[chat_id] = now
    return True


def fmt_amount(raw, decimals):
    v = int(raw) / (10 ** decimals)
    return f"{v:,.2f}" if v < 1_000_000 else f"{v:,.0f}"


def short_addr(a):
    return f"{a[:6]}…{a[-4:]}" if a and len(a) > 12 else a


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 STOA Trade BOT — quotes & safety checks for Robinhood Chain tokens, "
        "powered by Stoa (stoadex.com).\n\n"
        "/quote <token> [amount] — e.g. /quote FOREVER 0.1\n"
        "/check <token> — e.g. /check FOREVER\n\n"
        "Token can be a ticker or a contract address. Not financial advice.")


async def quote_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _flood_ok(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /quote <token> [amount in ETH]")
        return
    token_q = ctx.args[0]
    amount_eth = DEFAULT_AMOUNT_ETH
    if len(ctx.args) > 1:
        try:
            amount_eth = float(ctx.args[1])
        except ValueError:
            await update.message.reply_text("Amount must be a number, e.g. /quote FOREVER 0.25")
            return
    wait = await update.message.reply_text("⏳ Getting quote from Stoa…")
    try:
        address, symbol, decimals = stoa.resolve_token(token_q)
        if address == stoa.NATIVE:
            raise stoa.StoaError("Pick a token to buy — ETH is what you pay with.")
        q = stoa.quote(stoa.NATIVE, address, int(amount_eth * 10**18),
                       referrer=REFERRER, slippage_bps=SLIPPAGE_BPS)
        out = int(q["amountOut"]) / (10 ** decimals)
        min_out = int(q["minOut"]) / (10 ** decimals)
        rate = out / amount_eth if amount_eth else 0
        venues = ", ".join(
            leg.get("name") or short_addr(leg.get("venue", ""))
            for leg in q.get("route", {}).get("legs", [])) or "Stoa router"
        sym = symbol or short_addr(address)
        text = (
            f"💱 <b>Quote — {amount_eth:g} ETH → {html.escape(sym)}</b>\n"
            f"You receive ≈ <b>{out:,.2f} {html.escape(sym)}</b>\n"
            f"Min received ({SLIPPAGE_BPS/100:g}% slippage): {min_out:,.2f} {html.escape(sym)}\n"
            f"Rate: 1 ETH ≈ {rate:,.2f} {html.escape(sym)}\n"
            f"Route: {html.escape(venues)}\n"
            f"Price impact: {q.get('priceImpactPct', 0)}%\n"
            f"⏱ Quote valid ~{q.get('validForSeconds', 30)}s. Amounts move with the market.\n"
            f"Contract: <code>{address}</code>")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Swap on Stoa ↗",
                                 url=stoa.trade_url(address, REFERRER))]])
        await wait.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except stoa.StoaError as e:
        await wait.edit_text(f"❌ {e}")


async def check_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _flood_ok(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /check <token>")
        return
    wait = await update.message.reply_text("🛡 Running Stoa safety check…")
    try:
        address, symbol, _ = stoa.resolve_token(ctx.args[0])
        if address == stoa.NATIVE:
            raise stoa.StoaError("ETH is the native token — nothing to check.")
        r = stoa.safety_check(address)
        t = r.get("test", {})
        verdict = r.get("verdict", "unknown")
        icon = {"ok": "✅", "caution": "⚠️", "danger": "🚨"}.get(verdict, "❔")
        sym = r.get("symbol") or symbol or short_addr(address)
        lines = [
            f"🛡 <b>{html.escape(str(sym))} safety check</b>",
            f"Verdict: <b>{verdict}</b> {icon}",
            f"Buy: {'ok' if t.get('buyOk') else 'FAILED'} · "
            f"Sell: {'ok' if t.get('sellOk') else 'FAILED'}",
            f"Taxes: buy {t.get('buyTaxPct', '?')}% · sell {t.get('sellTaxPct', '?')}%",
            f"Round trip (buy+sell): {t.get('roundTripPct', '?')}%",
        ]
        if r.get("creatorPct") is not None:
            lines.append(f"Creator holds: {r['creatorPct']}%")
        if r.get("top10Pct") is not None:
            lines.append(f"Top 10 holders: {r['top10Pct']}%")
        for n in r.get("notes", []):
            lines.append(f"• {html.escape(str(n))}")
        if t.get("why"):
            lines.append(f"Note: {html.escape(str(t['why']))}")
        lines.append("Source: Stoa token safety check (simulated buy/sell on-chain)")
        lines.append(f"Contract: <code>{address}</code>")
        await wait.edit_text("\n".join(lines), parse_mode="HTML")
    except stoa.StoaError as e:
        await wait.edit_text(f"❌ {e}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (from @BotFather) in your .env")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("quote", quote_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    print("STOA Trade BOT running…")
    app.run_polling()


if __name__ == "__main__":
    main()
