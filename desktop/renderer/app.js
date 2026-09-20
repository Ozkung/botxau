'use strict';

// ------------------------------------------------------------ tab switch --

const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('.panel');
tabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    tabs.forEach((t) => t.classList.toggle('active', t === tab));
    const name = tab.dataset.tab;
    panels.forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
    if (name === 'dashboard' || name === 'trades') refreshState();
  });
});

// ----------------------------------------------------------------- utils --

function el(id) { return document.getElementById(id); }

function fmtNum(n, digits = 2) {
  return typeof n === 'number' ? n.toFixed(digits) : '-';
}

function fmtTime(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
      .toLocaleString(undefined, { hour12: false });
  } catch {
    return iso;
  }
}

function appendLine(consoleEl, line) {
  const div = document.createElement('div');
  if (/\[FAIL\]/.test(line)) div.className = 'line-fail';
  else if (/\[WARN\]/.test(line)) div.className = 'line-warn';
  else if (/\[ OK \]/.test(line)) div.className = 'line-ok';
  div.textContent = line;
  consoleEl.appendChild(div);
  consoleEl.scrollTop = consoleEl.scrollHeight;
  // cap history so a long-running bot doesn't grow the DOM forever
  while (consoleEl.childNodes.length > 2000) consoleEl.removeChild(consoleEl.firstChild);
}

function banner(container, kind, text) {
  container.innerHTML = '';
  if (!text) return;
  const div = document.createElement('div');
  div.className = `banner ${kind}`;
  div.textContent = text;
  container.appendChild(div);
}

// --------------------------------------------------------------- footer ---

window.bot.envInfo().then(({ repoRoot, platform, packaged }) => {
  el('footer-repo').textContent = repoRoot;
  el('titlebar-meta').textContent = `${platform}${packaged ? '' : ' (dev)'}`;
});

// ---------------------------------------------------------------- setup ---

const consoleSetup = el('console-setup');
const pillPython = el('pill-python');
const pillVenv = el('pill-venv');
const pillPlatform = el('pill-platform');

function setPill(pillEl, on, text) {
  pillEl.classList.toggle('on', on);
  pillEl.innerHTML = `<span class="dot"></span>${text}`;
}

async function checkEnvironment() {
  const [py, venv, info] = await Promise.all([
    window.bot.detectPython(),
    window.bot.venvStatus(),
    window.bot.envInfo(),
  ]);
  setPill(pillPython, !!py.command, py.command ? `Python ${py.version}` : 'Python: not found');
  setPill(pillVenv, venv.ready, venv.ready ? 'Virtualenv ready' : 'Virtualenv: not set up');
  setPill(pillPlatform, info.platform === 'win32', info.platform === 'win32' ? 'Windows' : `${info.platform} (MT5 needs Windows)`);
  return { py, venv };
}

el('btn-recheck-env').addEventListener('click', checkEnvironment);

el('btn-run-setup').addEventListener('click', async () => {
  const button = el('btn-run-setup');
  button.disabled = true;
  consoleSetup.textContent = '';
  const result = await window.bot.venvSetup();
  await checkEnvironment();
  if (result.ok) appendLine(consoleSetup, 'Setup complete. Continue to the Configuration tab.');
  else appendLine(consoleSetup, `Setup did not finish: ${result.error}`);
  button.disabled = false;
});

window.bot.on('venv:log', (line) => appendLine(consoleSetup, line));

checkEnvironment();

// --------------------------------------------------------------- config ---

const liveWarningCard = el('card-live-warning');
const dryRunToggle = el('f-dry-run');
dryRunToggle.addEventListener('change', () => {
  liveWarningCard.classList.toggle('hidden', dryRunToggle.checked);
});

function populateConfigForm(cfg) {
  el('f-symbol').value = cfg?.symbol ?? '';
  el('f-risk').value = cfg?.risk_per_trade_pct ?? '';
  el('f-daily-loss').value = cfg?.max_daily_loss_pct ?? '';
  el('f-max-spread').value = cfg?.max_spread ?? '';
  dryRunToggle.checked = cfg ? !!cfg.dry_run : true;
  liveWarningCard.classList.toggle('hidden', dryRunToggle.checked);

  el('f-mt5-path').value = cfg?.mt5_path ?? '';
  el('f-mt5-login').value = cfg?.mt5_login ?? '';
  el('f-mt5-server').value = cfg?.mt5_server ?? '';
  el('f-mt5-password').placeholder = cfg?.mt5_password_set
    ? 'already set - leave blank to keep it'
    : 'prefer leaving this blank';

  el('f-tg-chat').value = cfg?.telegram_chat_id ?? '';
  el('f-tg-token').placeholder = cfg?.telegram_token_set
    ? 'already set - leave blank to keep it'
    : '123456:AA...';
  el('f-utc-offset').value = cfg?.server_utc_offset ?? '';
}

// `keepBanner`: a reload right after a successful save re-populates the
// form (to show what was actually persisted) but must not clobber the
// "Saved config.yaml." confirmation the save handler just showed - that
// banner is the only feedback the user gets that anything happened.
async function loadConfigIntoForm(keepBanner = false) {
  const state = await window.bot.stateRefresh();
  if (state.error) {
    if (!keepBanner) banner(el('config-banner'), 'info', 'No config.yaml yet - fill in the fields below and save.');
    populateConfigForm(null);
    return;
  }
  if (!keepBanner) banner(el('config-banner'), null);
  populateConfigForm(state.config);
}

el('btn-reload-config').addEventListener('click', loadConfigIntoForm);

el('btn-save-config').addEventListener('click', async () => {
  const button = el('btn-save-config');
  button.disabled = true;
  const values = {
    symbol: el('f-symbol').value.trim(),
    dryRun: dryRunToggle.checked,
    risk: el('f-risk').value,
    dailyLoss: el('f-daily-loss').value,
    maxSpread: el('f-max-spread').value,
    mt5Path: el('f-mt5-path').value.trim(),
    mt5Login: el('f-mt5-login').value.trim(),
    mt5Password: el('f-mt5-password').value, // intentionally not trimmed
    mt5Server: el('f-mt5-server').value.trim(),
    telegramToken: el('f-tg-token').value.trim(),
    telegramChatId: el('f-tg-chat').value.trim(),
    serverUtcOffset: el('f-utc-offset').value,
  };
  const result = await window.bot.configSave(values);
  if (result.ok) {
    banner(el('config-banner'), 'ok', 'Saved config.yaml.');
    el('f-mt5-password').value = '';
    el('f-tg-token').value = '';
    await loadConfigIntoForm(true);
  } else {
    banner(el('config-banner'), 'error', `Could not save: ${result.error}`);
  }
  button.disabled = false;
});

loadConfigIntoForm();

// ------------------------------------------------------------ dashboard ---

const consoleBot = el('console-bot');
const consoleDoctor = el('console-doctor');
let botRunningKnown = false;

function renderStatusPills(state) {
  const wrap = el('status-pills');
  wrap.innerHTML = '';
  const add = (text, on) => {
    const span = document.createElement('span');
    span.className = `pill${on ? ' on' : ''}`;
    span.innerHTML = `<span class="dot"></span>${text}`;
    wrap.appendChild(span);
  };
  if (state.error) {
    add('Config: not found', false);
    return;
  }
  add(state.config.dry_run ? 'Mode: DRY-RUN' : 'Mode: LIVE', state.config.dry_run);
  add(`Symbol: ${state.config.symbol}`, true);
  add(state.botRunning ? 'Bot process: RUNNING' : 'Bot process: STOPPED', state.botRunning);
  add(state.kill_switch_active ? 'Kill switch: ON' : 'Kill switch: off', !state.kill_switch_active);
}

function renderTodayStats(state) {
  const cards = el('today-stats').querySelectorAll('.stat-value');
  if (state.error) {
    cards.forEach((c) => (c.textContent = '-'));
    return;
  }
  cards[0].textContent = state.trades_today ?? 0;
  cards[1].textContent = state.today ? fmtNum(state.today.start_equity) : '-';
  cards[2].textContent = state.config.max_trades_per_day ?? '-';
}

async function refreshState() {
  const state = await window.bot.stateRefresh();
  renderStatusPills(state);
  renderTodayStats(state);
  renderTrades(state);

  botRunningKnown = !!state.botRunning;
  el('btn-start-bot').disabled = botRunningKnown || !!state.error;
  el('btn-stop-bot').disabled = !botRunningKnown;
  el('btn-toggle-killswitch').textContent = state.kill_switch_active
    ? 'Remove kill switch'
    : 'Activate kill switch';
  if (!botRunningKnown && !consoleBot.childNodes.length) {
    consoleBot.setAttribute('data-placeholder', 'The bot is not running.');
  }
  return state;
}

el('btn-refresh-state').addEventListener('click', refreshState);

el('btn-start-bot').addEventListener('click', async () => {
  const button = el('btn-start-bot');
  button.disabled = true;
  consoleBot.textContent = '';
  const result = await window.bot.botStart();
  if (!result.ok) {
    appendLine(consoleBot, `Could not start: ${result.error}`);
    button.disabled = false;
  }
  await refreshState();
});

el('btn-stop-bot').addEventListener('click', async () => {
  const button = el('btn-stop-bot');
  button.disabled = true;
  appendLine(consoleBot, '--- stopping process ---');
  const result = await window.bot.botStopProcess();
  appendLine(consoleBot, result.graceful === false ? '--- stopped (forced) ---' : '--- stopped ---');
  await refreshState();
});

el('btn-toggle-killswitch').addEventListener('click', async () => {
  const state = await window.bot.stateRefresh();
  const result = await window.bot.killSwitchSet(!state.kill_switch_active);
  if (!result.ok) banner(el('dashboard-banner'), 'error', `Could not update kill switch: ${result.error}`);
  else banner(el('dashboard-banner'), null);
  await refreshState();
});

el('btn-run-doctor').addEventListener('click', async () => {
  const button = el('btn-run-doctor');
  button.disabled = true;
  consoleDoctor.textContent = '';
  const result = await window.bot.doctorRun();
  appendLine(consoleDoctor, `\n(exit code ${result.code})`);
  button.disabled = false;
});

el('btn-clear-log').addEventListener('click', () => { consoleBot.textContent = ''; });

window.bot.on('bot:log', (line) => appendLine(consoleBot, line));
window.bot.on('bot:exit', ({ code, signal }) => {
  appendLine(consoleBot, `--- process exited (code ${code ?? 'null'}${signal ? `, signal ${signal}` : ''}) ---`);
  refreshState();
});
window.bot.on('doctor:log', (line) => appendLine(consoleDoctor, line));

// ---------------------------------------------------------------- trades ---

function renderTrades(state) {
  const wrap = el('trades-table-wrap');
  const events = el('events-list');
  if (state.error || !state.entries) {
    wrap.innerHTML = `<div class="empty-state">${state.error || 'No data yet.'}</div>`;
    events.innerHTML = '';
    return;
  }
  if (!state.entries.length) {
    wrap.innerHTML = '<div class="empty-state">No trades yet.</div>';
  } else {
    const rows = state.entries.map((e) => `
      <tr>
        <td class="text-mute">${fmtTime(e.created_utc)}</td>
        <td>${e.side}</td>
        <td class="mono-num">${fmtNum(e.lots, 2)}</td>
        <td class="mono-num">${fmtNum(e.price)}</td>
        <td class="mono-num">${fmtNum(e.sl)}</td>
        <td class="mono-num">${fmtNum(e.tp)}</td>
        <td>${e.dry_run ? 'dry' : 'live'}</td>
        <td class="${e.ok ? 'text-body' : 'text-mute'}">${e.ok ? 'ok' : 'blocked'}</td>
        <td class="text-mute">${e.message || e.reason || ''}</td>
      </tr>`).join('');
    wrap.innerHTML = `
      <table>
        <thead><tr>
          <th>Time</th><th>Side</th><th>Lots</th><th>Price</th><th>SL</th><th>TP</th>
          <th>Mode</th><th>Result</th><th>Note</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  if (!state.events?.length) {
    events.innerHTML = '<div class="empty-state">No events yet.</div>';
  } else {
    const rows = state.events.map((e) => `
      <tr>
        <td class="text-mute">${fmtTime(e.created_utc)}</td>
        <td class="${e.level === 'ERROR' ? 'text-body' : 'text-mute'}">${e.level}</td>
        <td>${e.message}</td>
      </tr>`).join('');
    events.innerHTML = `<table><tbody>${rows}</tbody></table>`;
  }
}

el('btn-refresh-trades').addEventListener('click', refreshState);
el('btn-open-repo').addEventListener('click', () => window.bot.openRepo());

// ---------------------------------------------------------------- polling --

refreshState();
setInterval(() => {
  const active = document.querySelector('.panel.active')?.id;
  if (active === 'tab-dashboard' || active === 'tab-trades') refreshState();
}, 4000);
