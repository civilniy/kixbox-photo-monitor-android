// Persistent queue API. Existing OAuth permissions and shared secret are reused.
function renameApiCanonical_(p) {
  return JSON.stringify({request_id:p.request_id,day:p.day,source_excel:p.source_excel,
    operations:p.operations.map(o=>({id:o.id,name:o.name,new_name:o.new_name,parent:o.parent,destination:o.destination,day:o.day,reviewed:o.reviewed===true}))});
}
function renameApiHash_(p) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,renameApiCanonical_(p),Utilities.Charset.UTF_8)
    .map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
}
function renameApiShape_(p) {
  if(!p || !/^[A-Za-z0-9_-]{8,80}$/.test(p.request_id||'') || !/^2026_(08|09)_\d{2}$/.test(p.day||'')) throw new Error('Invalid queue identity');
  if(typeof p.source_excel!=='string'||!p.source_excel.endsWith('.xlsx')) throw new Error('Excel provenance required');
  if(!Array.isArray(p.operations)||p.operations.length<1||p.operations.length>1000) throw new Error('Invalid queue size');
  const ids=new Set(),names=new Set();
  for(const o of p.operations) {
    for(const k of ['id','name','new_name','parent','destination','day']) if(typeof o[k]!=='string'||!o[k]) throw new Error('Missing operation field');
    if(![o.id,o.parent,o.destination].every(x=>/^[A-Za-z0-9_-]{10,100}$/.test(x))) throw new Error('Invalid Drive ID');
    if(o.day!==p.day||o.reviewed!==true||o.parent===o.destination||o.destination!==p.operations[0].destination) throw new Error('Unreviewed or mixed-day operation');
    if(/[\/\\\x00-\x1f]/.test(o.new_name)||o.new_name.length>240||!/^.+_.+_.+_.+_\d+\.jpg$/i.test(o.new_name)||o.new_name.includes('ПРОВЕРИТЬ')) throw new Error('Unsafe output name');
    const name=o.destination+'|'+o.new_name.normalize('NFKC').toLowerCase();
    if(ids.has(o.id)||names.has(name)) throw new Error('Duplicate ID or destination name');
    ids.add(o.id);names.add(name);
  }
}
function renameApiCurrent_() {
  const props=PropertiesService.getScriptProperties();
  const api=props.getProperty('RENAME_ACTIVE_API_ID');
  const old23=props.getProperty('RENAME_ACTIVE_23_ID'),old22=props.getProperty('RENAME_ACTIVE_22_ID');
  const f=DriveApp.getFileById(api||old23||old22||RENAME_PLAN_ID);
  const p=JSON.parse(f.getBlob().getDataAsString('UTF-8'));
  if(api) {
    renameApiShape_(p);
    if(renameApiHash_(p)!==props.getProperty('RENAME_ACTIVE_API_HASH')) throw new Error('Queue content differs from submitted plan');
  } else if(old23) validateApproved23_(p);
  else if(old22) validateApproved22_(p);
  else if(!Array.isArray(p.operations)||p.operations.length!==1515) throw new Error('Invalid legacy plan');
  return {file:f,plan:p};
}
function renameApiSummary_(p) {
  return Object.assign(renameSummary_(p),{request_id:p.request_id||null,day:p.day||null,api_version:2});
}
function renameApiImport_(input) {
  renameApiShape_(input);
  const hash=renameApiHash_(input),props=PropertiesService.getScriptProperties(),current=renameApiCurrent_();
  if(current.plan.request_id===input.request_id) {
    if(renameApiHash_(current.plan)!==hash) throw new Error('Request ID reused with different content');
    return Object.assign(renameApiSummary_(current.plan),{reused:true});
  }
  if(current.plan.operations.some(o=>o.status!=='completed')) throw new Error('Previous queue is unfinished');
  const folders=new Set();
  for(const o of input.operations) {
    const k=o.parent+'|'+o.destination;
    if(!folders.has(k)){renameFolderBoundary_(o);folders.add(k);}
    if(o.status && o.status!=='pending') throw new Error('New operations must be pending');
  }
  // Destination's parent is verified as the requested day by renameFolderBoundary_.
  const dayFolder=DriveApp.getFolderById(input.operations[0].destination).getParents().next();
  const reportFolders=dayFolder.getFoldersByName('Отчёты переименования');
  const reports=reportFolders.hasNext()?reportFolders.next():dayFolder.createFolder('Отчёты переименования');
  if(reportFolders.hasNext())throw new Error('Ambiguous reports folder');
  const name='KIXBOX_queue_'+input.request_id+'.json';
  const existing=reports.getFilesByName(name);
  let f,p;
  if(existing.hasNext()) {
    f=existing.next();if(existing.hasNext())throw new Error('Duplicate registry');
    p=JSON.parse(f.getBlob().getDataAsString('UTF-8'));
    if(renameApiHash_(p)!==hash||p.operations.some(o=>o.status!=='pending'))throw new Error('Stored request conflicts');
  } else {
    p={request_id:input.request_id,day:input.day,source_excel:input.source_excel,date:new Date().toISOString(),previous_plan:current.file.getId(),operations:input.operations.map(o=>({id:o.id,name:o.name,new_name:o.new_name,parent:o.parent,destination:o.destination,day:o.day,reviewed:true,status:'pending'}))};
    f=reports.createFile(name,JSON.stringify(p),MimeType.PLAIN_TEXT);
  }
  props.setProperties({RENAME_ACTIVE_API_ID:f.getId(),RENAME_ACTIVE_API_HASH:hash});
  return Object.assign(renameApiSummary_(p),{registry_id:f.getId(),prepared:true});
}
function doPost(e) {
  let b;try{b=JSON.parse(e.postData.contents);}catch(_){return renameJson_({ok:false,error:'Invalid JSON'});}
  const secret=PropertiesService.getScriptProperties().getProperty('RENAME_API_TOKEN');
  if(!secret||b.token!==secret)return renameJson_({ok:false,error:'Unauthorized'});
  if(!['run','status','import_plan','registry','monitor_scan','monitor_work'].includes(b.action))return renameJson_({ok:false,error:'Unknown action'});
  const lock=LockService.getScriptLock();if(!lock.tryLock(1000))return renameJson_({ok:false,error:'Busy'});
  try {
    if(b.action==='monitor_scan')return renameJson_(rmScan_());
    if(b.action==='monitor_work')return renameJson_(rmWork_(b.plan));
    if(b.action==='import_plan')return renameJson_(renameApiImport_(b.plan));
    const current=renameApiCurrent_(),p=current.plan;
    if(b.action==='status')return renameJson_(renameApiSummary_(p));
    if(b.action==='registry')return renameJson_({ok:true,registry_id:current.file.getId(),plan:p});
    const attempted=renameFastBatch_(p,current.file,Math.max(1,Math.min(25,Number(b.limit)||25)));
    return renameJson_(Object.assign(renameApiSummary_(p),{attempted}));
  }catch(error){return renameJson_({ok:false,error:String(error)});}finally{lock.releaseLock();}
}
