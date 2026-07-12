# INLABS API

API HTTP que busca atos normativos do Diário Oficial da União (DOU) via INLABS e devolve JSON limpo. Faz autenticação, download dos ZIPs, parse dos XMLs e cache em SQLite.

## Rodar na máquina (desenvolvimento)

```bash
# 1. Clone o repo
git clone <repo-url>
cd inlabs-api

# 2. Crie o ambiente virtual (Python 3.12+)
python -m venv .venv

# 3. Ative o venv e instale as dependências
# Linux/Mac:
.venv/bin/pip install -r requirements.txt
# Windows:
.venv\Scripts\pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas credenciais INLABS e defina uma API_KEY
nano .env   # ou use o bloco de notas

# 5. Rode o servidor
# Linux/Mac:
.venv/bin/uvicorn app.main:app --reload
# Windows:
.venv\Scripts\uvicorn app.main:app --reload

# API disponível em http://127.0.0.1:8000
# Swagger em http://127.0.0.1:8000/docs
```

## Subir no servidor (VPS / produção)

### 1. Preparação

```bash
# Na VPS, clone o repo em /opt
cd /opt
git clone <repo-url> inlabs-api
cd inlabs-api

# Crie o venv e instale
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Configure o .env
cp .env.example .env
nano .env   # preencha INLABS_EMAIL, INLABS_PASSWORD e API_KEY
```

### 2. Serviço systemd (roda em background, reinicia sozinho)

Crie o arquivo `/etc/systemd/system/inlabs-api.service`:

```ini
[Unit]
Description=INLABS API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/inlabs-api
EnvironmentFile=/opt/inlabs-api/.env
ExecStart=/opt/inlabs-api/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now inlabs-api

# Verificar se está rodando
sudo systemctl status inlabs-api
curl http://127.0.0.1:8000/health
```

### 3. Nginx reverso (HTTPS + domínio)

```nginx
server {
    listen 80;
    server_name api.seudominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/inlabs-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS com Certbot (Let's Encrypt)
sudo certbot --nginx -d api.seudominio.com
```

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `INLABS_EMAIL` | Sim | — | E-mail da conta INLABS |
| `INLABS_PASSWORD` | Sim | — | Senha da conta INLABS |
| `API_KEY` | Sim | — | Chave que os clientes enviam no header `X-API-Key` |
| `DATA_DIR` | Não | `./data` | Pasta do banco SQLite |
| `SECTIONS` | Não | `DO1,DO1E` | Seções do DOU monitoradas |
| `TZ` | Não | `America/Sao_Paulo` | Fuso horário |
| `SESSION_TTL_MIN` | Não | `30` | Minutos reaproveitando a sessão logada |
| `BLOCK_BACKOFF_MIN` | Não | `120` | Minutos de pausa ao detectar bloqueio do INLABS |

## Endpoints

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `GET` | `/` | Não | Info do serviço |
| `GET` | `/health` | Não | Healthcheck |
| `GET` | `/federal` | `X-API-Key` | Hoje + ontem, todas as seções configuradas |
| `GET` | `/norms?date=YYYY-MM-DD&sections=DO1,DO1E` | `X-API-Key` | Data e seções específicas |

## Como integrar (consumir a API)

Toda chamada que retorna dados exige o header `X-API-Key` com o valor definido no `.env`.

### curl

```bash
# Healthcheck (aberto)
curl https://api.seudominio.com/health

# Buscar itens de hoje + ontem (autenticado)
curl -H "X-API-Key: sua-chave" https://api.seudominio.com/federal

# Buscar data específica
curl -H "X-API-Key: sua-chave" "https://api.seudominio.com/norms?date=2026-07-10&sections=DO1,DO1E"
```

### Python

```python
import requests

resp = requests.get(
    "https://api.seudominio.com/federal",
    headers={"X-API-Key": "sua-chave"}
)
data = resp.json()
print(f"Status: {data['status']} — {data['count']} itens")
for item in data["items"]:
    print(item["title"], item["link"])
```

### Google Apps Script

```javascript
function buscarDou() {
  var url = "https://api.seudominio.com/federal";
  var options = {
    headers: { "X-API-Key": "sua-chave" },
    muteHttpExceptions: true
  };
  var resp = UrlFetchApp.fetch(url, options);
  var data = JSON.parse(resp.getContentText());
  // data.items contém o array de atos normativos
  return data.items;
}
```

## Formato da resposta

```json
{
  "status": "ok",
  "generatedAt": "2026-07-10T14:00:00+00:00",
  "count": 42,
  "sections": [
    {"date": "2026-07-10", "secao": "DO1", "count": 40, "cached": false}
  ],
  "items": [
    {
      "source": "INLABS",
      "externalId": "PRT456.xml@2026-07-10",
      "fileName": "PRT456.xml",
      "title": "PORTARIA Nº 456, DE 10 DE JULHO DE 2026",
      "subtitle": "",
      "ementa": "Dispõe sobre...",
      "orgao": "Ministério da Fazenda",
      "textoResumo": "O SECRETÁRIO...",
      "link": "https://www.in.gov.br/web/dou/-/portaria-456",
      "publishedAt": "2026-07-10T00:00:00",
      "publishedIso": "2026-07-10T00:00:00",
      "secao": "DO1",
      "editionDate": "2026-07-10"
    }
  ]
}
```

**Status possíveis:**
- `ok` — dados atualizados do INLABS ou cache válido
- `degraded` — INLABS indisponível/bloqueado, servindo cache do dia anterior
- `blocked` — INLABS bloqueado e sem cache para servir
