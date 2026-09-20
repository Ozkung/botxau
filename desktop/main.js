'use strict';
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');

const pythonEnv = require('./lib/pythonEnv');
const { runOnce, ManagedProcess } = require('./lib/procManager');

// The Python project this app drives. In dev it's the repo this desktop/
// folder lives in; packaged, electron-builder copies it under resources/
// (see package.json "extraResources").
const REPO_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, 'botxau')
  : path.join(__dirname, '..');
const CONFIG_PATH = path.join(REPO_ROOT, 'config.yaml');

// In dev, log every renderer<->main IPC call - the only console this app
// has to debug against before it's packaged.
if (!app.isPackaged) {
  const originalHandle = ipcMain.handle.bind(ipcMain);
  ipcMain.handle = (channel, listener) =>
    originalHandle(channel, async (event, ...args) => {
      const result = await listener(event, ...args);
      console.log(`[ipc] ${channel}(${args.map((a) => JSON.stringify(a)).join(', ')}) ->`, result);
      return result;
    });
}

let mainWindow = null;
let venvSetupRunning = false;
/** @type {ManagedProcess|null} */
let botProc = null;
let lastKillSwitchFile = 'STOP'; // updated from state:refresh so bot:stop-switch touches the right file
let allowQuit = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 800,
    minWidth: 860,
    minHeight: 600,
    backgroundColor: '#101010',
    title: 'XAUUSD Bot',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  if (!app.isPackaged) {
    // Surface renderer console output (and JS errors) in the terminal that
    // launched `npm start` - there is no other console to look at in dev.
    mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
      console.log(`[renderer] ${message} (${sourceId}:${line})`);
    });
  }
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
}

function activePython() {
  const venv = pythonEnv.venvPaths(REPO_ROOT);
  if (fs.existsSync(venv.python)) return venv.python;
  return pythonEnv.findSystemPython()?.command ?? null;
}

// ---------------------------------------------------------------- IPC ----

ipcMain.handle('env:info', async () => ({
  repoRoot: REPO_ROOT,
  platform: process.platform,
  packaged: app.isPackaged,
}));

ipcMain.handle('python:detect', async () => pythonEnv.findSystemPython() || { found: false });

ipcMain.handle('venv:status', async () => ({ ready: pythonEnv.venvReady(REPO_ROOT) }));

ipcMain.handle('venv:setup', async () => {
  if (venvSetupRunning) return { ok: false, error: 'Setup is already running.' };
  venvSetupRunning = true;
  const log = (line) => send('venv:log', line);
  try {
    const py = pythonEnv.findSystemPython();
    if (!py) {
      throw new Error(
        `No Python ${pythonEnv.MIN_PYTHON.join('.')}+ found on PATH. Install it from python.org and try again.`
      );
    }
    log(`Using ${py.command} (Python ${py.version})`);
    const venv = pythonEnv.venvPaths(REPO_ROOT);
    if (pythonEnv.venvReady(REPO_ROOT)) {
      log('.venv already exists - reusing it.');
    } else {
      log('Creating virtual environment...');
      const r = await runOnce(py.command, ['-m', 'venv', venv.dir], { cwd: REPO_ROOT }, log);
      if (r.code !== 0) throw new Error('python -m venv failed - see the log above.');
    }
    log('Upgrading pip...');
    await runOnce(venv.python, ['-m', 'pip', 'install', '--upgrade', 'pip', '--quiet'], { cwd: REPO_ROOT }, log);
    log('Installing requirements (this can take a few minutes)...');
    const install = await runOnce(venv.python, ['-m', 'pip', 'install', '-r', 'requirements.txt'], { cwd: REPO_ROOT }, log);
    if (install.code !== 0) throw new Error('pip install failed - see the log above.');
    log('Checking the MetaTrader5 package...');
    const check = await runOnce(venv.python, ['-c', 'import MetaTrader5'], { cwd: REPO_ROOT }, log);
    if (check.code === 0) {
      log('MetaTrader5 import OK.');
    } else if (process.platform === 'win32') {
      log('WARNING: MetaTrader5 did not import. Re-run setup, or check the pip output above.');
    } else {
      log('MetaTrader5 is Windows-only, so it is expected to be unavailable here. Backtesting still works.');
    }
    log('Setup finished.');
    return { ok: true };
  } catch (err) {
    log(`ERROR: ${err.message}`);
    return { ok: false, error: err.message };
  } finally {
    venvSetupRunning = false;
  }
});

ipcMain.handle('state:refresh', async () => {
  const python = activePython();
  if (!python) return { error: 'No Python interpreter available yet - run Setup first.' };
  const r = await runOnce(python, ['scripts/export_state.py', '--config', CONFIG_PATH, '--limit', '30'], {
    cwd: REPO_ROOT,
  });
  if (r.code !== 0 || !r.stdout.trim()) {
    return { error: r.stderr.trim() || 'export_state.py produced no output.' };
  }
  try {
    const state = JSON.parse(r.stdout.trim().split('\n').pop());
    if (state.config?.kill_switch_file) lastKillSwitchFile = state.config.kill_switch_file;
    state.botRunning = botProc?.isRunning() ?? false;
    return state;
  } catch (err) {
    return { error: `Could not parse state: ${err.message}` };
  }
});

ipcMain.handle('config:save', async (_evt, values) => {
  const python = activePython();
  if (!python) return { ok: false, error: 'No Python interpreter available yet - run Setup first.' };
  // Rebuild from the CURRENT config.yaml when one exists, not from the
  // example template - otherwise every save would silently reset every
  // field the form didn't just submit (notably the MT5 password, which
  // the form never re-populates so it would revert to null on any
  // save that isn't the one that first set it).
  const templatePath = fs.existsSync(CONFIG_PATH) ? CONFIG_PATH : path.join(REPO_ROOT, 'config.example.yaml');
  const args = ['installer/configure.py', '--out', CONFIG_PATH, '--template', templatePath, '--force'];
  const flagFor = {
    symbol: '--symbol',
    dryRun: '--dry-run',
    risk: '--risk',
    dailyLoss: '--daily-loss',
    maxSpread: '--max-spread',
    mt5Path: '--mt5-path',
    mt5Login: '--mt5-login',
    mt5Password: '--mt5-password',
    mt5Server: '--mt5-server',
    telegramToken: '--telegram-token',
    telegramChatId: '--telegram-chat-id',
    serverUtcOffset: '--server-utc-offset',
  };
  for (const [key, flag] of Object.entries(flagFor)) {
    const v = values[key];
    if (v === undefined || v === null || v === '') continue;
    args.push(flag, key === 'dryRun' ? (v ? 'true' : 'false') : String(v));
  }
  const r = await runOnce(python, args, { cwd: REPO_ROOT });
  if (r.code !== 0) return { ok: false, error: (r.stderr || r.stdout).trim() || 'configure.py failed.' };
  return { ok: true };
});

ipcMain.handle('doctor:run', async () => {
  const python = activePython();
  if (!python) return { code: -1, error: 'No Python interpreter available yet - run Setup first.' };
  const log = (line) => send('doctor:log', line);
  const r = await runOnce(python, ['scripts/doctor.py', '--config', CONFIG_PATH], { cwd: REPO_ROOT }, log);
  return { code: r.code };
});

ipcMain.handle('bot:start', async () => {
  if (botProc?.isRunning()) return { ok: false, error: 'The bot is already running.' };
  const python = activePython();
  if (!python) return { ok: false, error: 'No Python interpreter available yet - run Setup first.' };
  if (!fs.existsSync(CONFIG_PATH)) return { ok: false, error: 'config.yaml is missing - fill in Setup first.' };

  botProc = new ManagedProcess(python, ['scripts/run_live.py', '--config', CONFIG_PATH], { cwd: REPO_ROOT });
  botProc.onLog = (line) => send('bot:log', line);
  botProc.onExit = (code, signal) => send('bot:exit', { code, signal });
  try {
    const pid = botProc.start();
    return { ok: true, pid };
  } catch (err) {
    botProc = null;
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('bot:stop-process', async () => {
  if (!botProc?.isRunning()) return { ok: true, alreadyStopped: true };
  const result = await botProc.stop({ graceful: true });
  return result;
});

ipcMain.handle('bot:status', async () => ({
  running: botProc?.isRunning() ?? false,
  pid: botProc?.pid ?? null,
}));

ipcMain.handle('killswitch:set', async (_evt, active) => {
  const file = path.isAbsolute(lastKillSwitchFile) ? lastKillSwitchFile : path.join(REPO_ROOT, lastKillSwitchFile);
  try {
    if (active) {
      fs.writeFileSync(file, `stopped via desktop app on ${new Date().toISOString()}\n`, 'utf8');
    } else if (fs.existsSync(file)) {
      fs.unlinkSync(file);
    }
    return { ok: true, active };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('app:open-repo', async () => {
  await shell.openPath(REPO_ROOT);
  return { ok: true };
});

// ------------------------------------------------------------ lifecycle --

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// A live trading process outliving its control panel, with no window open
// to stop it, is exactly the failure mode this whole project guards
// against elsewhere (kill switch, dry-run default, doctor warnings). Quit
// asks first rather than orphaning it silently.
app.on('before-quit', (event) => {
  if (allowQuit || !botProc?.isRunning()) return;
  event.preventDefault();
  dialog
    .showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Stop bot and quit', 'Leave running and quit', 'Cancel'],
      defaultId: 0,
      cancelId: 2,
      title: 'The bot is still running',
      message: 'The XAUUSD bot process is still running.',
      detail:
        'Stopping it here ends the process cleanly (open positions keep their SL/TP on the broker side). ' +
        'Leaving it running keeps it trading in the background with no window open to control it - ' +
        "you'd need Task Manager to stop it later.",
    })
    .then(async ({ response }) => {
      if (response === 2) return; // Cancel
      if (response === 0) await botProc.stop({ graceful: true });
      allowQuit = true;
      app.quit();
    });
});
