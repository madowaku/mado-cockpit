import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  MadoHumanGateCard,
  MadoToolCard,
} from './mado-cockpit-renderers';

type ToolResult = {
  ok?: boolean;
  data?: {
    status?: string;
    human_gate?: {
      gate?: {
        id?: string;
        question?: string;
        reason?: string;
        materiality?: string;
        choices?: string[];
        impacts?: Record<string, string>;
        recommendation?: string;
        safe_default?: string;
        allow_choose_for_me?: boolean;
      };
    } | null;
  };
};

async function requestJson(url: string, init?: RequestInit) {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body ? { 'content-type': 'application/json' } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok)
    throw new Error(
      payload &&
        typeof payload === 'object' &&
        'error' in payload &&
        typeof payload.error === 'string'
        ? payload.error
        : `Request failed with HTTP ${response.status}`,
    );
  return payload;
}

export function MadoDogfoodPage() {
  const operatorId = useMemo(
    () => new URLSearchParams(location.search).get('operator_id') ?? '',
    [],
  );
  const [statusResult, setStatusResult] = useState<unknown>();
  const [resolutionResult, setResolutionResult] = useState<unknown>();
  const [gateFinished, setGateFinished] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!operatorId) throw new Error('operator_id query parameter is required.');
    const result = await requestJson(
      `/api/mado-dogfood/status?operator_id=${encodeURIComponent(operatorId)}`,
    );
    setStatusResult(result);
    return result as ToolResult;
  }, [operatorId]);

  useEffect(() => {
    void refresh().catch((cause) =>
      setError(cause instanceof Error ? cause.message : 'Status load failed.'),
    );
  }, [refresh]);

  const typed = statusResult as ToolResult | undefined;
  const gate = typed?.data?.human_gate?.gate;
  const gateArgs =
    gate?.id && gate.question && gate.materiality
      ? {
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
        }
      : undefined;

  const resolve = useCallback(
    async (decision: unknown) => {
      if (!decision || typeof decision !== 'object')
        throw new Error('Human Gate decision was not an object.');

      const result = await requestJson('/api/mado-dogfood/resolve', {
        method: 'POST',
        body: JSON.stringify(decision),
      });
      setResolutionResult(result);
      setGateFinished(true);
      await refresh();
    },
    [refresh],
  );

  return (
    <main className="mado-dogfood-page">
      <header className="mado-dogfood-heading">
        <span className="eyebrow">MCC-M1.6 BROWSER DOGFOOD</span>
        <h1>OpenDots × MADO Cockpit</h1>
        <p>Real browser clickthrough against the local Cockpit runtime.</p>
      </header>

      {error && (
        <p className="chat-error" role="alert">
          {error}
        </p>
      )}

      {statusResult !== undefined && (
        <section aria-label="Current mission card">
          <MadoToolCard
            name="mado_check_mission"
            toolCallId="mcc-m1.6-status"
            status="complete"
            result={statusResult}
          />
        </section>
      )}

      {gateArgs && (
        <section aria-label="Human Gate clickthrough">
          <MadoHumanGateCard
            args={gateArgs}
            status={gateFinished ? 'complete' : 'executing'}
            result={
              gateFinished
                ? {
                    choice:
                      resolutionResult &&
                      typeof resolutionResult === 'object' &&
                      'data' in resolutionResult &&
                      resolutionResult.data &&
                      typeof resolutionResult.data === 'object' &&
                      'resolution' in resolutionResult.data &&
                      resolutionResult.data.resolution &&
                      typeof resolutionResult.data.resolution === 'object' &&
                      'choice' in resolutionResult.data.resolution
                        ? resolutionResult.data.resolution.choice
                        : undefined,
                  }
                : undefined
            }
            respond={resolve}
            toolCallId="mcc-m1.6-human-gate"
          />
        </section>
      )}

      {resolutionResult !== undefined && (
        <section aria-label="Human Gate resolution card">
          <MadoToolCard
            name="mado_answer_human_gate"
            toolCallId="mcc-m1.6-resolution"
            status="complete"
            result={resolutionResult}
          />
        </section>
      )}

      {!gateArgs &&
        typed?.ok === true &&
        typed.data?.status !== 'awaiting_human' && (
          <p className="mado-dogfood-success" role="status">
            Human Gate cleared. Cockpit resumed at {typed.data?.status ?? 'unknown'}.
          </p>
        )}
    </main>
  );
}
