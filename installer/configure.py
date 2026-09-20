"""Write config.yaml from config.example.yaml, keeping every comment intact.

Used by the Windows installer so the user never has to hand-edit YAML, but it
is an ordinary script - run it directly to change a setting later:

    python installer/configure.py --symbol XAUUSDm --risk 0.25 --dry-run true

Only keys that already exist in the example file can be set; a typo raises
instead of silently adding a key that bot/config.py would then reject.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config.example.yaml"
TARGET = ROOT / "config.yaml"

# setting -> (section or None for top level, key)
SETTINGS = {
    "symbol": (None, "symbol"),
    "magic": (None, "magic"),
    "dry_run": (None, "dry_run"),
    "risk": ("risk", "risk_per_trade_pct"),
    "daily_loss": ("risk", "max_daily_loss_pct"),
    "max_spread": ("risk", "max_spread"),
    "mt5_path": ("mt5", "path"),
    "mt5_login": ("mt5", "login"),
    "mt5_password": ("mt5", "password"),
    "mt5_server": ("mt5", "server"),
    "telegram_token": ("notify", "telegram_token"),
    "telegram_chat_id": ("notify", "telegram_chat_id"),
    "server_utc_offset": ("backtest", "server_utc_offset"),
}

_SECTION = re.compile(r"^([A-Za-z_][\w]*):\s*$")
_ENTRY = re.compile(r"^(\s*)([A-Za-z_][\w]*):(\s*)([^#\n]*?)(\s*)(#.*)?$")


# Settings whose value must stay a YAML string. A Telegram group chat id is a
# negative integer and an MT5 password can be all digits: written bare, YAML
# would hand bot/config.py an int where the code expects text.
_ALWAYS_STRING = {"symbol", "mt5_path", "mt5_password", "mt5_server",
                  "telegram_token", "telegram_chat_id"}


def quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def as_yaml(value, force_string: bool = False) -> str:
    """Render a Python value the way the example file writes its defaults."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return quote(value) if force_string else str(value)
    text = str(value)
    if force_string:
        return quote(text)
    if text in ("null", "true", "false") or re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    if re.fullmatch(r"[A-Za-z0-9_.\-]+", text):  # plain scalar needs no quotes
        return text
    return quote(text)


def set_value(lines: list[str], section: Optional[str], key: str, value,
              force_string: bool = False) -> list[str]:
    """Replace one key's value in place, leaving its inline comment alone."""
    out = list(lines)
    current: Optional[str] = None
    for i, line in enumerate(out):
        header = _SECTION.match(line)
        if header:
            current = header.group(1)
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            current = None  # a top-level entry ends the previous section
        m = _ENTRY.match(line)
        if not m:
            continue
        indent, name, gap, _old, trail, comment = m.groups()
        at_top_level = indent == ""
        in_target = (section is None and at_top_level) or (section is not None and current == section and not at_top_level)
        if name != key or not in_target:
            continue
        rebuilt = f"{indent}{name}:{gap}{as_yaml(value, force_string)}"
        if comment:
            rebuilt += f"{trail or '  '}{comment}"
        out[i] = rebuilt
        return out
    where = f"{section}.{key}" if section else key
    raise KeyError(f"{where} not found in config.example.yaml")


def build(values: dict, template: str) -> str:
    lines = template.splitlines()
    for name, value in values.items():
        if name not in SETTINGS:
            raise KeyError(f"Unknown setting {name!r}; known: {sorted(SETTINGS)}")
        section, key = SETTINGS[name]
        lines = set_value(lines, section, key, value, force_string=name in _ALWAYS_STRING)
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(TARGET))
    ap.add_argument("--template", default=str(EXAMPLE))
    ap.add_argument("--force", action="store_true", help="overwrite an existing config.yaml")
    ap.add_argument("--symbol")
    ap.add_argument("--magic", type=int)
    ap.add_argument("--dry-run", dest="dry_run", choices=["true", "false"])
    ap.add_argument("--risk", type=float, help="risk per trade, %% of equity")
    ap.add_argument("--daily-loss", dest="daily_loss", type=float)
    ap.add_argument("--max-spread", dest="max_spread", type=float)
    ap.add_argument("--mt5-path", dest="mt5_path")
    ap.add_argument("--mt5-login", dest="mt5_login", type=int)
    ap.add_argument("--mt5-password", dest="mt5_password")
    ap.add_argument("--mt5-server", dest="mt5_server")
    ap.add_argument("--telegram-token", dest="telegram_token")
    ap.add_argument("--telegram-chat-id", dest="telegram_chat_id")
    ap.add_argument("--server-utc-offset", dest="server_utc_offset", type=int)
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists - pass --force to overwrite (it is gitignored, so back it up first)")

    values = {k: v for k, v in vars(args).items() if k in SETTINGS and v is not None}
    if "dry_run" in values:
        values["dry_run"] = values["dry_run"] == "true"

    template = Path(args.template).read_text(encoding="utf-8")
    out.write_text(build(values, template), encoding="utf-8")
    shown = {k: ("***" if "password" in k or "token" in k else v) for k, v in values.items()}
    print(f"Wrote {out}" + (f" with {shown}" if shown else " (all defaults)"))


if __name__ == "__main__":
    main()
