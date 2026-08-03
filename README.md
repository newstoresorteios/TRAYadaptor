# TrayAdapter

Serviço FastAPI independente para comunicação com a API da Tray. Nesta etapa ele não se conecta diretamente ao NSAgent, backend ou frontend. O Adapter calcula frete, consulta formas de envio e cria, consulta e atualiza dados de envio de pedidos, mas não executa cobranças.

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
| Produtos | `GET /internal/products`, `GET /internal/products/search`, `GET /internal/products/{id}`, `GET /internal/products/{id}/stock` |
| Variantes de produto | `GET /internal/products/variants`, `GET /internal/products/variants/{id}` |
| Categorias | `GET /internal/categories`, `GET /internal/categories/{id}`, `GET /internal/categories/tree/{id}` |
| Carrinhos | `POST /internal/carts`, `PUT /internal/carts/{session_id}/items`, `GET /internal/carts/{session_id}` |
| Carrinho completo | `GET /internal/carts/{session_id}/complete` |
| Opções de pagamento | `GET /internal/payments/options?cart_session_id=...` ou `?order_id=...` |
| Métodos de pagamento ativos | `GET /internal/payments/methods/active` |
| Frete | `POST /internal/shippings/quote`, `GET /internal/shippings/methods` |
| Pedidos | `POST /internal/orders`, `GET /internal/orders`, `GET /internal/orders/{id}` |
| Pedido completo | `GET /internal/orders/{id}/complete` |
| Pagamento do pedido | `GET /internal/orders/{id}/payment` |
| Envio/rastreio | `PUT /internal/orders/{id}/shipping` |
| Marcas | `GET /internal/brands`, `GET /internal/brands/{id}` |
| Kits | `GET /internal/kits` |
| MultiCD | `GET /internal/inventory/distribution-centers`, `GET /internal/inventory/distribution-centers/{id}`, `GET /internal/inventory/products/{id}/distribution-centers` |
| Clientes | `GET /internal/customers`, `GET /internal/customers/{id}` |
| Endereços | `GET /internal/customer-addresses`, `GET /internal/customer-addresses/{id}` |
| Cupons | `GET /internal/coupons`, `GET /internal/coupons/{id}`, além das seis rotas de relacionamentos por tipo |
| Usuários | `GET /internal/users` |

As rotas internas são majoritariamente de leitura. As mutações expostas nesta etapa são `POST /internal/carts`, `PUT /internal/carts/{session_id}/items`, `POST /internal/orders` e o PUT restrito aos campos de envio/rastreio. As demais operações POST/PUT/DELETE disponíveis nos resources/client continuam sem rotas de execução automática.

## APIs Tray implementadas

| Resource | Endpoint Tray | Métodos |
|---|---|---|
| Auth | `/auth` | POST auth e GET refresh |
| Products | `/products`, `/products/{id}` | GET, POST, PUT, DELETE |
| Product variants | `/products/variants/`, `/products/variants/{id}` | GET |
| Categories | `/categories/`, `/categories/{id}`, `/categories/tree/{id}` | GET |
| Carts | `/carts`, `/carts/{session_id}` | POST, GET e PUT de quantidade absoluta |
| Complete cart | `/carts/{session_id}/complete` | GET |
| Payment options | `/payments/options` | GET |
| Active payment methods | `/payments/methods/1/active` | GET |
| Shipping quote | `/shippings/cotation/` | GET |
| Shipping methods | `/shippings/` | GET |
| Orders | `/orders`, `/orders/{id}` | GET, POST e PUT restrito a envio |
| Complete order | `/orders/{id}/full`, fallback `/orders/{id}/complete` | GET |
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

`POST /internal/carts` recebe `product_id`, `quantity`, `price`, `session_id` obrigatório e, opcionalmente, `variant_id`. O campo `price` permanece no contrato interno por compatibilidade, mas não é encaminhado à Tray: a loja determina o preço a partir do produto e da variante. O Adapter envia JSON com wrapper `Cart`, IDs e quantidade numéricos, sem calcular preço ou escolher variante. Quando há variante, confirma antes que ela pertence ao produto. Em uma resposta 401, atualiza o token e reconcilia a sessão; em timeout, conexão interrompida ou resposta ambígua, reconcilia antes de qualquer nova tentativa. O POST é repetido no máximo uma vez e somente quando o item ainda não existe.

`GET /internal/carts/{session_id}` consulta o carrinho simples. `GET /internal/carts/{session_id}/complete` preserva itens, preços, quantidades, estoque, disponibilidade, imagens e totais informados pela Tray.

`PUT /internal/carts/{session_id}/items` define a quantidade absoluta de um item já existente, identificado pelo par factual `product_id` e `variant_id`. O body recebe somente esses identificadores e `quantity >= 1`; não recebe preço. Antes do PUT em `/carts/{session_id}`, o Adapter consulta o carrinho completo e não escreve quando a quantidade já está correta. Depois de qualquer PUT bem-sucedido ou ambíguo, consulta novamente o carrinho completo e só confirma sucesso quando a quantidade factual coincide. A operação não adiciona item ausente e não remove item com `quantity=0`.

Antes do primeiro item, o NSAgent cria e persiste uma `session_id` estável de carrinho. Todos os itens do mesmo carrinho reutilizam essa sessão. O Adapter exige e apenas transporta esse identificador; ele não gera sessões nem combina itens localmente.

Erros da API Tray mantêm `success`, `error` e `status_code` e acrescentam, quando disponíveis, `tray_error_code`, `tray_error_type`, `tray_error_field`, `tray_error_fields` e `tray_error_message`. Apenas diagnósticos sanitizados são devolvidos; tokens, credenciais, URLs de erro e payloads completos não são expostos.

## Frete e pedidos

`POST /internal/shippings/quote` recebe CEP e uma lista JSON simples de produtos. O CEP é reduzido a oito dígitos e o resource traduz os itens para `products[n][product_id]`, `price`, `quantity` e `sku` somente quando existe variante. A resposta preserva opções factuais, valores e prazos sem selecionar ou descrever comercialmente uma alternativa. `GET /internal/shippings/methods` apenas consulta os métodos e aceita filtro de status.

`POST /internal/orders` recebe sessão, escolha factual de frete e pagamento, cliente, endereço e produtos. O resource envia `Order`, com `point_sale=PARTICULAR`, `Customer.CustomerAddress` e `ProductsSold`; opcionais ausentes e `variant_id` inexistente não são enviados. `payment_form` recebe o nome factual informado no contrato interno, sem processar pagamento. `shipment` e `shipment_value` recebem diretamente a escolha de frete, sem recotação.

O POST de pedido desativa o retry automático. Em timeout, reset, resposta inválida ou redirect ambíguo, consulta `GET /orders?session_id=...`; se encontrar o pedido, não repete o POST. Caso contrário, permite uma única nova tentativa e, se ela também for ambígua, faz somente uma reconciliação final. Nunca há terceiro POST.

O endpoint interno de pedido completo permanece `/internal/orders/{id}/complete`. No upstream, usa primeiro `/orders/{id}/full` e tenta o legado `/orders/{id}/complete` somente para 404 ou 405. A atualização de envio aceita apenas `status_id`, `shipment`, `shipment_value`, `sending_code`, `sending_date` e `tracking_url`, enviando somente os campos presentes.

`GET /internal/orders/{id}/payment` reutiliza a mesma consulta completa e extrai apenas fatos financeiros. `payment_url` usa primeiro `Order.urls.payment` e, na ausência, uma URL válida de `OrderTransactions[].url_payment`. A URL nunca é construída com `order_id`, `access_code`, sessão, token ou hash. `payments_notification.notification` é callback técnico e não é tratado como link para o cliente. O indicador de pagamento confirmado é `has_payment`; a simples existência de um pedido ou de registros em `Payment` não confirma pagamento.

Shipping label, cancelamento, criação de transportadora, configuração de gateway de frete e processamento de Pix, boleto ou cartão continuam fora do escopo.

## Imagens e opções de pagamento

Produtos e variantes preservam as imagens retornadas pela Tray, priorizando URLs HTTPS. A URL oficial do produto também é normalizada para uma string, priorizando `url.https` e depois `url.http`. O contrato contém `url`, `images` e `primary_image_url`; nenhuma URL é construída pelo Adapter.

`GET /internal/payments/methods/active` consulta os métodos ativos da loja. `GET /internal/payments/options` exige exatamente um entre `cart_session_id` e `order_id`, consultando as opções factuais do carrinho ou do pedido e preservando identificadores, códigos de integração, valores, descontos, acréscimos, impostos e parcelas fornecidos pela Tray. Essas consultas não executam cobrança. A criação do pedido apenas registra `payment_form`; não existe endpoint interno de pagamento e nenhum dado de cartão é recebido.

As capacidades são separadas em três níveis:

- métodos ativos configurados na loja;
- condições e opções disponíveis para um carrinho ou pedido;
- iniciação ou processamento de cobrança.

Os dois primeiros níveis são consultas e não provam o terceiro. A documentação oficial da Tray descreve `POST /payments` como cadastro de um pagamento do pedido, recebendo método, valor pago, data e observação. Ela não documenta esse POST como geração de Pix ou boleto, captura de cartão ou solicitação ao gateway. Por isso o Adapter não expõe essa operação e mantém `native_pix_available`, `native_boleto_available` e `native_card_available` como `false`. Cartão deve permanecer no checkout hospedado ou mecanismo oficial indicado por uma URL retornada pela Tray; o Adapter não recebe PAN, CVV ou outros dados de cartão.
