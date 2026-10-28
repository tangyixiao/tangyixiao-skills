const SECRET_KEY = /(^|[_-])(authorization|access.?token|refresh.?token|api.?key|secret|password|credential|cookie|token)([_-]|$)|authorization|access.?token|refresh.?token|api.?key/i;
const SECRET_TEXT = /(\bBearer\s+)[A-Za-z0-9._~+/-]+=*|\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{12,}|xox[baprs]-[A-Za-z0-9-]{8,})\b/gi;
export function redactText(value, maxStringLength = 8_000) {
  let text = String(value ?? '').replace(SECRET_TEXT, '[REDACTED]');
  text = text.replace(/\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|credential)\s*[:=]\s*([^\s,;]+)/gi, '$1=[REDACTED]');
  return text.length > maxStringLength ? `${text.slice(0, Math.max(0, maxStringLength - 1))}…` : text;
}
export function redactValue(value, { maxStringLength = 8_000, maxDepth = 12, maxItems = 200 } = {}) {
  function walk(input, depth) {
    if (typeof input === 'string') return redactText(input, maxStringLength);
    if (input === null || typeof input === 'number' || typeof input === 'boolean') return input;
    if (depth >= maxDepth) return '[TRUNCATED]';
    if (Array.isArray(input)) return input.slice(0, maxItems).map(v => walk(v, depth + 1));
    if (typeof input === 'object') {
      const out = {};
      for (const [key, val] of Object.entries(input).slice(0, maxItems)) out[key] = SECRET_KEY.test(key) ? '[REDACTED]' : walk(val, depth + 1);
      return out;
    }
    return String(input);
  }
  return walk(value, 0);
}
