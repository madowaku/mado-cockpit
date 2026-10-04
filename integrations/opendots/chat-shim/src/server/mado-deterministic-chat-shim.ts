import { Hono } from 'hono';

type ChatMessage = {
  role?: string;
  content?: string;
  tool_call_id?: string;
};

type ToolDef = {
  function?: {
    name?: string;
    description?: string;
  };
};

type ChatBody = {
  messages?: ChatMessage[];
  tools?: ToolDef[];
};

function completion(
  delta: Record<string, unknown>,
  finishReason = 'stop',
) {
  const chunks = [
    {
      id: 'mcc-m1.9-completion',
      object: 'chat.completion.chunk',
      created: 1,
      model: 'mcc-m1.9-deterministic',
      choices: [{ index: 0, delta, finish_reason: null }],
    },
    {
      id: 'mcc-m1.9-completion',
      object: 'chat.completion.chunk',
      created: 1,
      model: 'mcc-m1.9-deterministic',
      choices: [{ index: 0, delta: {}, finish_reason: finishReason }],
    },
  ];
  const body =
    chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join('') +
    'data: [DONE]\n\n';
  return new Response(body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-store',
    },
  });
}

function toolCall(id: string, name: string, args: Record<string, unknown>) {
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

function parseToolResult(
  messages: ChatMessage[],
  toolCallId: string,
): Record<string, unknown> | undefined {
  const message = messages.find(
    (item) => item.role === 'tool' && item.tool_call_id === toolCallId,
  );
  if (!message || typeof message.content !== 'string') return undefined;
  try {
    const parsed = JSON.parse(message.content);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

function offered(body: ChatBody, name: string) {
  return body.tools?.some((item) => item.function?.name === name) ?? false;
}

function requireTool(body: ChatBody, name: string) {
  if (!offered(body, name))
    throw new Error(`MCC-M1.9 expected tool ${name} to be offered.`);
}

function operatorFrom(body: ChatBody) {
  const text = [...(body.messages ?? [])]
    .reverse()
    .find((item) => item.role === 'user' && typeof item.content === 'string')
    ?.content;
  const match = text?.match(/\bopr_[A-Za-z0-9]+\b/);
  if (!match) throw new Error('MCC-M1.9 could not find an Operator ID.');
  const expected = process.env.MADO_M1_9_OPERATOR_ID;
  if (expected && match[0] !== expected)
    throw new Error('MCC-M1.9 Operator ID did not match the fixture.');
  return match[0];
}

function gateFromMission(result: Record<string, unknown>) {
  const data =
    result.data && typeof result.data === 'object' && !Array.isArray(result.data)
      ? (result.data as Record<string, unknown>)
      : undefined;
  if (!data)
    throw new Error('MCC-M1.9 mission result did not contain data.');
  const gate =
    data.human_gate &&
    typeof data.human_gate === 'object' &&
    !Array.isArray(data.human_gate)
      ? (data.human_gate as Record<string, unknown>)
      : undefined;
  if (!gate || typeof gate.id !== 'string')
    throw new Error('MCC-M1.9 mission result did not contain an open Human Gate.');
  return { data, gate };
}

export function madoDeterministicChatShimRoutes() {
  const app = new Hono();

  app.post('/v1/chat/completions', async (c) => {
    const body = (await c.req.json()) as ChatBody;
    const messages = body.messages ?? [];

    requireTool(body, 'mado_check_mission');
    requireTool(body, 'mado_answer_human_gate');

    const answer = parseToolResult(messages, 'm1.9-gate-answer');
    if (answer) {
      if (answer.ok !== true)
        throw new Error(
          `MCC-M1.9 Gate answer failed: ${JSON.stringify(answer)}`,
        );
      console.log(
        JSON.stringify({
          schema: 'mado.opendots.m1.9-shim.v1',
          stage: 'final_reply',
        }),
      );
      return completion({
        role: 'assistant',
        content:
          'Mission resumed on the free path. Cockpit is ready for Builder work.',
      });
    }

    const human = parseToolResult(messages, 'm1.9-human-review');
    if (human) {
      if (human.choice !== 'stay_free' || typeof human.gate_id !== 'string')
        throw new Error(
          `MCC-M1.9 unexpected Human Gate result: ${JSON.stringify(human)}`,
        );
      console.log(
        JSON.stringify({
          schema: 'mado.opendots.m1.9-shim.v1',
          stage: 'forward_human_decision',
          choice: human.choice,
          gate_id: human.gate_id,
        }),
      );
      return toolCall('m1.9-gate-answer', 'mado_answer_human_gate', {
        operator_id: human.operator_id,
        gate_id: human.gate_id,
        choice: human.choice,
        choose_for_me: false,
        ...(typeof human.note === 'string' ? { note: human.note } : {}),
      });
    }

    const mission = parseToolResult(messages, 'm1.9-mission-check');
    if (mission) {
      const { data, gate } = gateFromMission(mission);
      requireTool(body, 'mado_review_human_gate');
      console.log(
        JSON.stringify({
          schema: 'mado.opendots.m1.9-shim.v1',
          stage: 'open_human_gate',
          gate_id: gate.id,
        }),
      );
      return toolCall('m1.9-human-review', 'mado_review_human_gate', {
        operator_id: data.operator_id,
        gate_id: gate.id,
        question: gate.question,
        reason: gate.reason ?? '',
        materiality: gate.materiality,
        choices: gate.choices ?? [],
        impacts: gate.impacts ?? {},
        recommendation: gate.recommendation,
        safe_default: gate.safe_default,
        allow_choose_for_me: gate.allow_choose_for_me ?? false,
      });
    }

    const operatorId = operatorFrom(body);
    console.log(
      JSON.stringify({
        schema: 'mado.opendots.m1.9-shim.v1',
        stage: 'check_mission',
        operator_id: operatorId,
      }),
    );
    return toolCall('m1.9-mission-check', 'mado_check_mission', {
      operator_id: operatorId,
    });
  });

  return app;
}
