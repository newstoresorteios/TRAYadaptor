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
| Carrinhos | `POST /internal/carts`, `GET /internal/carts/{session_id}` |
| Carrinho completo | `GET /internal/carts/{session_id}/complete` |
| Opções de pagamento | `GET /internal/payments/options?cart_session_id=...` |
| Marcas | `GET /internal/brands`, `GET /internal/brands/{id}` |
| Kits | `GET /internal/kits` |
| MultiCD | `GET /internal/inventory/distribution-centers`, `GET /internal/inventory/distribution-centers/{id}`, `GET /internal/inventory/products/{id}/distribution-centers` |
| Clientes | `GET /internal/customers`, `GET /internal/customers/{id}` |
| Endereços | `GET /internal/customer-addresses`, `GET /internal/customer-addresses/{id}` |
| Cupons | `GET /internal/coupons`, `GET /internal/coupons/{id}`, além das seis rotas de relacionamentos por tipo |
| Usuários | `GET /internal/users` |

As rotas internas são majoritariamente de leitura. A exceção atual é `POST /internal/carts`, que cria ou adiciona um item ao carrinho; as demais operações POST/PUT/DELETE disponíveis nos resources/client continuam sem rotas de execução automática.

## APIs Tray implementadas

| Resource | Endpoint Tray | Métodos |
|---|---|---|
| Auth | `/auth` | POST auth e POST refresh interno |
| Products | `/products`, `/products/{id}` | GET, POST, PUT, DELETE |
| Product variants | `/products/variants/`, `/products/variants/{id}` | GET |
| Categories | `/categories/`, `/categories/{id}`, `/categories/tree/{id}` | GET |
| Carts | `/carts/`, `/carts/{session_id}` | POST, GET |
| Complete cart | `/carts/{session_id}/complete` | GET |
| Payment options | `/payments/options` | GET |
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

## Carrinhos

`POST /internal/carts` recebe `product_id`, `quantity`, `price`, `session_id` obrigatório e, opcionalmente, `variant_id`. O Adapter envia esses campos no objeto oficial `Cart` sem calcular preço, disponibilidade ou variante. Por segurança contra duplicação, a escrita não é repetida automaticamente após falha de autenticação ou erro upstream.

`GET /internal/carts/{session_id}` consulta o carrinho simples. `GET /internal/carts/{session_id}/complete` preserva itens, preços, quantidades, estoque, disponibilidade, imagens e totais informados pela Tray.

Antes do primeiro item, o NSAgent cria e persiste uma `session_id` estável de carrinho. Todos os itens do mesmo carrinho reutilizam essa sessão. O Adapter exige e apenas transporta esse identificador; ele não gera sessões nem combina itens localmente.

## Imagens e opções de pagamento

Produtos e variantes preservam as imagens retornadas pela Tray, priorizando URLs HTTPS. O contrato normalizado contém `images` e `primary_image_url`; nenhuma URL é construída pelo Adapter.

`GET /internal/payments/options?cart_session_id=...` consulta opções do carrinho e preserva valores, descontos, acréscimos, impostos e parcelas fornecidos pela Tray. Não há endpoint de criação de pagamento e nenhum dado de cartão é recebido.
