import "./helpers/notes-locks.ts";
/** Node storage replay, not browser/OS restart evidence. Python invokes each
 * phase in a fresh process with the same serialized localStorage bytes. */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import dns from 'node:dns';
import { syncBuiltinESMExports } from 'node:module';
import { addNote, loadNotesState } from '../src/lib/notes.ts';

test('saved research notes replay in a fresh process with an explicit synthetic clock', { skip: !process.env.VR_SAVED_REPLAY_FILE }, async () => {
  const path = process.env.VR_SAVED_REPLAY_FILE!;
  const phase = process.env.VR_SAVED_REPLAY_PHASE!;
  const clock = process.env.VR_SAVED_JOURNEY_CLOCK!;
  const externalAttempts: string[] = [];
  const restores: (() => void)[] = [];
  function guard(target: object, key: string) {
    const descriptor = Object.getOwnPropertyDescriptor(target, key)!;
    Object.defineProperty(target, key, { ...descriptor, value: () => {
      externalAttempts.push(key);
      throw new Error('Network forbidden in saved storage replay');
    } });
    restores.push(() => Object.defineProperty(target, key, descriptor));
  }
  for (const [target, key] of [[globalThis, 'fetch'], [net.Socket.prototype, 'connect'],
    [http, 'request'], [http, 'get'], [https, 'request'], [https, 'get'],
    [dgram, 'createSocket'], [dns, 'lookup'], [dns, 'resolve']] as [object, string][]) guard(target, key);
  syncBuiltinESMExports();
  const originalNow = Date.now;
  Date.now = () => Date.parse(clock);
  let writes = 0;
  const values: Record<string, string> = phase === 'capture' ? {} : JSON.parse(readFileSync(path, 'utf8'));
  const before = phase === 'capture' ? null : readFileSync(path, 'utf8');
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => values[key] ?? null,
    setItem: (key: string, value: string) => { writes++; values[key] = value; },
    removeItem: (key: string) => { writes++; delete values[key]; },
  } });
  try {
    if (phase === 'capture') {
      const record = JSON.parse(readFileSync(process.env.VR_SAVED_REPLAY_RECORD!, 'utf8'));
      (await addNote('Company research', 'Synthetic restart research', JSON.stringify(record)));
      assert.equal(writes, 1);
      writeFileSync(path, JSON.stringify(values));
    }
    const state = loadNotesState();
    assert.equal(state.error, '');
    assert.equal(state.notes.length, 1);
    const note = state.notes[0];
    const record = JSON.parse(note.content);
    assert.equal(record.status, 'COMPLETED');
    assert.equal(record.stages.length, 6);
    assert.equal(note.ts, Date.parse('2026-10-19T12:00:00.000000Z'));
    assert.ok(note.id.startsWith(`${note.ts}-`));
    if (phase !== 'capture') {
      assert.equal(writes, 0);
      assert.equal(readFileSync(path, 'utf8'), before);
    }
    assert.deepEqual(externalAttempts, []);
    console.log('SAVED_REPLAY_RECEIPT=' + JSON.stringify({ phase, clock, external_attempts: externalAttempts, date_mode: 'SIMULATED_NOT_NATURAL_ELAPSED', writes, note, raw_sha256: createHash('sha256').update(readFileSync(path)).digest('hex') }));
  } finally {
    Date.now = originalNow;
    for (const restore of restores.reverse()) restore();
    syncBuiltinESMExports();
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});
