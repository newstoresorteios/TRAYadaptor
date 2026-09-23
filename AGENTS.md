# Integração Tray

Estas instruções se aplicam a qualquer alteração neste repositório.

## Fonte de verdade

- Antes de alterar autenticação, endpoints, parâmetros, payloads, webhooks ou normalizadores da Tray, use primeiro a skill `tray-visao-geral` e depois a skill específica do recurso.
- Consulte obrigatoriamente a documentação atual pelo MCP `tray-docs`, usando `tray.search_docs` com o tópico correspondente.
- Trate o resultado da documentação oficial como fonte primária. Os textos e schemas estáticos das skills são auxiliares e podem estar desatualizados.
- Quando houver schema compatível, execute também `tray.validate`, mas confronte o resultado com a documentação atual.

## Limites arquiteturais

- Este serviço é a única fronteira autorizada a chamar a API REST administrativa da Tray.
- Nunca exponha `access_token`, `refresh_token`, `consumer_key`, `consumer_secret`, `code` OAuth ou a URL administrativa completa nas respostas internas, logs ou testes.
- Preserve os contratos normalizados de `/internal/*`; não repasse envelopes ou erros brutos da Tray ao NSAgent.
- Preserve idempotência e reconciliação de mutações. Não adicione retry cego a POST, PUT ou DELETE.
- Preserve o limite máximo de 50 itens por página e o controle centralizado de rate limit e refresh de token.

## Validação

- Para toda mudança de contrato, atualize testes de rota, payload upstream e normalização de resposta.
- Antes de concluir, compare o método e caminho upstream com `tray.search_docs` e execute os testes específicos do recurso.
- Se a documentação oficial e uma skill divergirem, documente a divergência no teste e siga a documentação oficial validada.
