// Read-only inventory of the approved ready root. No images are renamed here.
function rmRead_(key, fallback) {
  const p=PropertiesService.getScriptProperties(), n=Number(p.getProperty(key+'_N')||0);
  if(!n)return fallback;
  let s='';for(let i=0;i<n;i++)s+=p.getProperty(key+'_'+i)||'';
  return JSON.parse(s);
}
function rmWrite_(key, value) {
  const p=PropertiesService.getScriptProperties(),s=JSON.stringify(value),old=Number(p.getProperty(key+'_N')||0),n=Math.ceil(s.length/2200);
  const out={};for(let i=0;i<n;i++)out[key+'_'+i]=s.slice(i*2200,(i+1)*2200);
  out[key+'_N']=String(n);p.setProperties(out);
  for(let i=n;i<old;i++)p.deleteProperty(key+'_'+i);
}
function rmList_(id, page) {
  const q="'"+id+"' in parents and trashed=false";
  const path='files?q='+encodeURIComponent(q)+'&pageSize=1000&fields='+encodeURIComponent('nextPageToken,incompleteSearch,files(id,name,mimeType)')+(page?'&pageToken='+encodeURIComponent(page):'');
  const r=renameRestResult_(UrlFetchApp.fetchAll([renameRestRequest_(path)])[0]);
  if(r.incompleteSearch)throw new Error('Incomplete Drive listing');
  return r;
}
function rmWork_(input) {
  if(!input || !['paused','reviewing','matching','renaming','verifying','idle','error'].includes(input.phase))throw new Error('Invalid work phase');
  const snapshot=rmRead_('RM_SNAPSHOT',{}),folders=snapshot.folders||[];
  if(input.folder_id&&!folders.some(f=>f.id===input.folder_id))throw new Error('Unknown inventory folder');
  const prev=rmRead_('RM_WORK',{});
  const next={phase:input.phase,folder_id:input.folder_id||null,folder_name:input.folder_name||null,
    message:String(input.message||'').slice(0,250),updated_at:new Date().toISOString(),review_ids:prev.review_ids||{}};
  if(input.review_ids) {
    for(const id in input.review_ids) {
      if(!folders.some(f=>f.id===id)||!Array.isArray(input.review_ids[id])||input.review_ids[id].some(x=>!/^[A-Za-z0-9_-]{10,100}$/.test(x)))throw new Error('Invalid review IDs');
    }
    next.review_ids=input.review_ids;
  }
  rmWrite_('RM_WORK',next);return {ok:true,work:next};
}
function rmScan_() {
  const now=Date.now(),old=rmRead_('RM_SNAPSHOT',null),work=rmRead_('RM_WORK',{phase:'paused'});
  let scan=rmRead_('RM_SCAN',null);
  if(!scan&&old&&now-Date.parse(old.generated_at)<300000)return {ok:true,snapshot:old,work:work,scanning:false};
  if(!scan)scan={started_at:new Date().toISOString(),pending:[{id:RENAME_ROOT_ID,top:null,renamed:false}],folders:{},visited:{},excluded_files:0,visited_folders:0};
  // A checkpoint after each page permits bounded, resumable scans.
  while(scan.pending.length&&Date.now()-now<4000) {
    const item=scan.pending[0],data=rmList_(item.id,item.page);
    for(const f of data.files||[]) {
      if(f.mimeType==='application/vnd.google-apps.folder') {
        if(scan.visited[f.id])continue;
        scan.visited[f.id]=true;
        if(/^Отч[её]ты переименования$/i.test(f.name))continue;
        const top=item.top||f.id;
        if(!item.top)scan.folders[top]={id:f.id,name:f.name,total:0,renamed:0,review:0};
        scan.pending.push({id:f.id,top:top,renamed:item.renamed||f.name==='Переименовано'});
      } else if(/^image\//.test(f.mimeType)) {
        const top=item.top||RENAME_ROOT_ID;
        if(!scan.folders[top])scan.folders[top]={id:top,name:'В корне «02 готово»',total:0,renamed:0,review:0};
        const row=scan.folders[top];row.total++;
        if(item.renamed)row.renamed++;
        else if((work.review_ids?.[top]||[]).includes(f.id))row.review++;
      } else scan.excluded_files++;
    }
    if(data.nextPageToken)item.page=data.nextPageToken;
    else {scan.pending.shift();scan.visited_folders++;}
    rmWrite_('RM_SCAN',scan);
  }
  if(scan.pending.length)return {ok:true,snapshot:old,work:work,scanning:true,scanned_folders:scan.visited_folders};
  const folders=Object.values(scan.folders).sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  const out={generated_at:new Date().toISOString(),scan_started_at:scan.started_at,folders:folders,
    excluded_files:scan.excluded_files,root_id:RENAME_ROOT_ID,definition:'Images inside Переименовано / all images in 02 готово; report folders and non-images excluded'};
  const history=rmRead_('RM_HISTORY',[]);
  history.push({at:out.generated_at,total:folders.reduce((s,f)=>s+f.total,0),renamed:folders.reduce((s,f)=>s+f.renamed,0)});
  out.history=history.filter(x=>Date.parse(x.at)>Date.now()-7*86400000).slice(-2016);
  rmWrite_('RM_HISTORY',out.history);rmWrite_('RM_SNAPSHOT',out);rmWrite_('RM_SCAN',null);
  return {ok:true,snapshot:out,work:work,scanning:false};
}
