import { randomUUID } from 'node:crypto';
import { Hono } from 'hono';
import { z } from 'zod';
import { callMadoCockpit } from './mado-cockpit-caller.js';

const operatorId = z.string().min(1).max(128);
const gateId = z.string().min(1).max(128);

function context() {
  return {
    dot_id: 'mcc-m1.6-browser-e2e',
    space_id: 'mcc-m1.6-browser-e2e',
    thread_id: 'mcc-m1.6-browser-e2e',
  };
}

export function madoDogfoodRoutes() {
  const app = new Hono();

  app.get('/status', async (c) => {
    const parsed = operatorId.safeParse(c.req.query('operator_id'));
    if (!parsed.success)
      return c.json({ error: 'operator_id is required.' }, 400);

    const result = await callMadoCockpit({
      schema: 'mado.opendots.tool-call.v1',
      tool_call_id: `browser-status-${randomUUID()}`,
      tool_name: 'mado_check_mission',
      context: context(),
      arguments: {
        operator_id: parsed.data,
      },
    });

    return c.json(result);
  });

  app.post('/resolve', async (c) => {
    const parsed = z
      .object({
        operator_id: operatorId,
        gate_id: gateId,
        choice: z.string().min(1).max(400).optional(),
        choose_for_me: z.boolean().default(false),
        note: z.string().max(2000).optional(),
      })
      .strict()
      .refine(
        (value) => Boolean(value.choice) !== value.choose_for_me,
        'Provide exactly one of choice or choose_for_me.',
      )
      .safeParse(await c.req.json().catch(() => null));

    if (!parsed.success)
      return c.json({ error: 'Invalid Human Gate decision.' }, 400);

    const result = await callMadoCockpit({
      schema: 'mado.opendots.tool-call.v1',
      tool_call_id: `browser-resolve-${randomUUID()}`,
      tool_name: 'mado_answer_human_gate',
      context: context(),
      arguments: parsed.data,
    });

    return c.json(result);
  });

  return app;
}
