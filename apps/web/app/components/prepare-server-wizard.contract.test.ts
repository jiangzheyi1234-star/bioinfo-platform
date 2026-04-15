import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./prepare-server-wizard.tsx"), "utf-8");
const inspectionSource = readFileSync(resolve(import.meta.dirname, "./runtime-inspection.ts"), "utf-8");

test("prepare server wizard contains the agreed four-step flow", () => {
  for (const expected of ["检测环境", "运行时决策", "准备 Runtime", "完成"]) {
    assert.match(source, new RegExp(expected));
  }
});

test("prepare server wizard contains the agreed Docker decision options", () => {
  for (const expected of ["我会自己安装 Docker", "软件协助安装 Docker", "继续使用 Conda Runtime"]) {
    assert.match(source, new RegExp(expected));
  }
});

test("prepare server wizard no longer includes prototype-mode fallback copy", () => {
  assert.doesNotMatch(source, /UI 原型模式/);
  assert.doesNotMatch(source, /后端检测\/安装接口尚未接通/);
  assert.doesNotMatch(source, /prototypeMode/);
  assert.doesNotMatch(source, /FALLBACK_PREFLIGHT/);
});

test("prepare server wizard exposes explicit inspection failure copy", () => {
  assert.match(source, /运行时检测失败|检测失败/);
  assert.match(source, /重新检测/);
  assert.match(inspectionSource, /本地 API 未启动或不可达/);
});

test("prepare server wizard still requires next-step confirmation from step 1", () => {
  assert.match(source, />\s*下一步\s*</);
  assert.doesNotMatch(source, /step1PrimaryAction/);
});

test("prepare server wizard step 1 no longer renders the right-side strategy card", () => {
  assert.doesNotMatch(source, /智能部署决策/);
  assert.doesNotMatch(source, /推荐 PROFILE/);
  assert.doesNotMatch(source, /可选运行方式/);
});

test("prepare server wizard does not expose raw fetch failures", () => {
  assert.doesNotMatch(source, /Failed to fetch/);
  assert.match(inspectionSource, /本地 API 未启动或不可达/);
});

test("runtime prepare start now distinguishes health-check success from install-request disconnects", () => {
  assert.match(source, /startRemoteEnvInstall/);
  assert.match(inspectionSource, /本地 API 健康检查已通过，但启动 Runtime 请求时连接中断/);
  assert.match(inspectionSource, /\/health/);
});

test("prepare server wizard uses a fixed dialog shell size", () => {
  assert.match(source, /w-\[960px\]/);
  assert.match(source, /h-\[760px\]/);
});
