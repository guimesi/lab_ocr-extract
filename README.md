# OCR Extract

App Streamlit para OCR de documentos com **Claude via Databricks** (Foundation
Model API, consumida com o **OpenAI SDK**), com chat sobre o documento e
extração estruturada no padrão de uma **tabela Snowflake**.

## Funcionalidades

1. **Upload de imagem** (nota fiscal, fatura, tabela, formulário, print...).
2. **OCR livre** — transcrição fiel em markdown, preservando a estrutura.
3. **Extração no padrão de uma tabela Snowflake** — informe
   `DB.SCHEMA.TABELA`; o app lê o schema (`DESCRIBE TABLE`) e algumas linhas
   de exemplo, e o modelo devolve os dados da imagem como linhas dessa tabela
   (JSON → DataFrame editável).
4. **Chat** — converse com o modelo sobre o documento (a imagem e os
   resultados já extraídos vão como contexto).
5. **Export** — CSV / Excel da extração estruturada (após revisão no editor)
   ou `.md` da transcrição.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # e preencha os valores
streamlit run app.py
```

## Configuração (`.env`)

### Databricks (obrigatório)

| Variável | Descrição |
|---|---|
| `DATABRICKS_HOST` | URL do workspace, ex.: `https://adb-123...azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Personal Access Token (User Settings → Developer → Access tokens) |
| `DATABRICKS_MODEL` | Nome do serving endpoint, ex.: `databricks-claude-sonnet-4-5` |

O OpenAI SDK aponta para `{DATABRICKS_HOST}/serving-endpoints`, com o PAT como
`api_key` e o nome do endpoint como `model`. O endpoint precisa aceitar
entrada de imagem (os endpoints Claude pay-per-token aceitam).

### Snowflake (opcional — habilita a tabela de referência)

Mesmas variáveis do projeto `lab_data-quali-score` (`SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_USER`, `SNOWFLAKE_AUTHENTICATOR=externalbrowser`,
`SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`,
`SNOWFLAKE_ROLE`). Sem elas o app funciona só com OCR livre + chat.

`SNOWFLAKE_SAMPLE_ROWS` (padrão 5) controla quantas linhas reais da tabela são
mostradas ao modelo como exemplo de formatação (0 = só o schema).

## Estrutura

```
app.py                    # UI Streamlit (upload, OCR, chat, export)
config/settings.py        # settings via .env
src/llm_client.py         # Claude via Databricks (OpenAI SDK) + prompts + parse JSON
src/snowflake_client.py   # conexão Snowflake (adaptado do lab_data-quali-score)
```

## Notas

- A conexão Snowflake usa `externalbrowser` por padrão (abre o navegador na
  primeira consulta) e é compartilhada no processo para evitar múltiplas
  autenticações.
- O modelo é instruído a **não inventar valores**: campos ilegíveis viram
  `null` na extração estruturada e `[ilegível]` na transcrição.
- Revise sempre a extração no editor antes de exportar — OCR de LLM é bom,
  mas não infalível.
