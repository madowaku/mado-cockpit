import { z } from 'zod';

export const madoHumanGateReviewSchema = z
  .object({
    operator_id: z.string().min(1).max(128),
    gate_id: z.string().min(1).max(128),
    question: z.string().min(1).max(4000),
    reason: z.string().max(4000).default(''),
    materiality: z.string().min(1).max(80),
    choices: z.array(z.string().min(1).max(400)).max(12).default([]),
    impacts: z.record(z.string(), z.string().max(2000)).default({}),
    recommendation: z.string().max(400).optional(),
    safe_default: z.string().max(400).optional(),
    allow_choose_for_me: z.boolean().default(false),
  })
  .strict();

export const madoHumanGateReviewTool = {
  name: 'mado_review_human_gate',
  description:
    'Pause for the owner to answer a MADO Cockpit Human Question Gate. Copy gate metadata exactly from mado_check_mission. Wait for the result, then forward only operator_id, gate_id, choice or choose_for_me, and note to mado_answer_human_gate. Never choose before this review completes.',
  parameters: z.toJSONSchema(madoHumanGateReviewSchema),
};
