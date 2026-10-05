const RENAME_PLAN_ID = PropertiesService.getScriptProperties().getProperty('RENAME_PLAN_ID');
const RENAME_ROOT_ID = '10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f';

function renameSummary_(plan) {
  const ops = plan.operations;
  return {ok: true, total: ops.length,
    completed: ops.filter(x => x.status === 'completed').length,
    renamed: ops.filter(x => ['completed', 'renamed'].includes(x.status)).length,
    errors: ops.filter(x => x.status === 'error').map(x => ({id:x.id, day:x.day, reason:x.error})),
    updated_at: plan.updated_at || plan.date};
}

function renameDirectParent_(item, parentId) {
  const parents = item.getParents();
  while (parents.hasNext()) if (parents.next().getId() === parentId) return true;
  return false;
}

function renameOneExact_(op) {
  if (op.name.includes('_ПРОВЕРИТЬ_БИРКУ') || /[\/\\]/.test(op.new_name)) throw new Error('Unsafe name');
  const parent = DriveApp.getFolderById(op.parent);
  const destination = DriveApp.getFolderById(op.destination);
  if (!renameDirectParent_(parent, RENAME_ROOT_ID) || parent.getName() !== op.day ||
      !renameDirectParent_(destination, op.parent) || destination.getName() !== 'Переименовано') {
    throw new Error('Folder differs from approved plan');
  }
  const file = DriveApp.getFileById(op.id);
  const current = file.getName();
  if (!/^image\//.test(file.getMimeType()) || file.isTrashed()) throw new Error('Invalid image');
  if (![op.name, op.new_name].includes(current)) throw new Error('File name changed outside plan');
  const inSource = renameDirectParent_(file, op.parent);
  const inDestination = renameDirectParent_(file, op.destination);
  if (!inSource && !inDestination) throw new Error('File moved outside plan');
  if (inDestination && current !== op.new_name) throw new Error('Unexpected destination name');
  const collisions = destination.getFilesByName(op.new_name);
  while (collisions.hasNext()) if (collisions.next().getId() !== op.id) throw new Error('Destination collision');
  if (current !== op.new_name) file.setName(op.new_name);
  if (!inDestination) file.moveTo(destination);
  const check = DriveApp.getFileById(op.id);
  if (check.getName() !== op.new_name || !renameDirectParent_(check, op.destination)) throw new Error('Verification failed');
  op.status = 'completed'; op.completed_at = new Date().toISOString(); delete op.error;
}

function doPostLegacy(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (_) { return renameJson_({ok:false,error:'Invalid JSON'}); }
  const secret = PropertiesService.getScriptProperties().getProperty('RENAME_API_TOKEN');
  if (!secret || body.token !== secret) return renameJson_({ok:false,error:'Unauthorized'});
  if (!['status', 'run'].includes(body.action)) return renameJson_({ok:false,error:'Unknown action'});
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return renameJson_({ok:false,error:'Busy'});
  try {
    const planFile = DriveApp.getFileById(RENAME_PLAN_ID);
    const plan = JSON.parse(planFile.getBlob().getDataAsString('UTF-8'));
    if (!Array.isArray(plan.operations) || plan.operations.length !== 1515) throw new Error('Invalid approved plan');
    if (body.action === 'status') return renameJson_(renameSummary_(plan));
    const limit = Math.max(1, Math.min(25, Number(body.limit) || 25));
    const started = Date.now(); let attempted = 0;
    for (const op of plan.operations) {
      if (['completed', 'error'].includes(op.status)) continue;
      if (attempted >= limit || Date.now() - started > 150000) break;
      attempted++;
      // Persist intent before changing a file. A retry accepts both its old and new state.
      op.status = 'in_progress'; plan.updated_at = new Date().toISOString();
      planFile.setContent(JSON.stringify(plan));
      try { renameOneExact_(op); } catch (error) { op.status = 'error'; op.error = String(error); }
      plan.updated_at = new Date().toISOString();
      planFile.setContent(JSON.stringify(plan));
    }
    const result = renameSummary_(plan); result.attempted = attempted;
    return renameJson_(result);
  } catch (error) {
    return renameJson_({ok:false,error:String(error)});
  } finally { lock.releaseLock(); }
}

function renameJson_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function renameRestRequest_(path, method, body) {
  const req = {url:'https://www.googleapis.com/drive/v3/'+path, method:method||'get',
    headers:{Authorization:'Bearer '+ScriptApp.getOAuthToken()}, muteHttpExceptions:true};
  if (body) {req.contentType='application/json';req.payload=JSON.stringify(body);}
  return req;
}
function renameApiAuthorize() {
  const response=UrlFetchApp.fetchAll([renameRestRequest_(renameFilePath_(RENAME_PLAN_ID))])[0];
  const file=renameRestResult_(response); Logger.log('Rename registry API ready: '+file.id);
}
function renameRestResult_(response) {
  if (response.getResponseCode()<200 || response.getResponseCode()>=300) throw new Error('Drive HTTP '+response.getResponseCode());
  return JSON.parse(response.getContentText());
}
function renameFilePath_(id) {return 'files/'+encodeURIComponent(id)+'?fields=id,name,parents,mimeType,trashed';}
function renameFastValidate_(op,file,collisions) {
  if(op.name.includes('_ПРОВЕРИТЬ_БИРКУ') || /[\/\\]/.test(op.new_name)) throw new Error('Unsafe name');
  if(!/^image\//.test(file.mimeType) || file.trashed) throw new Error('Invalid image');
  if(![op.name,op.new_name].includes(file.name)) throw new Error('File name changed outside plan');
  const parents=file.parents||[];
  if(!parents.includes(op.parent) && !parents.includes(op.destination)) throw new Error('File moved outside plan');
  if(parents.includes(op.destination) && file.name!==op.new_name) throw new Error('Unexpected destination name');
  if(collisions.files.some(x=>x.id!==op.id)) throw new Error('Destination collision');
}
function renameFastBatch_(plan,planFile,limit) {
  const ops=plan.operations.filter(x=>!['completed','error'].includes(x.status)).slice(0,limit);
  if(!ops.length) return 0;
  const validatedFolders={};
  for(const op of ops) {
    const key=op.parent+'|'+op.destination;
    if(validatedFolders[key]) continue;
    const p=DriveApp.getFolderById(op.parent),d=DriveApp.getFolderById(op.destination);
    if(!renameDirectParent_(p,RENAME_ROOT_ID) || p.getName()!==op.day || !renameDirectParent_(d,op.parent) || d.getName()!=='Переименовано') throw new Error('Folder differs from approved plan');
    validatedFolders[key]=true;
  }
  const requests=[];
  for(const op of ops) {
    requests.push(renameRestRequest_(renameFilePath_(op.id)));
    const escape=s=>s.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    const q="'"+escape(op.destination)+"' in parents and name = '"+escape(op.new_name)+"' and trashed = false";
    requests.push(renameRestRequest_('files?q='+encodeURIComponent(q)+'&pageSize=2&fields=files(id),nextPageToken'));
  }
  const responses=UrlFetchApp.fetchAll(requests),work=[];
  for(let i=0;i<ops.length;i++) {
    const op=ops[i];
    try {
      const file=renameRestResult_(responses[2*i]),collision=renameRestResult_(responses[2*i+1]);
      renameFastValidate_(op,file,collision);
      if(file.name===op.new_name && (file.parents||[]).includes(op.destination)) {
        op.status='completed';op.completed_at=new Date().toISOString();delete op.error;
      } else {
        op.status='in_progress';
        const move=(file.parents||[]).includes(op.destination)?'':'&addParents='+encodeURIComponent(op.destination)+'&removeParents='+encodeURIComponent(op.parent);
        work.push({op,request:renameRestRequest_(renameFilePath_(op.id)+move,'patch',{name:op.new_name})});
      }
    } catch(e) {op.status='error';op.error=String(e);}
  }
  plan.updated_at=new Date().toISOString();planFile.setContent(JSON.stringify(plan));
  if(work.length) {
    const updates=UrlFetchApp.fetchAll(work.map(x=>x.request));
    for(let i=0;i<work.length;i++) {
      const op=work[i].op;
      try {
        const f=renameRestResult_(updates[i]);
        if(f.id!==op.id || f.name!==op.new_name || !(f.parents||[]).includes(op.destination)) throw new Error('Verification failed');
        op.status='completed';op.completed_at=new Date().toISOString();delete op.error;
      } catch(e) {op.status='error';op.error=String(e);}
    }
  }
  plan.updated_at=new Date().toISOString();planFile.setContent(JSON.stringify(plan));
  return ops.length;
}
function doPost(e) {
  let b;try{b=JSON.parse(e.postData.contents);}catch(_){return renameJson_({ok:false,error:'Invalid JSON'});}
  const secret=PropertiesService.getScriptProperties().getProperty('RENAME_API_TOKEN');
  if(!secret || b.token!==secret) return renameJson_({ok:false,error:'Unauthorized'});
  if(!['run','status'].includes(b.action)) return renameJson_({ok:false,error:'Unknown action'});
  const lock=LockService.getScriptLock();if(!lock.tryLock(1000)) return renameJson_({ok:false,error:'Busy'});
  try {
    const pf=DriveApp.getFileById(RENAME_PLAN_ID),p=JSON.parse(pf.getBlob().getDataAsString('UTF-8'));
    if(!Array.isArray(p.operations)||p.operations.length!==1515) throw new Error('Invalid approved plan');
    if(b.action==='status') return renameJson_(renameSummary_(p));
    const attempted=renameFastBatch_(p,pf,Math.max(1,Math.min(25,Number(b.limit)||25)));
    return renameJson_(Object.assign(renameSummary_(p),{attempted}));
  }catch(error){return renameJson_({ok:false,error:String(error)});}finally{lock.releaseLock();}
}
