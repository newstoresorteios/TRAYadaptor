"""Current public product details, constrained to a known ready-delivery snapshot."""
import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
from .ready_delivery import search_ready_delivery


class DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth = 0; self.parts = []; self.blocked = False
    def handle_starttag(self, tag, attrs):
        if tag == 'div' and (self.depth or dict(attrs).get('id') == 'desc_product'):
            self.depth += 1
        if self.depth and tag in {'script', 'style'}:
            self.blocked = True
    def handle_endtag(self, tag):
        if self.depth and tag == 'div': self.depth -= 1
        if tag in {'script', 'style'}: self.blocked = False
    def handle_data(self, data):
        if self.depth and not self.blocked: self.parts.append(data.strip())


def storefront_product(html, expected_url):
    rows = []
    for match in re.finditer(r'\bdataLayer\s*=\s*', html):
        try:
            data, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
        except ValueError:
            continue
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict) and r.get('idProduct') and not r.get('listProducts'))
    if len(rows) != 1:
        raise ValueError('public_product_evidence_missing')
    row = rows[0]
    if str(row.get('urlProduct', '')).replace('http://', 'https://', 1).rstrip('/') != expected_url.rstrip('/'):
        raise ValueError('public_product_identity_mismatch')
    parser = DescriptionParser(); parser.feed(html)
    return {'@type': 'Product', 'url': expected_url, 'name': row.get('nameProduct'),
            'sku': row.get('reference'), 'description': ' '.join(p for p in parser.parts if p),
            'offers': {'price': row.get('priceSell'), 'priceCurrency': 'BRL'}}


def parse_details(html, expected_url):
    products = []
    for block in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        def visit(item):
            if isinstance(item, list):
                for entry in item: visit(entry)
            elif isinstance(item, dict):
                types = item.get('@type', [])
                if types == 'Product' or isinstance(types, list) and 'Product' in types:
                    products.append(item)
                if '@graph' in item: visit(item['@graph'])
        visit(value)
    if not products:
        products = [storefront_product(html, expected_url)]
    if len(products) != 1:
        raise ValueError('public_product_evidence_missing')
    product = products[0]
    declared = product.get('url')
    if declared and str(declared).replace('http://', 'https://', 1).rstrip('/') != expected_url.rstrip('/'):
        raise ValueError('public_product_identity_mismatch')
    clean = lambda text: unescape(re.sub(r'<[^>]+>', ' ', str(text or ''))).strip()
    properties = product.get('additionalProperty') or []
    if isinstance(properties, dict):
        properties = [properties]
    if not isinstance(properties, list):
        properties = []
    result = {'name': clean(product.get('name')), 'url': expected_url,
              'description': clean(product.get('description'))[:18000],
              'reference': clean(product.get('sku') or product.get('mpn')),
              'properties': [{'name': clean(p.get('name')), 'value': clean(p.get('value'))}
                             for p in properties if isinstance(p, dict)]}
    offers = product.get('offers') or {}
    if isinstance(offers, list):
        offers = offers[0] if len(offers) == 1 else {}
    if isinstance(offers, dict) and offers.get('priceCurrency') == 'BRL' and offers.get('price') is not None:
        from decimal import Decimal, InvalidOperation
        try:
            price = Decimal(str(offers['price']))
        except InvalidOperation as exc:
            raise ValueError('invalid_public_product_price') from exc
        if price.is_finite() and price >= 0:
            result['price'] = str(price)
            result['currency'] = 'BRL'
    return result


async def product_details(url, snapshot_id, client=None):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.newstorerj.com'
            or parsed.query or parsed.fragment or not parsed.path or parsed.path == '/'):
        raise ValueError('invalid_public_product_url')
    offset = 0
    while True:
        page = await search_ready_delivery('pronta entrega', offset=offset, limit=50, snapshot_id=snapshot_id)
        if any(p['url'] == url for p in page['products']):
            break
        if not page['has_more']:
            raise ValueError('product_not_in_snapshot')
        offset = page['next_offset']
    async def fetch(http):
        chunks = []; size = 0
        async with http.stream('GET', url, timeout=10, follow_redirects=False) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 3_000_000:
                    raise ValueError('public_product_too_large')
                chunks.append(chunk)
        details = parse_details(b''.join(chunks).decode('utf-8', errors='replace'), url)
        return {'success': True, 'product': details, 'source': url,
                'checkedAt': datetime.now(timezone.utc).isoformat(),
                'evidenceType': 'public_product_page', 'stockConfirmed': False}
    if client is not None:
        return await fetch(client)
    async with httpx.AsyncClient() as http:
        return await fetch(http)
