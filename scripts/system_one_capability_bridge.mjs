#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const optionValue = (args, name) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
};

const readStdin = async () => {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
};

const tokens = (value) =>
  new Set(
    String(value)
      .toLowerCase()
      .match(/[a-z0-9_+-]+/g)
      ?.filter((token) => token.length > 1) ?? [],
  );

const overlapScore = (requestText, option) => {
  const left = tokens(requestText);
  const right = tokens(
    [
      option.id,
      option.label,
      option.description ?? "",
    ].join(" "),
  );
  let score = 0;
  for (const token of left) {
    if (right.has(token)) score += 1;
  }
  return score;
};

const distributionFor = (requestText, options) => {
  const raw = options.map((option) => ({
    id: option.id,
    score: overlapScore(requestText, option),
  }));
  const positive = raw.reduce(
    (sum, item) => sum + item.score,
    0,
  );

  if (positive === 0) {
    const equal = options.length > 0 ? 1 / options.length : 0;
    return Object.fromEntries(
      options.map((option) => [option.id, equal]),
    );
  }

  return Object.fromEntries(
    raw.map((item) => [
      item.id,
      item.score / positive,
    ]),
  );
};

const selectedFrom = (distribution) =>
  Object.entries(distribution).sort(
    (left, right) =>
      right[1] - left[1] ||
      left[0].localeCompare(right[0]),
  )[0]?.[0] ?? null;

const extractUserRequest = (state) => {
  const prefix = "User request:\n";
  const start = state.indexOf(prefix);
  if (start < 0) return state;
  const rest = state.slice(start + prefix.length);
  const divider = rest.indexOf("\n\n");
  return divider >= 0 ? rest.slice(0, divider) : rest;
};

class DeterministicBridgeProvider {
  id = "mado-cockpit-system-one-bridge";
  probabilitySemantics = "heuristic";

  capabilities() {
    return {
      primitives: ["choice", "noul"],
      modalities: ["text"],
      inferenceFamily: "specialist_classifier",
      specialization: "task",
      probabilitySemantics: "heuristic",
      confidenceSemantics: "selected_probability",
      calibration: {
        status: "uncalibrated",
        notes:
          "Deterministic zero-quota bridge fixture provider.",
      },
      patternSupport: {
        route: {
          status: "supported",
        },
      },
      supportsBatch: false,
      supportsAdaptiveReads: false,
    };
  }

  async decide(request) {
    const userRequest = extractUserRequest(request.state);
    const results = {};

    for (const [id, question] of Object.entries(request.questions)) {
      if (question.type === "choice") {
        const distribution = distributionFor(
          userRequest,
          question.options,
        );
        results[id] = {
          type: "choice",
          selected: selectedFrom(distribution),
          distribution,
        };
        continue;
      }

      if (question.type === "noul") {
        if (id === "needsCapability") {
          const match = request.state
            .split("\n")
            .filter((line) => line.startsWith("["))
            .some((line) => {
              const option = {
                id: line,
                label: line,
                description: line,
              };
              return overlapScore(userRequest, option) > 0;
            });
          results[id] = {
            type: "noul",
            probabilityYes: match ? 0.95 : 0.2,
          };
          continue;
        }

        if (id.startsWith("fit:")) {
          const capabilityId = id.slice("fit:".length);
          const lines = request.state.split("\n");
          const start = lines.findIndex((line) =>
            line.startsWith(`[${capabilityId}]`),
          );
          const block = [];
          if (start >= 0) {
            for (let index = start; index < lines.length; index += 1) {
              if (
                index > start &&
                lines[index].startsWith("[")
              ) {
                break;
              }
              block.push(lines[index]);
            }
          }
          const score = block.length > 0
            ? overlapScore(userRequest, {
                id: capabilityId,
                label: block[0],
                description: block.slice(1).join(" "),
              })
            : 0;
          results[id] = {
            type: "noul",
            probabilityYes: score > 0 ? 0.9 : 0.15,
          };
          continue;
        }

        results[id] = {
          type: "noul",
          probabilityYes: 0.5,
        };
        continue;
      }

      throw new Error(
        `unsupported bridge question type: ${question.type}`,
      );
    }

    return {
      traceId: request.traceId,
      providerId: this.id,
      probabilitySemantics: this.probabilitySemantics,
      results,
    };
  }
}

const main = async () => {
  const args = process.argv.slice(2);
  const root =
    optionValue(args, "--system-one-root") ??
    process.env.MADO_SYSTEM_ONE_ROOT;

  if (!root) {
    throw new Error(
      "MADO_SYSTEM_ONE_ROOT or --system-one-root is required",
    );
  }

  const entry = resolve(
    root,
    "dist",
    "src",
    "index.js",
  );
  const systemOne = await import(
    pathToFileURL(entry).href
  );

  const rawInput = await readStdin();
  const input = JSON.parse(rawInput);

  if (
    !input ||
    typeof input !== "object" ||
    !Array.isArray(input.capabilities) ||
    !input.request
  ) {
    throw new Error(
      "bridge input requires request and capabilities",
    );
  }

  const registry = new systemOne.CapabilityRegistry(
    input.capabilities,
  );
  const resolver = new systemOne.CapabilityResolver({
    provider: new DeterministicBridgeProvider(),
    registry,
    config: {
      topK: input.config?.topK ?? 3,
      needThreshold:
        input.config?.needThreshold ?? 0.3,
      fitThreshold:
        input.config?.fitThreshold ?? 0.4,
    },
  });

  const suggestion = await resolver.resolve(
    input.request,
  );
  process.stdout.write(
    JSON.stringify(suggestion),
  );
};

main().catch((error) => {
  process.stderr.write(
    error instanceof Error
      ? `${error.name}: ${error.message}\n`
      : `${String(error)}\n`,
  );
  process.exitCode = 1;
});
