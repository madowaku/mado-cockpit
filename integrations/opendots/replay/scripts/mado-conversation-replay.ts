import { EventType, type RunAgentInput } from '@ag-ui/core';
import { lastValueFrom, toArray } from 'rxjs';
import { DotAgent } from '../src/server/dot-agent.js';
import { Store } from '../src/server/store.js';
import { WorkspaceStore } from '../src/server/workspace.js';
import { madoHumanGateReviewTool } from '../src/shared/mado-human-gate.js';

type JsonRecord = Record<string, unknown>;

const operatorId = process.env.MADO_REPLAY_OPERATOR_ID;
const evidencePath = process.env.MADO_REPLAY_EVIDENCE_PATH;

if (!operatorId) throw new Error('MADO_REPLAY_OPERATOR_ID is required.');

let reviewArgs: JsonRecord | undefined;
let modelCalls = 0;
let answerCallSeen = false;

function completion(
  delta: Record<string, unknown>,
  finishReason = 'stop',
) {
  const chunks = [
    {
      id: 'mcc-m1.7-completion',
      object: 'chat.completion.chunk',
      created: 1,
      model: 'mcc-m1.7-replay',
      choices: [{ index: 0, delta, finish_reason: null }],
    },
    {
      id: 'mcc-m1.7-completion',
      object: 'chat.completion.chunk',
      created: 1,
      model: 'mcc-m1.7-replay',
      choices: [{ index: 0, delta: {}, finish_reason: finishReason }],
    },
  ];
  return new Response(
    chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join('') +
      'data: [DONE]\n\n',
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
}

function toolCall(id: string, name: string, args: JsonRecord) {
  return completion(
    {
      role: 'assistant',
      tool_calls: [
        {
          index: 0,
          id,
          type: 'function',
          function: {
            name,
            arguments: JSON.stringify(args),
          },
        },
      ],
    },
    'tool_calls',
  );
}

function parseBody(init?: RequestInit) {
  if (typeof init?.body !== 'string')
    throw new Error('Expected deterministic model request body.');
  return JSON.parse(init.body) as {
    messages?: Array<{
      role?: string;
      content?: string;
      tool_call_id?: string;
    }>;
    tools?: Array<{
      function?: { name?: string; description?: string };
    }>;
  };
}

function toolResult(
  body: ReturnType<typeof parseBody>,
  id: string,
): JsonRecord | undefined {
  const message = body.messages?.find(
    (item) => item.role === 'tool' && item.tool_call_id === id,
  );
  if (!message || typeof message.content !== 'string') return undefined;
  try {
    return JSON.parse(message.content) as JsonRecord;
  } catch {
    return undefined;
  }
}

function assertToolOffered(
  body: ReturnType<typeof parseBody>,
  name: string,
) {
  if (!body.tools?.some((item) => item.function?.name === name))
    throw new Error(`Expected model tool surface to offer ${name}.`);
}

const nativeFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = String(input);
  if (!url.endsWith('/chat/completions'))
    throw new Error(`Unexpected network request in deterministic replay: ${url}`);

  modelCalls += 1;
  const body = parseBody(init);
  assertToolOffered(body, 'mado_check_mission');
  assertToolOffered(body, 'mado_answer_human_gate');

  const gateAnswerResult = toolResult(body, 'gate-answer');
  if (gateAnswerResult) {
    if (gateAnswerResult.ok !== true)
      throw new Error(
        `Gate answer tool failed: ${JSON.stringify(gateAnswerResult)}`,
      );
    return completion({
      role: 'assistant',
      content:
        'Mission resumed on the free path. Cockpit is ready for Builder work.',
    });
  }

  const humanResult = toolResult(body, 'human-review');
  if (humanResult) {
    answerCallSeen = true;
    const gateId = humanResult.gate_id;
    const choice = humanResult.choice;
    if (typeof gateId !== 'string' || choice !== 'stay_free')
      throw new Error(
        `Unexpected human review result: ${JSON.stringify(humanResult)}`,
      );
    return toolCall('gate-answer', 'mado_answer_human_gate', {
      operator_id: operatorId,
      gate_id: gateId,
      choice,
      choose_for_me: false,
      note:
        typeof humanResult.note === 'string'
          ? humanResult.note
          : 'Keep the zero-cost path.',
    });
  }

  const missionResult = toolResult(body, 'mission-check');
  if (missionResult) {
    const data =
      missionResult.data &&
      typeof missionResult.data === 'object' &&
      !Array.isArray(missionResult.data)
        ? (missionResult.data as JsonRecord)
        : undefined;
    const gate =
      data?.human_gate &&
      typeof data.human_gate === 'object' &&
      !Array.isArray(data.human_gate)
        ? (data.human_gate as JsonRecord)
        : undefined;
    if (!gate || typeof gate.id !== 'string')
      throw new Error(
        `Mission tool result did not expose an open gate: ${JSON.stringify(missionResult)}`,
      );

    reviewArgs = {
      operator_id: operatorId,
      gate_id: gate.id,
      question: gate.question,
      reason: gate.reason ?? '',
      materiality: gate.materiality,
      choices: gate.choices ?? [],
      impacts: gate.impacts ?? {},
      recommendation: gate.recommendation,
      safe_default: gate.safe_default,
      allow_choose_for_me: gate.allow_choose_for_me ?? false,
    };

    assertToolOffered(body, madoHumanGateReviewTool.name);
    return toolCall(
      'human-review',
      madoHumanGateReviewTool.name,
      reviewArgs,
    );
  }

  if (answerCallSeen)
    throw new Error('Replay attempted an unexpected model step after gate answer.');

  return toolCall('mission-check', 'mado_check_mission', {
    operator_id: operatorId,
  });
};

const store = new Store(':memory:');
const workspace = new WorkspaceStore(':memory:', 'mcc-m1.7-owner');
const dot = workspace.dots()[0];
const threadId = 'mcc-m1.7-real-conversation';
workspace.bindThread(threadId, dot.id, 'MCC-M1.7 deterministic replay');

const agent = new DotAgent(
  store,
  workspace,
  {
    intelligenceKey: 'mcc-m1.7-local-fixture',
    apiKey: 'mcc-m1.7-local-fixture',
    model: 'mcc-m1.7-replay',
    baseUrl: 'https://mcc-m1.7.invalid/v1',
    runtimeUrl: '',
    voiceName: 'marin',
    slackUsers: [],
  },
  dot.id,
);

function baseInput(runId: string, messages: RunAgentInput['messages']): RunAgentInput {
  return {
    threadId,
    runId,
    state: {},
    context: [],
    messages,
    tools: [madoHumanGateReviewTool],
    forwardedProps: {},
  };
}

const firstInput = baseInput('mcc-m1.7-run-1', [
  {
    id: 'user-1',
    role: 'user',
    content: `Check MADO mission ${operatorId} and continue safely.`,
  },
]);

try {
  const firstEvents = await lastValueFrom(
    agent.run(firstInput).pipe(toArray()),
  );

  const firstToolNames = firstEvents
    .filter((event) => event.type === EventType.TOOL_CALL_START)
    .map((event) => (event as { toolCallName?: string }).toolCallName);

  if (!firstToolNames.includes('mado_check_mission'))
    throw new Error('First run never called mado_check_mission.');
  if (!firstToolNames.includes(madoHumanGateReviewTool.name))
    throw new Error('First run never opened the Human Gate review tool.');
  if (
    firstEvents.some(
      (event) =>
        event.type === EventType.TOOL_CALL_RESULT &&
        (event as { toolCallId?: string }).toolCallId === 'human-review',
    )
  )
    throw new Error('Human review tool was resolved without a human result.');
  if (!reviewArgs)
    throw new Error('Replay did not capture Human Gate review arguments.');

  const humanDecision = {
    operator_id: operatorId,
    gate_id: reviewArgs.gate_id,
    choice: 'stay_free',
    choose_for_me: false,
    note: 'Keep the zero-cost path.',
  };

  const secondInput = baseInput('mcc-m1.7-run-2', [
    firstInput.messages[0],
    {
      id: 'assistant-human-review',
      role: 'assistant',
      content: '',
      toolCalls: [
        {
          id: 'human-review',
          type: 'function',
          function: {
            name: madoHumanGateReviewTool.name,
            arguments: JSON.stringify(reviewArgs),
          },
        },
      ],
    },
    {
      id: 'human-review-result',
      role: 'tool',
      toolCallId: 'human-review',
      content: JSON.stringify(humanDecision),
    },
  ]);

  const secondEvents = await lastValueFrom(
    agent.run(secondInput).pipe(toArray()),
  );

  const secondToolNames = secondEvents
    .filter((event) => event.type === EventType.TOOL_CALL_START)
    .map((event) => (event as { toolCallName?: string }).toolCallName);

  if (!secondToolNames.includes('mado_answer_human_gate'))
    throw new Error('Second run never forwarded the human decision to Cockpit.');

  const finalText = secondEvents
    .filter((event) => event.type === EventType.TEXT_MESSAGE_CHUNK)
    .map((event) => (event as { delta?: string }).delta ?? '')
    .join('');

  if (!finalText.includes('Mission resumed on the free path'))
    throw new Error(`Unexpected final assistant text: ${finalText}`);

  const evidence = {
    schema: 'mado.opendots.conversation-replay.v1',
    replay_version: 'MCC-M1.7',
    operator_id: operatorId,
    thread_id: threadId,
    runs: [
      {
        run_id: firstInput.runId,
        user_text: firstInput.messages[0].content,
        tool_calls: firstToolNames,
        human_gate_args: reviewArgs,
        human_gate_result_present: false,
      },
      {
        run_id: secondInput.runId,
        human_decision: humanDecision,
        tool_calls: secondToolNames,
        final_text: finalText,
      },
    ],
    model_calls: modelCalls,
    network_policy: 'model_fixture_only',
  };

  if (evidencePath) {
    const { mkdir, writeFile } = await import('node:fs/promises');
    const { dirname } = await import('node:path');
    await mkdir(dirname(evidencePath), { recursive: true });
    await writeFile(evidencePath, JSON.stringify(evidence, null, 2) + '\n');
  }

  console.log(JSON.stringify(evidence, null, 2));
} finally {
  globalThis.fetch = nativeFetch;
  store.close();
  workspace.close();
}
