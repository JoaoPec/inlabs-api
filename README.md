# INLABS API

API HTTP que expõe os atos normativos do **Diário Oficial da União (DOU)** como
JSON limpo. Ela faz o trabalho chato — autenticar no [INLABS](https://inlabs.in.gov.br),
baixar o pacote do dia, descompactar e parsear os XMLs — e devolve os itens já
normalizados, prontos para qualquer cliente consumir (integrações, bots, planilhas,
pipelines de dados, etc.).

O ganho principal é rodar isso a partir de **um IP dedicado e estável**, com cache,
em vez de cada cliente bater direto no INLABS (o que costuma levar a bloqueios por
excesso de requisições).

## Como funciona

- **Login com sessão reaproveitada** por `SESSION_TTL_MIN` — não autentica a cada request.
- **Cache por edição em SQLite** (persistido em disco/volume), com TTL baseado na
  cadência real do DOU:
  - **DO1** (Seção 1) sai 1x por dia útil, de manhã, e não muda depois → edição
    passada é cacheada **para sempre**; a de hoje, já publicada, fica estável por 6h.
  - **DO1E** (edição extra) é irregular e pode surgir/crescer no dia → cache de 1h.
  - DO1 de hoje ainda não publicada → novo retry em 20min.
- **Proteção contra bloqueio**: ao detectar bloqueio temporário do INLABS, a API
  para de tocar nele por `BLOCK_BACKOFF_MIN` e passa a servir o último cache conhecido.

## Endpoints

Todos, exceto `/health` e `/`, exigem o header `X-API-Key` (quando `API_KEY` está definida).

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Healthcheck (sem auth). |
| GET | `/federal` | Itens de hoje + ontem, todas as seções configuradas. |
| GET | `/norms?date=YYYY-MM-DD&sections=DO1,DO1E` | Data e seções específicas. |

### Exemplo

```bash
curl -H "X-API-Key: SUA_CHAVE" https://SEU-HOST/federal
```

### Formato da resposta

```json
{
  "status": "ok",            // ok | degraded | blocked
  "generatedAt": "2026-07-09T22:00:00+00:00",
  "count": 42,
  "sections": [{"date": "2026-07-09", "secao": "DO1", "count": 40, "cached": true}],
  "blockedUntil": null,
  "items": [
    {
      "source": "INLABS",
      "externalId": "PRT456.xml@2026-07-09",
      "fileName": "PRT456.xml",
      "title": "PORTARIA RFB Nº 456, DE 9 DE JULHO DE 2026",
      "subtitle": "",
      "ementa": "Dispõe sobre despacho aduaneiro e a DUIMP...",
      "orgao": "Ministério da Fazenda/Receita Federal do Brasil",
      "textoResumo": "O SECRETÁRIO da Receita Federal resolve...",
      "link": "https://www.in.gov.br/web/dou/-/portaria-rfb-no-456-de-2026",
      "publishedAt": "2026-07-09T00:00:00",
      "publishedIso": "2026-07-09T00:00:00",
      "secao": "DO1",
      "editionDate": "2026-07-09"
    }
  ]
}
```

Campo `status`:
- `ok` — dados atuais do INLABS (ou cache válido).
- `degraded` — INLABS indisponível/bloqueado; servindo cache anterior.
- `blocked` — INLABS bloqueado e sem cache para servir.

## Variáveis de ambiente

Veja `.env.example`. Obrigatórias: `INLABS_EMAIL`, `INLABS_PASSWORD`, `API_KEY`.

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `INLABS_EMAIL` | — | E-mail da conta INLABS. |
| `INLABS_PASSWORD` | — | Senha da conta INLABS. |
| `API_KEY` | — | Chave exigida no header `X-API-Key`. Se vazia, a API fica aberta. |
| `DATA_DIR` | `./data` | Diretório do banco SQLite. |
| `SECTIONS` | `DO1,DO1E` | Seções coletadas. |
| `TZ` | `America/Sao_Paulo` | Fuso para determinar "hoje"/"ontem". |
| `SESSION_TTL_MIN` | `30` | Minutos que a sessão logada é reaproveitada. |
| `BLOCK_BACKOFF_MIN` | `120` | Minutos de pausa ao detectar bloqueio. |

> As credenciais do INLABS ficam **somente no ambiente**, nunca no código.

## Rodar localmente

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/Mac: .venv/bin/pip
cp .env.example .env                              # e preencha os valores
.venv/Scripts/uvicorn app.main:app --reload      # Linux/Mac: .venv/bin/uvicorn
```

Docs interativas (Swagger UI) em `http://127.0.0.1:8000/docs`.

## Deploy

A aplicação é um serviço ASGI padrão (`app.main:app`), sem dependências além das do
`requirements.txt`. Funciona em qualquer plataforma que rode Python.

Comando de start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Para o cache persistir entre reinícios/deploys, aponte `DATA_DIR` para um diretório
persistente (um volume). Sem isso, o cache ainda funciona, mas zera a cada deploy.

## Stack

FastAPI · Uvicorn · Requests · SQLite (stdlib). Python 3.12+.
