export type Mode = "projects" | "agents" | "qa";
export type Row = { title: string; detail: string; status: string };
export type ViewData = {
  project: string;
  projects: Row[];
  agents: Row[];
  qa: Row[];
};
export const MODES: readonly Mode[];
export const EMPTY: unknown;
export const FIXTURE: ViewData;
export function normalizeSnapshot(raw: unknown): ViewData;
export function buildProgram(mode: Mode, data: ViewData, source?: "sample" | "live"): string;
export function byteSize(value: string): number;
