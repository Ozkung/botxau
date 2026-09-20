# XAUUSD Bot (MT5 · Python)

บอทเทรดทองคำ XAUUSD อัตโนมัติผ่าน MetaTrader 5 มี backtester ในตัว ใช้โค้ด strategy/risk ชุดเดียวกันทั้งตอน backtest และตอนเทรดจริง
อ่านสถาปัตยกรรมและรายละเอียดกลยุทธ์ได้ที่ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## ติดตั้งบน Windows (วิธีที่แนะนำ): แอป Desktop

ตัวติดตั้งแบบ `.bat`/`.ps1` ถูกแทนที่ด้วยแอป **Electron** ใน [`desktop/`](desktop/) แล้ว หน้าตาแบ่งเป็น 4 แท็บ:

| แท็บ | ทำอะไร |
|---|---|
| **Setup** | หา Python 3.10+, สร้าง `.venv`, ลงไลบรารีทั้งหมด (รวม `MetaTrader5`) — log สดระหว่างติดตั้ง |
| **Configuration** | ฟอร์มเขียน `config.yaml` (symbol, risk, dry-run, MT5 login/server, Telegram) โดยคงคอมเมนต์เดิมไว้ครบ — บันทึกซ้ำได้โดยไม่ทับรหัสผ่านเดิมที่ตั้งไว้ |
| **Dashboard** | ปุ่ม Start/Stop bot, kill switch (สร้าง/ลบไฟล์ `STOP`), รัน preflight check, ดู log สดของบอทที่รันอยู่ |
| **Trades** | อ่าน `data/journal.sqlite` โดยตรง แสดงเทรดและ event ล่าสุด ไม่ต้องรอบอทรันอยู่ |

รันตอน dev:

```bash
cd desktop
npm install
npm start
```

Build เป็นตัวติดตั้ง Windows (NSIS):

```bash
cd desktop
npm run dist
```

ปิดแอปขณะบอทกำลังรันอยู่ แอปจะถามก่อนเสมอว่าจะ "Stop bot and quit" หรือ "Leave running and quit" กันไม่ให้บอทค้างรันเงียบๆ โดยไม่มีหน้าต่างควบคุมเหลืออยู่ ดูรายละเอียดสถาปัตยกรรมของแอปที่ [`desktop/README.md`](desktop/README.md)

ถ้าต้องการให้บอทขึ้นเองหลัง VPS รีบูตโดยไม่ต้องมีคนเปิดแอป (ไม่ผ่าน Electron) ยังใช้ `installer\install-task.ps1` ได้เหมือนเดิม — ดูข้อ 8 ใน `docs/ARCHITECTURE.md`

> ปุ่ม **kill switch** ในแท็บ Dashboard **ไม่ได้ปิด position ที่เปิดอยู่** และไม่ได้ฆ่าโปรเซส มันแค่ห้ามเปิดออเดอร์ใหม่ ส่วน position เดิมยังมี SL/TP ฝั่ง server คุ้มครองและบอทยังดูแลต่อ (breakeven, force close) ถ้าจะปิดเดี๋ยวนี้ให้ปิดใน MT5 เอง ส่วนปุ่ม **Stop process** จะจบโปรเซสจริง — บน Windows เป็นการหยุดทันที (ไม่มี graceful shutdown ผ่าน signal เหมือน POSIX) ดู "Known limits" ใน `desktop/README.md`

`scripts/doctor.py` ตรวจให้ตั้งแต่เวอร์ชัน Python, key ที่พิมพ์ผิดใน config, บัญชีเป็น demo หรือ real, Algo Trading เปิดหรือยัง, symbol มีจริงไหม (ถ้าไม่มีจะลิสต์ชื่อทองที่โบรกมีให้), filling mode, stops level, spread ตอนนี้เทียบ `max_spread`, offset เวลา server เทียบกับใน config, จำนวนแท่งย้อนหลังที่ดึงได้ และที่สำคัญที่สุด — **ล็อตที่บอทจะส่งจริงจากเงินในพอร์ตตอนนี้** ถ้าน้อยกว่าล็อตขั้นต่ำมันจะข้ามทุกสัญญาณ ซึ่งเป็นกับดักที่เจอบ่อยกับพอร์ตเล็ก

## Quick start (ติดตั้งเอง / macOS / Linux)

```bash
python -m venv .venv && .venv\Scripts\activate      # (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy config.example.yaml config.yaml                  # (macOS/Linux: cp)
```

แก้ค่าใน `config.yaml` ด้วยมือก็ได้ หรือใช้ตัวเขียนที่คงคอมเมนต์ไว้ครบ:

```bash
python installer/configure.py --symbol XAUUSDm --risk 0.25 --dry-run true
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

### อ่านผลลัพธ์

| ตัวเลขใน `stats.json` | ความหมาย |
|---|---|
| `max_drawdown_pct` | drawdown จาก equity ที่ mark-to-market ทุกแท่งด้วยราคาที่แย่ที่สุดในแท่งนั้น นับสิ่งที่ position ที่เปิดอยู่พาเราผ่านมาด้วย — **ใช้ตัวนี้เป็นเกณฑ์** |
| `max_drawdown_closed_pct` | drawdown จาก balance ที่ปิดเทรดแล้วเท่านั้น จะน้อยกว่าหรือเท่ากับตัวบน |
| `expectancy_r`, `avg_win_r`, `avg_loss_r` | R หัก commission แล้ว ตรงกับ `pnl` ดังนั้นเทรดที่โดน SL จะแย่กว่า −1R นิดหน่อย |
| `spread_model` | backtest ใช้ spread จากไหน (คอลัมน์ใน CSV หรือค่าคงที่) พร้อม median/max เป็น USD — เช็กว่าตรงกับบัญชีจริงไหม |
| `signals_skipped` | สัญญาณที่ถูก guard บล็อก แยกตามเหตุผล รวมถึง `spread too wide` |

`spread` ใน CSV เป็นหน่วย **point** ตามที่ MT5 ให้มา (XAUUSD 2 หลัก: 25 point = $0.25) ถ้าไฟล์ของคุณเก็บเป็น USD อยู่แล้ว ให้ตั้ง `backtest.spread_source: fixed`

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

## หมายเหตุเรื่อง hosting

บอทฝั่ง live ต้องรันบน **Windows** เท่านั้น เพราะไลบรารี `MetaTrader5` มีแต่ Windows build และมันคุยกับ MT5 terminal ผ่าน IPC ไม่ใช่ API ที่ยิงตรงเข้าโบรก จึงต้องมี terminal เปิดค้างและ login ไว้ — deploy ลง PaaS ที่เป็น Linux (Render, Railway, Fly.io) ไม่ได้ ส่วน backtester เป็น pandas ล้วน รันได้ทุก OS

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
