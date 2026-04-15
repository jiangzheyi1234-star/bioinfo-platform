import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./prepare-server-wizard.tsx"), "utf-8");

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

test("prepare server wizard includes prototype-mode fallback copy", () => {
  assert.match(source, /UI 原型模式/);
  assert.match(source, /后端检测\/安装接口尚未接通/);
});
