export function canonicalUtcInstant(value: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  if (!match || match[0] !== value || match[1].startsWith("0000-")) return null;

  const wholeSecond = match[1];
  const timestamp = Date.parse(`${wholeSecond}Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 19) !== wholeSecond) {
    return null;
  }

  return `${wholeSecond}.${(match[2] ?? "").padEnd(6, "0")}Z`;
}
