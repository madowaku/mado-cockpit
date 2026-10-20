import test from "node:test";
import assert from "node:assert/strict";
import { buildProgram, byteSize, normalizeSnapshot, FIXTURE } from "../src/model.mjs";

test("produces distinct OpenUI components for each view", () => {
  for (const [mode, expected] of [["projects", "ProjectPanel"], ["agents", "AgentPanel"], ["qa", "QaPanel"]]) {
    const out = buildProgram(mode, FIXTURE);
    assert.match(out, /root = CockpitScreen\(/);
    assert.ok(out.includes("panel = " + expected + "("));
  }
  assert.throws(() => buildProgram("write", FIXTURE), /Unsupported/);
});

test("normalizes arbitrary snapshot fields with strict bounded lists", () => {
  const snap = normalizeSnapshot({
    project: { name: "Fixture" },
    missions: Array.from({length: 40}, (_, i) => ({ id: "M" + i, title: "x".repeat(400) })),
    workers: [{ id: "agent", role: "qa", provider: "replay" }],
    gates: [{ id: "g1", status: "open", question: "private secret" }, { id: "g2", status: "resolved" }],
    evidence: { tasks: [{ id: "t1", status: "failed" }] },
    token: "MUST_NOT_LEAK",
  });
  assert.equal(snap.projects.length, 12);
  assert.equal(snap.projects[0].title.length, 100);
  assert.equal(snap.qa[0].status, "review only");
  assert.equal(snap.qa.length, 2);
  const output = buildProgram("qa", snap, "live");
  assert.ok(!output.includes("private secret"));
  assert.ok(!output.includes("MUST_NOT_LEAK"));
  assert.match(output, /localhost/);
});

test("quotes user-controlled text as data, not executable OpenUI lines", () => {
  const snap = normalizeSnapshot({ missions: [{id: 'x\\nroot = Bad("escape")', title: 'Hello\nroot = Evil("x")'}] });
  const program = buildProgram("projects", snap);
  assert.equal(program.split("\n").length, 3);
  assert.ok(program.includes('\\nroot = Evil'));
  assert.equal(byteSize("🛸"), 4);
});

test("does not invent live data, actions, or approvals", () => {
  assert.deepEqual(normalizeSnapshot({}).qa, []);
  for (const m of ["projects", "agents", "qa"]) {
    assert.doesNotMatch(buildProgram(m, FIXTURE), /@Run|@Mutation|@OpenUrl|gate.resolve|operator.advance/);
  }
  assert.throws(() => normalizeSnapshot(null), /object/);
});
