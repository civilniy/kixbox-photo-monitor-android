import asyncio
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('rename_api', Path(__file__).resolve().parents[1] / 'rename_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
app = FastAPI()
app.include_router(api.router)

def test_api_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv('RENAME_API_TOKEN', raising=False)
    assert TestClient(app).post('/api/v1/rename/start').status_code == 503

def test_wrong_token_cannot_start(monkeypatch):
    monkeypatch.setenv('RENAME_API_TOKEN', 'test-secret')
    assert TestClient(app).post('/api/v1/rename/start', headers={'Authorization':'Bearer wrong'}).status_code == 401

def test_status_uses_persisted_google_counts(monkeypatch):
    monkeypatch.setenv('RENAME_API_TOKEN', 'test-secret')
    monkeypatch.setattr(api, '_task', None)
    monkeypatch.setattr(api, 'call_script', AsyncMock(return_value={'ok':True,'total':1515,'completed':130,'renamed':154}))
    response = TestClient(app).get('/api/v1/rename/status', headers={'Authorization':'Bearer test-secret'})
    assert response.status_code == 200
    assert response.json()['completed'] == 130
    assert response.json()['renamed'] == 154

def test_queue_stops_on_conflict(monkeypatch):
    mock = AsyncMock(return_value={'ok':True,'total':1515,'completed':131,'attempted':1,'errors':[{'id':'photo'}]})
    monkeypatch.setattr(api,'call_script',mock)
    monkeypatch.setattr(api,'_stop',False)
    asyncio.run(api.run_queue())
    assert mock.await_count == 1
    assert api._last['state'] == 'needs_review'

def test_queue_reports_completion(monkeypatch):
    mock = AsyncMock(return_value={'ok':True,'total':1515,'completed':1515,'attempted':25,'errors':[]})
    monkeypatch.setattr(api,'call_script',mock)
    monkeypatch.setattr(api,'_stop',False)
    asyncio.run(api.run_queue())
    assert api._last['state'] == 'completed'
