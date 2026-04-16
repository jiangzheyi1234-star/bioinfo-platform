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

test("prepare server wizard auto-detects bash, java, and nextflow before confirmation", () => {
  assert.match(source, /Bash → Java → Nextflow/);
  assert.match(source, /一键配置确认/);
  assert.match(source, /RuntimePath label="Bash"/);
});

test("prepare server wizard step 1 no longer renders the right-side strategy card", () => {
  assert.doesNotMatch(source, /智能部署决策/);
  assert.doesNotMatch(source, /推荐 PROFILE/);
  assert.doesNotMatch(source, /可选运行方式/);
});

test("prepare server wizard does not regress to interruptive per-path browser popups", () => {
  assert.doesNotMatch(source, /window\.confirm/);
  assert.doesNotMatch(source, /window\.alert/);
});

test("prepare server wizard does not expose raw fetch failures", () => {
  assert.doesNotMatch(source, /Failed to fetch/);
  assert.match(inspectionSource, /本地 API 未启动或不可达/);
});

test("prepare server wizard uses explicit terminal-mediated remediation instead of implicit bootstrap install calls", () => {
  assert.doesNotMatch(source, /startRemoteEnvInstall/);
  assert.doesNotMatch(source, /installJobId/);
  assert.match(source, /onSendTerminalCommand/);
  assert.match(source, /命令发送成功 ≠ 修复成功/);
  assert.match(source, /发送到终端/);
});

test("prepare server wizard blocks bootstrap when Java or the selected profile is unsupported", () => {
  assert.match(source, /bootstrapBlockReason/);
  assert.match(source, /supported_profile_kinds/);
  assert.match(source, /版本不满足 Nextflow 要求（需 17-25）|请先修复 Java/);
  assert.match(source, /if \(blockReason\)/);
  assert.match(source, /setError\(blockReason\)/);
});

test("prepare server wizard uses a fixed dialog shell size", () => {
  assert.match(source, /w-\[960px\]/);
  assert.match(source, /h-\[760px\]/);
});

test("prepare server wizard uses resolved nextflow path instead of only the runtime default path", () => {
  assert.match(source, /confirmationNextflowPath/);
  assert.match(source, /isRuntimeReady\(preflight, envStatus, resolvedRuntimeForInspection\)/);
  assert.match(source, /isRuntimeReady\(nextPreflight, nextEnv, inspection\.resolvedRuntime\)/);
});

test("prepare server wizard offers terminal repair entry from runtime setup", () => {
  assert.match(source, /打开终端修复/);
  assert.match(source, /onOpenTerminal/);
  assert.match(source, /sendRemediationCommand/);
});

test("prepare server wizard renders sequential bash-lc remediation commands for java, nextflow, and docker", () => {
  assert.match(source, /sdk install java 17\.0\.10-tem/);
  assert.match(source, /"\$HOME\/\.local\/bin\/nextflow" info/);
  assert.match(source, /get\.docker\.com/);
  assert.match(source, /bash -lc/);
});

test("prepare server wizard requires explicit recheck after terminal remediation", () => {
  assert.match(source, /runRecheck/);
  assert.match(source, /重新检测/);
  assert.match(source, /syncPreparedState/);
  assert.match(source, /命令发送成功 ≠ 环境已修复成功/);
});

test("prepare server wizard keeps conda as an optional fallback instead of a hard blocker", () => {
  assert.match(source, /Conda 仅作为可选 fallback，不会阻塞一键配置/);
  assert.match(source, /Conda Runtime 只作为容器运行时缺失时的补位能力/);
  assert.match(source, /不再依赖 PATH 漂移或 Conda 自动激活/);
});
