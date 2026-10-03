import { defineTool } from '@copilotkit/runtime/v2';
import { z } from 'zod';

export const MADO_TOOL_CALL_SCHEMA = 'mado.opendots.tool-call.v1';

export type MadoToolContext = {
  dotId: string;
  spaceId?: string;
  threadId?: string;
};

export type MadoToolCaller = (request: {
  schema: typeof MADO_TOOL_CALL_SCHEMA;
  tool_call_id: string;
  tool_name: string;
  context: {
    dot_id: string;
    space_id?: string;
    thread_id?: string;
  };
  arguments: Record<string, unknown>;
}) => Promise<unknown>;

function bridgeContext(context: MadoToolContext) {
  return {
    dot_id: context.dotId,
    ...(context.spaceId ? { space_id: context.spaceId } : {}),
    ...(context.threadId ? { thread_id: context.threadId } : {}),
  };
}

export function madoCockpitTools(
  context: MadoToolContext,
  call: MadoToolCaller,
) {
  const invoke = (toolName: string, args: Record<string, unknown>) =>
    call({
      schema: MADO_TOOL_CALL_SCHEMA,
      tool_call_id: crypto.randomUUID(),
      tool_name: toolName,
      context: bridgeContext(context),
      arguments: args,
    });

  const operatorId = z.string().min(1).max(128);

  return [
    defineTool({
      name: 'mado_check_mission',
      description:
        'Read the current MADO Cockpit mission state, next action, and any open Human Question Gate. Read-only.',
      parameters: z.object({ operator_id: operatorId }),
      execute: (args) => invoke('mado_check_mission', args),
    }),
    defineTool({
      name: 'mado_advance_mission',
      description:
        'Advance only deterministic MADO Cockpit orchestration. This does not launch a model or shell command.',
      parameters: z.object({ operator_id: operatorId }),
      execute: (args) => invoke('mado_advance_mission', args),
    }),
    defineTool({
      name: 'mado_answer_human_gate',
      description:
        'Resolve the current MADO Human Question Gate only after the owner explicitly chose an option, or explicitly asked to use the declared safe default. When mado_review_human_gate returns gate_id, forward that gate_id unchanged.',
      parameters: z
        .object({
          operator_id: operatorId,
          gate_id: z.string().min(1).max(128).optional(),
          choice: z.string().min(1).optional(),
          choose_for_me: z.boolean().default(false),
          note: z.string().max(2000).optional(),
        })
        .refine(
          (value) => Boolean(value.choice) !== value.choose_for_me,
          'Provide exactly one of choice or choose_for_me.',
        ),
      execute: (args) => invoke('mado_answer_human_gate', args),
    }),
    defineTool({
      name: 'mado_show_evidence',
      description:
        'Show Builder/QA evidence metadata without exposing Cockpit filesystem paths. Read-only.',
      parameters: z.object({
        operator_id: operatorId,
        scope: z.enum(['builder', 'qa', 'all']).default('all'),
      }),
      execute: (args) => invoke('mado_show_evidence', args),
    }),
    defineTool({
      name: 'mado_show_qa_result',
      description:
        'Show the current QA handoff, latest QA result, and verdict. Read-only.',
      parameters: z.object({ operator_id: operatorId }),
      execute: (args) => invoke('mado_show_qa_result', args),
    }),
  ];
}
