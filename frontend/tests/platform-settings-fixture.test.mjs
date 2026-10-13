import test from 'node:test';import assert from 'node:assert/strict';
import {platformFixture,CONTACT,update} from './e2e/platform-settings.fixture.mjs';
test('platform fixture only accepts exact explicit synthetic commands',()=>{
 const f=platformFixture();f.readFailure=false;
 const get=()=>f.handle('GET','/api/settings/platform','').body.data;
 assert.equal(get().sec_contact.revision,'absent');
 for(const [method,path,search,body] of [['GET','/api/settings/platform','?x=1'],['POST','/api/settings/platform',''],['PUT','/api/settings/platform/sec-contact','',{contact:'private',revision:'absent'}],['POST','/api/settings/platform/check-update','',{contact:CONTACT}]])assert.equal(f.handle(method,path,search,body).status,400);
 const saved=f.handle('PUT','/api/settings/platform/sec-contact','',{contact:CONTACT,revision:'absent'});assert.equal(saved.status,200);assert.equal(get().sec_contact.revision,saved.body.data.revision);
 f.writeMode='malformed';const previous=get().sec_contact;f.handle('PUT','/api/settings/platform/sec-contact','',{contact:'',revision:previous.revision});assert.deepEqual(get().sec_contact,previous);
 f.updateMode='normal';assert.deepEqual(f.handle('POST','/api/settings/platform/check-update','').body.data,update);
});
