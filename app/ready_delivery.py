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
        tokens = [t for t in tokenize(query) if t not in stop and (len(t) > 1 or t.isdigit())]
        matches = [p for p in rows.values() if p['listedAvailable'] and
                   (not tokens or set(tokens).issubset(set(tokenize(p['name'] + ' ' + p['reference']))))]
        return {'success': True, 'source': SOURCE, 'checkedAt': datetime.now(timezone.utc).isoformat(),
                'complete': True, 'products': matches[:10], 'requiresModel': False,
                'evidenceType': 'public_listing', 'stockConfirmed': False}
    async def execute():
        if client is not None:
            return await run(client)
        async with httpx.AsyncClient() as http:
            return await run(http)
    return await asyncio.wait_for(execute(), timeout=20.0)
