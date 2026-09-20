# XAUUSD Bot - desktop control panel

An Electron GUI that replaces the old `install.bat` / PowerShell installer.
It drives the same Python backend (`installer/configure.py`,
`scripts/doctor.py`, `scripts/run_live.py`, `scripts/export_state.py`) as
before by shelling out to it - this app has no trading logic of its own,
it is a cockpit around the Python project one level up.

## Develop

```bash
cd desktop
npm install
npm start
```

In dev, `REPO_ROOT` is resolved as `desktop/..` - the repo this folder
lives in. Every renderer<->main IPC call and any renderer console output is
logged to the terminal that ran `npm start` (see the `!app.isPackaged`
guards in `main.js`); there is no other console available before the app
is packaged.

## Build a Windows installer

```bash
npm run dist
```

Uses `electron-builder` with the `extraResources` config in `package.json`,
which copies `bot/`, `scripts/`, `installer/configure.py`,
`config.example.yaml`, `requirements.txt` and `docs/` from the repo root
into `resources/botxau` inside the packaged app. At runtime the packaged
app resolves `REPO_ROOT` to that folder (`main.js`, `app.isPackaged`
branch) instead of `desktop/..`.

The packaged app still needs the user's own Python 3.10+ on PATH - it is
not bundled. The Setup tab creates a `.venv` inside `resources/botxau` and
installs `requirements.txt` into it (including the Windows-only
`MetaTrader5` package) the first time it runs.

## Architecture

- `main.js` - window + IPC handlers. Spawns Python as a child process for
  every action; never talks to MT5 or the filesystem's trading state
  directly except the kill-switch file and reading `env:info`.
- `lib/pythonEnv.js` - finds a system Python 3.10+, computes `.venv` paths
  for the current platform.
- `lib/procManager.js` - `runOnce()` for one-shot commands (doctor, export,
  configure) that stream their output line by line, and `ManagedProcess`
  for the long-running bot process (`scripts/run_live.py`).
- `preload.js` - the only bridge between renderer and main, exposing a
  fixed `window.bot.*` API via `contextBridge` (context isolation +
  sandbox are both on).
- `renderer/` - plain HTML/CSS/JS, four tabs: Setup, Configuration,
  Dashboard, Trades. No build step, no framework.

## Known limits

- **Graceful stop is POSIX-only.** `ManagedProcess.stop()` sends `SIGINT`
  first on macOS/Linux, which `run_live.py` catches as `KeyboardInterrupt`
  and uses to call `broker.shutdown()` cleanly. Node has no equivalent
  signal it can deliver to a plain Windows console child, so on Windows
  "Stop process" is an immediate `TerminateProcess` - open positions are
  unaffected (their SL/TP lives on the broker's server), but the MT5 IPC
  side is not closed cleanly. This mirrors what closing the old
  `start-bot.bat` console window already did.
- **The live log only covers this session.** `console-bot` shows output
  since *this window* started the bot process. If the app is closed and
  reopened while the bot is still running (the user chose "leave running"
  on the quit prompt), the new window has no log backlog - only
  `logs/bot.log` on disk has the full history.
- **No packaged build has been produced or run.** `npm start` has been
  smoke-tested (headless, via Chrome DevTools Protocol driving real button
  clicks - see the session notes), but `npm run dist` has not been
  exercised, and nothing here has touched a real MT5 terminal.
