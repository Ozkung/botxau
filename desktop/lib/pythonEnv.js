'use strict';
/**
 * Locate a Python 3.10+ interpreter and compute .venv paths.
 * Mirrors the logic the earlier installer/install.ps1 used (py -3, then
 * python3, then python), reimplemented in Node so it works the same way
 * whether Electron is running on Windows, macOS or Linux.
 */
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const MIN_PYTHON = [3, 10];

function runSync(cmd, args) {
  try {
    const res = spawnSync(cmd, args, { encoding: 'utf8', timeout: 5000, windowsHide: true });
    if (res.error || res.status !== 0 || !res.stdout) return null;
    return res.stdout.trim();
  } catch {
    return null;
  }
}

function meetsMin(version) {
  const [maj, min] = version.split('.').map(Number);
  return maj > MIN_PYTHON[0] || (maj === MIN_PYTHON[0] && min >= MIN_PYTHON[1]);
}

/** Find a Python 3.10+ interpreter on PATH. Returns {command, version} or null. */
function findSystemPython() {
  const candidates = [];
  if (process.platform === 'win32') {
    candidates.push(['py', ['-3', '-c', 'import sys;print(sys.executable)']]);
  }
  for (const exe of ['python3', 'python']) {
    candidates.push([exe, ['-c', 'import sys;print(sys.executable)']]);
  }
  for (const [cmd, args] of candidates) {
    const exePath = runSync(cmd, args);
    if (!exePath) continue;
    const version = runSync(exePath, ['-c', "import sys;print('%d.%d.%d'%sys.version_info[:3])"]);
    if (version && meetsMin(version)) return { command: exePath, version };
  }
  return null;
}

/** Paths inside repoRoot/.venv, for the platform Electron is running on. */
function venvPaths(repoRoot) {
  const dir = path.join(repoRoot, '.venv');
  const isWin = process.platform === 'win32';
  const bin = isWin ? 'Scripts' : 'bin';
  return {
    dir,
    python: path.join(dir, bin, isWin ? 'python.exe' : 'python'),
    pip: path.join(dir, bin, isWin ? 'pip.exe' : 'pip'),
  };
}

function venvReady(repoRoot) {
  return fs.existsSync(venvPaths(repoRoot).python);
}

module.exports = { findSystemPython, venvPaths, venvReady, MIN_PYTHON };
