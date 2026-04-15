import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./prepare-server-wizard.tsx"), "utf-8");
const inspectionSource = readFileSync(resolve(import.meta.dirname, "./runtime-inspection.ts"), "utf-8");

test("prepare server wizard keeps runtime setup grouped into detection, prepare, and completion", () => {
  for (const expected of ["检测环境", "准备 Runtime", "完成"]) {
    assert.match(source, new RegExp(expected));
  }
  assert.doesNotMatch(source, /运行时决策/);
});

test("prepare server wizard no longer exposes manual decision cards as the main flow", () => {
  assert.doesNotMatch(source, /currentStep === 2/);
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

test("prepare server wizard uses one-click configuration instead of next-step flow", () => {
  assert.match(source, /一键配置 Runtime/);
  assert.doesNotMatch(source, />\s*下一步\s*</);
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

test("prepare server wizard blocks bootstrap when Java or the selected profile is unsupported", () => {
  assert.match(source, /bootstrapBlockReason/);
  assert.match(source, /supported_profile_kinds/);
  assert.match(source, /版本不满足 Nextflow 要求（需 17-25）|请先修复 Java/);
  assert.match(source, /!bootstrapBlockReason/);
});

test("prepare server wizard uses a fixed dialog shell size", () => {
  assert.match(source, /w-\[960px\]/);
  assert.match(source, /h-\[760px\]/);
});

test("prepare server wizard uses resolved nextflow path instead of only the runtime default path", () => {
  assert.match(source, /capabilities\?\.nextflow\?\.path/);
});

test("prepare server wizard offers terminal repair entry from runtime setup", () => {
  assert.match(source, /打开终端修复/);
  assert.match(source, /onOpenTerminal/);
});

test("prepare server wizard polling is not gated by dialog open state", () => {
  assert.doesNotMatch(source, /if \(!open \|\| !installJobId\)/);
  assert.match(source, /if \(!installJobId\)/);
});

test("prepare server wizard only enters completion when refreshed nextflow is resolved and usable", () => {
  assert.match(source, /nextflowNowUsable/);
  assert.match(source, /nextflowResolvedPath/);
  assert.match(source, /extractLogField\(snapshot\.log_text \|\| "", "NEXTFLOW_PATH"\)/);
  assert.match(source, /Runtime 准备已完成，但重新检测时仍未解析到可用 Nextflow/);
});
