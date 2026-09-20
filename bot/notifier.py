"""Telegram notifications (optional). Failures never stop the bot."""
from __future__ import annotations

import json
import logging
import urllib.request

from .config import NotifyConfig

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: NotifyConfig):
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.telegram_token and self.cfg.telegram_chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
        body = json.dumps({"chat_id": self.cfg.telegram_chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram notify failed: %s", exc)
