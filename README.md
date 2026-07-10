# INLABS API

API intermediária que faz o trabalho frágil (login no INLABS, download do DOU,
unzip e parse do XML) a partir de um **IP dedicado**, devolvendo JSON pronto para
o Google Apps Script consumir. Resolve o bloqueio `#01` que acontece quando o
Apps Script bate no INLABS pelos IPs compartilhados do Google.

## Por que isso mitiga o rate limit

- **IP dedicado** (a VM/Railway) em vez dos IPs compartilhados do Google.
- **Sessão logada reaproveitada** por `SESSION_TTL_MIN` — não faz login por request.
- **Cache por edição em SQLite** (persistido no volume), baseado na cadência real do DOU:
  - **DO1** sai 1x por dia útil, de manhã, e não muda depois → edição passada é
    cacheada **para sempre**; DO1 de hoje já baixada fica estável por 6h.
  - **DO1E** (extra) é irregular e pode surgir/crescer no dia → cache de 1h.
  - DO1 de hoje ainda não publicada → retry curto de 20min.
- **Detecção de bloqueio**: ao ver `#01`, a API para de tocar no INLABS por
  `BLOCK_BACKOFF_MIN` e passa a servir o último cache conhecido (stale).

## Endpoints

Todos (exceto `/health` e `/`) exigem o header `X-API-Key`.

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Healthcheck (sem auth). |
| GET | `/federal` | Hoje + ontem, todas as seções. **É o que o Apps Script chama.** |
| GET | `/norms?date=YYYY-MM-DD&sections=DO1,DO1E` | Data/seções específicas. |

Resposta (`/federal`):

```json
{
  "status": "ok",            // ok | degraded | blocked
  "generatedAt": "2026-07-09T22:00:00+00:00",
  "count": 42,
  "sections": [{"date":"2026-07-09","secao":"DO1","count":40,"cached":true}],
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

## Variáveis de ambiente

Ver `.env.example`. As obrigatórias: `INLABS_EMAIL`, `INLABS_PASSWORD`, `API_KEY`.

## Deploy no Railway

1. Suba este diretório para um repositório Git e conecte no Railway (New Project → Deploy from repo).
2. Em **Variables**, defina `INLABS_EMAIL`, `INLABS_PASSWORD`, `API_KEY`, e `DATA_DIR=/data`.
3. Crie um **Volume** e monte no caminho **`/data`** — é onde o SQLite persiste (`/data/inlabs.db`),
   sobrevivendo a redeploys. (Sem volume, o cache ainda funciona, mas zera a cada deploy.)
4. O Railway detecta Python pelo `.python-version`/`requirements.txt` e usa o `Procfile`
   (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`). Nada mais a configurar.

## Rodar local

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
INLABS_EMAIL=... INLABS_PASSWORD=... API_KEY=secret .venv/Scripts/uvicorn app.main:app --reload
```

## Ligar no Apps Script

Substitua a função `collectFederalFromInlabs_` do projeto Apps Script por esta —
o resto do pipeline (filtros, dedup, Chat, planilha) continua igual. As credenciais
do INLABS saem do Apps Script e passam a viver só na API.

```javascript
function collectFederalFromInlabs_(config) {
  var props = PropertiesService.getScriptProperties();
  var base = (props.getProperty('FEDERAL_API_URL') || '').replace(/\/$/, '');
  var key = props.getProperty('FEDERAL_API_KEY') || '';
  if (!base) {
    Logger.log('FEDERAL_API_URL não configurada — eixo federal ignorado.');
    return [];
  }

  var resp = UrlFetchApp.fetch(base + '/federal', {
    method: 'get',
    muteHttpExceptions: true,
    headers: key ? { 'X-API-Key': key } : {}
  });

  var code = resp.getResponseCode();
  if (code !== 200) {
    throw new Error('API federal HTTP ' + code + ': ' + resp.getContentText().slice(0, 200));
  }

  var data = JSON.parse(resp.getContentText());
  if (data.status === 'blocked') {
    // Reaproveita a supressão de alerta de manutenção (1x a cada 6h).
    throw inlabsMaintenanceError_();
  }

  return (data.items || []).map(function (it) {
    it.publishedAt = it.publishedIso ? new Date(it.publishedIso) : null;
    return it;
  });
}
```

Configure nas **Propriedades do Script**: `FEDERAL_API_URL` (ex.: `https://seu-app.up.railway.app`)
e `FEDERAL_API_KEY` (o mesmo valor do `API_KEY` da API). `INLABS_EMAIL`/`INLABS_PASSWORD`
podem ser removidas do Apps Script.
