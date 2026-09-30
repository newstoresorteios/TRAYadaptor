# Consulta pública de pronta entrega

`GET /internal/ready-delivery?query=...` requer o mesmo Bearer interno dos demais contratos.
Query: texto entre 1 e 500 caracteres. Fonte fixa: `https://www.newstorerj.com/pronta-entrega`.

Retorno: `success`, `complete`, `checkedAt`, `source`, `products` (nome, referência, URL e `listedAvailable`), `requiresModel`, `evidenceType=public_listing`, `stockConfirmed=false`.
Não retorna IDs utilizáveis no catálogo administrativo `.com.br`, nem confirma estoque físico ou valores.

Consulta até 20 páginas, com concorrência 3, timeout 8s por página e 20s total. Falha ou HTML inválido produz HTTP 503 `ready_delivery_unavailable`, nunca lista vazia como se fosse consulta completa. Não aceita host arbitrário nem segue redirects.

Publicar este adaptador antes da versão do NSAgent que consome o contrato. O NSAgent responde indisponibilidade de consulta se o endpoint ainda não estiver publicado.
