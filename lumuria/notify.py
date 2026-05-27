"""Telegram notifications so you can watch the bot from your phone.

The token and chat id come from the environment (TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID) or are passed in — never hardcoded. Sending is best-effort:
a Telegram outage must never crash the trading loop, so every failure is
swallowed and the bot keeps going.

Find your chat id (on the VPS, after messaging your bot once):

    python3 -m lumuria.notify <BOT_TOKEN>
"""
from __future__ import annotations

import os

from .sources import http


class TelegramNotifier:
    def __init__(self, token: str = "", chat_id: str = "",
                 enabled: bool | None = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id) if enabled is None else enabled

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        return cls(os.getenv("TELEGRAM_BOT_TOKEN", ""),
                   os.getenv("TELEGRAM_CHAT_ID", ""))

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            http.post_json(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                {"chat_id": self.chat_id, "text": text},
                timeout=8.0, retries=1,
            )
            return True
        except Exception:
            return False  # never let a notification break the bot

    # -- event helpers -----------------------------------------------------

    def startup(self, mode: str, budget_sol: float, per_trade_sol: float) -> None:
        self.send(f"Lumuria TurboBot started [{mode}]\n"
                  f"budget {budget_sol} SOL | per trade {per_trade_sol} SOL")

    def buy(self, symbol: str, sol: float, liq: float, dry_run: bool) -> None:
        kind = "WOULD BUY (dry)" if dry_run else "BUY"
        self.send(f"[{kind}] {symbol}\n{sol:.4f} SOL | liquidity ${liq:,.0f}")

    def sell(self, symbol: str, pnl_sol: float, reason: str, dry_run: bool) -> None:
        kind = "WOULD SELL (dry)" if dry_run else "SELL"
        sign = "PROFIT" if pnl_sol > 0 else "loss"
        self.send(f"[{kind} {reason}] {symbol}\n{sign} {pnl_sol:+.4f} SOL")

    def trap(self, symbol: str) -> None:
        self.send(f"[TRAP] {symbol}: sell route vanished (honeypot realized)")

    def status(self, bankroll: float, open_n: int, realized: float,
               scanned: int, skipped: int) -> None:
        self.send(f"Status\nbankroll {bankroll:.4f} SOL | open {open_n} | "
                  f"realized {realized:+.4f} SOL\nscanned {scanned} | "
                  f"skipped {skipped}")

    def performance(self, all_m, recent_m, realized_sol: float,
                    open_n: int, recent_window: int) -> None:
        """Send a profitability analysis built from the trade journal."""
        if all_m.trades == 0:
            self.send(f"Performance\nno closed trades yet | open {open_n}")
            return
        # Honest proxy for 'evolving': is the recent window beating all-time?
        if recent_m.trades >= 5:
            delta = recent_m.expectancy_r - all_m.expectancy_r
            trend = ("improving" if delta > 0.1 else
                     "declining" if delta < -0.1 else "stable")
            recent_line = (f"\nlast {recent_window}: {recent_m.expectancy_r:+.2f} R "
                           f"({trend})")
        else:
            recent_line = ""
        verdict = "PROFITABLE" if all_m.expectancy_usd > 0 else "not profitable yet"
        self.send(
            f"Performance ({all_m.trades} trades)\n"
            f"win rate {all_m.win_rate:.0%} ({all_m.wins}W/{all_m.losses}L)\n"
            f"expectancy {all_m.expectancy_r:+.2f} R "
            f"({all_m.expectancy_usd:+.4f} SOL/trade)\n"
            f"profit factor {all_m.profit_factor:.2f}\n"
            f"realized {realized_sol:+.4f} SOL | open {open_n}\n"
            f"max drawdown {all_m.max_drawdown_usd:.4f} SOL"
            f"{recent_line}\n=> {verdict}")

    def error(self, msg: str) -> None:
        self.send(f"[ERROR] {msg}")

    def shutdown(self, realized: float, open_n: int) -> None:
        self.send(f"Lumuria TurboBot stopped\nrealized {realized:+.4f} SOL | "
                  f"still holding {open_n}")


def get_chat_ids(token: str) -> list[tuple[str, str]]:
    """Read recent chats that messaged the bot, for first-time setup."""
    payload = http.get_json(f"https://api.telegram.org/bot{token}/getUpdates")
    seen: dict[str, str] = {}
    for upd in (payload or {}).get("result", []):
        chat = ((upd.get("message") or upd.get("channel_post") or {})
                .get("chat") or {})
        cid = chat.get("id")
        if cid is not None:
            name = chat.get("title") or chat.get("username") or chat.get("first_name", "")
            seen[str(cid)] = name
    return list(seen.items())


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python3 -m lumuria.notify <BOT_TOKEN>")
        sys.exit(1)
    print("Message your bot first, then these are the chat ids it can reach:")
    for cid, name in get_chat_ids(sys.argv[1]):
        print(f"  {cid}  {name}")
