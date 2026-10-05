const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function test(options={}){
 const iter=a=>({hasNext:()=>a.length,next:()=>a.shift()});
 const root={getId:()=> '10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f'},day={getId:()=> 'day-root',getName:()=> options.foreign?'other-day':'day',getParents:()=>iter([root])};
 const src={getId:()=> 'src',getName:()=> 'day',getParents:()=>iter([options.nested?day:root])};
 const dst={getId:()=> 'dst',getName:()=> 'Переименовано',getParents:()=>iter([options.nested?day:src])};
 const op={id:'image',parent:'src',destination:'dst',day:'day',name:'old.jpg',new_name:'new.jpg',status:'pending'};
 const f={id:'image',name:options.done?'new.jpg':'old.jpg',parents:[options.done?'dst':'src'],mimeType:'image/jpeg',trashed:false};
 const p={operations:[op]},saved=[];let patches=0;
 const response=(data,status=200)=>({getResponseCode:()=>status,getContentText:()=>JSON.stringify(data)});
 const c={PropertiesService:{getScriptProperties:()=>({getProperty:()=> 'mock-plan'})},Date,encodeURIComponent,ScriptApp:{getOAuthToken:()=> 'mock'},
  DriveApp:{getFolderById:id=> id==='src'?src:dst},
  renameDirectParent_:(x,id)=>{const it=x.getParents();while(it.hasNext())if(it.next().getId()===id)return true;return false;},
  UrlFetchApp:{fetchAll:reqs=>reqs.map(r=>{
    if(r.method==='patch'){patches++;assert.equal(saved[0].operations[0].status,'in_progress');
      if(options.failed)return response({},403);return response({...f,name:'new.jpg',parents:['dst']});}
    if(r.url.includes('files?q='))return response({files:options.collision?[{id:'other'}]:[]});
    return response(options.changed?{...f,name:'unexpected.jpg'}:f);
  })}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(__dirname+'/../rename_api.gs','utf8'),c);
 c.renameFastBatch_(p,{setContent:s=> saved.push(JSON.parse(s))},25);
 return {op,patches,saved};
}
let t=test();assert.equal(t.op.status,'completed');assert.equal(t.patches,1);
t=test({done:true});assert.equal(t.patches,0);assert.equal(t.op.status,'completed');
t=test({collision:true});assert.equal(t.patches,0);assert.match(t.op.error,/collision/);
t=test({changed:true});assert.equal(t.patches,0);assert.match(t.op.error,/name changed/);
t=test({failed:true});assert.equal(t.op.status,'error');assert.match(t.op.error,/403/);
t=test({nested:true});assert.equal(t.op.status,'completed');assert.equal(t.patches,1);
assert.throws(()=>test({nested:true,foreign:true}),/Folder differs/);
console.log('7 parallel batch safety scenarios passed');
