import test from 'node:test';
import assert from 'node:assert/strict';
import { api, selectApiFacility, scopedRequest } from '../src/api.ts';

const originalFetch = globalThis.fetch;
test.afterEach(() => { globalThis.fetch = originalFetch; selectApiFacility('IA-AMES-SC'); });

test('facility requests capture site in query and POST body; registry and health are shared', async () => {
  const calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return new Response('{}', { headers: { 'content-type': 'application/json' } }); };
  selectApiFacility('NC-WILMINGTON-SC');
  await api.evaluateReplay('2025-06-01T08:00:00Z');
  await scopedRequest('/api/notifications/packages', { method: 'POST', body: JSON.stringify({ decision_id: 5 }) });
  await api.health();
  await api.facilities();
  assert.equal(new URL(calls[0].path, 'https://test.local').searchParams.get('facility_id'), 'NC-WILMINGTON-SC');
  assert.equal(JSON.parse(calls[0].init.body).facility_id, 'NC-WILMINGTON-SC');
  assert.equal(JSON.parse(calls[1].init.body).facility_id, 'NC-WILMINGTON-SC');
  assert.equal(calls[2].path, '/api/health');
  assert.equal(calls[3].path, '/api/facilities');
});

test('switching sites aborts old work and rejects a response even when its transport ignores abort', async () => {
  let finish, outgoing;
  globalThis.fetch = (path, init) => { outgoing = { path, init }; return new Promise(resolve => { finish = resolve; }); };
  const old = api.latest();
  selectApiFacility('NC-WILMINGTON-SC');
  assert.equal(outgoing.init.signal.aborted, true);
  finish(new Response(JSON.stringify({ facility_id: 'IA-AMES-SC' }), { headers: { 'content-type': 'application/json' } }));
  await assert.rejects(old, error => error.name === 'AbortError');
});

test('a response from the wrong site cannot become the selected dashboard', async () => {
  selectApiFacility('NC-WILMINGTON-SC');
  globalThis.fetch = async () => new Response(JSON.stringify({ facility_id: 'IA-AMES-SC' }), { headers: { 'content-type': 'application/json' } });
  await assert.rejects(api.latest(), /different facility/);
});

test('Live Check accepts only a hypothetical copy of the selected facility', async () => {
  selectApiFacility('NC-WILMINGTON-SC');
  const payload = { mode: 'livecheck', facility_id: 'WHATIF-123', facility: { id: 'WHATIF-123', hypothetical: true,
    provider_settings: { origin_facility_id: 'NC-WILMINGTON-SC' } }, livecheck: { base_facility_id: 'NC-WILMINGTON-SC' } };
  globalThis.fetch = async () => Response.json(payload);
  assert.equal((await api.liveEvaluate('alert-test', true)).facility.id, 'WHATIF-123');
  assert.equal((await api.snapshot('saved-what-if')).facility.id, 'WHATIF-123');
  payload.livecheck.base_facility_id = 'IA-AMES-SC';
  await assert.rejects(api.liveEvaluate('alert-test', true), /different facility/);
  payload.livecheck.base_facility_id = 'NC-WILMINGTON-SC';
  await assert.rejects(api.latest(), /different facility/);
});
