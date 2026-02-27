export type DetailViewport = {
  width: number;
  height: number;
  offset: number;
  maxOffset: number;
  lines: string[];
  allLinesCount: number;
};

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function wrapLine(line: string, width: number): string[] {
  if (width <= 0) return [""];
  if (line.length === 0) return [""];
  const out: string[] = [];
  for (let i = 0; i < line.length; i += width) {
    out.push(line.slice(i, i + width));
  }
  return out.length > 0 ? out : [""];
}

export function wrapText(text: string, width: number): string[] {
  const rawLines = text.split(/\r?\n/);
  const out: string[] = [];
  for (const raw of rawLines) {
    out.push(...wrapLine(raw, width));
  }
  return out.length > 0 ? out : [""];
}

export function buildViewport(text: string, width: number, height: number, offset: number): DetailViewport {
  const safeWidth = Math.max(1, Math.floor(width));
  const safeHeight = Math.max(1, Math.floor(height));

  const wrapped = wrapText(text, safeWidth);
  const maxOffset = Math.max(0, wrapped.length - safeHeight);
  const safeOffset = clamp(Math.floor(offset), 0, maxOffset);
  const lines = wrapped.slice(safeOffset, safeOffset + safeHeight);

  return {
    width: safeWidth,
    height: safeHeight,
    offset: safeOffset,
    maxOffset,
    lines,
    allLinesCount: wrapped.length,
  };
}

