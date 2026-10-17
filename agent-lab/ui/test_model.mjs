// Derivations checked against real recordings from the public showcase, so the
// numbers the console shows are the numbers the harness recorded.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { buildRun, buildBench, buildProcess, failureCode, patchContextMisses, wilson, fisher, esc, verdict } from "./model.js";

const showcase = fileURLToPath(new URL("../../site/showcase/", import.meta.url));
const load = (id) => JSON.parse(readFileSync(`${showcase}runs/${id}.json`, "utf8"));
const runOf = (id) => { const r = load(id); return { state: r, run: buildRun(r.events_full, r) }; };

test("the blocked static-page run reads as the recorder shows it", () => {
  const { state, run } = runOf("matrix-20261016-065825-001-deep");
  assert.equal(run.turns.length, 24);
  assert.equal(run.tools.length, 21);
  assert.deepEqual(run.turns.filter((t) => t.truncated).map((t) => t.n), [18], "turn 18 hit the 3,072-token cap");
  assert.equal(run.verdict.key, "blocked");
  assert.equal(failureCode(state.summary.blocked_reason, state.status), "R");
  const index = run.files.get("index.html").map((e) => `${e.turn}${e.kind}`).join(" ");
  assert.equal(index, "2W 10W 12W 17R 20R 21P! 23R 24X");
  const fb = run.tools.find((t) => t.fallback);
  assert.equal(fb.turn, 21);
  assert.equal(fb.fallback.beforeTurn, 20);
  assert.ok(fb.fallback.misses[0].missing.includes('<body class="bg-dark">'), "the quoted body tag never existed");
  assert.equal(run.repair.status, "budget_exhausted");
  assert.equal(run.evals.at(-1).passedCount, 14);
  const tags = run.alarms.map((a) => `${a.pri}:${a.tag}:${a.state}`);
  assert.ok(tags.includes("1:RUN.REPAIR:LATCHED"));
  assert.ok(tags.includes("2:EDIT.FALLBACK:ACTIVE"));
  assert.ok(tags.includes("3:GATE.PLAN:RTN"), "the plan refusal was recovered from");
  const units = Object.fromEntries(buildProcess(state, run).units.map((u) => [u.id, u.kind]));
  assert.equal(units.implement, "current");
  assert.equal(units.eval, "alarm");
});

test("a repaired pass keeps its history but clears active alarms", () => {
  const { run } = runOf("matrix-20261016-065825-003-deep");
  assert.equal(run.verdict.key, "repaired");
  assert.equal(run.verdict.tag, "Passed · repaired");
  assert.ok(run.tools.some((t) => t.fallback && t.turn === 10), "turn 10's patch also landed by line number");
  assert.ok(run.alarms.every((a) => a.state === "RTN"));
});

test("the context-miss replay follows the harness, hunk by hunk", () => {
  const file = "a\nb\nc\n";
  assert.deepEqual(patchContextMisses("*** Update File: f\n@@ -1,2 +1,3 @@\n a\n+x\n b", "f", file), []);
  const miss = patchContextMisses("*** Update File: f\n@@ -1,2 +1,3 @@\n a\n+x\n z", "f", file);
  assert.equal(miss.length, 1);
  assert.deepEqual(miss[0].missing, ["z"]);
  // The second hunk quotes a line the first hunk added: not a miss.
  assert.deepEqual(patchContextMisses("*** Update File: f\n@@ -1,1 +1,2 @@\n a\n+x\n@@ -2,2 +2,3 @@\n x\n+y\n b", "f", file), []);
  // A context miss that also removes lines is rejected by the harness, so it is not reported as accepted.
  assert.deepEqual(patchContextMisses("*** Update File: f\n@@ -1,2 +1,2 @@\n z\n-a\n+x", "f", file), []);
  assert.equal(patchContextMisses("*** Update File: f\n@@ -1 +1 @@\n a", "f", null), null, "unknown content is never guessed");
});

test("bench numbers match the 2026-10-16 reports", () => {
  const manifest = JSON.parse(readFileSync(`${showcase}manifest.json`, "utf8"));
  const bench = buildBench(manifest.benchmarks);
  const base = bench.experiments.find((e) => e.id === "baseline-20261016");
  const ablation = bench.experiments.find((e) => e.id === "no-apply-patch-20261016");
  assert.equal(`${base.k}/${base.n}`, "21/36");
  assert.deepEqual(base.ci.map((x) => Math.round(x * 100)), [42, 73]);
  assert.equal(base.firstPass, 18);
  assert.deepEqual(base.repairEpisodes, { passed: 3, total: 15 });
  assert.deepEqual(base.causes, { R: 5, E: 7, T: 1, W: 1, G: 1 });
  assert.deepEqual(base.rows.map((r) => `${r.k}/${r.n}`), ["4/9", "9/9", "3/9", "5/9"]);
  assert.equal(`${ablation.k}/${ablation.n}`, "22/36");
  assert.equal(ablation.comparison.p.toFixed(2), "1.00");
  assert.deepEqual(ablation.causes, { D: 5, E: 5, W: 1, R: 2, B: 1 });
  assert.ok(bench.experiments.filter((e) => e.status === "planned").length >= 3);
});

test("statistics and failure codes", () => {
  assert.deepEqual(wilson(0, 0), [0, 0]);
  assert.ok(Math.abs(fisher(3, 6, 0, 9) - 0.206) < 0.01, "structured validation 3/9 vs 0/9");
  assert.equal(failureCode("recovery exhausted for tool_failure after 2 attempts: apply_patch: could not find"), "E");
  assert.equal(failureCode("recovery exhausted for duplicate_action after 2 attempts: the model repeated write_file"), "D");
  assert.equal(failureCode("reached the 18-turn limit without a finish action"), "T");
  assert.equal(failureCode("The task is blocked. The report was validated", "blocked"), "B");
  assert.equal(verdict({ status: "success", summary: {} }).key, "finished", "an ungraded success is never called a pass");
  assert.equal(esc('<img src=x onerror="a">&'), "&lt;img src=x onerror=&quot;a&quot;&gt;&amp;");
});
