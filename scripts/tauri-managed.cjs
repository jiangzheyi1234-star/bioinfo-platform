#!/usr/bin/env node

const { spawn } = require("node:child_process");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const desktopDir = path.join(repoRoot, "apps", "desktop");
const localAppData = process.env.LOCALAPPDATA;
const home = process.env.HOME || process.env.USERPROFILE;

function defaultCargoTargetDir() {
  if (process.env.H2OMETA_CARGO_TARGET_DIR) {
    return process.env.H2OMETA_CARGO_TARGET_DIR;
  }
  if (process.env.CARGO_TARGET_DIR) {
    return process.env.CARGO_TARGET_DIR;
  }
  if (localAppData) {
    return path.join(localAppData, "H2OMeta", "dev-cache", "cargo-target", "bio_ui");
  }
  if (home) {
    return path.join(home, ".cache", "h2ometa", "cargo-target", "bio_ui");
  }
  return path.join(repoRoot, "apps", "desktop", "src-tauri", "target");
}

const isWindows = process.platform === "win32";
const tauriBin = path.join(
  desktopDir,
  "node_modules",
  ".bin",
  isWindows ? "tauri.cmd" : "tauri"
);
const args = process.argv.slice(2);

const child = isWindows
  ? spawn(
      process.env.ComSpec || "cmd.exe",
      ["/d", "/s", "/c", tauriBin, ...args],
      {
        stdio: "inherit",
        cwd: desktopDir,
        env: {
          ...process.env,
          CARGO_TARGET_DIR: defaultCargoTargetDir(),
        },
      }
    )
  : spawn(tauriBin, args, {
      stdio: "inherit",
      cwd: desktopDir,
      env: {
        ...process.env,
        CARGO_TARGET_DIR: defaultCargoTargetDir(),
      },
    });

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});

child.on("error", (error) => {
  console.error(`[ERROR] Failed to launch managed Tauri CLI: ${error.message}`);
  process.exit(1);
});
