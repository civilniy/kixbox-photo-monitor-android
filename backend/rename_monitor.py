"""Cached, authenticated read-only progress for all folders in the ready root."""
from datetime import datetime, timezone, timedelta
import asyncio
import logging
import re

logger = logging.getLogger(__name__)
last_error_detail = None
from fastapi import HTTPException
from rename_inventory import scan_inventory

snapshot = None
last_error = None
refreshing = False

def parse_date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def build_snapshot(raw, work=None, now=None):
    now = now or datetime.now(timezone.utc)
    work = dict(work or {'phase': 'paused'})
    work.pop('review_ids', None)
    rows = []
    for folder in raw['folders']:
        total, renamed = int(folder['total']), int(folder['renamed'])
        review = int(folder.get('review', 0))
        if min(total, renamed, review) < 0 or renamed + review > total:
            raise ValueError('Inventory counts are inconsistent')
        remaining = total - renamed
        rows.append(dict(folder, total=total, renamed=renamed, remaining=remaining, review=review,
            progress_percent=round(100 * renamed / total, 2) if total else 0,
            state='empty' if not total else 'completed' if not remaining else 'needs_review' if review == remaining else 'partial' if renamed else 'pending'))
    total = sum(f['total'] for f in rows)
    renamed = sum(f['renamed'] for f in rows)
    remaining = total - renamed
    active = work.get('phase') in {'reviewing', 'matching', 'renaming', 'verifying'}
    age = (now - parse_date(raw['generated_at'])).total_seconds()
    if active and (not work.get('updated_at') or (now - parse_date(work['updated_at'])).total_seconds() > 900):
        work['phase'] = 'awaiting_update'
        active = False
    for row in rows:
        if active and row['id'] == work.get('folder_id'):
            row['state'] = 'working'
    # Wall-clock pace includes review, pauses and execution. Never extrapolate a fast API batch.
    history = [p for p in raw.get('history', []) if 0 <= (now - parse_date(p['at'])).total_seconds() <= 7*86400]
    rate, hours, completion = None, None, None
    reason = 'Собираем историю: для прогноза нужно не меньше 2 часов наблюдений.'
    if len(history) >= 3:
        first, last = history[0], history[-1]
        span = (parse_date(last['at']) - parse_date(first['at'])).total_seconds()/3600
        delta = last['renamed'] - first['renamed']
        monotonic = all(b['renamed'] >= a['renamed'] for a,b in zip(history, history[1:]))
        if span >= 2 and delta > 0 and monotonic:
            rate = delta/span
            hours = remaining/rate
            reason = 'По наблюдаемому темпу, включая разбор и перерывы. Спорные файлы входят в остаток.'
            if active and age <= 900:
                completion = (now + timedelta(hours=hours)).isoformat()
    if not remaining and total:
        hours, reason = 0, 'Все фотографии переименованы.'
    elif not active:
        reason = 'Работа на паузе. Дата появится после возобновления.' if work.get('phase') == 'paused' else 'Нет подтверждения активной работы. Дата завершения пока не рассчитывается.'
    return {'generated_at':raw['generated_at'], 'scan_started_at':raw.get('scan_started_at'),
        'data_status':'stale' if age > 900 else 'live', 'total':total, 'renamed':renamed,
        'remaining':remaining, 'review':sum(f['review'] for f in rows),
        'progress_percent':round(100*renamed/total,2) if total else 0,
        'folders_total':len(rows),'folders_complete':sum(f['state']=='completed' for f in rows),
        'folders':rows,'work':work,'estimated_hours_remaining':hours,
        'estimated_completion_at':completion,'pace_per_hour':rate,'forecast_note':reason,
        'excluded_files':raw.get('excluded_files',0), 'root_id':raw.get('root_id')}

async def refresh_once():
    global snapshot, last_error, refreshing, last_error_detail
    refreshing = True
    try:
        import rename_api
        work = dict(rename_api._work_cache or (snapshot or {}).get('work') or {'phase': 'paused'})
        raw = await asyncio.to_thread(scan_inventory, work)
        current_work = dict(rename_api._work_cache or work)
        history = list((snapshot or {}).get('_history', []))
        history.append({'at': raw['generated_at'], 'renamed': sum(f['renamed'] for f in raw['folders'])})
        history = [p for p in history if (datetime.now(timezone.utc)-parse_date(p['at'])).total_seconds() <= 7*86400][-2016:]
        raw['history'] = history
        updated = build_snapshot(raw, current_work)
        updated['_history'] = history
        snapshot = updated
        last_error = None
        last_error_detail = None
        return False
    except Exception as error:
        detail = str(getattr(error, 'detail', type(error).__name__))
        detail = re.sub(r'https?://\\S+', '[url]', detail)[:500]
        last_error_detail = detail
        logger.warning('Rename inventory refresh failed: %s: %s', type(error).__name__, detail)
        last_error = 'Не удалось обновить статистику Drive. Показаны последние полученные данные.'
        return False
    finally:
        refreshing = False

async def refresh_loop():
    while True:
        scanning = await refresh_once()
        await asyncio.sleep(300)

def get_snapshot():
    if snapshot is None:
        raise HTTPException(503, last_error or 'Первичная инвентаризация фотографий выполняется')
    result = dict(snapshot)
    result.pop('_history', None)
    age = (datetime.now(timezone.utc)-parse_date(result['generated_at'])).total_seconds()
    result['data_status'] = 'stale' if last_error or age > 900 else result['data_status']
    import rename_api
    if rename_api._task is not None and not rename_api._task.done():
        current = next((f for f in result['folders'] if f['name'] == rename_api._last.get('day')), None)
        if current:
            result['work'] = {'phase':'renaming', 'folder_id':current['id'], 'folder_name':current['name'],
                'message':f"Очередь: {rename_api._last.get('completed', 0)} из {rename_api._last.get('total', 0)}. Итоги папок обновляются после сканирования.",
                'updated_at':rename_api._last.get('updated_at', result['generated_at'])}
            result['folders'] = [dict(f, state='working') if f['id']==current['id'] else f for f in result['folders']]
    elif result['work'].get('phase') in {'reviewing','matching','renaming','verifying'}:
        stamp = result['work'].get('updated_at')
        if not stamp or (datetime.now(timezone.utc)-parse_date(stamp)).total_seconds()>900:
            result['work'] = dict(result['work'], phase='awaiting_update')
            result['estimated_completion_at'] = None
    result['refresh_error'] = last_error
    result['refresh_error_detail'] = last_error_detail
    result['refreshing'] = refreshing
    return result
