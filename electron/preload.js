"use strict"

/**
 * Electron preload script.
 *
 * Runs in an isolated context (contextIsolation: true, sandbox: true) and is
 * the ONLY bridge between the React renderer and the host. Node APIs are never
 * exposed; only the narrow window controls below are made available via
 * contextBridge.
 */

const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("desktop", {
  isElectron: true,
  platform: process.platform,
  minimize: () => ipcRenderer.send("window:minimize"),
  close: () => ipcRenderer.send("window:close"),
  toggleAlwaysOnTop: () => ipcRenderer.invoke("window:toggle-always-on-top"),
  isAlwaysOnTop: () => ipcRenderer.invoke("window:is-always-on-top"),
  onAlwaysOnTopChanged: (callback) => {
    const listener = (_event, pinned) => callback(pinned)
    ipcRenderer.on("window:always-on-top-changed", listener)
    return () => ipcRenderer.removeListener("window:always-on-top-changed", listener)
  },
})
