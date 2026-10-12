// Separate upload stage. This does not change the rename queue or its boundaries.
const UPLOAD_READY_ROOT = '10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f';
const UPLOAD_TARGET = '12RM4-TUdAX2PR33ouN03SIHpRES0gUoY';
const UPLOAD_PROJECT = '1bP6uVlI-NPXhXOwaQiymfz412XohVjD7';
function uploadShape_(p) {
  if (!p || !/^[A-Za-z0-9_-]{8,80}$/.test(p.request_id || '') || p.destination !== UPLOAD_TARGET ||
      !Array.isArray(p.operations) || p.operations.length < 1 || p.operations.length > 1000) throw new Error('Invalid upload plan');
  const ids = new Set();
  for (const o of p.operations) {
    if (!o || ![o.id,o.parent].every(x => typeof x === 'string' && /^[A-Za-z0-9_-]{10,100}$/.test(x)) ||
        typeof o.name !== 'string' || !o.name || o.reviewed !== true || ids.has(o.id)) throw new Error('Invalid upload operation');
    ids.add(o.id);
  }
}
function uploadHash_(p) {
  uploadShape_(p);
  const s = JSON.stringify({request_id:p.request_id,destination:p.destination,
    operations:p.operations.map(o=>({id:o.id,name:o.name,parent:o.parent,reviewed:true}))});
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,s,Utilities.Charset.UTF_8)
    .map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
}
function uploadStoredHash_(p) {
  const s=uploadHash_(p)+'|'+JSON.stringify(p.operations.map(o=>o.before));
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,s,Utilities.Charset.UTF_8)
    .map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
}
function uploadRequest_(id,method,parent) {
  let url = 'https://www.googleapis.com/drive/v3/files/'+encodeURIComponent(id)+
    '?supportsAllDrives=true&fields=id,name,mimeType,parents,trashed,md5Checksum,size';
  if(method === 'patch') url += '&addParents='+encodeURIComponent(UPLOAD_TARGET)+'&removeParents='+encodeURIComponent(parent);
  return {url,method:method||'get',headers:{Authorization:'Bearer '+ScriptApp.getOAuthToken()},
    muteHttpExceptions:true,contentType:'application/json',...(method==='patch'?{payload:'{}'}:{})};
}
function uploadResponse_(r) {
  if(r.getResponseCode()<200||r.getResponseCode()>=300) throw new Error('Drive HTTP '+r.getResponseCode());
  return JSON.parse(r.getContentText());
}
function uploadBoundary_(id) {
  let f=DriveApp.getFolderById(id);
  if(f.getName()!=='Переименовано') throw new Error('Upload source must be Переименовано');
  for(let depth=0;depth<8;depth++) {
    const ps=f.getParents();
    if(!ps.hasNext()) break;
    f=ps.next();
    if(ps.hasNext()) throw new Error('Ambiguous source ancestry');
    if(f.getId()===UPLOAD_READY_ROOT) return;
  }
  throw new Error('Source is outside 02 готовые');
}
function uploadDestination_() {
  const f=DriveApp.getFolderById(UPLOAD_TARGET),ps=f.getParents();
  if(f.getName()!=='готово к выгрузке'||!ps.hasNext()||ps.next().getId()!==UPLOAD_PROJECT||ps.hasNext())
    throw new Error('Upload destination changed');
}
function uploadCurrent_() {
  const props=PropertiesService.getScriptProperties(),id=props.getProperty('UPLOAD_ACTIVE_API_ID');
  if(!id) return null;
  const file=DriveApp.getFileById(id),plan=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  if(uploadStoredHash_(plan)!==props.getProperty('UPLOAD_ACTIVE_API_HASH')) throw new Error('Upload plan content changed');
  return {file,plan};
}
function uploadSummary_(p) {
  if(!p) return {ok:true,total:0,completed:0,pending:0,errors:[],request_id:null,api_version:1};
  return {ok:true,request_id:p.request_id,total:p.operations.length,
    completed:p.operations.filter(o=>o.status==='completed').length,
    pending:p.operations.filter(o=>o.status==='pending').length,
    errors:p.operations.filter(o=>o.error).map(o=>({id:o.id,error:o.error})),api_version:1};
}
function uploadValidateFile_(f,o,p,allowDestination) {
  if(f.id!==o.id||f.name!==o.name||f.trashed||f.mimeType!=='image/jpeg') throw new Error('Upload file changed');
  const parents=f.parents||[];
  const atSource=parents.length===1&&parents[0]===o.parent;
  const atTarget=parents.length===1&&parents[0]===UPLOAD_TARGET;
  if(!atSource&&!(allowDestination&&atTarget)) throw new Error('Upload parent changed');
  if(o.before&&(f.md5Checksum!==o.before.md5Checksum||f.size!==o.before.size)) throw new Error('Upload content changed');
  return atTarget;
}
function uploadImport_(input) {
  uploadShape_(input);uploadDestination_();
  const props=PropertiesService.getScriptProperties(),hash=uploadHash_(input),active=uploadCurrent_();
  if(active&&active.plan.request_id===input.request_id) {
    if(uploadHash_(active.plan)!==hash) throw new Error('Upload request ID reused');
    return Object.assign(uploadSummary_(active.plan),{registry_id:active.file.getId(),reused:true});
  }
  if(active&&active.plan.operations.some(o=>o.status!=='completed')) throw new Error('Previous upload queue unfinished');
  if(renameApiCurrent_().plan.operations.some(o=>o.status!=='completed')) throw new Error('Rename queue unfinished');
  new Set(input.operations.map(o=>o.parent)).forEach(uploadBoundary_);
  const ops=[];
  for(let start=0;start<input.operations.length;start+=25) {
    const batch=input.operations.slice(start,start+25),responses=UrlFetchApp.fetchAll(batch.map(o=>uploadRequest_(o.id)));
    batch.forEach((o,i)=>{
      const f=uploadResponse_(responses[i]);uploadValidateFile_(f,o,input,false);
      if(!f.md5Checksum||!f.size) throw new Error('Missing file content fingerprint');
      ops.push({id:o.id,name:o.name,parent:o.parent,reviewed:true,status:'pending',before:f});
    });
  }
  const root=DriveApp.getFolderById(UPLOAD_READY_ROOT),folders=root.getFoldersByName('Отчёты выгрузки');
  const reports=folders.hasNext()?folders.next():root.createFolder('Отчёты выгрузки');
  if(folders.hasNext()) throw new Error('Ambiguous upload reports folder');
  const name='KIXBOX_upload_'+input.request_id+'.json',existing=reports.getFilesByName(name);
  if(existing.hasNext()) throw new Error('Upload registry already exists without active pointer');
  const p={request_id:input.request_id,destination:UPLOAD_TARGET,created_at:new Date().toISOString(),operations:ops};
  const file=reports.createFile(name,JSON.stringify(p),MimeType.PLAIN_TEXT);
  props.setProperties({UPLOAD_ACTIVE_API_ID:file.getId(),UPLOAD_ACTIVE_API_HASH:uploadStoredHash_(p)});
  return Object.assign(uploadSummary_(p),{registry_id:file.getId(),prepared:true});
}
function uploadRun_(current,limit) {
  const p=current.plan,file=current.file;uploadDestination_();
  if(renameApiCurrent_().plan.operations.some(o=>o.status!=='completed')) throw new Error('Rename queue unfinished');
  const ops=p.operations.filter(o=>o.status==='pending').slice(0,limit);
  if(!ops.length) return Object.assign(uploadSummary_(p),{attempted:0});
  new Set(ops.map(o=>o.parent)).forEach(uploadBoundary_);
  const before=UrlFetchApp.fetchAll(ops.map(o=>uploadRequest_(o.id))),work=[];
  ops.forEach((o,i)=>{
    try {
      delete o.error;
      const f=uploadResponse_(before[i]);
      if(uploadValidateFile_(f,o,p,true)) {o.status='completed';o.after=f;o.completed_at=new Date().toISOString();return;}
      o.intent_at=new Date().toISOString();work.push(o);
    } catch(e) {o.status='error';o.error=String(e);}
  });
  // Persist intent before any writes, so a timeout/deploy can resume by reading IDs.
  file.setContent(JSON.stringify(p));
  if(work.length) {
    try {UrlFetchApp.fetchAll(work.map(o=>uploadRequest_(o.id,'patch',o.parent)));} catch(e) { /* Readback decides actual outcome. */ }
    const after=UrlFetchApp.fetchAll(work.map(o=>uploadRequest_(o.id)));
    work.forEach((o,i)=>{
      try {
        const f=uploadResponse_(after[i]);
        if(!uploadValidateFile_(f,o,p,true)) throw new Error('Move not confirmed');
        o.status='completed';o.after=f;o.completed_at=new Date().toISOString();delete o.error;
      } catch(e) {o.error=String(e); /* Keep pending after ambiguous transport outcome. */ }
    });
  }
  file.setContent(JSON.stringify(p));
  return Object.assign(uploadSummary_(p),{attempted:ops.length});
}
function uploadDispatch_(b) {
  if(b.action==='upload_import') return uploadImport_(b.plan);
  const current=uploadCurrent_();
  if(b.action==='upload_status') return uploadSummary_(current?current.plan:null);
  if(b.action==='upload_registry') return {ok:true,registry_id:current?current.file.getId():null,plan:current?current.plan:null};
  if(!current) throw new Error('No upload queue');
  if(b.plan&&b.plan.request_id!==current.plan.request_id) throw new Error('Upload request differs');
  return uploadRun_(current,Math.max(1,Math.min(25,Number(b.limit)||25)));
}
