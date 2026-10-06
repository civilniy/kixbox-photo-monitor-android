import json,re,sys
from pathlib import Path
import label_reread as reader
from build_campaign import norm,color_candidates
from campaign_worker import atomic
BASE=Path('/var/lib/kixbox-rename');DEST=BASE/'september23-recheck-20261006'
DAY='2026_09_23'
original=reader.select_product
reader.PROMPT += '''\nIMPORTANT correction: A store inventory number below the barcode (such as 1044793) is NOT the manufacturer article. A printed M3636-W54 means model M3636 and printed colour code W54. Split this exact printed model-colour string into sku and color. Prefer manufacturer STYLE and COL fields when present. Example STYLE M1588V126 COL 97A must yield sku M1588V126 color 97A, even if store sticker says M1588V-97A. Codes printed on a manufacturer tag below an article can be colour codes, not sizes; sizes are S/M/L/XL. Read all tags in full image. If only M3636-W54 is visible, return M3636 and W54; never invent the catalogue suffix. Do not treat a store model-colour shorthand and a matching manufacturer STYLE/COL as contradictory.\n'''
def select(read,products,index=None):
    p,reason=original(dict(read,confidence=1),products,index)
    if p or not read.get('label_present') or read.get('ambiguous') or not read.get('color'):return p,reason
    sku=norm(read.get('sku',''))
    if not re.fullmatch(r'[A-Z]\d{4}[A-Z]?',sku):return None,reason
    candidates=color_candidates([p for p in products if reader.brand_key(p['brand'])=='FREDPERRY' and re.fullmatch(re.escape(sku)+r'\d{3}',norm(p['sku']))],read['color'])
    if read.get('season'):candidates=[p for p in candidates if reader.season_key(p['season'])==reader.season_key(read['season'])]
    if read.get('brand') and reader.brand_key(read['brand'])!='FREDPERRY':return None,'Бренд противоречит Fred Perry'
    if len(candidates)==1:return candidates[0],'unique_printed_fred_perry_model_color'
    return None,'Несколько строк Excel для модели и цвета' if candidates else reason
reader.select_product=select
class Worker(reader.LabelWorker):
    def work(self,phase,job=None,message='',force=False):
        total=sum(len(j['files']) for j in self.manifest['jobs']);s=self.state
        summary=f"Проверка очереди: {s['photos_checked']} из {total} фото. Переименовано: {s['renamed']}; на разбор: {s['manual']}. 23 сентября: повторная проверка исправленных полей. "
        super().work(phase,job,summary+message,force)
def prepare():
    if (DEST/'manifest.json').exists():return
    primary=BASE/'label-reread-20261006';m=json.loads((primary/'manifest.json').read_text());done=set();reserved=m['reserved']
    for dr in ['label-reread-20261006','label-source-followup-20261006','label-candidates-307-20261006']:
        src=BASE/dr;done.update(json.loads((src/'state.json').read_text()).get('renamed_ids',[]))
        for rp in (src/'results').glob('*.json'):
            for op in json.loads(rp.read_text()).get('operations',[]):reserved.setdefault(op['day'],[]).append(op['new_name'])
    jobs=[]
    for job in m['jobs']:
        if job['day']!=DAY:continue
        j=dict(job,files=[f for f in job['files'] if f['id'] not in done])
        if not j['files']:continue
        jobs.append(j);cache=DEST/'images'/j['label_id'];cache.parent.mkdir(parents=True,exist_ok=True);cache.symlink_to(primary/'images'/j['label_id'],target_is_directory=True)
    manifest=dict(m,jobs=jobs,reserved=reserved,review_ids={k:[fid for fid in ids if fid not in done] for k,ids in m['review_ids'].items()},unmapped=[f for f in m['unmapped'] if f['day']==DAY and f['id'] not in done])
    atomic(DEST/'manifest.json',manifest);(DEST/'INGESTION_COMPLETE').touch()
    print(json.dumps({'photos_to_reread':sum(len(j['files']) for j in jobs),'labels':len(jobs),'unmapped':len(manifest['unmapped'])}),flush=True)
if __name__=='__main__':
    prepare();reader.LabelWorker=Worker;sys.argv=[sys.argv[0],'--directory',str(DEST)];reader.main()
