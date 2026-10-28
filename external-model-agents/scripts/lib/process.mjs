import { spawn } from 'node:child_process';

export function runProcess({ command, args = [], cwd, env = process.env, signal, onStdout, onStderr, input } = {}) {
  if (typeof command !== 'string' || !command) throw new Error('command is required');
  if (!Array.isArray(args) || args.some(a => typeof a !== 'string')) throw new Error('args must be an array of strings');
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, shell: false, windowsHide: true, detached: process.platform !== 'win32', stdio: ['pipe', 'pipe', 'pipe'] });
    let settled = false;
    let escalation;
    const finish = (code, sig) => {
      if (settled) return;
      settled = true; clearTimeout(escalation); signal?.removeEventListener('abort', abort);
      resolve({ exitCode: code ?? (sig ? null : 1), signal: sig ?? null });
    };
    const killTree = () => {
      try {
        if (process.platform === 'win32' && child.pid) {
          const killer = spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { shell: false, windowsHide: true, stdio: 'ignore' });
          killer.once('error', () => {}); killer.unref();
        } else if (child.pid) process.kill(-child.pid, 'SIGTERM');
        else child.kill('SIGTERM');
      } catch { try { child.kill('SIGTERM'); } catch {} }
      escalation = setTimeout(() => {
        try {
          if (process.platform === 'win32' && child.pid) {
            const killer = spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { shell: false, windowsHide: true, stdio: 'ignore' });
            killer.once('error', () => {}); killer.unref();
          } else if (child.pid) process.kill(-child.pid, 'SIGKILL');
        } catch {}
      }, 1_000);
      escalation.unref?.();
    };
    const fail = error => {
      if (settled) return;
      settled = true; clearTimeout(escalation); signal?.removeEventListener('abort', abort);
      killTree(); reject(error);
    };
    const abort = () => killTree();
    const deliver = callback => chunk => {
      if (settled || !callback) return;
      try { callback(chunk); } catch (error) { fail(error); }
    };
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', deliver(onStdout)); child.stderr.on('data', deliver(onStderr));
    child.once('error', fail); child.once('close', finish);
    if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
    if (input !== undefined) child.stdin.end(input, 'utf8'); else child.stdin.end();
  });
}
