"""Cliente INLABS: login (com cache de sessão), download e unzip.

Estratégias anti-rate-limit implementadas aqui:
  * Uma sessão logada é reaproveitada por SESSION_TTL_MIN — não faz login por request.
  * Login é serializado por lock (requisições concorrentes não disparam N logins).
  * Ao detectar o bloqueio #01, marca `blocked_until` e para de tocar no INLABS
    por BLOCK_BACKOFF_MIN, deixando a camada de serviço servir cache.
"""
import io
import logging
import re
import threading
import time
import zipfile

import requests

from .config import settings
from .parser import parse_article_xml

LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
ACESSAR_URL = "https://inlabs.in.gov.br/acessar.php"
DOWNLOAD_BASE = "https://inlabs.in.gov.br/index.php?p="
ORIGEM = "736372697074"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

log = logging.getLogger("inlabs")


class InlabsBlocked(Exception):
    """INLABS respondeu com bloqueio temporário (#01 / tente mais tarde)."""


class InlabsMaintenance(Exception):
    """INLABS em manutenção programada."""


class InlabsAuthError(Exception):
    """Login não produziu inlabs_session_cookie (credencial ou sessão inválida)."""


def _is_maintenance(text):
    t = (text or "").lower()
    return (
        "manutenção programada" in t
        or "manutencao programada" in t
        or "sistema em manuten" in t
        or ("inlabs" in t and "tente novamente mais tarde" in t)
    )


def _is_rate_limit(text):
    return bool(re.search(r"tente mais tarde|#\s*01", text or "", re.I))


class InlabsClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._session = None
        self._session_ts = 0.0
        self.blocked_until = 0.0

    # -- login ----------------------------------------------------------------
    def _login(self):
        email = settings.inlabs_email
        password = (settings.inlabs_password or "").strip()
        if not email or not password:
            raise InlabsAuthError("INLABS_EMAIL/INLABS_PASSWORD não configurados no ambiente.")

        session = requests.Session()
        session.headers.update({
            "Origem": ORIGEM,
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9",
        })

        for attempt in range(2):
            if attempt == 1:
                # warmup: abre acessar.php antes do POST (fluxo de navegador)
                try:
                    session.get(ACESSAR_URL, timeout=30)
                except requests.RequestException:
                    pass
            resp = session.post(
                LOGIN_URL,
                data={"email": email, "password": password},
                timeout=30,
                allow_redirects=True,
            )
            body = resp.text or ""
            if _is_maintenance(body):
                raise InlabsMaintenance()
            if _is_rate_limit(body):
                raise InlabsBlocked()
            if session.cookies.get("inlabs_session_cookie"):
                log.info("Login INLABS OK (tentativa %s).", attempt + 1)
                return session

        raise InlabsAuthError("Login sem inlabs_session_cookie (e-mail/senha ou bloqueio silencioso).")

    def _get_session(self):
        now = time.time()
        if self.blocked_until > now:
            raise InlabsBlocked()
        if self._session is not None and (now - self._session_ts) < settings.session_ttl_min * 60:
            return self._session
        with self._lock:
            now = time.time()
            if self.blocked_until > now:
                raise InlabsBlocked()
            if self._session is not None and (now - self._session_ts) < settings.session_ttl_min * 60:
                return self._session
            try:
                self._session = self._login()
                self._session_ts = time.time()
                return self._session
            except InlabsBlocked:
                self.blocked_until = time.time() + settings.block_backoff_min * 60
                log.warning("INLABS bloqueou (#01). Pausando por %s min.", settings.block_backoff_min)
                raise

    # -- download -------------------------------------------------------------
    def _download(self, session, date_iso, secao):
        url = "%s%s&dl=%s-%s.zip" % (DOWNLOAD_BASE, date_iso, date_iso, secao)
        resp = session.get(url, timeout=90)
        if resp.status_code != 200:
            log.info("INLABS %s-%s indisponível (HTTP %s).", date_iso, secao, resp.status_code)
            return None
        content = resp.content or b""
        if content[:2] == b"PK":
            return content
        text = content.decode("utf-8", "ignore")
        if _is_maintenance(text):
            raise InlabsMaintenance()
        if _is_rate_limit(text):
            self.blocked_until = time.time() + settings.block_backoff_min * 60
            raise InlabsBlocked()
        # Não é ZIP nem manutenção → sessão provavelmente expirou.
        raise InlabsAuthError("download não retornou ZIP (sessão expirada?)")

    def download_zip(self, date_iso, secao):
        try:
            session = self._get_session()
            return self._download(session, date_iso, secao)
        except InlabsAuthError:
            # Sessão velha: invalida e tenta relogar UMA vez.
            self._session = None
            session = self._get_session()
            try:
                return self._download(session, date_iso, secao)
            except InlabsAuthError:
                return None

    # -- unzip + parse --------------------------------------------------------
    def fetch_items(self, date_iso, secao):
        zip_bytes = self.download_zip(date_iso, secao)
        if not zip_bytes:
            return []
        items = []
        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile:
            log.warning("INLABS %s-%s: ZIP inválido.", date_iso, secao)
            return []
        with archive:
            for name in archive.namelist():
                if not name.lower().endswith(".xml"):
                    continue
                try:
                    item = parse_article_xml(archive.read(name), name, date_iso, secao)
                    if item:
                        items.append(item)
                except Exception as err:  # XML malformado isolado não derruba o lote
                    log.warning("XML ignorado (%s): %s", name, err)
        return items


client = InlabsClient()
