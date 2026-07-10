"""Cache TTL em SQLite (memória do dia + persistência no volume).

Chave por (data, seção). `ttl=None` = nunca expira (edições passadas, imutáveis).
`allow_stale=True` devolve o valor mesmo expirado — usado quando o INLABS está
bloqueado e servir o último dado conhecido é melhor que nada.

Uma conexão por operação (baixo volume) + WAL, seguro entre as threads do uvicorn.
"""
import json
import os
import sqlite3
import threading
import time


class TTLCache:
    def __init__(self, db_path):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS cache ("
                    "key TEXT PRIMARY KEY, "
                    "value TEXT NOT NULL, "
                    "expires REAL, "
                    "stored REAL NOT NULL)"
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, key, allow_stale=False):
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT value, expires FROM cache WHERE key = ?", (key,)
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        value_json, expires = row
        if allow_stale or expires is None or expires > now:
            try:
                return json.loads(value_json)
            except ValueError:
                return None
        return None

    def set(self, key, value, ttl):
        expires = None if ttl is None else time.time() + ttl
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO cache (key, value, expires, stored) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value, expires = excluded.expires, stored = excluded.stored",
                    (key, payload, expires, time.time()),
                )
                conn.commit()
            finally:
                conn.close()
