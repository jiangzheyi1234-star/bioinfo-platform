#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "..");
const webDir = path.join(repoRoot, "apps", "web");
const packageJson = path.join(webDir, "package.json");
const nextPackageJson = path.join(webDir, "node_modules", "next", "package.json");
const nextBin = path.join(
  webDir,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "next.cmd" : "next"
);

function fail(message) {
  console.error(`[ERROR] ${message}`);
  process.exit(1);
}

function runInstall(command, args, label) {
  console.log(`[INFO] Installing Web dependencies with ${label}...`);

  const installCommand =
    process.platform === "win32" ? "cmd.exe" : command;
  const installArgs =
    process.platform === "win32" ? ["/d", "/c", [command, ...args].join(" ")] : args;

  const installResult = spawnSync(installCommand, installArgs, {
    cwd: webDir,
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
  fail(`Web package manifest not found: ${packageJson}`);
}

if (fs.existsSync(nextPackageJson) && fs.existsSync(nextBin)) {
  console.log("[INFO] Web dependencies already installed.");
  process.exit(0);
}

console.log("[INFO] Web dependencies missing or incomplete.");

let installed = false;

if (process.platform === "win32") {
  installed = runInstall(
    "corepack.cmd",
    ["pnpm", "install", "--no-lockfile"],
    "corepack pnpm install --no-lockfile"
  );
  if (!installed) {
    console.log("[INFO] Falling back to npm install on Windows.");
  }
}

if (!installed) {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  installed = runInstall(npmCommand, ["install"], "npm install");
}

if (!installed) {
  fail("Web dependency installation failed.");
}

if (!fs.existsSync(nextPackageJson) || !fs.existsSync(nextBin)) {
  fail(`Install finished but Next.js entrypoints are still missing under ${path.join(webDir, "node_modules")}`);
}

console.log("[OK] Web dependencies installed successfully.");
