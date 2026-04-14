import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./ssh-shell.tsx"), "utf-8");

test("ssh shell source includes the frozen remote terminal v1 UI copy", () => {
  assert.match(source, /终端|远程终端/);
  assert.match(source, /远程终端 · 当前服务器/);
  assert.match(source, /请先连接远端服务器/);
  assert.match(source, /SSH 已断开，终端会话已结束/);
});

test("ssh shell source mounts xterm.js inside the docked terminal buffer", () => {
  assert.match(source, /import\("@xterm\/xterm"\)/);
  assert.match(source, /import\("@xterm\/addon-fit"\)/);
  assert.match(source, /nextTerminal\.onData\(\(data\) =>/);
  assert.match(source, /data-terminal-input-enabled=/);
  assert.doesNotMatch(source, /terminalCommand/);
  assert.doesNotMatch(source, /submitTerminalCommand/);
  assert.doesNotMatch(source, /终端已就绪，输入命令后按 Enter 执行/);
});

test("ssh shell source stays within the v1 non-goals", () => {
  for (const bannedCopy of ["本地终端模式", "切换到本地终端", "多 tab", "快捷命令", "文件管理", "端口转发", "安装联动"]) {
    assert.doesNotMatch(source, new RegExp(bannedCopy));
  }
});
