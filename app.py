"""
OCR Extract - Streamlit app.

Upload de imagem -> OCR com Claude (via Databricks serving endpoint,
OpenAI SDK) -> chat sobre o documento -> extração estruturada no padrão
de uma tabela Snowflake -> export CSV / Excel.

Run: streamlit run app.py
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from config.settings import SETTINGS
from src import llm_client
from src.snowflake_client import get_shared_client, qualify

st.set_page_config(
    page_title="OCR Extract",
    page_icon=":material/document_scanner:",
    layout="wide",
)


# =============================================================================
# Cached data access
# =============================================================================

@st.cache_data(ttl=600, show_spinner="Lendo schema no Snowflake...")
def load_table_schema(table_ref: str) -> pd.DataFrame:
    return get_shared_client().describe_table(table_ref)


@st.cache_data(ttl=600, show_spinner="Buscando linhas de exemplo...")
def load_table_sample(table_ref: str, limit: int) -> pd.DataFrame:
    return get_shared_client().fetch_sample(table_ref, limit=limit)


# =============================================================================
# Session state
# =============================================================================

_DEFAULTS = {
    "messages": [],          # visible chat history: {"role", "content"}
    "ocr_text": None,        # free-form OCR transcription (str)
    "extracted_df": None,    # structured extraction (DataFrame)
    "table_ref": "",         # qualified table reference in use
    "image_key": None,       # id of the current upload, to detect changes
}
for key, default in _DEFAULTS.items():
    st.session_state.setdefault(key, default)


def reset_results() -> None:
    st.session_state.messages = []
    st.session_state.ocr_text = None
    st.session_state.extracted_df = None


# =============================================================================
# Sidebar: connection status + Snowflake table reference
# =============================================================================

with st.sidebar:
    st.title(":material/document_scanner: OCR Extract")

    if SETTINGS.databricks_enabled:
        st.success(f"Databricks: `{SETTINGS.databricks_model}`", icon=":material/cloud_done:")
    else:
        st.error(
            "Databricks não configurado. Preencha DATABRICKS_HOST e "
            "DATABRICKS_TOKEN no `.env` (veja `.env.example`).",
            icon=":material/cloud_off:",
        )

    st.divider()
    st.subheader("Tabela de referência (opcional)")
    st.caption(
        "Aponte uma tabela do Snowflake para o OCR extrair os dados no "
        "padrão dela (colunas e tipos)."
    )

    if not SETTINGS.snowflake_enabled:
        st.info(
            "Snowflake não configurado no `.env` - o OCR fará transcrição "
            "livre.",
            icon=":material/database_off:",
        )
    else:
        table_input = st.text_input(
            "Tabela (NOME, SCHEMA.NOME ou DB.SCHEMA.NOME)",
            value=st.session_state.table_ref,
            placeholder="ex.: VENDAS.NOTAS_FISCAIS",
        )
        col_load, col_clear = st.columns(2)
        if col_load.button("Carregar schema", width="stretch", type="primary"):
            try:
                ref = qualify(table_input)
                load_table_schema.clear()
                load_table_sample.clear()
                load_table_schema(ref)  # validates + warms the cache
                st.session_state.table_ref = ref
                st.session_state.extracted_df = None
            except Exception as exc:
                st.error(f"Falha ao carregar a tabela: {exc}")
        if col_clear.button("Limpar", width="stretch"):
            st.session_state.table_ref = ""
            st.session_state.extracted_df = None

        if st.session_state.table_ref:
            st.success(f"Usando `{st.session_state.table_ref}`", icon=":material/table:")
            with st.expander("Colunas da tabela"):
                st.dataframe(
                    load_table_schema(st.session_state.table_ref),
                    width="stretch",
                    hide_index=True,
                )


# =============================================================================
# Main: upload + OCR
# =============================================================================

st.header("1. Documento", divider="gray")

uploaded = st.file_uploader(
    "Envie uma imagem (nota, fatura, tabela, formulário...)",
    type=["png", "jpg", "jpeg", "webp", "gif"],
)

if uploaded is None:
    st.session_state.image_key = None
    reset_results()
    st.info("Envie uma imagem para começar.", icon=":material/upload_file:")
    st.stop()

# New file replaces previous results / conversation
if st.session_state.image_key != uploaded.file_id:
    st.session_state.image_key = uploaded.file_id
    reset_results()

image_bytes = uploaded.getvalue()
mime_type = uploaded.type or "image/png"

col_img, col_ocr = st.columns([2, 3], gap="large")

with col_img:
    st.image(image_bytes, caption=uploaded.name, width="stretch")

with col_ocr:
    structured = bool(st.session_state.table_ref)
    extra = st.text_area(
        "Instruções adicionais (opcional)",
        placeholder="ex.: considere apenas a tabela de itens, ignore o rodapé",
    )
    label = (
        "Extrair no padrão da tabela" if structured else "Executar OCR (transcrição)"
    )
    if st.button(label, type="primary", icon=":material/document_scanner:"):
        if structured:
            schema = load_table_schema(st.session_state.table_ref)
            sample = None
            if SETTINGS.sf_sample_rows > 0:
                try:
                    sample = load_table_sample(
                        st.session_state.table_ref, SETTINGS.sf_sample_rows
                    )
                except Exception:
                    sample = None  # amostra é opcional; o schema basta
            prompt = llm_client.build_extraction_prompt(schema, sample, extra)
            with st.spinner("Extraindo dados da imagem..."):
                answer = llm_client.complete([
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            llm_client.image_content(image_bytes, mime_type),
                        ],
                    }
                ])
            try:
                st.session_state.extracted_df = llm_client.parse_rows_json(
                    answer, schema["NAME"].tolist()
                )
                st.session_state.ocr_text = None
            except ValueError as exc:
                st.error(f"{exc} Resposta bruta abaixo:")
                st.code(answer)
        else:
            ocr_prompt = (
                "Transcreva todo o conteúdo da imagem em markdown, "
                "preservando a estrutura (títulos, tabelas, campos). "
                "Marque trechos ilegíveis com [ilegível]."
            )
            if extra.strip():
                ocr_prompt += f"\n\nInstruções adicionais: {extra.strip()}"
            with st.chat_message("assistant"):
                text = st.write_stream(
                    llm_client.stream_chat([
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": ocr_prompt},
                                llm_client.image_content(image_bytes, mime_type),
                            ],
                        }
                    ])
                )
            st.session_state.ocr_text = text
            st.session_state.extracted_df = None


# =============================================================================
# Results + export
# =============================================================================

if st.session_state.extracted_df is not None or st.session_state.ocr_text:
    st.header("2. Resultado", divider="gray")

if st.session_state.extracted_df is not None:
    st.caption("Revise e edite os valores antes de exportar.")
    edited = st.data_editor(
        st.session_state.extracted_df,
        width="stretch",
        num_rows="dynamic",
        key="result_editor",
    )
    csv_bytes = edited.to_csv(index=False).encode("utf-8-sig")
    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        edited.to_excel(writer, index=False, sheet_name="extracao")
    col_a, col_b = st.columns(2)
    col_a.download_button(
        "Baixar CSV", csv_bytes, "extracao.csv", "text/csv",
        icon=":material/download:", width="stretch",
    )
    col_b.download_button(
        "Baixar Excel", xlsx_buf.getvalue(), "extracao.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", width="stretch",
    )
elif st.session_state.ocr_text:
    st.markdown(st.session_state.ocr_text)
    st.download_button(
        "Baixar transcrição (.md)",
        st.session_state.ocr_text.encode("utf-8"),
        "transcricao.md",
        "text/markdown",
        icon=":material/download:",
    )


# =============================================================================
# Chat sobre o documento
# =============================================================================

st.header("3. Chat sobre o documento", divider="gray")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("Pergunte algo sobre o documento...", submit_mode="disable"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # API messages: the image (and any prior result) goes as context in
    # the first user turn; the visible history follows as plain text.
    context_parts: list[str] = ["Esta é a imagem do documento em análise."]
    if st.session_state.ocr_text:
        context_parts.append(
            "Transcrição OCR já produzida:\n" + st.session_state.ocr_text
        )
    if st.session_state.extracted_df is not None:
        context_parts.append(
            "Dados já extraídos (CSV):\n"
            + st.session_state.extracted_df.to_csv(index=False)
        )
    api_messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "\n\n".join(context_parts)},
                llm_client.image_content(image_bytes, mime_type),
            ],
        },
        {
            "role": "assistant",
            "content": "Entendido. Estou analisando o documento. O que deseja saber?",
        },
        *st.session_state.messages,
    ]

    with st.chat_message("assistant"):
        try:
            response = st.write_stream(llm_client.stream_chat(api_messages))
        except Exception as exc:
            st.error(f"Erro ao chamar o modelo: {exc}")
            st.session_state.messages.pop()
            st.stop()
    st.session_state.messages.append({"role": "assistant", "content": response})
