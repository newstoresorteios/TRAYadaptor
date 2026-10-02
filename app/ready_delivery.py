"""Public ready-delivery evidence, isolated from the .com.br admin catalog."""
import asyncio
import json
import re
import unicodedata
import time
from uuid import uuid4
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

SOURCE = "https://www.newstorerj.com/pronta-entrega"
_SNAPSHOTS = {}
SNAPSHOT_TTL_SECONDS = 600


def _result(query, rows, checked_at, snapshot_id, offset, limit):
    selected = rows[offset:offset + limit]
    more = offset + len(selected) < len(rows)
    return {'success': True, 'source': SOURCE, 'checkedAt': checked_at,
            'complete': True, 'products': selected, 'requiresModel': False,
            'query': query, 'total': len(rows), 'returned': len(selected), 'offset': offset, 'limit': limit,
            'has_more': more, 'next_offset': offset + len(selected) if more else None,
            'snapshot_id': snapshot_id, 'evidenceType': 'public_listing', 'stockConfirmed': False}


def folded(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))
    value = re.sub(r'\bprateado\b', 'prata', value)
    # Normalize the unit without collapsing 35, 35.5 and 40 millimetres.
    return re.sub(r'\b(\d{2}(?:[.,]\d)?)\s*mm\b', lambda m: m[1].replace(',', '.') + ' mm', value)


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
        image = str(row.get('urlImage') or '').replace(r'\/', '/')
        parsed_image = urlparse(image)
        if parsed_image.scheme == 'https' and (parsed_image.hostname or '').endswith('.tcdn.com.br'):
            products[-1]['image_url'] = image
    pages = [int(n) for n in re.findall(r'[?&]pg=(\d+)', html)]
    return products, max(pages, default=1)


async def search_ready_delivery(query: str, client=None, *, offset: int = 0, limit: int = 10,
                                snapshot_id: str | None = None):
    """No stock quantities or foreign-store product IDs escape this boundary."""
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError('ready_delivery_invalid_pagination')
    now = time.monotonic()
    for key, entry in list(_SNAPSHOTS.items()):
        if now - entry[0] > SNAPSHOT_TTL_SECONDS:
            del _SNAPSHOTS[key]
    if snapshot_id:
        entry = _SNAPSHOTS.get(snapshot_id)
        if not entry or entry[1] != query:
            raise KeyError('ready_delivery_snapshot_expired')
        return _result(query, entry[2], entry[3], snapshot_id, offset, limit)
    async def run(http):
        async def page(number):
            response = await http.get(SOURCE, params={'pg': number}, timeout=8.0, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 3_000_000:
                raise ValueError('ready_delivery_invalid_page')
            return parse_page(response.text)
        first, total = await page(1)
        # Bounded concurrency and total deadline; partial results are never "not found".
        semaphore = asyncio.Semaphore(3)
        async def bounded(number):
            async with semaphore:
                return await page(number)
        rows = {p['url']: p for p in first}
        next_page = 2
        # The storefront shows a sliding pagination window, not the last page.
        # Follow newly discovered pages while retaining the same hard bounds.
        while True:
            if total > 20:
                raise ValueError('ready_delivery_incomplete')
            if next_page > total:
                break
            batch_end = min(total, next_page + 2)
            rest = await asyncio.gather(*(bounded(n) for n in range(next_page, batch_end + 1)))
            next_page = batch_end + 1
            for products, discovered_total in rest:
                total = max(total, discovered_total)
                rows.update({p['url']: p for p in products})
        stop = set('ola oi bom boa dia tarde noite tudo bem voces voce teria teriam tem esse essa esses essas este esta aquele aquela algum alguma relogio relogios modelo modelos na no de da do a o os as um uma cor pronta entrega disponivel disponibilidade por favor para gostaria saber se e em qual quanto custa valor preco ai hoje quero queria comprar preciso procuro procurando buscando busco encontrar consultar verificar pode podem poderia poderiam me informar sobre ha existe ainda obrigado obrigada'.split())
        stop.update({'estou', 'com', 'mostrador', 'sim', 'consegue', 'passar', 'quais', 'que', 'estoque', 'ja', 'falei'})
        tokenize = lambda value: re.findall(r'[a-z0-9]+(?:\.[0-9]+)*', folded(value))
        # A storefront/category navigation request supplies a source, not a
        # product name. Remove that intent phrase but retain every SKU/facet.
        product_query = re.sub(
            r'\b(?:(?:ver|abrir|mostrar|consultar)\s+)?(?:a\s+|o\s+)?'
            r'(?:categoria|catalogo|lista|secao)\s+(?:(?:de|da)\s+)?pronta entrega\b',
            '', folded(query))
        tokens = [t for t in tokenize(product_query) if t not in stop and (len(t) > 1 or t.isdigit())]
        matches = [p for p in rows.values() if p['listedAvailable'] and
                   (not tokens or set(tokens).issubset(set(tokenize(p['name'] + ' ' + p['reference']))))]
        checked_at = datetime.now(timezone.utc).isoformat()
        snapshot = uuid4().hex
        if len(_SNAPSHOTS) >= 32:
            del _SNAPSHOTS[next(iter(_SNAPSHOTS))]
        _SNAPSHOTS[snapshot] = (time.monotonic(), query, matches, checked_at)
        return _result(query, matches, checked_at, snapshot, offset, limit)
    async def execute():
        if client is not None:
            return await run(client)
        async with httpx.AsyncClient() as http:
            return await run(http)
    return await asyncio.wait_for(execute(), timeout=20.0)
