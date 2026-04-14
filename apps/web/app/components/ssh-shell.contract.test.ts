import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./ssh-shell.tsx"), "utf-8");
const globalsCss = readFileSync(resolve(import.meta.dirname, "../globals.css"), "utf-8");
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
  assert.match(source, /data-terminal-input-enabled=/);
  assert.doesNotMatch(source, /terminalCommand/);
  assert.doesNotMatch(source, /submitTerminalCommand/);
  assert.doesNotMatch(source, /终端已就绪，输入命令后按 Enter 执行/);
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
