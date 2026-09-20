# XAUUSD Bot (MT5 · Python)

บอทเทรดทองคำ XAUUSD อัตโนมัติผ่าน MetaTrader 5 มี backtester ในตัว ใช้โค้ด strategy/risk ชุดเดียวกันทั้งตอน backtest และตอนเทรดจริง
อ่านสถาปัตยกรรมและรายละเอียดกลยุทธ์ได้ที่ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Quick start

```bash
python -m venv .venv && .venv\Scripts\activate      # (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy config.example.yaml config.yaml                  # (macOS/Linux: cp)
```

### 1) ลอง backtest กับข้อมูลสังเคราะห์ (รันได้ทุก OS)

```bash
python scripts/make_sample_data.py --days 365
python scripts/run_backtest.py --csv data/sample_M15.csv --config config.yaml --out results
```

ผลลัพธ์จะอยู่ในโฟลเดอร์ `results/` ได้แก่ `trades.csv`, `equity.csv`, `stats.json` และ `equity.png`
ข้อมูลชุดนี้เป็น random walk จึงบอกอะไรเรื่องกำไรไม่ได้ ใช้แค่ตรวจว่า pipeline ทำงาน

### 2) Backtest ด้วยข้อมูลจริงจาก MT5 (ต้องใช้ Windows)

```bash
python scripts/fetch_history.py --config config.yaml --from 2023-01-01 --to 2026-09-01 --out data/XAUUSD_M15.csv
python scripts/run_backtest.py --csv data/XAUUSD_M15.csv --config config.yaml --from 2023-01-01 --to 2025-01-01
```

ตั้ง `backtest.server_utc_offset` ให้ตรงกับเวลา server ของโบรก (ส่วนใหญ่เป็น 2 หรือ 3)
ใช้ไฟล์ที่ export จาก MT5 เอง (ไฟล์แบบมีคอลัมน์ `<DATE>` `<TIME>`) ได้เหมือนกัน

### 3) รันบน demo account

1. เปิด MT5 แล้ว login บัญชี **demo** จากนั้นกดเปิด **Algo Trading**
2. ตรวจว่า `symbol` ใน config ตรงกับชื่อที่โบรกใช้ (เช่น `XAUUSD`, `XAUUSDm`, `GOLD`)
3. คง `dry_run: true` ไว้ก่อน แล้วรัน:

```bash
python scripts/run_live.py --config config.yaml
```

log จะอยู่ใน `logs/bot.log` และ journal อยู่ใน `data/journal.sqlite`
ถ้าต้องการหยุดเปิดออเดอร์ใหม่ทันที ให้สร้างไฟล์ชื่อ `STOP` ไว้ในโฟลเดอร์ที่รันบอท

## Tests

```bash
pytest -q
```

## โครงสร้าง

```
bot/
  strategy/         base.py, session_breakout.py, registry
  broker/           base.py (interface), mt5_broker.py
  backtest.py       bar-by-bar simulator + stats
  engine.py         live loop
  risk.py           position sizing + guards
  journal.py        SQLite
  notifier.py       Telegram
scripts/            run_backtest, run_live, fetch_history, make_sample_data
docs/ARCHITECTURE.md
```

> ⚠️ ซอฟต์แวร์นี้เป็นเครื่องมือทางเทคนิค ไม่ใช่คำแนะนำการลงทุน การเทรด CFD ทองคำมีความเสี่ยงสูง
