"""
Snowflake client wrapper (adapted from lab_data-quali-score).

Supports externalbrowser auth (default). Returns pandas DataFrames.

Two paths to fetch data:

- :meth:`SnowflakeClient.fetch_table` - fast Arrow path
  (``cursor.fetch_pandas_all``).
- :meth:`SnowflakeClient.fetch_query` - Python-rows path
  (``cursor.fetchall``), resilient to Snowflake's Arrow chunk-schema
  mismatch (``ArrowInvalid: Schema at index N was different ...``).

Extras for this project:

- :meth:`SnowflakeClient.describe_table` - column names + types via
  ``DESCRIBE TABLE``, used to guide the OCR structured extraction.
- :func:`qualify` - resolves a user-typed table reference (bare name or
  ``DB.SCHEMA.TABLE``) against the ``.env`` defaults.

A shared client (:func:`get_shared_client` / :func:`close_shared_client`)
lets multiple call sites within a single Streamlit run reuse one open
connection and one externalbrowser auth round-trip.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

import pandas as pd

from config.settings import SETTINGS

# Snowflake unquoted identifiers: letters, digits, _ and $.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def qualify(table_ref: str) -> str:
    """Resolve a table reference to ``DB.SCHEMA.TABLE``.

    Accepts a bare table name (qualified with the ``.env`` database and
    schema), ``SCHEMA.TABLE`` or a fully qualified name. Each part is
    validated as an unquoted identifier - the result is interpolated
    into SQL, so anything else is rejected.
    """
    parts = [p.strip() for p in table_ref.strip().split(".")]
    if len(parts) == 1:
        parts = [SETTINGS.sf_database, SETTINGS.sf_schema, parts[0]]
    elif len(parts) == 2:
        parts = [SETTINGS.sf_database, parts[0], parts[1]]
    elif len(parts) != 3:
        raise ValueError(f"Referência de tabela inválida: {table_ref!r}")
    for p in parts:
        if not p or not _IDENT.match(p):
            raise ValueError(
                f"Identificador inválido em {table_ref!r}: {p!r}. "
                "Use nomes sem aspas (letras, números, _ e $)."
            )
    return ".".join(p.upper() for p in parts)


class SnowflakeClient:
    """Thin wrapper over snowflake.connector. Instantiated lazily."""

    def __init__(self) -> None:
        self._conn = None

    def connect(self):
        if self._conn is not None:
            return self._conn

        # Imported lazily so the app runs without the package until the
        # Snowflake feature is actually used.
        import snowflake.connector  # type: ignore

        params = {
            "account": SETTINGS.sf_account,
            "user": SETTINGS.sf_user,
            "authenticator": SETTINGS.sf_authenticator,
            "database": SETTINGS.sf_database,
            "schema": SETTINGS.sf_schema,
        }
        if SETTINGS.sf_warehouse:
            params["warehouse"] = SETTINGS.sf_warehouse
        if SETTINGS.sf_role:
            params["role"] = SETTINGS.sf_role

        self._conn = snowflake.connector.connect(**params)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def describe_table(self, table_ref: str) -> pd.DataFrame:
        """Return ``DESCRIBE TABLE`` as a DataFrame with NAME / TYPE /
        NULLABLE / COMMENT columns (uppercased)."""
        qualified = qualify(table_ref)
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute(f"DESCRIBE TABLE {qualified}")
            rows = cur.fetchall()
            cols = [d[0].upper() for d in cur.description]
        finally:
            cur.close()
        df = pd.DataFrame(rows, columns=cols)
        keep = [c for c in ("NAME", "TYPE", "NULL?", "COMMENT") if c in df.columns]
        df = df[keep].rename(columns={"NULL?": "NULLABLE"})
        return df

    def fetch_sample(self, table_ref: str, limit: int = 5) -> pd.DataFrame:
        """Fetch a few sample rows (Python-rows path, resilient)."""
        qualified = qualify(table_ref)
        return self.fetch_query(
            f"SELECT * FROM {qualified} LIMIT {int(limit)}"
        )

    def fetch_table(
        self,
        table_name: str,
        limit: Optional[int] = None,
        where: Optional[str] = None,
        params: Optional[Sequence[object]] = None,
    ) -> pd.DataFrame:
        """Fetch a table as DataFrame via the fast Arrow path.

        ``where`` takes ``%s`` placeholders bound server-side through
        ``params`` - no quoting / escaping happens in this module.
        """
        conn = self.connect()
        qualified = qualify(table_name)
        query = f"SELECT * FROM {qualified}"
        if where:
            query += f" WHERE {where}"
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        cur = conn.cursor()
        try:
            if where and params:
                cur.execute(query, list(params))
            else:
                cur.execute(query)
            df = cur.fetch_pandas_all()
        finally:
            cur.close()
        df.columns = [c.upper() for c in df.columns]
        return df

    def fetch_query(self, sql: str) -> pd.DataFrame:
        """Run an arbitrary SELECT and return the result as a DataFrame.

        Uses ``cur.fetchall()`` (Python rows -> pandas) instead of the
        Arrow path, so callers are immune to the Arrow chunk-schema
        mismatch on tables with inconsistently inferred nullable columns.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0].upper() for d in cur.description]
        finally:
            cur.close()
        return pd.DataFrame(rows, columns=cols)

    def __enter__(self) -> "SnowflakeClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# =============================================================================
# Process-wide shared client (one externalbrowser auth round-trip per
# Streamlit process; app.py additionally wraps this in st.cache_resource)
# =============================================================================

_SHARED: Optional[SnowflakeClient] = None


def get_shared_client() -> SnowflakeClient:
    """Return a process-wide cached :class:`SnowflakeClient`."""
    global _SHARED
    if _SHARED is None:
        _SHARED = SnowflakeClient()
    _SHARED.connect()  # idempotent: returns the existing _conn if any
    return _SHARED


def close_shared_client() -> None:
    """Close and drop the cached shared client. Safe no-op when nothing
    is cached."""
    global _SHARED
    if _SHARED is not None:
        try:
            _SHARED.close()
        finally:
            _SHARED = None
