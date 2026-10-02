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
@pytest.mark.parametrize('query', ['pronta entrega', 'Você consegue me passar quais modelos tem a pronta entrega?',
                                  'Quero saber quais pronta entrega você tem',
                                  'Categoria pronta entrega', 'Ver a categoria de pronta entrega',
                                  'Catálogo de pronta entrega'])
async def test_broad_inventory_request_lists_available_options(query):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html()))) as client:
        result = await search_ready_delivery(query, client)
    assert len(result['products']) == 1
    assert not result['requiresModel'] and not result['stockConfirmed']


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
    async def fail(query, **kwargs):
        raise httpx.ConnectError('private details')
    monkeypatch.setattr('app.ready_delivery.search_ready_delivery', fail)
    response = TestClient(main.app).get('/internal/ready-delivery?query=Tissot', headers={'Authorization': 'Bearer adapter-token'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'ready_delivery_unavailable'}


@pytest.mark.asyncio
async def test_sliding_pagination_discovers_all_nine_pages_once():
    calls = []
    def handler(req):
        number = int(req.url.params['pg'])
        calls.append(number)
        name = 'Tissot Heritage 1938 Salmão' if number == 9 else f'Outro modelo {number}'
        body = html(name, pages=f'?pg={min(9, max(4, number + 1))}')
        return httpx.Response(200, text=body.replace('/heritage', f'/product-{number}'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_ready_delivery('Tissot Heritage 1938 salmão', client)
    assert sorted(calls) == list(range(1, 10))
    assert result['complete'] and len(result['products']) == 1
    assert result['products'][0]['url'].endswith('product-9')


@pytest.mark.asyncio
async def test_unbounded_pagination_fails_instead_of_reporting_not_found():
    calls = []
    def handler(req):
        number = int(req.url.params['pg'])
        calls.append(number)
        return httpx.Response(200, text=html(pages=f'?pg={number + 1}'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match='ready_delivery_incomplete'):
            await search_ready_delivery('Hamilton', client)
    assert max(calls) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['', 'Quero comprar', 'Preciso do', 'Vocês poderiam me informar sobre', 'Estou procurando'])
async def test_conversational_words_do_not_hide_available_model(prefix):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(
        200, text=html('Hamilton Khaki Field Preto H69401131')))) as client:
        result = await search_ready_delivery(f'{prefix} Hamilton Khaki Field Preto H69401131 pronta entrega', client)
    assert len(result['products']) == 1


@pytest.mark.asyncio
async def test_color_and_reference_are_still_required():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html()))) as client:
        for query in ('Quero comprar Tissot Heritage 1938 azul', 'Preciso do Tissot Heritage T999'):
            assert not (await search_ready_delivery(query, client))['products']


@pytest.mark.asyncio
@pytest.mark.parametrize('query,name,match', [
    ('PRX 35mm azul', 'Tissot PRX Azul 35 mm', True),
    ('PRX 35 mm azul', 'Tissot PRX Azul 35mm', True),
    ('PRX 35mm azul', 'Tissot PRX Azul 40 mm', False),
    ('PRX 35mm azul', 'Tissot PRX Azul 35.5 mm', False),
    ('PRX 35,5mm azul', 'Tissot PRX Azul 35.5 mm', True),
    ('PRX 35mm azul', 'Tissot PRX Lady Ouro Rosa Madrepérola Branca 35 mm', False),
    ('PRX 35mm prateado', 'Tissot PRX Prata 35 mm', True),
    ('PRX 35mm prateado', 'Tissot PRX Branco 35 mm', False),
    ('T999', 'Tissot PRX Azul L999 35 mm', False),
])
async def test_story_size_color_and_reference_constraints(query, name, match):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html(name)))) as client:
        result = await search_ready_delivery(query, client)
    assert bool(result['products']) is match


@pytest.mark.asyncio
async def test_pagination_total_continuation_images_and_last_page():
    def handler(req):
        page = int(req.url.params['pg'])
        rows = [{'nameProduct': f'Relogio {n}', 'availability': 'YES', 'reference': str(n),
                 'urlProduct': f'https://www.newstorerj.com/relogios/{n}',
                 'urlImage': f'https://images.tcdn.com.br/img/{n}.jpg'}
                for n in range((page-1)*12, page*12)]
        return httpx.Response(200, text='"listProducts":'+json.dumps(rows)+'}?pg=3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pages = [await search_ready_delivery('pronta entrega', client, offset=n, limit=10)
                 for n in (0, 10, 20, 30, 40)]
    assert all(p['total'] == 36 and p['complete'] for p in pages)
    assert [p['returned'] for p in pages] == [10, 10, 10, 6, 0]
    assert [p['next_offset'] for p in pages] == [10, 20, 30, None, None]
    assert [p['has_more'] for p in pages] == [True, True, True, False, False]
    urls = [p['url'] for page in pages for p in page['products']]
    assert len(set(urls)) == len(urls) == 36
    assert pages[0]['products'][0]['image_url'].endswith('/0.jpg')


def test_route_pagination_contract(monkeypatch):
    configure(monkeypatch)
    seen = []
    async def lookup(query, **kwargs):
        seen.append((query, kwargs))
        return {'products': [], 'total': 25, 'returned': 0, 'has_more': False, 'next_offset': None}
    monkeypatch.setattr('app.ready_delivery.search_ready_delivery', lookup)
    client = TestClient(main.app)
    headers = {'Authorization': 'Bearer adapter-token'}
    assert client.get('/internal/ready-delivery?query=pronta&offset=20&limit=10', headers=headers).status_code == 200
    assert seen == [('pronta', {'offset': 20, 'limit': 10})]
    for query in ('offset=-1', 'limit=0', 'limit=51'):
        assert client.get('/internal/ready-delivery?query=pronta&'+query, headers=headers).status_code == 422


def test_image_host_cannot_be_injected():
    body = html().replace('"reference": "T142"', '"urlImage": "https://evil.test/photo.jpg", "reference": "T142"')
    assert 'image_url' not in parse_page(body)[0][0]
