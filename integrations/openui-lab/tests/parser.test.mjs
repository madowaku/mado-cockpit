import test from "node:test";
import assert from "node:assert/strict";
import { createLibrary, defineComponent, createParser, createStreamingParser } from "@openuidev/lang-core";
import { z } from "zod/v4";
import { buildProgram, FIXTURE } from "../src/model.mjs";

const row = z.object({ title: z.string(), detail: z.string(), status: z.string() });
const components = ["ProjectPanel", "AgentPanel", "QaPanel"].map((name) =>
  defineComponent({
    name,
    description: "Display only",
    props: z.object({ rows: z.array(row) }),
    component: () => null,
  })
);
const screen = defineComponent({
  name: "CockpitScreen",
  description: "Read only root",
  props: z.object({ title: z.string(), subtitle: z.string(), panels: z.array(z.any()) }),
  component: () => null,
});
const library = createLibrary({ root: "CockpitScreen", components: [screen, ...components] });
const schema = library.toJSONSchema();

test("official parser accepts each generated view with no schema or reference errors", () => {
  for (const mode of ["projects", "agents", "qa"]) {
    const parsed = createParser(schema, "CockpitScreen").parse(buildProgram(mode, FIXTURE));
    assert.equal(parsed.root?.typeName, "CockpitScreen", mode);
    assert.deepEqual(parsed.meta.errors, [], mode);
    assert.deepEqual(parsed.meta.unresolved, [], mode);
    assert.deepEqual(parsed.queryStatements, [], mode);
    assert.deepEqual(parsed.mutationStatements, [], mode);
  }
});

test("official streaming parser accepts root-before-panel incremental output", () => {
  const program = buildProgram("projects", FIXTURE);
  const [root] = program.trimEnd().split("\n");
  const stream = createStreamingParser(schema, "CockpitScreen");
  stream.set(root + "\n");
  const final = stream.set(program, true);
  assert.equal(final.root?.typeName, "CockpitScreen");
  assert.deepEqual(final.meta.errors, []);
  assert.deepEqual(final.meta.unresolved, []);
});
