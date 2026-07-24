# TrayAdapter

Serviço FastAPI independente para comunicação com a API da Tray. Nesta etapa ele não se conecta diretamente ao NSAgent, backend ou frontend e não cria pedidos nem executa cobranças.

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

`TRAY_API_BASE` já é o endereço completo da API (incluindo `/web_api`); o cliente não acrescenta esse segmento novamente. Tokens ficam em memória e são reutilizados enquanto válidos. Requisições idempotentes podem receber uma tentativa única de refresh após HTTP 401; o POST de carrinho usa reconciliação antes de qualquer nova tentativa.

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
| Métodos de pagamento ativos | `GET /internal/payments/methods/active` |
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
| Auth | `/auth` | POST auth e GET refresh |
| Products | `/products`, `/products/{id}` | GET, POST, PUT, DELETE |
| Product variants | `/products/variants/`, `/products/variants/{id}` | GET |
| Categories | `/categories/`, `/categories/{id}`, `/categories/tree/{id}` | GET |
| Carts | `/carts`, `/carts/{session_id}` | POST, GET |
| Complete cart | `/carts/{session_id}/complete` | GET |
| Payment options | `/payments/options` | GET |
| Active payment methods | `/payments/methods/1/active` | GET |
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

`POST /internal/carts` recebe `product_id`, `quantity`, `price`, `session_id` obrigatório e, opcionalmente, `variant_id`. O Adapter envia JSON com wrapper `Cart`, IDs e quantidade numéricos e preço decimal, sem calcular preço ou escolher variante. Quando há variante, confirma antes que ela pertence ao produto. Em uma resposta 401, atualiza o token e reconcilia a sessão; em timeout, conexão interrompida ou resposta ambígua, reconcilia antes de qualquer nova tentativa. O POST é repetido no máximo uma vez e somente quando o item ainda não existe.

`GET /internal/carts/{session_id}` consulta o carrinho simples. `GET /internal/carts/{session_id}/complete` preserva itens, preços, quantidades, estoque, disponibilidade, imagens e totais informados pela Tray.

Antes do primeiro item, o NSAgent cria e persiste uma `session_id` estável de carrinho. Todos os itens do mesmo carrinho reutilizam essa sessão. O Adapter exige e apenas transporta esse identificador; ele não gera sessões nem combina itens localmente.

Erros da API Tray mantêm `success`, `error` e `status_code` e acrescentam, quando disponíveis, `tray_error_code`, `tray_error_type`, `tray_error_field`, `tray_error_fields` e `tray_error_message`. Apenas diagnósticos sanitizados são devolvidos; tokens, credenciais, URLs de erro e payloads completos não são expostos.

## Imagens e opções de pagamento

Produtos e variantes preservam as imagens retornadas pela Tray, priorizando URLs HTTPS. A URL oficial do produto também é normalizada para uma string, priorizando `url.https` e depois `url.http`. O contrato contém `url`, `images` e `primary_image_url`; nenhuma URL é construída pelo Adapter.

`GET /internal/payments/methods/active` consulta os métodos ativos da loja. `GET /internal/payments/options?cart_session_id=...` consulta opções do carrinho e preserva identificadores, códigos de integração, valores, descontos, acréscimos, impostos e parcelas fornecidos pela Tray. Essas consultas não executam cobrança. Não há endpoint interno de criação de pedido ou pagamento e nenhum dado de cartão é recebido.
