import os
import json
import logging
from datetime import datetime, timezone

import pandas as pd
from google.oauth2.service_account import Credentials
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Tabela sincronizada pelo Apps Script da planilha
BQ_QUERY_SHEETS = """
    SELECT * EXCEPT(synced_at)
    FROM `leads-ts.Unnichat_Mentorias.sheets_mentoria_tonho`
"""

BQ_QUERY_CRM = """
    SELECT *
    FROM `leads-ts.Unnichat_Mentorias.vw_crm_mentoriaTS_Tonho2026_staging`
    WHERE DATE(event_date) = CURRENT_DATE('America/Sao_Paulo')
"""

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")

SCOPES = ["https://www.googleapis.com/auth/bigquery.readonly"]


def build_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not raw:
        raise EnvironmentError("Variável de ambiente GOOGLE_CREDENTIALS não definida.")
    cleaned = raw.encode("utf-8").decode("utf-8-sig")  # remove BOM se presente
    return Credentials.from_service_account_info(json.loads(cleaned), scopes=SCOPES)


def run_query(client: bigquery.Client, query: str, label: str) -> pd.DataFrame:
    log.info("Consultando BQ: %s...", label)
    try:
        df = client.query(query).to_dataframe()
        log.info("%s: %d linhas.", label, len(df))
        return df
    except Exception as exc:
        log.error("Erro em %s: %s", label, exc)
        return pd.DataFrame()


def safe_records(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    df = df.where(pd.notna(df), None)
    for col in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]", "datetimetz"]):
        df[col] = df[col].astype(str)
    return df.to_dict(orient="records")


def compute_summary(alunos: pd.DataFrame, crm: pd.DataFrame) -> dict:
    summary = {}

    if not alunos.empty:
        def find(cols, *keywords):
            for kw in keywords:
                match = next((c for c in cols if kw in c.lower()), None)
                if match:
                    return match
            return None

        cols = alunos.columns.tolist()
        col_capital    = find(cols, "capital")
        col_saldo      = find(cols, "saldo")
        col_bonus      = find(cols, "b_nus", "bonus", "bônus")
        col_status     = find(cols, "status")
        col_broker     = find(cols, "broker")
        col_comprov_dep = find(cols, "comprovante_dep", "comprovante dep")

        def to_num(s):
            return pd.to_numeric(s, errors="coerce").fillna(0)

        summary["total_alunos"]          = len(alunos)
        summary["capital_liquido_total"] = round(to_num(alunos[col_capital]).sum(), 2) if col_capital else 0
        summary["saldo_total"]           = round(to_num(alunos[col_saldo]).sum(), 2)   if col_saldo   else 0
        summary["bonus_total"]           = round(to_num(alunos[col_bonus]).sum(), 2)   if col_bonus   else 0

        if col_status:
            summary["por_status"] = alunos[col_status].fillna("sem status").value_counts().to_dict()
        if col_broker:
            summary["por_broker"] = alunos[col_broker].fillna("sem broker").value_counts().to_dict()
            if col_capital:
                summary["capital_por_broker"] = (
                    alunos.groupby(alunos[col_broker].fillna("sem broker"))[col_capital]
                    .apply(lambda s: round(to_num(s).sum(), 2))
                    .to_dict()
                )
        if col_comprov_dep:
            sem = alunos[col_comprov_dep].isnull() | (alunos[col_comprov_dep].astype(str).str.strip() == "")
            summary["sem_comprovante_deposito"] = int(sem.sum())
        else:
            summary["sem_comprovante_deposito"] = 0

    if not crm.empty:
        col_att  = next((c for c in crm.columns if "attendant" in c.lower() and "name" in c.lower()), None)
        col_tags = next((c for c in crm.columns if c.lower() == "tags"), None)
        if col_att:
            summary["leads_por_atendente"] = crm[col_att].fillna("sem atendente").value_counts().to_dict()
        if col_tags:
            summary["leads_por_tag"] = crm[col_tags].fillna("sem tag").value_counts().to_dict()

    return summary


def main():
    creds   = build_credentials()
    project = os.environ.get("GCP_PROJECT_ID", "leads-ts")
    client  = bigquery.Client(credentials=creds, project=project)

    alunos_df = run_query(client, BQ_QUERY_SHEETS, "sheets_mentoria_tonho")
    crm_df    = run_query(client, BQ_QUERY_CRM,    "vw_crm_staging")

    summary = compute_summary(alunos_df, crm_df)

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "alunos":   safe_records(alunos_df),
        "crm_hoje": safe_records(crm_df),
    }

    out_path = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("data.json salvo em: %s", out_path)


if __name__ == "__main__":
    main()
