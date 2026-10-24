import './helpers/notes-locks.ts';
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { addNote, deleteNote, clearNotes, importNotesBackupJson, replaceCorruptedNotesFromBackupJson, createNotesBackupJson, loadNotesState, NOTES_STORAGE_KEY } from '../src/lib/notes.ts';
const data = new Map<string, string>();
beforeEach(() => { data.clear(); Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => data.get(key) ?? null,
  setItem: (key: string, value: string) => data.set(key, value),
  removeItem: (key: string) => data.delete(key),
} }); });
const legacy = [{ id: 'legacy', kind: 'manual', title: 'Legacy', content: 'Preserved original', ts: 1 }];
test('simultaneous acknowledged adds preserve both records and legacy bytes', async () => {
  const raw = JSON.stringify(legacy); data.set('vr-notes', raw);
  const results = await Promise.all(Array.from({ length: 20 }, (_, i) => addNote('manual', `note ${i}`, `body ${i}`)));
  assert.equal(results.length, 20); assert.equal(loadNotesState().notes.length, 21);
  assert.equal(new Set(loadNotesState().notes.map(note => note.id)).size, 21);
  assert.equal(data.get('vr-notes'), raw);
});
test('delete and import serialize without resurrecting deleted records or losing additions', async () => {
  data.set('vr-notes', JSON.stringify(legacy));
  const imported = { ...legacy[0], id: 'imported' };
  await Promise.all([deleteNote('legacy'), importNotesBackupJson(createNotesBackupJson([imported])), addNote('manual', 'new', 'new')]);
  assert.equal(loadNotesState().notes.length, 2);
  assert.equal(loadNotesState().notes.some(n => n.id === 'legacy'), false);
  assert.ok(loadNotesState().notes.some(n => n.id === 'imported'));
});
test('clear is ordered before a queued add and does not resurrect legacy after reload', async () => {
  data.set('vr-notes', JSON.stringify(legacy));
  await Promise.all([clearNotes(), addNote('manual', 'after clear', 'new')]);
  assert.deepEqual(loadNotesState().notes.map(n => n.title), ['after clear']);
  await clearNotes(); assert.deepEqual(loadNotesState().notes, []);
  assert.equal(data.get('vr-notes'), JSON.stringify(legacy));
});
test('explicit corrupted recovery shares the lock with subsequent add', async () => {
  data.set('vr-notes', 'bad');
  await Promise.all([replaceCorruptedNotesFromBackupJson(createNotesBackupJson(legacy), 'bad'), addNote('manual', 'after recovery', 'body')]);
  assert.equal(loadNotesState().notes.length, 2); assert.equal(data.get('vr-notes'), 'bad');
});
test('non-cooperating old tabs cannot erase v2 acknowledgments; all new writes fail closed', async () => {
  await addNote('manual', 'acknowledged', 'body');
  const saved = data.get(NOTES_STORAGE_KEY);
  data.set('vr-notes', JSON.stringify(legacy));
  assert.match(loadNotesState().error, /旧版本页面/);
  for (const action of [() => addNote('manual', 'blocked', 'body'), () => deleteNote('legacy'), clearNotes,
    () => importNotesBackupJson(createNotesBackupJson(legacy)), () => replaceCorruptedNotesFromBackupJson(createNotesBackupJson(legacy), JSON.stringify(legacy))]) await assert.rejects(action);
  assert.equal(data.get(NOTES_STORAGE_KEY), saved); assert.equal(data.get('vr-notes'), JSON.stringify(legacy));
});
test('missing Web Locks refuses every writer, leaving legacy readable and byte-identical', async () => {
  data.set('vr-notes', JSON.stringify(legacy));
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {} });
  assert.deepEqual(loadNotesState().notes, legacy);
  for (const action of [() => addNote('manual', 'blocked', 'body'), () => deleteNote('legacy'), clearNotes, () => importNotesBackupJson(createNotesBackupJson(legacy))]) await assert.rejects(action, /Web Locks/);
  assert.equal(data.has(NOTES_STORAGE_KEY), false);
});
