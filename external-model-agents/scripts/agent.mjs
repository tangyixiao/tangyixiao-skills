import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createJobManager } from './lib/jobs.mjs';
import { redactText, redactValue } from './lib/redact.mjs';

const HELP = `external-model-agents — durable local task executor\n\nUsage: node scripts/agent.mjs [--state-dir DIR] [--config FILE] <command> [options]\n\nCommands:\n  doctor <provider>             Inspect installation and authentication state (no model call)\n  models <provider> [--refresh] List available catalog entries (no model call)\n  spawn --spec FILE|-           Start a durable job; spec must include allowLive:true\n  status <job-id>               Read task status\n  wait <job-id> [--timeout-ms N] Wait for status change/terminal state\n  result <job-id>               Read final result\n  followup <job-id> --allow-live --prompt TEXT [--timeout-ms N] Continue the exact saved session\n  cancel <job-id>               Request cancellation through task control file\n  list                          List known jobs\n  worker --id ID                Internal detached worker command\n\nThe first release enforces global concurrency 1. State and output are local to --state-dir.\n`;
const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = dirname(scriptPath);
function parse(argv) {
  const options = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--state-dir' || arg === '--config' || arg === '--spec' || arg === '--timeout-ms' || arg === '--prompt' || arg === '--id') options[arg.slice(2)] = argv[++i];
    else if (arg === '--refresh') options.refresh = true;
    else if (arg === '--allow-live') options.allowLive = true;
    else if (arg.startsWith('--')) throw new Error(`unknown option: ${arg}`);
    else options.positional.push(arg);
  }
  return options;
}
async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes('--help') || argv.includes('-h') || argv.length === 0) { process.stdout.write(HELP); return; }
  const opts = parse(argv);
  const command = opts.positional.shift();
  const providerNames = ['workbuddy', 'workbuddy-ai', 'opencode', 'zcode'];
  let config = {};
  if (opts.config) config = JSON.parse(await readFile(resolve(opts.config), 'utf8'));
  const stateDir = resolve(opts['state-dir'] ?? process.env.EXTERNAL_AGENTS_STATE_DIR ?? '.runtime/external-model-agents');
  const manager = createJobManager({ stateDir, adapterLoader: async (provider, taskConfig = {}) => {
    const { getAdapter } = await import('./lib/providers/index.mjs');
    return getAdapter(provider, { ...config, ...taskConfig });
  } });
  const print = value => process.stdout.write(`${JSON.stringify(redactValue(value), null, 2)}\n`);
  if (command === 'doctor' || command === 'models') {
    const provider = opts.positional[0];
    if (!providerNames.includes(provider)) throw new Error(`provider must be one of: ${providerNames.join(', ')}`);
    const adapter = await (await import('./lib/providers/index.mjs')).getAdapter(provider, config);
    print(command === 'doctor' ? await adapter.doctor(config) : await adapter.listModels({ config, refresh: opts.refresh === true })); return;
  }
  if (command === 'spawn') {
    const raw = opts.spec === '-' || !opts.spec ? await new Promise((resolve, reject) => { let s = ''; process.stdin.setEncoding('utf8'); process.stdin.on('data', c => s += c); process.stdin.on('end', () => resolve(s)); process.stdin.on('error', reject); }) : await readFile(resolve(opts.spec), 'utf8');
    const spec = JSON.parse(raw);
    spec.id ??= randomUUID();
    if (Object.keys(config).length) spec.config = { ...config, ...spec.config };
    const workerArgs = [scriptPath, '--state-dir', stateDir];
    if (opts.config) workerArgs.push('--config', resolve(opts.config));
    workerArgs.push('worker', '--id', spec.id);
    const started = await manager.start(spec, { detached: true, workerCommand: { command: process.execPath, args: workerArgs, cwd: scriptDir } });
    print(started); return;
  }
  const id = opts.positional[0];
  if (command === 'worker') { await manager.runWorker(opts.id ?? id, process.env.EXTERNAL_AGENTS_WORKER_TOKEN); return; }
  if (!id && command !== 'list') throw new Error(`${command} requires a job id`);
  if (command === 'status') print(await manager.status(id));
  else if (command === 'wait') print(await manager.wait(id, { timeoutMs: Number(opts['timeout-ms'] ?? 30_000) }));
  else if (command === 'result') print(await manager.result(id));
  else if (command === 'cancel') print(await manager.cancel(id));
  else if (command === 'followup') print(await manager.followup(id, { prompt: opts.prompt, timeoutMs: opts['timeout-ms'] ? Number(opts['timeout-ms']) : undefined, allowLive: opts.allowLive }, {
    detached: true,
    workerCommand: jobId => ({ command: process.execPath, cwd: scriptDir, args: [scriptPath, '--state-dir', stateDir, ...(opts.config ? ['--config', resolve(opts.config)] : []), 'worker', '--id', jobId] }),
  }));
  else if (command === 'list') print(await manager.list());
  else throw new Error(`unknown command: ${command}`);
}
main().catch(error => { process.stderr.write(`${redactText(error?.message ?? String(error))}\n`); process.exitCode = 1; });
