/**
 * Gate 0 G1 probe — single source of truth for both the PowerShell and the Python
 * side. Usage:
 *
 *     node scripts/probe_core.mjs [kernelDir]
 *
 * Output: one line of JSON on stdout, exit 0 when ok / 2 otherwise.
 *   { "ok": true,  "version": "0.2.66", "entry": "..." }
 *   { "ok": false, "reason": "..." }
 *
 * THREE traps this file exists to avoid, all of which produced a WRONG "missing":
 *
 * 1. `require('@aragon-agent/core/package.json')` throws
 *    ERR_PACKAGE_PATH_NOT_EXPORTED — the package's `exports` map does not expose
 *    package.json. Probing that way reports "missing" on a perfectly installed
 *    machine, which silently downgrades every course to the static template.
 * 2. A bare `import('@aragon-agent/core')` resolves relative to THIS file (repo
 *    root), not to the caller's cwd, so it must resolve from kernelDir explicitly.
 * 3. `createRequire(...).resolve(...)` also fails: the package is ESM-only, its
 *    `exports` map has `import` but no `require` condition.
 *
 * So: locate the package directory on disk by walking node_modules, read its
 * package.json, then import the actual ESM entry.
 */

import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const PACKAGE = '@aragon-agent/core';
const [scope, name] = PACKAGE.split('/');
const kernelDir = resolve(process.argv[2] || join(process.cwd(), 'services', 'agent-kernel'));

function emit(payload, code) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
  process.exit(code);
}

function findPackageDir(startDir) {
  let dir = startDir;
  for (let i = 0; i < 12; i += 1) {
    const candidate = join(dir, 'node_modules', scope, name);
    if (existsSync(join(candidate, 'package.json'))) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

const packageDir = findPackageDir(kernelDir);
if (!packageDir) {
  emit({ ok: false, reason: `not installed under ${kernelDir} (run: pnpm -C services/agent-kernel install)` }, 2);
}

let manifest;
try {
  manifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8'));
} catch (err) {
  emit({ ok: false, reason: `package.json unreadable: ${String(err?.message ?? err).slice(0, 160)}` }, 2);
}

const rootExport = typeof manifest.exports === 'object' && manifest.exports !== null ? manifest.exports['.'] : null;
const entryRel = (rootExport && (rootExport.import || rootExport.default)) || manifest.module || manifest.main;
if (!entryRel) {
  emit({ ok: false, reason: 'package.json declares no ESM entry' }, 2);
}
const entry = isAbsolute(entryRel) ? entryRel : join(packageDir, entryRel);
if (!existsSync(entry)) {
  emit({ ok: false, reason: `entry file missing: ${entry}` }, 2);
}

try {
  const mod = await import(pathToFileURL(entry).href);
  if (typeof mod.Agent !== 'function' || typeof mod.initProviders !== 'function') {
    emit({ ok: false, reason: 'package imported but Agent/initProviders missing' }, 2);
  }
  emit({ ok: true, version: manifest.version ?? null, entry }, 0);
} catch (err) {
  emit({ ok: false, reason: `import failed: ${String(err?.message ?? err).slice(0, 200)}` }, 2);
}
