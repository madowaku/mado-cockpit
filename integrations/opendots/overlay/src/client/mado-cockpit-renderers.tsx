import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FlaskConical,
  ShieldQuestion,
} from 'lucide-react';
import {
  useHumanInTheLoop,
  useRenderTool,
} from '@copilotkit/react-core/v2';
import { z } from 'zod';
import {
  madoHumanGateReviewSchema,
  madoHumanGateReviewTool,
} from '../shared/mado-human-gate';

type ToolRenderProps = {
  name: string;
  toolCallId: string;
  status: string;
  args?: unknown;
  result?: unknown;
};

type HitlRenderProps = {
  args: unknown;
  status: string;
  result?: unknown;
  respond?: (result: unknown) => Promise<void>;
  toolCallId: string;
};

const presentationSchema = z
  .object({
    kind: z.enum([
      'mission_status',
      'mission_advanced',
      'human_gate_resolved',
      'evidence_summary',
      'qa_result',
    ]),
    title: z.string(),
    status: z.string(),
    summary: z.string(),
    facts: z
      .array(
        z.object({
          label: z.string(),
          value: z.unknown(),
        }),
      )
      .default([]),
    human_gate: z.unknown().optional(),
  })
  .passthrough();

const toolResultSchema = z
  .object({
    schema: z.literal('mado.opendots.tool-result.v1'),
    surface_version: z.string(),
    tool_call_id: z.string(),
    tool_name: z.string(),
    ok: z.boolean(),
    presentation: presentationSchema.optional(),
    error: z
      .object({
        code: z.string(),
        message: z.string(),
      })
      .optional(),
  })
  .passthrough();

function objectResult(raw: unknown): Record<string, unknown> {
  if (typeof raw === 'string') {
    try {
      raw = JSON.parse(raw);
    } catch {
      return { error: raw };
    }
  }
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? Object.fromEntries(Object.entries(raw))
    : {};
}

const iconFor = (kind?: string) =>
  kind === 'evidence_summary'
    ? FlaskConical
    : kind === 'qa_result'
      ? ClipboardCheck
      : kind === 'human_gate_resolved'
        ? CheckCircle2
        : Activity;

export function MadoToolCard({
  name,
  status,
  result,
}: ToolRenderProps) {
  const parsed = toolResultSchema.safeParse(objectResult(result));
  const complete = status === 'complete';

  if (!complete && !parsed.success) {
    return (
      <section className="mado-card" aria-label="MADO Cockpit tool">
        <header>
          <Activity size={16} aria-hidden="true" />
          <strong>Checking MADO Cockpit</strong>
          <span>Working</span>
        </header>
      </section>
    );
  }

  if (!parsed.success || !parsed.data.ok || !parsed.data.presentation) {
    const message =
      parsed.success
        ? parsed.data.error?.message
        : typeof objectResult(result).error === 'string'
          ? String(objectResult(result).error)
          : undefined;
    return (
      <section className="mado-card mado-card-attention" role="alert">
        <header>
          <AlertTriangle size={16} aria-hidden="true" />
          <strong>MADO Cockpit</strong>
          <span>Needs attention</span>
        </header>
        <p>{message ?? `${name} returned no renderable Cockpit result.`}</p>
      </section>
    );
  }

  const presentation = parsed.data.presentation;
  const Icon = iconFor(presentation.kind);
  const hasHumanGate =
    presentation.human_gate !== null &&
    typeof presentation.human_gate === 'object';
  return (
    <section
      className={`mado-card mado-card-${presentation.kind}`}
      aria-label={presentation.title}
    >
      <header>
        <Icon size={16} aria-hidden="true" />
        <strong>{presentation.title}</strong>
        <span>{presentation.status}</span>
      </header>
      <p className="mado-card-summary">{presentation.summary}</p>
      {presentation.facts.length > 0 && (
        <dl className="mado-card-facts">
          {presentation.facts.map((fact, index) => (
            <div key={`${fact.label}-${index}`}>
              <dt>{fact.label}</dt>
              <dd>{String(fact.value ?? '')}</dd>
            </div>
          ))}
        </dl>
      )}
      {hasHumanGate && (
          <div className="mado-card-gate">
            <ShieldQuestion size={16} aria-hidden="true" />
            <div>
              <strong>Human decision pending</strong>
              <small>
                The Dot must open the dedicated decision card before Cockpit can
                resume.
              </small>
            </div>
          </div>
        )}
    </section>
  );
}

async function settleHumanGate(
  respond: HitlRenderProps['respond'],
  payload: Record<string, unknown>,
): Promise<string | null> {
  if (!respond)
    return 'The decision channel is not ready yet. Try again in a moment.';
  try {
    await respond(payload);
    return null;
  } catch (cause) {
    return cause instanceof Error
      ? `Could not record this decision in the conversation: ${cause.message}`
      : 'Could not record this decision in the conversation. Try again.';
  }
}

export function MadoHumanGateCard({
  args,
  status,
  result,
  respond,
}: HitlRenderProps) {
  const parsed = madoHumanGateReviewSchema.safeParse(args);
  const prior = objectResult(result);
  const [note, setNote] = useState('');
  const [freeform, setFreeform] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const finished = status === 'complete';

  if (!parsed.success) {
    return (
      <section className="mado-card mado-card-attention" role="alert">
        <header>
          <AlertTriangle size={16} aria-hidden="true" />
          <strong>Human decision</strong>
          <span>Invalid request</span>
        </header>
        <p>The Human Gate metadata could not be validated.</p>
      </section>
    );
  }

  const gate = parsed.data;
  const recordedChoice =
    typeof prior.choice === 'string'
      ? prior.choice
      : prior.choose_for_me === true
        ? gate.safe_default ?? 'safe default'
        : '';

  const decide = async (payload: Record<string, unknown>) => {
    if (busy || finished) return;
    setBusy(true);
    setError('');
    const problem = await settleHumanGate(respond, {
      operator_id: gate.operator_id,
      gate_id: gate.gate_id,
      ...payload,
      ...(note.trim() ? { note: note.trim() } : {}),
    });
    if (problem) {
      setError(problem);
      setBusy(false);
    }
  };

  return (
    <section className="mado-gate-card" aria-label="MADO Human Question Gate">
      <header>
        <ShieldQuestion size={17} aria-hidden="true" />
        <strong>Human decision required</strong>
        <span>{finished ? 'Answered' : gate.materiality}</span>
      </header>
      <div className="mado-gate-body">
        <h3>{gate.question}</h3>
        {gate.reason && <p>{gate.reason}</p>}
        {gate.recommendation && !finished && (
          <div className="mado-gate-recommendation">
            <strong>Cockpit recommendation</strong>
            <span>{gate.recommendation}</span>
          </div>
        )}
        {!finished && gate.choices.length > 0 && (
          <div className="mado-gate-choices">
            {gate.choices.map((choice) => (
              <button
                type="button"
                key={choice}
                disabled={busy || !respond}
                onClick={() =>
                  void decide({ choice, choose_for_me: false })
                }
              >
                <strong>{choice}</strong>
                {gate.impacts[choice] && <small>{gate.impacts[choice]}</small>}
              </button>
            ))}
          </div>
        )}
        {!finished && gate.choices.length === 0 && (
          <div className="mado-gate-freeform">
            <label>
              Your answer
              <textarea
                rows={3}
                value={freeform}
                maxLength={2000}
                onChange={(event) => setFreeform(event.target.value)}
                placeholder="Type the decision you want Cockpit to follow."
              />
            </label>
            <button
              type="button"
              disabled={busy || !respond || !freeform.trim()}
              onClick={() =>
                void decide({
                  choice: freeform.trim(),
                  choose_for_me: false,
                })
              }
            >
              Submit answer
            </button>
          </div>
        )}
        {!finished && gate.allow_choose_for_me && gate.safe_default && (
          <button
            type="button"
            className="mado-gate-safe-default"
            disabled={busy || !respond}
            onClick={() => void decide({ choose_for_me: true })}
          >
            Use declared safe default: {gate.safe_default}
          </button>
        )}
        {!finished && (
          <label className="mado-gate-note">
            Optional note
            <textarea
              rows={2}
              value={note}
              maxLength={2000}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Context for the decision, if useful."
            />
          </label>
        )}
        {finished && (
          <div className="mado-gate-recorded" role="status">
            <CheckCircle2 size={16} aria-hidden="true" />
            <span>
              Decision returned to the Dot
              {recordedChoice ? `: ${recordedChoice}` : '.'}
            </span>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
      </div>
      <footer>
        <small>
          This card only records your choice in the conversation. Cockpit changes
          state only after the Dot forwards this exact decision to
          mado_answer_human_gate.
        </small>
      </footer>
    </section>
  );
}

const operatorRenderParameters = z
  .object({ operator_id: z.string() })
  .passthrough();

const evidenceRenderParameters = z
  .object({
    operator_id: z.string(),
    scope: z.enum(['builder', 'qa', 'all']).optional(),
  })
  .passthrough();

const gateAnswerRenderParameters = z
  .object({
    operator_id: z.string(),
    gate_id: z.string().optional(),
    choice: z.string().optional(),
    choose_for_me: z.boolean().optional(),
    note: z.string().optional(),
  })
  .passthrough();

export function useMadoCockpitRenderers() {
  useRenderTool(
    {
      name: 'mado_check_mission',
      parameters: operatorRenderParameters,
      render: (props) => <MadoToolCard {...props} />,
    },
    [],
  );
  useRenderTool(
    {
      name: 'mado_advance_mission',
      parameters: operatorRenderParameters,
      render: (props) => <MadoToolCard {...props} />,
    },
    [],
  );
  useRenderTool(
    {
      name: 'mado_answer_human_gate',
      parameters: gateAnswerRenderParameters,
      render: (props) => <MadoToolCard {...props} />,
    },
    [],
  );
  useRenderTool(
    {
      name: 'mado_show_evidence',
      parameters: evidenceRenderParameters,
      render: (props) => <MadoToolCard {...props} />,
    },
    [],
  );
  useRenderTool(
    {
      name: 'mado_show_qa_result',
      parameters: operatorRenderParameters,
      render: (props) => <MadoToolCard {...props} />,
    },
    [],
  );

  useHumanInTheLoop(
    {
      name: madoHumanGateReviewTool.name,
      description: madoHumanGateReviewTool.description,
      parameters: madoHumanGateReviewSchema,
      render: (props: HitlRenderProps) => <MadoHumanGateCard {...props} />,
    },
    [],
  );
}
