const net = require("net");
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = 3100;
const WEB_DIR = path.resolve(__dirname, "../../web");
const VERSION_PATH = path.join(WEB_DIR, "public", "app-version.json");

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
        host: HOST,
        port: PORT,
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
  if (await isPortOpen(HOST, PORT)) {
    const runningBuildId = await fetchRunningBuildId().catch(() => "");
    if (runningBuildId === expectedBuildId) {
      console.log(`[ensure-web-dev] Reusing existing web dev server on http://${HOST}:${PORT}`);
      return;
    }
    throw new Error(
      `stale web dev server detected on http://${HOST}:${PORT}; expected build ${expectedBuildId}, got ${runningBuildId || "<unknown>"}. Stop the old server before launching desktop dev.`
    );
  }

  console.log(`[ensure-web-dev] Starting web dev server on http://${HOST}:${PORT}`);

  const child =
    process.platform === "win32"
      ? spawn("cmd.exe", ["/d", "/c", "npm run dev"], {
          cwd: WEB_DIR,
          stdio: "inherit",
          shell: false,
        })
      : spawn("npm", ["run", "dev"], {
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
}

main().catch((error) => {
  console.error("[ensure-web-dev] Failed:", error);
  process.exit(1);
});
