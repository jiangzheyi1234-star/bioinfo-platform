import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./ssh-shell.tsx"), "utf-8");
const globalsCss = readFileSync(resolve(import.meta.dirname, "../globals.css"), "utf-8");
const apiSource = readFileSync(resolve(import.meta.dirname, "../../../api/main.py"), "utf-8");
const packageJson = JSON.parse(readFileSync(resolve(import.meta.dirname, "../../package.json"), "utf-8")) as {
  dependencies?: Record<string, string>;
};

test("ssh shell source includes the frozen remote terminal v1 UI copy", () => {
  assert.match(source, /终端|远程终端/);
  assert.match(source, /远程终端 · 当前服务器/);
  assert.match(source, /请先连接远端服务器/);
  assert.match(source, /SSH 已断开，终端会话已结束/);
  assert.match(source, /@xterm\/xterm/);
  assert.match(source, /@xterm\/addon-fit/);
});

test("ssh shell source mounts xterm.js inside the docked terminal buffer", () => {
  assert.match(source, /onData\(\(data\) =>/);
  assert.match(source, /aria-label="调整终端高度"/);
  assert.match(source, /cursor-row-resize/);
  assert.match(source, /ssh-terminal h-full w-full/);
  assert.match(source, /openTerminalStream/);
  assert.match(source, /type: "resize"/);
  assert.doesNotMatch(source, /terminalCommand/);
  assert.doesNotMatch(source, /submitTerminalCommand/);
  assert.doesNotMatch(source, /终端已就绪，输入命令后按 Enter 执行/);
  assert.doesNotMatch(source, /直接在终端区域内输入命令，按 Enter 执行/);
});

test("ssh shell package declares xterm dependencies", () => {
  assert.equal(packageJson.dependencies?.["@xterm/xterm"] !== undefined, true);
  assert.equal(packageJson.dependencies?.["@xterm/addon-fit"] !== undefined, true);
});

test("ssh shell global styles include xterm.css", () => {
  assert.match(globalsCss, /@import "@xterm\/xterm\/css\/xterm\.css";/);
});

test("ssh shell source stays within the v1 non-goals", () => {
  for (const bannedCopy of ["本地终端模式", "切换到本地终端", "多 tab", "快捷命令", "文件管理", "端口转发", "安装联动"]) {
    assert.doesNotMatch(source, new RegExp(bannedCopy));
  }
});

test("ssh shell source uses in-buffer terminal input instead of a standalone command field", () => {
  assert.doesNotMatch(source, /terminalCommand/);
  assert.doesNotMatch(source, /终端已就绪，输入命令后按 Enter 执行/);
});

test("ssh shell source uses websocket streaming instead of polling terminal output", () => {
  assert.match(source, /terminalStreamRef/);
  assert.match(source, /type: "input"/);
  assert.match(source, /type: "resize"/);
  assert.doesNotMatch(source, /terminal\/sessions\/\$\{terminalSessionId\}\?cursor=/);
  assert.doesNotMatch(source, /terminal\/sessions\/\$\{sessionId\}\/input/);
  assert.match(apiSource, /@app\.websocket\(\"\/api\/v1\/ssh\/terminal\/sessions\/\{session_id\}\/stream\"\)/);
  assert.doesNotMatch(apiSource, /@app\.get\(\"\/api\/v1\/ssh\/terminal\/sessions\/\{session_id\}\"\)/);
  assert.doesNotMatch(apiSource, /@app\.post\(\"\/api\/v1\/ssh\/terminal\/sessions\/\{session_id\}\/input\"\)/);
});

test("ssh shell source includes clipboard copy and paste handlers", () => {
  assert.match(source, /writeTerminalClipboard/);
  assert.match(source, /readTerminalClipboard/);
  assert.match(source, /attachCustomKeyEventHandler/);
  assert.match(source, /node\.addEventListener\("paste"/);
});

test("ssh shell uses a single runtime settings entry", () => {
  assert.match(source, /运行时设置/);
  assert.doesNotMatch(source, /重新检查环境/);
  assert.doesNotMatch(source, /prepareDialogMode/);
});

test("ssh shell remembers configured runtime per server identity and only blocks on confirmed missing state", () => {
  assert.match(source, /lastSilentRuntimeCheckKeyRef/);
  assert.match(source, /resolvedRuntimeState/);
  assert.match(source, /const checkedStatus = await detectRuntimeReadiness\(\)/);
  assert.match(source, /checkedStatus === "missing"/);
  assert.match(source, /resolvedRuntimeState\?\.hostKey === runtimeIdentityKey/);
  assert.match(source, /resolvedRuntimeState\?\.verificationStatus === "verified"/);
  assert.doesNotMatch(source, /rememberRuntimePrepared/);
  assert.doesNotMatch(source, /clearRememberedRuntimePrepared/);
});

test("desktop dev origin is allowed by api CORS config", () => {
  assert.match(apiSource, /http:\/\/127\.0\.0\.1:3100/);
});
