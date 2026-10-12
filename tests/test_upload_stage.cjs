const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),crypto=require('crypto');
const code=fs.readFileSync(__dirname+'/../apps-script/upload_stage.gs','utf8');
function fixture() {
  const root='10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f',target='12RM4-TUdAX2PR33ouN03SIHpRES0gUoY',project='1bP6uVlI-NPXhXOwaQiymfz412XohVjD7';
  const source='sourceFolder1234',outside='outsideFolder1234';
  const props={},files=new Map(),folders=new Map(); let patches=0,losePatch=false,renamePending=false,n=0;
  const iter=xs=>({hasNext:()=>xs.length>0,next:()=>xs.shift()});
  function folder(id,name,parent) {
    const f={getId:()=>id,getName:()=>name,getParents:()=>iter(parent?[folders.get(parent)]:[]),
      getFoldersByName:name=>iter([...folders.values()].filter(x=>x.parent===id&&x.getName()===name)),
      createFolder:name=>folder('reportsFolder'+(++n),name,id),getFilesByName:()=>iter([]),
      createFile:(name,content)=>{const id='registryFile'+(++n),f={getId:()=>id,setContent:c=>{content=c;},getBlob:()=>({getDataAsString:()=>content})};files.set(id,f);return f;},parent};
    folders.set(id,f);return f;
  }
  folder(project,'Обработка фото');folder(root,'02 готовые',project);folder(target,'готово к выгрузке',project);
  folder('dayFolder12345','2026_09_24',root);folder(source,'Переименовано','dayFolder12345');folder(outside,'Переименовано',project);
  const drive=new Map();
  function add(id='photoFile12345',name='SS-26_BRAND_123_BLACK_0.jpg',parent=source) {
    drive.set(id,{id,name,parents:[parent],mimeType:'image/jpeg',md5Checksum:'abc',size:'123',trashed:false});
    return {id,name,parent,reviewed:true};
  }
  const ctx=vm.createContext({Set,JSON,Date,Math,Number,String,Error,
    PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k],setProperties:o=>Object.assign(props,o)})},
    Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},computeDigest:(a,s)=>[...crypto.createHash('sha256').update(s).digest()]},
    DriveApp:{getFolderById:id=>{if(!folders.has(id))throw Error('Missing folder');return folders.get(id);},getFileById:id=>files.get(id)},
    MimeType:{PLAIN_TEXT:'text/plain'},ScriptApp:{getOAuthToken:()=>'<test-token>'},
    renameApiCurrent_:()=>({plan:{operations:renamePending?[{status:'pending'}]:[]}}),
    UrlFetchApp:{fetchAll:reqs=>reqs.map(req=>{
      const u=new URL(req.url),id=decodeURIComponent(u.pathname.split('/').pop()); const f=drive.get(id);
      if(req.method==='patch') {patches++;f.parents=[u.searchParams.get('addParents')];if(losePatch){losePatch=false;throw Error('Lost response after successful move');}}
      return {getResponseCode:()=>f?200:404,getContentText:()=>JSON.stringify(f)};
    })}});
  vm.runInContext(code,ctx);
  return {ctx,add,drive,source,outside,target,plan:ops=>({request_id:'upload-test-1234',destination:target,operations:ops}),
    patches:()=>patches,lose:()=>losePatch=true,pending:()=>renamePending=true};
}
// A successful move preserves ID/name/content and a repeated batch performs no writes.
{
  const f=fixture(),op=f.add();f.ctx.uploadImport_(f.plan([op]));const c=f.ctx.uploadCurrent_();
  assert.equal(f.ctx.uploadRun_(c,25).completed,1);assert.equal(f.patches(),1);
  assert.equal(f.ctx.uploadRun_(f.ctx.uploadCurrent_(),25).attempted,0);assert.equal(f.patches(),1);
  assert.equal(f.drive.get(op.id).name,op.name);assert.equal(f.drive.get(op.id).md5Checksum,'abc');
}
// Server timeout after a committed patch is recovered by reading the same ID.
{
  const f=fixture();f.ctx.uploadImport_(f.plan([f.add()]));f.lose();
  assert.equal(f.ctx.uploadRun_(f.ctx.uploadCurrent_(),25).completed,1);assert.equal(f.patches(),1);
}
// Same-name photos are independent IDs; no copy, overwrite, or rename is issued.
{
  const f=fixture(),a=f.add(),b=f.add('otherPhoto12345',a.name);
  f.ctx.uploadImport_(f.plan([a,b]));assert.equal(f.ctx.uploadRun_(f.ctx.uploadCurrent_(),25).completed,2);
  assert.equal(f.drive.size,2);
}
// Source boundary, target identity, duplicate ID, unfinished rename all fail before writes.
for(const kind of ['outside','target','duplicate','rename']) {
  const f=fixture(),op=f.add();const p=f.plan([op]);
  if(kind==='outside') {op.parent=f.outside;f.drive.get(op.id).parents=[f.outside];}
  if(kind==='target')p.destination='arbitraryTarget1234';
  if(kind==='duplicate')p.operations.push({...op});
  if(kind==='rename')f.pending();
  assert.throws(()=>f.ctx.uploadImport_(p));assert.equal(f.patches(),0);
}
// Content/name/parent changes after approval stop that file without mutation.
for(const kind of ['checksum','name','parent']) {
  const f=fixture(),op=f.add();f.ctx.uploadImport_(f.plan([op]));
  const d=f.drive.get(op.id);if(kind==='checksum')d.md5Checksum='changed';if(kind==='name')d.name='changed.jpg';if(kind==='parent')d.parents=[f.outside];
  const r=f.ctx.uploadRun_(f.ctx.uploadCurrent_(),25);assert.equal(r.completed,0);assert.equal(r.errors.length,1);assert.equal(f.patches(),0);
}
// Immutable approval rejects edits to IDs, names, or folders after staging.
{
  const f=fixture(),op=f.add();f.ctx.uploadImport_(f.plan([op]));const c=f.ctx.uploadCurrent_();c.plan.operations[0].name='changed.jpg';c.file.setContent(JSON.stringify(c.plan));
  assert.throws(()=>f.ctx.uploadCurrent_());assert.equal(f.patches(),0);
}
console.log('Upload stage: 11 behavioral scenarios passed');
