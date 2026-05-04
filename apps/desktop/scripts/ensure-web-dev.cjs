const net = require("net");
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 3765;
const WEB_DIR = path.resolve(__dirname, "../../web");
const VERSION_PATH = path.join(WEB_DIR, "public", "app-version.json");
const NEXT_BIN = path.join(
  WEB_DIR,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "next.cmd" : "next"
);
const WEB_HOST =
  (process.env.H2OMETA_WEB_HOST || process.env.WEB_HOST || DEFAULT_HOST).trim() ||
  DEFAULT_HOST;
const WEB_PORT = Number.parseInt(
  process.env.H2OMETA_WEB_PORT || process.env.WEB_PORT || String(DEFAULT_PORT),
  10
);

if (!Number.isInteger(WEB_PORT) || WEB_PORT < 1 || WEB_PORT > 65535) {
  throw new Error(
    `Invalid web port: ${
      process.env.H2OMETA_WEB_PORT || process.env.WEB_PORT || String(DEFAULT_PORT)
    }`
  );
}

function quoteCmdArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

function isPortOpen(host, port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });

    const finish = (value) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(value);
    };

    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

function readExpectedBuildId() {
  const raw = fs.readFileSync(VERSION_PATH, "utf-8");
  const payload = JSON.parse(raw);
  return String(payload.build_id || "").trim();
}

function fetchRunningBuildId() {
  return new Promise((resolve, reject) => {
    const request = http.get(
      {
        host: WEB_HOST,
        port: WEB_PORT,
        path: "/app-version.json",
        timeout: 1200,
      },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
        });
        response.on("end", () => {
          try {
            const payload = JSON.parse(body || "{}");
            resolve(String(payload.build_id || "").trim());
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("version request timeout"));
    });
    request.on("error", reject);
  });
}

async function main() {
  const expectedBuildId = readExpectedBuildId();
  if (await isPortOpen(WEB_HOST, WEB_PORT)) {
    const runningBuildId = await fetchRunningBuildId().catch(() => "");
    if (runningBuildId === expectedBuildId) {
      console.log(
        `[ensure-web-dev] Reusing existing web dev server on http://${WEB_HOST}:${WEB_PORT}`
      );
      return;
    }
    throw new Error(
      `stale web dev server detected on http://${WEB_HOST}:${WEB_PORT}; expected build ${expectedBuildId}, got ${runningBuildId || "<unknown>"}. Stop the old server before launching desktop dev.`
    );
  }

  console.log(
    `[ensure-web-dev] Starting web dev server on http://${WEB_HOST}:${WEB_PORT}`
  );

  if (!fs.existsSync(NEXT_BIN)) {
    throw new Error(`Next binary not found: ${NEXT_BIN}`);
  }

  const args = ["dev", "--hostname", WEB_HOST, "--port", String(WEB_PORT)];

  const child =
    process.platform === "win32"
      ? spawn(
          process.env.ComSpec || "cmd.exe",
          [
            "/d",
            "/s",
            "/c",
            ["call", quoteCmdArg(NEXT_BIN), ...args.map(quoteCmdArg)].join(" "),
          ],
          {
            cwd: WEB_DIR,
            stdio: "inherit",
            shell: false,
            windowsVerbatimArguments: true,
          }
        )
      : spawn(NEXT_BIN, args, {
          cwd: WEB_DIR,
          stdio: "inherit",
          shell: false,
        });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });

  child.on("error", (error) => {
    console.error(`[ensure-web-dev] Failed to launch Next.js: ${error.message}`);
    process.exit(1);
  });
}

main().catch((error) => {
  console.error("[ensure-web-dev] Failed:", error);
  process.exit(1);
});
