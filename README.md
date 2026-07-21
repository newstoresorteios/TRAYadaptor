# TrayAdapter

Serviço FastAPI independente para autenticar na API da Tray e consultar produtos. Nesta etapa não há integração com NSAgent, backend, frontend ou outros domínios.

## Executar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Configure no ambiente as cinco credenciais e `TRAY_STORE_CODE`; `TRAY_COUPON_VALID_DAYS` usa 180 por padrão. Nunca comite valores reais.

## Rotas

- `GET /health` — health check local, sem chamar a Tray.
- `GET /tray/test-auth` — autentica e valida a loja sem expor tokens.
- `GET /tray/test-products` — consulta no máximo um produto e retorna um resumo.
- `GET /internal/products?name=Relogio&limit=10` — proxy controlado com produtos normalizados.

A autenticação é mantida em memória e reutiliza o token; respostas 401/403 tentam refresh uma única vez. O `render.yaml` contém o comando de build e start do Web Service.

## Testes

```bash
pytest
python -m compileall app tests
```
