export type ResultsGroup = "web" | "reddit" | "clips";

export const RESULTS_GROUPS: ResultsGroup[] = ["web", "reddit", "clips"];

export function cycleGroup(current: ResultsGroup, delta: number): ResultsGroup {
  const idx = RESULTS_GROUPS.indexOf(current);
  const safeIdx = idx >= 0 ? idx : 0;
  const next = wrapIndex(safeIdx + delta, RESULTS_GROUPS.length);
  return RESULTS_GROUPS[next] ?? "web";
}

export function wrapIndex(value: number, length: number): number {
  if (length <= 0) return 0;
  const raw = value % length;
  return raw < 0 ? raw + length : raw;
}

export function wrapSelection(currentIndex: number, delta: number, length: number): number {
  if (length <= 0) return 0;
  return wrapIndex(currentIndex + delta, length);
}

export function normalizeSelection(index: number, length: number): number {
  if (length <= 0) return 0;
  if (index < 0) return 0;
  if (index >= length) return 0;
  return index;
}

export function firstNonEmptyGroup(lengths: Record<ResultsGroup, number>): ResultsGroup | null {
  for (const g of RESULTS_GROUPS) {
    if ((lengths[g] ?? 0) > 0) return g;
  }
  return null;
}

export type HistoryState = {
  entries: string[];
  browsingIndex: number | null; // 0..entries.length-1, or null when not browsing
  draft: string;
};

export function initialHistoryState(): HistoryState {
  return { entries: [], browsingIndex: null, draft: "" };
}

export function pushHistory(state: HistoryState, entry: string): HistoryState {
  const trimmed = entry.trim();
  if (!trimmed) return state;
  return { ...state, entries: [...state.entries, trimmed] };
}

export function historyUp(state: HistoryState, currentInput: string): { state: HistoryState; value: string } {
  if (state.entries.length === 0) return { state, value: currentInput };

  if (state.browsingIndex === null) {
    const nextIndex = state.entries.length - 1;
    return {
      state: { ...state, browsingIndex: nextIndex, draft: currentInput },
      value: state.entries[nextIndex] ?? currentInput,
    };
  }

  const nextIndex = Math.max(0, state.browsingIndex - 1);
  return {
    state: { ...state, browsingIndex: nextIndex },
    value: state.entries[nextIndex] ?? currentInput,
  };
}

export function historyDown(state: HistoryState, currentInput: string): { state: HistoryState; value: string } {
  if (state.browsingIndex === null) return { state, value: currentInput };

  const lastIndex = state.entries.length - 1;
  if (state.browsingIndex >= lastIndex) {
    return { state: { ...state, browsingIndex: null }, value: state.draft };
  }

  const nextIndex = state.browsingIndex + 1;
  return {
    state: { ...state, browsingIndex: nextIndex },
    value: state.entries[nextIndex] ?? currentInput,
  };
}

export function exitHistoryBrowse(state: HistoryState): HistoryState {
  if (state.browsingIndex === null) return state;
  return { ...state, browsingIndex: null };
}

