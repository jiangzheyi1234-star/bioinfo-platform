const net = require("net");
const { spawn } = require("child_process");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = 3100;
const WEB_DIR = path.resolve(__dirname, "../../web");

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

async function main() {
  if (await isPortOpen(HOST, PORT)) {
    console.log(`[ensure-web-dev] Reusing existing web dev server on http://${HOST}:${PORT}`);
    return;
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
