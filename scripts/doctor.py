"""Preflight check - run this BEFORE trusting the bot with an account.

    python scripts/doctor.py --config config.yaml

Checks the environment, the config, and (on Windows) the live MT5 terminal:
symbol availability, Algo Trading, filling mode, stops level, server time
offset, current spread, history depth, and the lot size the bot would
actually send. Exits non-zero if anything is a hard failure.

Output is intentionally plain ASCII so it survives the Windows console.
"""
from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_PYTHON = (3, 10)


class Report:
    """Collects pass/warn/fail lines and decides the exit code."""

    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n{title}\n" + "-" * len(title))

    def ok(self, msg: str) -> None:
        print(f"  [ OK ] {msg}")

    def warn(self, msg: str) -> None:
        self.warns.append(msg)
        print(f"  [WARN] {msg}")

    def fail(self, msg: str) -> None:
        self.fails.append(msg)
        print(f"  [FAIL] {msg}")

    def info(self, msg: str) -> None:
        print(f"         {msg}")

    def finish(self) -> int:
        print()
        if self.fails:
            print(f"FAILED: {len(self.fails)} problem(s) must be fixed before running the bot")
            for m in self.fails:
                print(f"  - {m}")
        if self.warns:
            print(f"{len(self.warns)} warning(s):")
            for m in self.warns:
                print(f"  - {m}")
        if not self.fails and not self.warns:
            print("All checks passed.")
        elif not self.fails:
            print("No blocking problems. Read the warnings above before going live.")
        return 1 if self.fails else 0


def check_environment(r: Report) -> None:
    r.section("Environment")
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        r.ok(f"Python {version} ({platform.python_implementation()}, {platform.machine()})")
    else:
        r.fail(f"Python {version} is too old - need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
    for module in ("pandas", "numpy", "yaml"):
        try:
            __import__(module)
            r.ok(f"package {module} importable")
        except ImportError:
            r.fail(f"package {module} missing - run: pip install -r requirements.txt")
    r.info(f"OS: {platform.system()} {platform.release()}")


def check_config(r: Report, path: str):
    r.section("Config")
    from bot.config import load_config

    if not Path(path).exists():
        r.fail(f"{path} not found - copy config.example.yaml to config.yaml (or run installer/configure.py)")
        return None
    try:
        cfg = load_config(path)
    except Exception as exc:  # unknown keys, bad YAML, ...
        r.fail(f"{path} rejected: {exc}")
        return None
    r.ok(f"{path} parsed: symbol={cfg.symbol} timeframe={cfg.timeframe} magic={cfg.magic}")

    try:
        from bot.strategy import create_strategy

        strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
        r.ok(f"strategy '{cfg.strategy.name}' built (needs {strategy.min_bars} bars of history)")
        if cfg.history_bars < strategy.min_bars + 96:
            r.warn(f"history_bars={cfg.history_bars} leaves little margin over the {strategy.min_bars} the strategy needs")
    except Exception as exc:
        r.fail(f"strategy '{cfg.strategy.name}' rejected its params: {exc}")

    if cfg.dry_run:
        r.ok("dry_run is ON - signals are logged, no orders are sent")
    else:
        r.warn("dry_run is OFF - this bot WILL send real orders to the logged-in account")
    if cfg.risk.risk_per_trade_pct > 1.0:
        r.warn(f"risk_per_trade_pct={cfg.risk.risk_per_trade_pct}% is aggressive for an unvalidated strategy")
    if cfg.risk.max_daily_loss_pct <= cfg.risk.risk_per_trade_pct:
        r.fail(f"max_daily_loss_pct ({cfg.risk.max_daily_loss_pct}%) <= risk_per_trade_pct "
               f"({cfg.risk.risk_per_trade_pct}%) - the day would stop after one loss")

    journal = Path(cfg.journal_path)
    try:
        journal.parent.mkdir(parents=True, exist_ok=True)
        probe = journal.parent / ".doctor_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        state = "exists" if journal.exists() else "will be created"
        r.ok(f"journal {journal} {state}, directory is writable")
    except OSError as exc:
        r.fail(f"cannot write the journal directory {journal.parent}: {exc}")

    if Path(cfg.kill_switch_file).exists():
        r.warn(f"kill switch file '{cfg.kill_switch_file}' is present - the bot will not open new trades")
    else:
        r.ok(f"kill switch file '{cfg.kill_switch_file}' absent (create it to block new entries)")
    return cfg


def check_mt5(r: Report, cfg) -> None:
    r.section("MetaTrader 5")
    if platform.system() != "Windows":
        r.warn(f"the MetaTrader5 package is Windows-only, this is {platform.system()} - live checks skipped")
        r.info("backtesting works here; run this script on the Windows machine before trading")
        return
    try:
        from bot.broker.mt5_broker import MT5Broker, mt5
    except ImportError as exc:
        r.fail(f"cannot import the MT5 adapter: {exc}")
        return
    if mt5 is None:
        r.fail("MetaTrader5 package not installed - run: pip install MetaTrader5")
        return

    fallback = cfg.server_utc_offset if isinstance(cfg.server_utc_offset, int) else cfg.backtest.server_utc_offset
    broker = MT5Broker(cfg.mt5, fallback_utc_offset=fallback)
    try:
        broker.connect()
    except RuntimeError as exc:
        r.fail(f"{exc}")
        r.info("open MT5, log in, and keep the terminal running; set mt5.path in config if it is not the default install")
        return

    try:
        _check_account(r, mt5, cfg)
        spec = _check_symbol(r, broker, mt5, cfg)
        _check_market(r, broker, mt5, cfg, spec)
    finally:
        broker.shutdown()


def _check_account(r: Report, mt5, cfg) -> None:
    account, terminal = mt5.account_info(), mt5.terminal_info()
    if account is None or terminal is None:
        r.fail("connected but account_info/terminal_info returned nothing - is the terminal logged in?")
        return
    is_demo = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    kind = "DEMO" if is_demo else ("CONTEST" if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST else "REAL")
    r.ok(f"account {account.login} on {account.server}: {kind}, balance {account.balance:.2f} {account.currency}, "
         f"leverage 1:{account.leverage}")
    if not is_demo and not cfg.dry_run:
        r.warn(f"a {kind} account with dry_run OFF - real money is at risk on the next signal")
    if not terminal.trade_allowed:
        r.fail("Algo Trading is disabled in the terminal - orders will be rejected (toolbar button, or Tools > Options > Expert Advisors)")
    else:
        r.ok("Algo Trading is enabled")
    if not account.trade_allowed:
        r.fail("this account is not allowed to trade (investor password, or trading disabled by the broker)")
    if account.margin_free <= 0:
        r.warn(f"free margin is {account.margin_free:.2f} - no room to open a position")


def _check_symbol(r: Report, broker, mt5, cfg):
    try:
        spec = broker.symbol_spec(cfg.symbol)
    except RuntimeError as exc:
        r.fail(f"{exc}")
        candidates = [s.name for s in (mt5.symbols_get() or ()) if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]
        if candidates:
            r.info(f"gold symbols this broker offers: {', '.join(candidates[:12])}")
        return None
    r.ok(f"symbol {cfg.symbol}: contract_size={spec.contract_size} digits={spec.digits} "
         f"volume {spec.volume_min}-{spec.volume_max} step {spec.volume_step}")
    if spec.contract_size != 100:
        r.warn(f"contract_size is {spec.contract_size}, not the 100 oz/lot that backtest.contract_size defaults to "
               f"- set backtest.contract_size={spec.contract_size} or your backtest sizing is wrong")
    if spec.stops_level > 0:
        r.ok(f"broker minimum stop distance: {spec.stops_level:.2f} price units (engine widens SL/TP to respect it)")

    info = mt5.symbol_info(cfg.symbol)
    modes = [name for bit, name in ((1, "FOK"), (2, "IOC"), (4, "RETURN")) if info.filling_mode & bit]
    if modes:
        r.ok(f"filling modes supported: {', '.join(modes)} (adapter picks {modes[0]})")
    else:
        r.warn("symbol reports no filling mode - order_send may fail with retcode 10030")
    if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        r.fail(f"trading is disabled for {cfg.symbol}")
    elif info.trade_mode == mt5.SYMBOL_TRADE_MODE_CLOSEONLY:
        r.warn(f"{cfg.symbol} is close-only right now - new entries will be rejected")
    return spec


def _check_market(r: Report, broker, mt5, cfg, spec) -> None:
    if spec is None:
        return
    try:
        tick = broker.tick(cfg.symbol)
    except RuntimeError as exc:
        r.warn(f"no tick for {cfg.symbol}: {exc} (market closed?)")
        return
    verdict = r.ok if tick.spread <= cfg.risk.max_spread else r.warn
    verdict(f"spread now {tick.spread:.2f} vs max_spread {cfg.risk.max_spread} "
            f"(bid {tick.bid} / ask {tick.ask} at {tick.time_server} server time)")

    try:
        offset = broker.server_utc_offset_hours(cfg.symbol)
        r.ok(f"server UTC offset detected: {offset:+d} h")
        configured = cfg.backtest.server_utc_offset
        if offset != configured:
            r.warn(f"backtest.server_utc_offset is {configured:+d} h - re-fetch history or fix it, "
                   f"or backtest sessions land on the wrong hours (DST)")
    except RuntimeError as exc:
        r.warn(f"{exc}")

    try:
        bars = broker.closed_bars(cfg.symbol, cfg.timeframe, cfg.history_bars)
    except RuntimeError as exc:
        r.fail(f"cannot read {cfg.timeframe} history: {exc}")
        return
    if len(bars) < cfg.history_bars:
        r.warn(f"asked for {cfg.history_bars} {cfg.timeframe} bars, got {len(bars)} "
               f"- set Tools > Options > Charts > 'Max bars in chart' to Unlimited")
    else:
        r.ok(f"history: {len(bars)} {cfg.timeframe} bars up to {bars.time.iloc[-1]} server time")

    _check_sizing(r, broker, cfg, spec, bars)


def _check_sizing(r: Report, broker, cfg, spec, bars) -> None:
    """The number that actually matters: would a real signal produce a valid lot?"""
    from bot.data import normalise
    from bot.risk import position_size
    from bot.strategy import create_strategy

    strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
    prepared = strategy.prepare(normalise(bars, broker.server_utc_offset_hours(cfg.symbol)))
    atr = prepared["atr"].dropna()
    if atr.empty:
        r.warn("not enough history to estimate ATR - cannot check lot sizing")
        return
    typical_atr = float(atr.median())
    sl_dist = typical_atr * float(cfg.strategy.params.get("sl_atr_mult", 1.5))
    equity = broker.equity()
    lots = position_size(equity, cfg.risk.risk_per_trade_pct, sl_dist, spec)
    risk_usd = equity * cfg.risk.risk_per_trade_pct / 100.0
    if lots <= 0:
        r.fail(f"equity {equity:.2f} risking {cfg.risk.risk_per_trade_pct}% (={risk_usd:.2f}) over a typical "
               f"{sl_dist:.2f} stop needs less than the {spec.volume_min} minimum lot - every signal would be skipped")
        r.info("fund the account, raise risk_per_trade_pct, or use a cent account")
    else:
        actual = lots * sl_dist * spec.contract_size
        r.ok(f"typical trade: ATR {typical_atr:.2f} -> stop {sl_dist:.2f}, {lots} lots, "
             f"risking {actual:.2f} of {risk_usd:.2f} budget ({actual / equity * 100:.2f}% of equity)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--skip-mt5", action="store_true", help="config and environment checks only")
    args = ap.parse_args()

    print("XAUUSD bot preflight check")
    r = Report()
    check_environment(r)
    cfg = check_config(r, args.config)
    if cfg is None:
        r.info("fix the config before the MT5 checks can run")
    elif args.skip_mt5:
        r.section("MetaTrader 5")
        r.info("skipped (--skip-mt5)")
    else:
        check_mt5(r, cfg)
    return r.finish()


if __name__ == "__main__":
    raise SystemExit(main())
