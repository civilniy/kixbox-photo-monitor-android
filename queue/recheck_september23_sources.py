import json,sys
from pathlib import Path
import recheck_september23 as current
import label_reread as reader
from ingest_label_sources import ingest
from campaign_worker import atomic
BASE=current.BASE;DEST=BASE/'september23-sources-20261006';DAY=current.DAY
if not (DEST/'manifest.json').exists():
    m=json.loads((current.DEST/'manifest.json').read_text());jobs=[]
    sample=m['jobs'][0]
    rows=[r for r in json.loads(Path('/opt/kixbox-retouch/queue.json').read_text()) if r['day']==DAY]
    for r in rows:
        record=json.loads((Path('/var/lib/kixbox-retouch/jobs')/r['source_id']/'state.json').read_text())
        if record.get('state')!='ready' or record.get('sha256')!=r['sha256'] or not record.get('drive_id'):raise RuntimeError('Retouch source is not verified')
        raw=Path('/var/lib/kixbox-retouch/sources')/r['source_id']/r['name']
        row=dict(label_id=r['source_id'],sha256=r['sha256'],bbox=None,local_path=str(raw))
        if ingest(row,DEST)=='failed':raise RuntimeError('Source ingestion failed')
        jobs.append(dict(day=DAY,folder_id=sample['folder_id'],destination=sample['destination'],label_id=r['source_id'],label_name=r['name'],label_relative=DAY+'/'+r['name'],sha256=r['sha256'],bbox=None,files=[dict(id=record['drive_id'],name=r['output_name'],parent=sample['folder_id'],association='verified_own_original_source',original_sources=[r['source_path']+'/'+r['name']])]))
    manifest=dict(m,jobs=jobs,prior_directory=str(current.DEST));atomic(DEST/'manifest.json',manifest);(DEST/'INGESTION_COMPLETE').touch()
    print(json.dumps({'additional_source_photos':len(jobs),'coverage':{'already_renamed':327,'tag_linked_remaining':210,'own_sources_remaining':55,'unlinked':2,'total':594}}),flush=True)
reader.LabelWorker=current.Worker
sys.argv=[sys.argv[0],'--directory',str(DEST),'--after-state',str(current.DEST/'state.json')];reader.main()
