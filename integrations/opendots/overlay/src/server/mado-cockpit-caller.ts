import { spawn } from 'node:child_process';
import path from 'node:path';
import type { MadoToolCaller } from './mado-cockpit-tools.js';

const MAX_OUTPUT_BYTES = 2_000_000;
const DEFAULT_TIMEOUT_MS = 30_000;

function appendChunk(
  chunks: Buffer[],
  chunk: Buffer,
  size: { value: number },
) {
  size.value += chunk.length;
  if (size.value > MAX_OUTPUT_BYTES)
    throw new Error('MADO Cockpit bridge output exceeded the safety limit.');
  chunks.push(chunk);
}

export const callMadoCockpit: MadoToolCaller = async (request) => {
  const root = process.env.MADO_COCKPIT_ROOT?.trim();
  if (!root)
    throw new Error(
      'MADO_COCKPIT_ROOT is required to use MADO Cockpit tools in OpenDots.',
    );

  const python = process.env.MADO_COCKPIT_PYTHON?.trim() || 'python';
  const pythonPath = [
    path.join(root, 'src'),
    process.env.PYTHONPATH,
  ]
    .filter(Boolean)
    .join(path.delimiter);

  return await new Promise<unknown>((resolve, reject) => {
    const child = spawn(
      python,
      ['-m', 'mado_cockpit.opendots_tools', '--root', root],
      {
        cwd: root,
        shell: false,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONPATH: pythonPath,
        },
      },
    );

    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    const stdoutSize = { value: 0 };
    const stderrSize = { value: 0 };
    let settled = false;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn();
    };

    const timer = setTimeout(() => {
      child.kill();
      finish(() =>
        reject(
          new Error(
            'MADO Cockpit bridge timed out. Check MADO_COCKPIT_ROOT and Python.',
          ),
        ),
      );
    }, DEFAULT_TIMEOUT_MS);

    child.stdout.on('data', (chunk: Buffer) => {
      try {
        appendChunk(stdout, chunk, stdoutSize);
      } catch (error) {
        child.kill();
        finish(() => reject(error));
      }
    });

    child.stderr.on('data', (chunk: Buffer) => {
      try {
        appendChunk(stderr, chunk, stderrSize);
      } catch (error) {
        child.kill();
        finish(() => reject(error));
      }
    });

    child.on('error', (error) => finish(() => reject(error)));

    child.on('close', (code) => {
      finish(() => {
        const out = Buffer.concat(stdout).toString('utf8').trim();
        const err = Buffer.concat(stderr).toString('utf8').trim();

        if (!out) {
          reject(
            new Error(
              `MADO Cockpit bridge returned no JSON (exit ${code ?? 'unknown'}): ${err || 'no stderr'}`,
            ),
          );
          return;
        }

        let payload: unknown;
        try {
          payload = JSON.parse(out);
        } catch {
          reject(
            new Error(
              `MADO Cockpit bridge returned invalid JSON: ${out.slice(0, 500)}`,
            ),
          );
          return;
        }

        if (code === 2) {
          reject(
            new Error(
              `MADO Cockpit rejected the tool call: ${err || out.slice(0, 500)}`,
            ),
          );
          return;
        }

        resolve(payload);
      });
    });

    child.stdin.end(JSON.stringify(request));
  });
};
