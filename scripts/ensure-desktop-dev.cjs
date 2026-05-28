#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "..");
const desktopDir = path.join(repoRoot, "apps", "desktop");
const packageJson = path.join(desktopDir, "package.json");
const tauriPackageJson = path.join(
  desktopDir,
  "node_modules",
  "@tauri-apps",
  "cli",
  "package.json"
);
const tauriBin = path.join(
  desktopDir,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "tauri.cmd" : "tauri"
);

function fail(message) {
  console.error(`[ERROR] ${message}`);
  process.exit(1);
}

function runInstall(command, args, label) {
  console.log(`[INFO] Installing Desktop dependencies with ${label}...`);

  const installCommand =
    process.platform === "win32" ? "cmd.exe" : command;
  const installArgs =
    process.platform === "win32" ? ["/d", "/c", [command, ...args].join(" ")] : args;

  const installResult = spawnSync(installCommand, installArgs, {
    cwd: desktopDir,
    stdio: "inherit",
    env: {
      ...process.env,
      WSL_UTF8: process.env.WSL_UTF8 || "1",
      PYTHONUTF8: process.env.PYTHONUTF8 || "1",
    },
  });

  if (installResult.error) {
    console.error(`[WARN] Failed to launch ${label}: ${installResult.error.message}`);
    return false;
  }

  if (installResult.status !== 0) {
    console.error(`[WARN] ${label} failed with exit code ${installResult.status}.`);
    return false;
  }

  return true;
}

if (!fs.existsSync(packageJson)) {
  fail(`Desktop package manifest not found: ${packageJson}`);
}

if (fs.existsSync(tauriPackageJson) && fs.existsSync(tauriBin)) {
  console.log("[INFO] Desktop dependencies already installed.");
  process.exit(0);
}

console.log("[INFO] Desktop dependencies missing or incomplete.");

let installed = false;

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
installed = runInstall(npmCommand, ["install"], "npm install");

if (!installed) {
  fail("Desktop dependency installation failed.");
}

if (!fs.existsSync(tauriPackageJson) || !fs.existsSync(tauriBin)) {
  fail(`Install finished but Tauri CLI entrypoints are still missing under ${path.join(desktopDir, "node_modules")}`);
}

console.log("[OK] Desktop dependencies installed successfully.");
