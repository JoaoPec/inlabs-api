"""Configuração via variáveis de ambiente (Railway → Variables)."""
import os


def _load_dotenv(path=".env"):
    """Carrega .env local sem dependência externa. Variáveis reais do ambiente
    (ex.: as do Railway) têm prioridade — só preenche o que ainda não existe."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings:
    # Credenciais INLABS — ficam SÓ no ambiente, nunca no código.
    inlabs_email = os.getenv("INLABS_EMAIL", "").strip()
    inlabs_password = os.getenv("INLABS_PASSWORD", "")

    # Chave que o Apps Script envia no header X-API-Key. Se vazia, a API fica aberta (não recomendado).
    api_key = os.getenv("API_KEY", "").strip()

    # Seções federais coletadas (DO1 = atos normativos; DO1E = edição extra).
    sections = [s.strip() for s in os.getenv("SECTIONS", "DO1,DO1E").split(",") if s.strip()]

    # Fuso para determinar "hoje"/"ontem" (DOU é Brasília).
    tz = os.getenv("TZ", "America/Sao_Paulo")

    # Diretório de dados (SQLite). No Railway, monte um Volume em /data e use DATA_DIR=/data.
    data_dir = os.getenv("DATA_DIR", "./data")
    db_path = os.getenv("DB_PATH", os.path.join(data_dir, "inlabs.db"))

    # Reaproveita a sessão logada por N minutos antes de relogar (menos batidas no login).
    session_ttl_min = _int("SESSION_TTL_MIN", 30)

    # Ao detectar bloqueio (#01), para de tocar no INLABS por N minutos e serve cache.
    block_backoff_min = _int("BLOCK_BACKOFF_MIN", 120)


settings = Settings()
