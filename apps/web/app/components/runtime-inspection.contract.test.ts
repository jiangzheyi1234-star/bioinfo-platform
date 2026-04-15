import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./runtime-inspection.ts"), "utf-8");

test("runtime inspection nextflow contract includes resolved launcher fields", () => {
  assert.match(source, /nextflow\?: \{ available\?: boolean; usable\?: boolean; version\?: string; path\?: string; command\?: string; message\?: string \}/);
});

test("runtime inspection java contract includes resolved java fields", () => {
  assert.match(source, /java\?: \{ available\?: boolean; usable\?: boolean; version\?: string; path\?: string; home\?: string; message\?: string \}/);
});
