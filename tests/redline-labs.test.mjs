import test from 'node:test';
import assert from 'node:assert/strict';
import {redlineLabsHTML} from '../static/redline-labs.js';
import {setLanguage} from '../static/i18n.js';

test('Labs distinguishes a personal opt-in from unavailable demo access and explains retention',()=>{
 setLanguage('zh-CN',{persist:false});
 const off=redlineLabsHTML({available:true,redline_enabled:false,effective:false});
 assert.match(off,/尚未开启/);assert.doesNotMatch(off,/ disabled/);assert.match(off,/不删除已保存/);
 assert.match(redlineLabsHTML({available:true,redline_enabled:true,effective:true}),/ checked/);
 const demo=redlineLabsHTML({available:false,requires_login:true});assert.match(demo,/ disabled/);assert.match(demo,/登录正式账号/);
 setLanguage('en',{persist:false});
 const english=redlineLabsHTML({available:true,effective:true,redline_enabled:true});
 assert.match(english,/Enable DOCX review/);assert.match(english,/Single-user DOCX/);assert.doesNotMatch(english,/关闭会停用/);
 setLanguage('zh-CN',{persist:false});
});
