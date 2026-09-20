'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Only these channels can be subscribed to from the renderer - a fixed
// allow-list so a compromised page can't ask preload to forward arbitrary
// main-process events.
const STREAM_CHANNELS = ['venv:log', 'bot:log', 'bot:exit', 'doctor:log'];

contextBridge.exposeInMainWorld('bot', {
  envInfo: () => ipcRenderer.invoke('env:info'),
  detectPython: () => ipcRenderer.invoke('python:detect'),
  venvStatus: () => ipcRenderer.invoke('venv:status'),
  venvSetup: () => ipcRenderer.invoke('venv:setup'),
  stateRefresh: () => ipcRenderer.invoke('state:refresh'),
  configSave: (values) => ipcRenderer.invoke('config:save', values),
  doctorRun: () => ipcRenderer.invoke('doctor:run'),
  botStart: () => ipcRenderer.invoke('bot:start'),
  botStopProcess: () => ipcRenderer.invoke('bot:stop-process'),
  botStatus: () => ipcRenderer.invoke('bot:status'),
  killSwitchSet: (active) => ipcRenderer.invoke('killswitch:set', active),
  openRepo: () => ipcRenderer.invoke('app:open-repo'),

  /** Subscribe to a streamed channel; returns an unsubscribe function. */
  on(channel, callback) {
    if (!STREAM_CHANNELS.includes(channel)) {
      throw new Error(`Unknown channel: ${channel}`);
    }
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
  },
});
