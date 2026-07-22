# TrayAdapter

Serviço FastAPI independente para comunicação com a API da Tray. Nesta etapa ele não se conecta ao NSAgent, backend, frontend, pedidos, pagamentos ou outros sistemas.

## Configuração

As configurações são lidas com `os.getenv`:

```text
TRAY_API_BASE=
TRAY_CODE=
TRAY_CONSUMER_KEY=
TRAY_CONSUMER_SECRET=
TRAY_COUPON_VALID_DAYS=180
TRAY_STORE_CODE=
TRAY_ADAPTER_TOKEN=
```

`TRAY_API_BASE` já é o endereço completo da API (incluindo `/web_api`); o cliente não acrescenta esse segmento novamente. Tokens ficam em memória, são reutilizados enquanto válidos e recebem uma tentativa única de refresh após HTTP 401.

## Execução local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Testes e checagem Python:

```bash
pytest -q tests -p no:cacheprovider
python -m compileall app tests
```

## Endpoints FastAPI internos

| Área | Endpoint |
|---|---|
| Health | `GET /health` |
| Diagnóstico somente leitura | `GET /tray/test-auth`, `/tray/test-products`, `/tray/test-resources` |
| Produtos | `GET /internal/products`, `GET /internal/products/{id}`, `GET /internal/products/{id}/stock` |
| Variantes de produto | `GET /internal/products/variants`, `GET /internal/products/variants/{id}` |
| Categorias | `GET /internal/categories`, `GET /internal/categories/{id}`, `GET /internal/categories/tree/{id}` |
| Marcas | `GET /internal/brands`, `GET /internal/brands/{id}` |
| Kits | `GET /internal/kits` |
| MultiCD | `GET /internal/inventory/distribution-centers`, `GET /internal/inventory/distribution-centers/{id}`, `GET /internal/inventory/products/{id}/distribution-centers` |
| Clientes | `GET /internal/customers`, `GET /internal/customers/{id}` |
| Endereços | `GET /internal/customer-addresses`, `GET /internal/customer-addresses/{id}` |
| Cupons | `GET /internal/coupons`, `GET /internal/coupons/{id}`, além das seis rotas de relacionamentos por tipo |
| Usuários | `GET /internal/users` |

As rotas internas são somente leitura. Operações POST/PUT/DELETE existem nos resources/client para uso futuro e são cobertas somente por mocks nesta etapa.

## APIs Tray implementadas

| Resource | Endpoint Tray | Métodos |
|---|---|---|
| Auth | `/auth` | POST auth e POST refresh interno |
| Products | `/products`, `/products/{id}` | GET, POST, PUT, DELETE |
| Product variants | `/products/variants/`, `/products/variants/{id}` | GET |
| Categories | `/categories/`, `/categories/{id}`, `/categories/tree/{id}` | GET |
| Brands | `/products/brands`, `/products/brands/{id}` | GET, POST, PUT, DELETE |
| Kits | `/products/kits` | GET |
| Inventory | `/products/{id}` | GET e PUT de estoque |
| MultiCD | `/multicd/distribution-centers`, `/multicd/distribution-centers/{id}`, `/multicd/stock/detailed/product/{id}` | GET |
| MultiCD stock | `/multicd/distribution-centers/{id}/stock` | PUT |
| Customers | `/customers`, `/customers/{id}` | GET, POST, PUT, DELETE |
| Customer addresses | `/customers/addresses`, `/customers/addresses/{id}` | GET |
| Coupons | `/discount_coupons`, `/discount_coupons/{id}` | GET, POST, PUT, DELETE |
| Coupon relationships | `/discount_coupons/*_relationship/{id}` | GET |
| Coupon relationships | `/discount_coupons/create_relationship/{id}` | POST, com batch de 100 clientes |
| Coupon relationships | `/delete_relationship/{id}` | DELETE |
| Users | `/users` | GET |

Produtos preservam separadamente estoque, disponibilidade e configurações de venda quando presentes. Produtos, clientes, endereços, cupons, usuários e estoque são normalizados para não expor os envelopes Tray nem tokens internos de clientes.

Cupons calculam `ends_at` usando `TRAY_COUPON_VALID_DAYS` somente quando o caller não fornece uma data explícita. Configurações conflitantes de produtos, marcas e categorias são rejeitadas antes do request.

## Render

O `render.yaml` contém apenas o Web Service, build e start command. As variáveis devem ser cadastradas no ambiente do Render sem valores versionados.

As rotas `/internal/*` exigem `Authorization: Bearer <TRAY_ADAPTER_TOKEN>`. `/health` e as rotas `/tray/*` permanecem públicas.
