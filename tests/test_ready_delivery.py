import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main
from app.ready_delivery import parse_page, search_ready_delivery
from tests.test_internal_auth import configure


def html(name='Tissot Heritage 1938 Salmão', available='YES', pages=''):
    return '"listProducts":' + json.dumps([{'nameProduct': name, 'availability': available,
        'reference': 'T142', 'urlProduct': 'https://www.newstorerj.com/relogios/heritage'}]) + '}' + pages


@pytest.mark.asyncio
async def test_pages_color_and_public_evidence():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, text=html('Tissot Heritage 1938 Antracite', pages='?pg=2') if req.url.params['pg'] == '1' else html())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_ready_delivery('Vocês teriam o Tissot heritage 1938 na cor salmão a pronta entrega?', client)
    assert len(calls) == 2
    assert result['products'][0]['name'].endswith('Salmão')
    assert result['stockConfirmed'] is False
    assert result['complete'] is True
    assert all(req.url.host == 'www.newstorerj.com' for req in calls)


@pytest.mark.asyncio
async def test_failure_on_later_page_is_not_empty_success():
    def handler(req):
        return httpx.Response(200, text=html(pages='?pg=2')) if req.url.params['pg'] == '1' else httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await search_ready_delivery('Heritage', client)


def test_unavailable_and_invalid_markup():
    assert parse_page(html(available='NO'))[0][0]['listedAvailable'] is False
    with pytest.raises(ValueError):
        parse_page('<html>blocked</html>')


def test_route_auth_validation_and_openapi(monkeypatch):
    configure(monkeypatch)
    client = TestClient(main.app)
    assert client.get('/internal/ready-delivery?query=Tissot').status_code == 401
    assert client.get('/internal/ready-delivery', headers={'Authorization': 'Bearer adapter-token'}).status_code == 422
    assert 'get' in main.app.openapi()['paths']['/internal/ready-delivery']


def test_route_returns_normalized_error(monkeypatch):
    configure(monkeypatch)
    async def fail(query):
        raise httpx.ConnectError('private details')
    monkeypatch.setattr('app.ready_delivery.search_ready_delivery', fail)
    response = TestClient(main.app).get('/internal/ready-delivery?query=Tissot', headers={'Authorization': 'Bearer adapter-token'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'ready_delivery_unavailable'}
