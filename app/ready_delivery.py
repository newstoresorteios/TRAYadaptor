"""Public ready-delivery evidence, isolated from the .com.br admin catalog."""
import asyncio
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

SOURCE = "https://www.newstorerj.com/pronta-entrega"


def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))


def parse_page(html):
    marker = re.search(r'"listProducts"\s*:\s*', html)
    if not marker:
        raise ValueError("ready_delivery_invalid_page")
    rows, _ = json.JSONDecoder().raw_decode(html[marker.end():])
    if not isinstance(rows, list):
        raise ValueError("ready_delivery_invalid_page")
    products = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('ready_delivery_invalid_page')
        url = str(row.get('urlProduct') or '')
        if urlparse(url).hostname != 'www.newstorerj.com' or not url.startswith('https://'):
            continue
        products.append({
            'name': str(row.get('nameProduct') or ''), 'reference': str(row.get('reference') or ''),
            'url': url, 'listedAvailable': row.get('availability') == 'YES',
            'source': SOURCE,
        })
    pages = [int(n) for n in re.findall(r'[?&]pg=(\d+)', html)]
    return products, max(pages, default=1)


async def search_ready_delivery(query: str, client=None):
    """No stock quantities or foreign-store product IDs escape this boundary."""
    async def run(http):
        async def page(number):
            response = await http.get(SOURCE, params={'pg': number}, timeout=8.0, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 3_000_000:
                raise ValueError('ready_delivery_invalid_page')
            return parse_page(response.text)
        first, total = await page(1)
        if total > 20:
            raise ValueError('ready_delivery_incomplete')
        # Bounded concurrency and total deadline; partial results are never "not found".
        semaphore = asyncio.Semaphore(3)
        async def bounded(number):
            async with semaphore:
                return await page(number)
        rest = await asyncio.gather(*(bounded(n) for n in range(2, total + 1)))
        rows = {p['url']: p for p in first}
        for products, discovered_total in rest:
            if discovered_total > total:
                raise ValueError('ready_delivery_incomplete')
            rows.update({p['url']: p for p in products})
        stop = set('ola oi voces voce teria teriam tem esse essa esses essas este esta aquele aquela algum alguma relogio relogios na no de da do a o os as um uma cor pronta entrega disponivel disponibilidade por favor para gostaria saber se e em qual quanto custa valor preco ai hoje'.split())
        tokens = [t for t in re.findall(r'[a-z0-9]+', folded(query)) if t not in stop and len(t) > 1]
        matches = [p for p in rows.values() if tokens and set(tokens).issubset(set(re.findall(r'[a-z0-9]+', folded(p['name'] + ' ' + p['reference']))))]
        return {'success': True, 'source': SOURCE, 'checkedAt': datetime.now(timezone.utc).isoformat(),
                'complete': True, 'products': matches[:10], 'requiresModel': not tokens,
                'evidenceType': 'public_listing', 'stockConfirmed': False}
    async def execute():
        if client is not None:
            return await run(client)
        async with httpx.AsyncClient() as http:
            return await run(http)
    return await asyncio.wait_for(execute(), timeout=20.0)
