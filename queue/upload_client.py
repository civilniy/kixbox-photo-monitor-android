"""Run the separate upload stage through Render with the existing private config."""
import argparse
import json
import os
from pathlib import Path

import requests


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('/etc/kixbox-rename/client.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', action='store_true', help='Start moving after staging the plan')
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    plan = json.loads(args.plan.read_text())
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + cfg['token']
    base = cfg['render_url'].rstrip('/') + '/api/v1/rename/upload'

    def call(method, path, body=None):
        response = session.request(method, base + path, json=body, timeout=(20, 300))
        if response.status_code == 404:
            raise RuntimeError('Upload API is not deployed; no files moved')
        response.raise_for_status()
        result = response.json()
        if not result.get('ok'):
            raise RuntimeError('Upload API rejected the operation')
        return result

    # Capability check does not mutate Drive, queue, or monitor settings.
    call('GET', '/status')
    result = call('POST', '/plan', plan)
    save(args.output, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not args.run:
        return
    for _ in range(1001):
        if result.get('errors'):
            raise RuntimeError('Upload queue requires review; see saved progress')
        if result['completed'] == result['total']:
            registry = call('GET', '/registry')
            stored = registry.get('plan') or {}
            wanted = {o['id']: o for o in plan['operations']}
            observed = stored.get('operations', [])
            if stored.get('request_id') != plan['request_id'] or len(observed) != len(wanted):
                raise RuntimeError('Final registry identity mismatch')
            for op in observed:
                original = wanted.get(op['id'])
                before, after = op.get('before', {}), op.get('after', {})
                if (not original or op.get('status') != 'completed' or
                        after.get('id') != original['id'] or after.get('name') != original['name'] or
                        after.get('parents') != [plan['destination']] or
                        after.get('md5Checksum') != before.get('md5Checksum') or
                        after.get('size') != before.get('size')):
                    raise RuntimeError('Final file verification failed')
            save(args.output.with_name('upload-registry.json'), registry)
            save(args.output, dict(result, state='completed_and_verified'))
            print('Completed and verified: ' + str(len(observed)), flush=True)
            return
        result = call('POST', '/run', {'request_id': plan['request_id']})
        save(args.output, result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result.get('attempted') and result['completed'] != result['total']:
            raise RuntimeError('Upload queue made no progress')
    raise RuntimeError('Upload batch limit exceeded')


if __name__ == '__main__':
    main()
