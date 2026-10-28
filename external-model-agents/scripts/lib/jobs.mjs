import { mkdir, readFile, writeFile, appendFile, open, stat, rm } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { redactText, redactValue } from './redact.mjs';

export const providers = ['workbuddy', 'workbuddy-ai', 'opencode', 'zcode'];
const terminal = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'interrupted']);
const active = new Set(['starting', 'running']);
const idPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;

export function validateSpec(input, { followup = false } = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('spec must be a JSON object');
  const spec = structuredClone(input);
  if (!providers.includes(spec.provider)) throw new Error(`unsupported provider: ${String(spec.provider)}`);
  for (const key of ['model', 'prompt', 'cwd']) if (typeof spec[key] !== 'string' || !spec[key].trim()) throw new Error(`${key} must be a non-empty string`);
  if (spec.mode !== 'read-only' && spec.mode !== 'workspace-write') throw new Error('mode must be read-only or workspace-write');
  if (!Number.isSafeInteger(spec.timeoutMs) || spec.timeoutMs <= 0) throw new Error('timeoutMs must be a positive integer');
  if (spec.maxTurns !== undefined && (!Number.isSafeInteger(spec.maxTurns) || spec.maxTurns <= 0)) throw new Error('maxTurns must be a positive integer');
  if (spec.maxTurns !== undefined) throw Object.assign(new Error('maxTurns cannot be enforced by the executor; remove it'), { code: 'UNSUPPORTED_HARD_LIMIT' });
  if (spec.allowedPaths !== undefined && (!Array.isArray(spec.allowedPaths) || spec.allowedPaths.some(p => typeof p !== 'string' || !p.trim()))) throw new Error('allowedPaths must be an array of non-empty strings');
  if (spec.allowedPaths?.length) throw Object.assign(new Error('allowedPaths cannot be enforced by the executor; remove it or use an adapter with verified enforcement'), { code: 'UNSUPPORTED_HARD_LIMIT' });
  if (spec.config !== undefined && (!spec.config || typeof spec.config !== 'object' || Array.isArray(spec.config))) throw new Error('config must be an object');
  if (spec.budget !== undefined && (!spec.budget || typeof spec.budget !== 'object' || Array.isArray(spec.budget))) throw new Error('budget must be an object');
  if (followup) {
    if (spec.allowLive !== true) throw new Error('followup requires explicit allowLive: true');
    if (typeof spec.sessionId !== 'string' || !spec.sessionId.trim()) throw new Error('followup requires an exact native sessionId');
  } else if (spec.allowLive !== true) throw new Error('live execution requires explicit allowLive: true');
  if (spec.id !== undefined && (typeof spec.id !== 'string' || !idPattern.test(spec.id))) throw new Error('id must contain 1-80 letters, digits, dots, underscores, or hyphens');
  return { ...spec, cwd: resolve(spec.cwd), id: spec.id ?? randomUUID() };
}

async function readJson(path) { return JSON.parse(await readFile(path, 'utf8')); }
async function atomicJson(path, value) {
  const tmp = `${path}.${randomUUID()}.tmp`;
  await writeFile(tmp, `${JSON.stringify(value, null, 2)}\n`, { flag: 'wx' });
  const h = await open(tmp, 'r+');
  try { await h.sync(); } finally { await h.close(); }
  await (await import('node:fs/promises')).rename(tmp, path);
}

export function createJobManager({ stateDir, configPath, maxConcurrency = 1, adapterLoader, heartbeatMs = 2_000, staleMs = 15_000 } = {}) {
  if (!stateDir) throw new Error('stateDir is required');
  if (!Number.isSafeInteger(maxConcurrency) || maxConcurrency !== 1) throw new Error('only maxConcurrency: 1 is supported');
  const root = resolve(stateDir);
  const inflight = new Map();
  const controllers = new Map();
  const stateWrites = new Map();
  const maxEventCount = 1_000;
  const maxEventBytes = 2 * 1024 * 1024;
  const jobDir = id => join(root, id);
  const taskPath = id => join(jobDir(id), 'task.json');
  const specPath = id => join(jobDir(id), 'spec.json');
  const eventsPath = id => join(jobDir(id), 'events.jsonl');
  const controlPath = id => join(jobDir(id), 'control.json');
  const lockPath = join(root, 'active.lock');
  async function emit(id, event) {
    const safe = redactValue(event);
    const path = eventsPath(id);
    const existing = await readFile(path, 'utf8');
    if (existing.split('\n').length > maxEventCount || Buffer.byteLength(existing) > maxEventBytes) return;
    const line = `${JSON.stringify({ at: new Date().toISOString(), ...safe })}\n`;
    if (Buffer.byteLength(existing) + Buffer.byteLength(line) > maxEventBytes) return;
    await appendFile(path, line, 'utf8');
  }
  async function getTask(id) {
    if (!idPattern.test(id)) throw new Error('invalid job id');
    const task = await readJson(taskPath(id));
    await recoverIfStale(task);
    return await readJson(taskPath(id));
  }
  async function recoverIfStale(task) {
    if (!active.has(task.status)) return;
    const age = Date.now() - Date.parse(task.heartbeatAt ?? task.updatedAt ?? task.createdAt);
    if (age <= staleMs) return;
    let workerAlive = true;
    try { if (Number.isSafeInteger(task.workerPid)) process.kill(task.workerPid, 0); }
    catch (e) { if (e.code === 'ESRCH') workerAlive = false; }
    if (workerAlive) {
      return;
    }
    task.status = 'interrupted'; task.error = 'worker heartbeat expired; outcome is unknown'; task.finishedAt = new Date().toISOString(); task.updatedAt = task.finishedAt;
    await atomicJson(taskPath(task.id), task);
    await releaseLock(task.id, task.lockToken);
  }
  async function releaseLock(id, token) {
    try {
      const lock = await readJson(lockPath);
      if (lock.id === id && lock.token === token) await rm(lockPath, { force: true });
    } catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
  async function acquireLock(id, token) {
    await mkdir(root, { recursive: true });
    const lock = { id, token, createdAt: new Date().toISOString() };
    try {
      const h = await open(lockPath, 'wx');
      try { await h.writeFile(JSON.stringify(lock)); await h.sync(); } finally { await h.close(); }
      return;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
    }
    let previous;
    try { previous = await readJson(lockPath); } catch {}
    if (previous?.id && idPattern.test(previous.id)) {
      try {
        const task = await readJson(taskPath(previous.id));
        const age = Date.now() - Date.parse(task.heartbeatAt ?? task.updatedAt ?? task.createdAt);
        if (!active.has(task.status) || age > staleMs) {
          if (active.has(task.status)) {
            await recoverIfStale(task);
            const recovered = await readJson(taskPath(previous.id));
            if (active.has(recovered.status)) throw Object.assign(new Error('stale worker is still alive or its exit cannot be confirmed; concurrency lock retained'), { code: 'STALE_WORKER_LOCK' });
          }
          else await releaseLock(previous.id, previous.token);
          return acquireLock(id, token);
        }
      } catch (e) { if (e.code === 'ENOENT') { await rm(lockPath, { force: true }); return acquireLock(id, token); } throw e; }
    }
    throw Object.assign(new Error('another job is active; default concurrency is 1'), { code: 'CONCURRENCY_LIMIT' });
  }
  async function setTask(id, updater) {
    const previous = stateWrites.get(id) ?? Promise.resolve();
    const current = previous.catch(() => {}).then(async () => {
      const p = taskPath(id); const task = await readJson(p);
      const next = updater(task); next.updatedAt = new Date().toISOString();
      await atomicJson(p, next); return next;
    });
    stateWrites.set(id, current);
    try { return await current; } finally { if (stateWrites.get(id) === current) stateWrites.delete(id); }
  }
  async function execute(id, { loader = adapterLoader, workerToken } = {}) {
    const spec = await readJson(specPath(id));
    let task = await readJson(taskPath(id));
    if (!workerToken || task.lockToken !== workerToken) throw new Error('worker identity does not match task reservation');
    const controller = new AbortController(); controllers.set(id, controller);
    const assertLease = async () => {
      const [lock, current] = await Promise.all([readJson(lockPath), readJson(taskPath(id))]);
      if (lock.id !== id || lock.token !== workerToken || current.lockToken !== workerToken) throw new Error('worker lease is no longer valid');
    };
    let timeout = false;
    let heartbeatTimer;
    let cancelTimer;
    let heartbeatPending = false;
    const heartbeat = async () => {
      if (heartbeatPending) return;
      heartbeatPending = true;
      try { await setTask(id, t => active.has(t.status) ? ({ ...t, heartbeatAt: new Date().toISOString() }) : t); } catch {} finally { heartbeatPending = false; }
    };
    heartbeatTimer = setInterval(heartbeat, heartbeatMs); heartbeatTimer.unref?.();
    cancelTimer = setInterval(async () => {
      try { const c = await readJson(controlPath(id)); if (c.cancel === true && c.token === task.controlToken) controller.abort('cancelled'); } catch {}
    }, 100);
    cancelTimer.unref?.();
    const timeoutTimer = setTimeout(() => { timeout = true; controller.abort('timeout'); }, spec.timeoutMs);
    timeoutTimer.unref?.();
    try {
      await assertLease();
      task = await setTask(id, t => ({ ...t, status: 'running', workerPid: process.pid, startedAt: t.startedAt ?? new Date().toISOString(), heartbeatAt: new Date().toISOString() }));
      await emit(id, { type: 'started', provider: spec.provider, model: spec.model });
      if (spec.budget) await emit(id, { type: 'budget_set', budget: spec.budget, enforcement: 'caller-declared; executor does not enforce usage caps' });
      if (typeof loader !== 'function') throw new Error('no adapter loader is configured');
      await assertLease();
      const adapter = await loader(spec.provider, spec.config ?? {});
      let sessionId = task.sessionId;
      const operation = Promise.resolve().then(() => adapter.run(spec, {
        signal: controller.signal,
        emit: event => emit(id, event),
        onSession: async exactId => {
          if (typeof exactId !== 'string' || !exactId.trim()) throw new Error('adapter returned an invalid session id');
          sessionId = exactId;
          await setTask(id, t => ({ ...t, sessionId: exactId }));
        },
      }));
      const aborted = new Promise((_, reject) => {
        const fail = () => reject(Object.assign(new Error(controller.signal.reason === 'timeout' ? 'job time limit exceeded' : 'job cancelled'), { code: controller.signal.reason === 'timeout' ? 'TIMEOUT' : 'CANCELLED' }));
        if (controller.signal.aborted) fail(); else controller.signal.addEventListener('abort', fail, { once: true });
      });
      let outcome;
      try {
        outcome = await Promise.race([operation, aborted]);
      } catch (error) {
        // The adapter owns its subprocesses and bridge. Keep the lease until
        // it finishes abort cleanup, even if that means retaining the lock.
        if (controller.signal.aborted) await operation.catch(() => {});
        throw error;
      }
      if (timeout || controller.signal.reason === 'timeout') throw Object.assign(new Error('job time limit exceeded'), { code: 'TIMEOUT' });
      if (controller.signal.aborted) throw Object.assign(new Error('job cancelled'), { code: 'CANCELLED' });
      const text = typeof outcome?.text === 'string' ? outcome.text : '';
      const status = outcome?.outcome === 'awaiting_input' ? 'awaiting_input' : outcome?.outcome === 'failed' ? 'failed' : (text.trim() || outcome?.toolEvidence === true ? 'completed' : 'failed');
      const result = { id, status, text: redactText(text), sessionId: outcome?.sessionId ?? sessionId, usage: outcome?.usage };
      await atomicJson(join(jobDir(id), 'result.json'), redactValue(result));
      await setTask(id, t => ({ ...t, status, sessionId: result.sessionId ?? t.sessionId, finishedAt: status === 'awaiting_input' ? undefined : new Date().toISOString(), outcome: outcome?.outcome }));
      await emit(id, { type: status, message: status === 'failed' ? 'adapter returned no substantive output or tool evidence' : undefined });
    } catch (error) {
      const status = timeout || error?.code === 'TIMEOUT' ? 'timed_out' : controller.signal.reason === 'cancelled' || error?.code === 'CANCELLED' ? 'cancelled' : 'failed';
      const safeError = redactText(error?.message ?? String(error));
      const safeCode = typeof error?.code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code) ? error.code : 'ADAPTER_ERROR';
      await atomicJson(join(jobDir(id), 'result.json'), { id, status, error: safeError, code: safeCode });
      await setTask(id, t => ({ ...t, status, error: safeError, errorCode: safeCode, finishedAt: new Date().toISOString() }));
      await emit(id, { type: status, error: safeError, code: safeCode });
    } finally {
      clearInterval(heartbeatTimer); clearInterval(cancelTimer); clearTimeout(timeoutTimer); controllers.delete(id);
      const finalTask = await readJson(taskPath(id));
      await releaseLock(id, workerToken);
    }
  }
  async function start(input, { detached = false, workerCommand } = {}) {
    const spec = validateSpec(input);
    const id = spec.id; const directory = jobDir(id);
    await mkdir(root, { recursive: true });
    try { await mkdir(directory); } catch (e) { if (e.code === 'EEXIST') throw new Error(`job already exists: ${id}`); throw e; }
    const token = randomUUID(); const controlToken = randomUUID();
    let launched = false;
    const now = new Date().toISOString();
    const task = { id, provider: spec.provider, model: spec.model, cwd: spec.cwd, mode: spec.mode, status: 'starting', sessionId: spec.sessionId, createdAt: now, updatedAt: now, heartbeatAt: now, lockToken: token, controlToken };
    try {
      // Execution input must be lossless; redact only exported events and results.
      await atomicJson(specPath(id), spec);
      await atomicJson(taskPath(id), task);
      await writeFile(eventsPath(id), '', { flag: 'wx' });
      await atomicJson(controlPath(id), { token: controlToken, cancel: false });
      await acquireLock(id, token);
      if (detached) {
        const { spawn } = await import('node:child_process');
        if (!workerCommand?.command || !Array.isArray(workerCommand.args)) throw new Error('workerCommand is required for detached start');
        const child = spawn(workerCommand.command, workerCommand.args, { cwd: workerCommand.cwd ?? process.cwd(), env: { ...process.env, ...workerCommand.env, EXTERNAL_AGENTS_STATE_DIR: root, EXTERNAL_AGENTS_WORKER_TOKEN: token }, stdio: 'ignore', detached: true, shell: false, windowsHide: true });
        await new Promise((resolve, reject) => {
          child.once('spawn', resolve);
          child.once('error', reject);
        });
        launched = true;
        child.unref();
      } else {
        const promise = execute(id, { workerToken: token }); inflight.set(id, promise); promise.finally(() => inflight.delete(id));
        launched = true;
      }
      return await getTask(id);
    } catch (e) {
      if (!launched) {
        await releaseLock(id, token);
        await rm(directory, { recursive: true, force: true });
      }
      throw e;
    }
  }
  async function wait(id, { timeoutMs = 30_000, pollMs = 50 } = {}) {
    const end = Date.now() + timeoutMs;
    while (Date.now() <= end) {
      const task = await getTask(id);
      if (terminal.has(task.status) || task.status === 'awaiting_input') return task;
      await delay(Math.min(pollMs, Math.max(1, end - Date.now())));
    }
    return getTask(id);
  }
  async function result(id) { await getTask(id); return readJson(join(jobDir(id), 'result.json')); }
  async function cancel(id) {
    const task = await getTask(id);
    if (!active.has(task.status) && task.status !== 'awaiting_input') return task;
    await atomicJson(controlPath(id), { token: task.controlToken, cancel: true, requestedAt: new Date().toISOString() });
    controllers.get(id)?.abort('cancelled');
    if (task.status === 'awaiting_input') {
      const previousResult = await readJson(join(jobDir(id), 'result.json'));
      await atomicJson(join(jobDir(id), 'result.json'), { ...previousResult, status: 'cancelled' });
      await setTask(id, t => ({ ...t, status: 'cancelled', finishedAt: new Date().toISOString() }));
      await releaseLock(id, task.lockToken);
    }
    return getTask(id);
  }
  async function followup(id, { prompt, timeoutMs, allowLive } = {}, startOptions = {}) {
    if (allowLive !== true) throw new Error('followup requires explicit --allow-live opt-in');
    const original = await getTask(id);
    if (!original.sessionId) throw new Error('cannot follow up: task has no persisted native session id');
    const originalSpec = await readJson(specPath(id));
    const next = { ...originalSpec, id: undefined, prompt, timeoutMs: timeoutMs ?? originalSpec.timeoutMs, sessionId: original.sessionId, allowLive };
    const validated = validateSpec(next, { followup: true });
    const options = { ...startOptions };
    if (typeof options.workerCommand === 'function') options.workerCommand = options.workerCommand(validated.id);
    return start(validated, options);
  }
  async function status(id) { return getTask(id); }
  async function list() {
    await mkdir(root, { recursive: true });
    const { readdir } = await import('node:fs/promises');
    const entries = await readdir(root, { withFileTypes: true }); const out = [];
    for (const entry of entries) if (entry.isDirectory() && idPattern.test(entry.name)) { try { out.push(await getTask(entry.name)); } catch {} }
    return out;
  }
  async function runWorker(id, token) { return execute(id, { workerToken: token }); }
  async function doctor(provider) {
    const adapter = await (adapterLoader ?? (await import('./providers/index.mjs')).getAdapter)(provider, {});
    return adapter.doctor({});
  }
  async function models(provider, { refresh = false } = {}) {
    const adapter = await (adapterLoader ?? (await import('./providers/index.mjs')).getAdapter)(provider, {});
    return adapter.listModels({ config: {}, refresh });
  }
  return { start, runWorker, status, wait, result, followup, cancel, list, doctor, models, root, lockPath };
}
