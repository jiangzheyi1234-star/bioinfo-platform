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

test("prepare server wizard auto-detects bash, java, and nextflow before direct execution", () => {
  assert.match(source, /Bash → Java → Nextflow/);
  assert.match(source, /点击“一键配置 Runtime”后会直接进入执行态/);
  assert.doesNotMatch(source, /一键配置确认/);
});

test("prepare server wizard keeps one-click execution on a single docker-centered path", () => {
  assert.match(source, /一键配置统一沿同一条执行路径推进/);
  assert.match(source, /统一执行路径/);
  assert.match(source, /personal_docker/);
  assert.doesNotMatch(source, /Podman 可用，配置流程会按 Podman 路线继续/);
  assert.doesNotMatch(source, /当前推荐 profile 是 Podman/);
  assert.doesNotMatch(source, /personal_podman/);
  assert.doesNotMatch(source, /personal_conda/);
  assert.doesNotMatch(source, /Micromamba \/ Conda 仅作为补位能力，不应阻塞一键配置主路径/);
  assert.doesNotMatch(source, /RuntimePath label="Micromamba"/);
  assert.doesNotMatch(source, /fallback_conda/);
  assert.doesNotMatch(inspectionSource, /return "use_podman"/);
  assert.doesNotMatch(inspectionSource, /return "fallback_conda"/);
  assert.doesNotMatch(inspectionSource, /podmanAvailable/);
  assert.doesNotMatch(inspectionSource, /micromambaAvailable/);
  assert.doesNotMatch(inspectionSource, /condaAvailable/);
});

test("prepare server wizard only interrupts for multiple candidate selection and persists the chosen path", () => {
  assert.match(source, /局部选择/);
  assert.match(source, /检测到多个可用 Java 路径/);
  assert.match(source, /检测到多个合规 Nextflow 路径/);
  assert.match(source, /persistCandidateSelection/);
  assert.match(source, /selectJavaCandidate/);
  assert.match(source, /selectNextflowCandidate/);
  assert.match(source, /nextflow_path: candidate\.path/);
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

test("prepare server wizard keeps terminal remediation on the one-click path even when docker is missing", () => {
  assert.match(source, /未检测到可用 Docker；一键配置仍保持同一条执行路径/);
  assert.match(source, /不再依赖 PATH 漂移或 Conda 自动激活/);
});
