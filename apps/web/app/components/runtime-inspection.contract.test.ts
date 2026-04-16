import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./runtime-inspection.ts"), "utf-8");

test("runtime inspection nextflow contract includes resolved launcher fields", () => {
  assert.match(source, /nextflow\?: \{[^}]*path\?: string; command\?: string; message\?: string; candidates\?: RuntimeCandidate\[\][^}]*\}/);
  assert.match(source, /host_key\?: string/);
  assert.match(source, /verification_status\?: string/);
});

test("runtime inspection java contract includes resolved java fields", () => {
  assert.match(source, /java\?: \{[^}]*path\?: string; home\?: string; message\?: string; candidates\?: RuntimeCandidate\[\][^}]*\}/);
});

test("runtime inspection runtime capability contract allows candidate arrays", () => {
  assert.match(source, /type RuntimeCandidate = \{/);
  assert.match(source, /candidates\?: RuntimeCandidate\[\]/);
});
