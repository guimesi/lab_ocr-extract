"""
Claude via Databricks Foundation Model API, through the OpenAI SDK.

Databricks serving endpoints expose an OpenAI-compatible API at
``<workspace-url>/serving-endpoints``; the personal access token is the
``api_key`` and the endpoint name (e.g. ``databricks-claude-sonnet-4-5``)
is the ``model``. Images travel as base64 data URIs in the standard
OpenAI vision content format, which Databricks forwards to Claude.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Iterable, Iterator, Optional

import pandas as pd
from openai import OpenAI

from config.settings import SETTINGS

SYSTEM_PROMPT = (
    "Você é um assistente de OCR e extração de dados. Você recebe "
    "documentos como imagens - uma imagem por página, no caso de PDFs - "
    "(notas, faturas, tabelas, formulários, prints) e deve "
    "transcrever e estruturar o conteúdo com fidelidade. Não invente "
    "valores: quando um campo estiver ilegível, use null e avise. "
    "Responda em português, exceto quando o documento estiver em outro "
    "idioma e o usuário pedir transcrição literal."
)


def get_client() -> OpenAI:
    if not SETTINGS.databricks_enabled:
        raise RuntimeError(
            "Databricks não configurado: defina DATABRICKS_HOST e "
            "DATABRICKS_TOKEN no .env (veja .env.example)."
        )
    return OpenAI(
        api_key=SETTINGS.databricks_token,
        base_url=f"{SETTINGS.databricks_host}/serving-endpoints",
    )


def image_content(image_bytes: bytes, mime_type: str) -> dict:
    """Build the OpenAI-format image content part (base64 data URI)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
    }


def stream_chat(messages: list[dict]) -> Iterator[str]:
    """Stream a chat completion, yielding text deltas.

    ``messages`` follow the OpenAI format; the system prompt is
    prepended here so callers only manage the visible conversation.
    """
    client = get_client()
    stream = client.chat.completions.create(
        model=SETTINGS.databricks_model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def complete(messages: list[dict]) -> str:
    """Non-streaming completion; returns the full text."""
    client = get_client()
    resp = client.chat.completions.create(
        model=SETTINGS.databricks_model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
    )
    return resp.choices[0].message.content or ""


# =============================================================================
# Structured extraction guided by a Snowflake table schema
# =============================================================================

def build_extraction_prompt(
    schema: pd.DataFrame,
    sample: Optional[pd.DataFrame],
    extra_instructions: str = "",
) -> str:
    """Prompt asking for a JSON array of rows matching the table columns.

    ``schema`` is the DataFrame returned by
    :meth:`src.snowflake_client.SnowflakeClient.describe_table`.
    """
    col_lines = []
    for _, row in schema.iterrows():
        line = f"- {row['NAME']} ({row['TYPE']})"
        comment = str(row.get("COMMENT") or "").strip()
        if comment and comment.lower() != "none":
            line += f" — {comment}"
        col_lines.append(line)

    parts = [
        "Extraia do documento (cada imagem é uma página) os dados no "
        "formato da tabela abaixo.",
        "Colunas da tabela de destino:",
        "\n".join(col_lines),
    ]
    if sample is not None and not sample.empty:
        parts.append(
            "Exemplos de linhas reais da tabela (siga o mesmo formato "
            "de datas, números e códigos):\n"
            + sample.head(5).to_csv(index=False)
        )
    parts.append(
        "Responda APENAS com um array JSON de objetos - um objeto por "
        "linha/registro identificado na imagem, com exatamente as chaves "
        "acima (em maiúsculas). Use null para campos ausentes ou "
        "ilegíveis. Não inclua explicações fora do JSON."
    )
    if extra_instructions.strip():
        parts.append(f"Instruções adicionais do usuário: {extra_instructions.strip()}")
    return "\n\n".join(parts)


def parse_rows_json(text: str, columns: Iterable[str]) -> pd.DataFrame:
    """Parse the model's JSON answer into a DataFrame with ``columns``.

    Tolerates a ```json fenced block or leading/trailing prose around
    the array; raises ``ValueError`` when no JSON array can be parsed.
    """
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    if not candidate.startswith("["):
        start, end = candidate.find("["), candidate.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("Nenhum array JSON encontrado na resposta do modelo.")
        candidate = candidate[start : end + 1]
    data = json.loads(candidate)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("A resposta do modelo não é uma lista JSON.")
    df = pd.DataFrame(data)
    df.columns = [str(c).upper() for c in df.columns]
    ordered = [c for c in columns if c in df.columns]
    extras = [c for c in df.columns if c not in ordered]
    return df[ordered + extras]
