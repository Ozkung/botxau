'use strict';
/**
 * Process helpers shared by main.js: one-shot commands that stream their
 * output line by line, and a small wrapper around a long-running child
 * (the live bot) that tracks whether it is still alive.
 */
const { spawn } = require('child_process');

/**
 * Run one command to completion, calling onLine(text) for every line of
 * stdout/stderr as it arrives (interleaved, in the order it was produced).
 * Resolves {code, stdout, stderr} - never rejects, so a bad exit code is
 * something the caller reads from `code`, not a thrown error.
 */
function runOnce(cmd, args, opts, onLine) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(cmd, args, { windowsHide: true, ...opts });
    } catch (err) {
      onLine?.(`ERROR: could not start ${cmd}: ${err.message}`);
      resolve({ code: -1, stdout: '', stderr: String(err.message) });
      return;
    }
    let stdout = '';
    let stderr = '';
    const outSink = { pending: '' };
    const errSink = { pending: '' };

    const flushLines = (buf, sink) => {
      const parts = (sink.pending + buf).split(/\r?\n/);
      sink.pending = parts.pop() ?? '';
      for (const line of parts) onLine?.(line);
    };

    child.stdout?.on('data', (chunk) => {
      const text = chunk.toString('utf8');
      stdout += text;
      flushLines(text, outSink);
    });
    child.stderr?.on('data', (chunk) => {
      const text = chunk.toString('utf8');
      stderr += text;
      flushLines(text, errSink);
    });
    child.on('error', (err) => {
      onLine?.(`ERROR: ${err.message}`);
      resolve({ code: -1, stdout, stderr: stderr + String(err.message) });
    });
    child.on('close', (code) => {
      if (outSink.pending) onLine?.(outSink.pending);
      if (errSink.pending) onLine?.(errSink.pending);
      resolve({ code, stdout, stderr });
    });
  });
}

/**
 * A long-running child process (the live bot). Tracks its own lifecycle so
 * main.js can ask "is it running" without keeping a second bookkeeping
 * variable in sync by hand.
 */
class ManagedProcess {
  constructor(cmd, args, opts) {
    this.cmd = cmd;
    this.args = args;
    this.opts = opts;
    this.child = null;
    this.onLog = null; // (line) => void
    this.onExit = null; // (code, signal) => void
  }

  start() {
    if (this.child) throw new Error('already running');
    const child = spawn(this.cmd, this.args, { windowsHide: true, ...this.opts });
    this.child = child;
    const sinks = { out: '', err: '' };
    const pump = (chunk, key) => {
      const parts = (sinks[key] + chunk.toString('utf8')).split(/\r?\n/);
      sinks[key] = parts.pop() ?? '';
      for (const line of parts) this.onLog?.(line);
    };
    child.stdout?.on('data', (c) => pump(c, 'out'));
    child.stderr?.on('data', (c) => pump(c, 'err'));
    child.on('exit', (code, signal) => {
      if (sinks.out) this.onLog?.(sinks.out);
      if (sinks.err) this.onLog?.(sinks.err);
      this.child = null;
      this.onExit?.(code, signal);
    });
    return child.pid;
  }

  isRunning() {
    return this.child !== null;
  }

  get pid() {
    return this.child?.pid ?? null;
  }

  /**
   * Ask the process to stop. On POSIX this is a real SIGINT, which
   * run_live.py catches as KeyboardInterrupt and uses to call
   * broker.shutdown() cleanly. Windows has no equivalent Node can send to
   * a plain console child, so there `graceful` is not attempted - the
   * caller should tell the user this is an immediate stop on Windows.
   */
  async stop({ graceful = true, timeoutMs = 5000 } = {}) {
    if (!this.child) return { ok: true, alreadyStopped: true };
    const pid = this.child.pid;
    if (graceful && process.platform !== 'win32') {
      this.child.kill('SIGINT');
      const stopped = await this._waitForExit(timeoutMs);
      if (stopped) return { ok: true, graceful: true };
    }
    if (this.child) this.child.kill(process.platform === 'win32' ? undefined : 'SIGKILL');
    await this._waitForExit(3000);
    return { ok: true, graceful: false, pid };
  }

  _waitForExit(timeoutMs) {
    return new Promise((resolve) => {
      if (!this.child) return resolve(true);
      const timer = setTimeout(() => resolve(this.child === null), timeoutMs);
      const check = setInterval(() => {
        if (this.child === null) {
          clearTimeout(timer);
          clearInterval(check);
          resolve(true);
        }
      }, 100);
    });
  }
}

module.exports = { runOnce, ManagedProcess };
