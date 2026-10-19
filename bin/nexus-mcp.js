#!/usr/bin/env node
import { spawnSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
if (args.includes('--help') || args.includes('-h')) {
  console.log('Usage: nexus-mcp [login|install-browser]\nStarts the Nexus stdio MCP. First use opens Union sign-in.\nRequires Python 3.10+ and Chrome, Edge, or Playwright Chromium.');
  process.exit(0);
}
if (args.length > 1 || (args.length === 1 && !['login', 'install-browser'].includes(args[0]))) {
  console.error('Usage: nexus-mcp [login|install-browser]');
  process.exit(1);
}
const fingerprint = createHash('sha256')
  .update(readFileSync(join(root, 'requirements.txt')))
  .update(readFileSync(join(root, 'requirements-login.txt')))
  .digest('hex').slice(0, 16);
const cache = join(homedir(), '.cache', 'nexus-mcp', fingerprint);
const python = join(cache, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const ready = join(cache, '.ready');

function run(command, commandArgs) {
  const result = spawnSync(command, commandArgs, { stdio: ['inherit', 2, 2] });
  if (result.error || result.status !== 0) {
    console.error('Nexus setup failed. Check Python 3.10+ and package-download access.');
    process.exit(1);
  }
}

if (!existsSync(ready) || !existsSync(python)) {
  const systemPython = ['python3', 'python'].find(candidate => {
    const result = spawnSync(candidate, ['-c', 'import sys; sys.exit(sys.version_info < (3, 10))'], { stdio: 'ignore' });
    return !result.error && result.status === 0;
  });
  if (!systemPython) {
    console.error('Install Python 3.10 or newer, then run nexus-mcp again.');
    process.exit(1);
  }
  mkdirSync(cache, { recursive: true, mode: 0o700 });
  run(systemPython, ['-m', 'venv', cache]);
  run(python, ['-m', 'pip', 'install', '-r', join(root, 'requirements-login.txt')]);
  writeFileSync(ready, '', { mode: 0o600 });
}

const pythonArgs = args[0] === 'install-browser'
  ? ['-m', 'playwright', 'install', 'chromium']
  : [join(root, args[0] === 'login' ? 'nexus_login.py' : 'server.py')];
const child = spawn(python, pythonArgs, { stdio: 'inherit' });
child.on('error', () => { console.error('Could not start Nexus MCP.'); process.exit(1); });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => { process.exitCode = code ?? 1; });
