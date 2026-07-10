"""Orquestração: decide o que baixar, aplica o cache com TTL baseado na
cadência de publicação do DOU, e monta a resposta para o Apps Script."""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .cache import TTLCache
from .config import settings
from .inlabs import InlabsAuthError, InlabsBlocked, InlabsMaintenance, client

log = logging.getLogger("service")
cache = TTLCache(settings.db_path)

HOUR = 3600


def _today():
    return datetime.now(ZoneInfo(settings.tz)).date()


def _ttl_for(date_iso, secao, items, today_iso):
    """TTL do cache conforme a cadência real do DOU."""
    if date_iso < today_iso:
        return None                      # edição passada é imutável → cache eterno
    if secao.upper().endswith("E"):
        return 1 * HOUR                  # edição extra pode surgir/crescer no dia
    if items:
        return 6 * HOUR                  # DO1 de hoje já publicada → estável no dia
    return 20 * 60                       # DO1 de hoje ainda vazia → retry curto


def _get_section(date_iso, secao, today_iso):
    """Retorna (items, from_cache). Em bloqueio/manutenção, serve cache stale."""
    key = "%s_%s" % (date_iso, secao)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    try:
        items = client.fetch_items(date_iso, secao)
    except (InlabsBlocked, InlabsMaintenance, InlabsAuthError):
        stale = cache.get(key, allow_stale=True)
        raise _Degraded(stale if stale is not None else [])
    cache.set(key, items, _ttl_for(date_iso, secao, items, today_iso))
    return items, False


class _Degraded(Exception):
    def __init__(self, items):
        self.items = items


def get_federal():
    today = _today()
    yesterday = today - timedelta(days=1)
    today_iso = today.isoformat()
    yest_iso = yesterday.isoformat()

    plan = []
    for date_iso in (today_iso, yest_iso):
        for secao in settings.sections:
            plan.append((date_iso, secao))

    items = []
    seen = set()
    sections_meta = []
    degraded = False

    for date_iso, secao in plan:
        from_cache = True
        try:
            secs, from_cache = _get_section(date_iso, secao, today_iso)
        except _Degraded as deg:
            degraded = True
            secs = deg.items
        sections_meta.append({
            "date": date_iso, "secao": secao,
            "count": len(secs), "cached": from_cache,
        })
        for it in secs:
            ext = it.get("externalId")
            if ext in seen:
                continue
            seen.add(ext)
            items.append(it)

    blocked = degraded and not items
    status = "blocked" if blocked else ("degraded" if degraded else "ok")
    blocked_until = None
    if client.blocked_until > 0:
        blocked_until = datetime.fromtimestamp(client.blocked_until, timezone.utc).isoformat()

    return {
        "status": status,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "sections": sections_meta,
        "blockedUntil": blocked_until if degraded else None,
        "items": items,
    }


def get_norms(date_iso, sections):
    today_iso = _today().isoformat()
    items = []
    seen = set()
    sections_meta = []
    degraded = False
    for secao in sections:
        from_cache = True
        try:
            secs, from_cache = _get_section(date_iso, secao, today_iso)
        except _Degraded as deg:
            degraded = True
            secs = deg.items
        sections_meta.append({
            "date": date_iso, "secao": secao,
            "count": len(secs), "cached": from_cache,
        })
        for it in secs:
            ext = it.get("externalId")
            if ext in seen:
                continue
            seen.add(ext)
            items.append(it)

    status = "degraded" if degraded else "ok"
    if degraded and not items:
        status = "blocked"
    return {
        "status": status,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "date": date_iso,
        "count": len(items),
        "sections": sections_meta,
        "items": items,
    }
