import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./runtime-inspection.ts"), "utf-8");

test("runtime inspection verifies local api health before starting runtime install", () => {
  assert.match(source, /export async function verifyLocalApiHealth/);
  assert.match(source, /requestLocalApiJson\("GET", "\/health"/);
  assert.match(source, /status !== "ok"/);
});

test("runtime inspection keeps install disconnects distinct after health check success", () => {
  assert.match(source, /export async function startRemoteEnvInstall/);
  assert.match(source, /requestLocalApiJson\("POST", "\/api\/v1\/ssh\/env\/install"/);
  assert.match(source, /本地 API 健康检查已通过，但启动 Runtime 请求时连接中断/);
});

test("runtime inspection still maps direct reachability failures to local api unreachable copy", () => {
  assert.match(source, /backend_unreachable/);
  assert.match(source, /本地 API 未启动或不可达/);
});
