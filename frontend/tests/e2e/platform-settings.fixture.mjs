import { readFileSync } from 'node:fs';
const initial = JSON.parse(readFileSync(new URL('../fixtures/platform-settings-startup.json', import.meta.url), 'utf8')).data;
export const CONTACT = 'Synthetic User synthetic@example.invalid';
export const golden = JSON.parse(readFileSync(new URL('../fixtures/platform-settings-workflow.json', import.meta.url), 'utf8'));
export const update = golden.update;
export function platformFixture() {
  const state = structuredClone(initial), calls = [], violations = []; let serial = 0;
  const fixture = { state, calls, violations, readFailure: true, writeMode: 'normal', updateMode: 'malformed',
    handle(method, path, search, body) {
      if (!path.startsWith('/api/settings/platform')) return null;
      if (search) return deny();
      if (path === '/api/settings/platform' && method === 'GET') { calls.push({method,path}); return fixture.readFailure ? {status:503,body:{detail:'SYNTHETIC_READ_FAILURE'}} : {status:200,body:{data:structuredClone(state)}}; }
      if (path === '/api/settings/platform/sec-contact' && method === 'PUT') {
        if (!body || Object.keys(body).sort().join(',') !== 'contact,revision' || ![CONTACT,''].includes(body.contact) || body.revision !== state.sec_contact.revision) return deny();
        calls.push({method,path,body:structuredClone(body)});
        if (fixture.writeMode === 'conflict') { state.sec_contact = { source:'saved',configured:true,revision:(++serial).toString(16).padStart(32,'0'),editable:true }; return {status:409,body:{detail:'SYNTHETIC_CONFLICT'}}; }
        if (fixture.writeMode === 'malformed') return {status:200,body:{data:{configured:true,revision:'invalid'}}};
        state.sec_contact = {source:body.contact?'saved':'none',configured:Boolean(body.contact),revision:(++serial).toString(16).padStart(32,'0'),editable:true};
        return {status:200,body:{data:structuredClone(state.sec_contact)}};
      }
      if (path === '/api/settings/platform/check-update' && method === 'POST' && body === undefined) {
        calls.push({method,path}); if (fixture.updateMode === 'malformed') return {status:200,body:{data:{...update,latest:{...update.latest,url:'https://unexpected.invalid'}}}};
        state.update = structuredClone(update); return {status:200,body:{data:structuredClone(update)}};
      }
      return deny();
      function deny() { violations.push({method,path,search}); return {status:400,body:{detail:'UNEXPECTED_SYNTHETIC_REQUEST'}}; }
    }
  }; return fixture;
}
