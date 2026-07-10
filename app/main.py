"""API HTTP (FastAPI). Endpoints consumidos pelo Apps Script."""
import logging
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .config import settings
from .service import get_federal, get_norms

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="INLABS API", version="1.0.0")


def _valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


@app.on_event("startup")
def _warn_open_api():
    if not settings.api_key:
        log.warning("API_KEY não configurada — a API está ABERTA. Defina API_KEY no ambiente.")
    if not settings.inlabs_email or not settings.inlabs_password:
        log.warning("INLABS_EMAIL/INLABS_PASSWORD ausentes — o eixo federal não vai autenticar.")


def require_key(x_api_key: str = Header(default=None)):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Chave de API inválida.")


@app.get("/")
def root():
    return {
        "service": "inlabs-api",
        "endpoints": ["/health", "/federal", "/norms?date=YYYY-MM-DD&sections=DO1,DO1E"],
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/federal", dependencies=[Depends(require_key)])
def federal():
    """Hoje + ontem, todas as seções configuradas. É o que o Apps Script chama."""
    return get_federal()


@app.get("/norms", dependencies=[Depends(require_key)])
def norms(
    date: str = Query(..., description="Data no formato YYYY-MM-DD"),
    sections: str = Query(default=None, description="Ex.: DO1,DO1E"),
):
    if not _valid_date(date):
        raise HTTPException(status_code=400, detail="date deve ser uma data válida YYYY-MM-DD.")
    secs = [s.strip() for s in sections.split(",")] if sections else settings.sections
    secs = [s for s in secs if s]
    if not secs:
        raise HTTPException(status_code=400, detail="Nenhuma seção válida.")
    return get_norms(date, secs)
