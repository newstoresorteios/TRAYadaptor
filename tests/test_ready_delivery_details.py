import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.ready_delivery_details import parse_details, product_details
from tests.test_ready_delivery import configure

URL='https://www.newstorerj.com/relogio'


def test_jsonld_optional_properties_and_malformed_price():
    product = {'@type': 'Product', 'url': URL, 'name': 'Watch', 'additionalProperty': None}
    def render():
        return '<script type="application/ld+json">' + json.dumps(product) + '</script>'
    assert parse_details(render(), URL)['properties'] == []
    product['additionalProperty'] = {'name': 'Calibre', 'value': 'L888'}
    assert parse_details(render(), URL)['properties'] == [{'name': 'Calibre', 'value': 'L888'}]
    product['offers'] = {'priceCurrency': 'BRL', 'price': 'invalid'}
    with pytest.raises(ValueError, match='invalid_public_product_price'):
        parse_details(render(), URL)


def page(url=URL):
    row={'idProduct':42,'urlProduct':url,'nameProduct':'Relógio real','reference':'REF42','priceSell':'1250.00'}
    return '<script>dataLayer = '+json.dumps([row])+'</script><div id="desc_product">Calibre L888<div>Caixa 40 mm</div></div><div>Recomendação falsa 99 mm</div>'


def test_only_product_description_and_current_price_are_evidence():
    result=parse_details(page(),URL)
    assert result['price']=='1250.00' and result['reference']=='REF42'
    assert '40 mm' in result['description'] and '99 mm' not in result['description']
    assert 'id' not in result  # A public-store ID must never be used at admin store.
    with pytest.raises(ValueError): parse_details(page('https://www.newstorerj.com/other'),URL)
    with pytest.raises(ValueError): parse_details('<html>error</html>',URL)


@pytest.mark.asyncio
async def test_snapshot_authorizes_url_and_download_is_bounded(monkeypatch):
    monkeypatch.setattr('app.ready_delivery_details.search_ready_delivery',AsyncMock(return_value={'products':[{'url':URL}],'has_more':False}))
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,text=page())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result=await product_details(URL,'a'*32,client)
    assert result['success'] and result['stockConfirmed'] is False
    assert result['evidenceType']=='public_product_page'
    assert seen[0].method=='GET' and seen[0].extensions['timeout']['read']==10
    assert 'authorization' not in seen[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize('url',['http://www.newstorerj.com/p','https://127.0.0.1/p','https://www.newstorerj.com.evil/p','https://www.newstorerj.com/p?q=x'])
async def test_untrusted_urls_rejected_before_network(url):
    with pytest.raises(ValueError): await product_details(url,'a'*32)


def test_route_auth_query_errors_and_openapi(monkeypatch):
    configure(monkeypatch)
    client=TestClient(main.app)
    headers={'Authorization':'Bearer adapter-token'}
    route='/internal/ready-delivery/product'
    assert client.get(route).status_code==401
    assert client.get(route,headers=headers).status_code==422
    params={'url':URL,'snapshot_id':'a'*32}
    monkeypatch.setattr('app.ready_delivery_details.product_details',AsyncMock(return_value={'success':True,'product':{'url':URL}}))
    assert client.get(route,params=params,headers=headers).json()['product']['url']==URL
    for exc,status,detail in [(KeyError(),409,'ready_delivery_snapshot_expired'),
                              (httpx.ReadTimeout('secret'),503,'ready_delivery_details_unavailable')]:
        monkeypatch.setattr('app.ready_delivery_details.product_details',AsyncMock(side_effect=exc))
        result=client.get(route,params=params,headers=headers)
        assert result.status_code==status and result.json()=={'detail':detail}
    schema=main.app.openapi()['paths']
    assert 'get' in schema[route]
    assert 'get' in schema['/internal/products/variants']
    assert 'post' in schema['/internal/shippings/quote']
    assert not any(p['name']=='url' for p in schema['/internal/products']['get'].get('parameters',[]))
