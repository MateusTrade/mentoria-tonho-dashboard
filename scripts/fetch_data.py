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

BQ_QUERY_SHEETS = """
    SELECT * EXCEPT(synced_at)
    FROM `leads-ts.Unnichat_Mentorias.sheets_mentoria_tonho`
"""

# CRM completo do evento (sem filtro de data)
BQ_QUERY_CRM = """
    SELECT *
    FROM `leads-ts.Unnichat_Mentorias.vw_crm_mentoriaTS_Tonho2026_staging`
"""

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")
SCOPES = ["https://www.googleapis.com/auth/bigquery.readonly"]

NAO_CONTATADOS = {"não contatado", "nao contatado", "não responderam", "nao responderam",
                  "não respondeu", "nao respondeu"}


def build_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not raw:
        raise EnvironmentError("GOOGLE_CREDENTIALS não definida.")
    cleaned = raw.encode("utf-8").decode("utf-8-sig")
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


def col(cols, *kws):
    for kw in kws:
        m = next((c for c in cols if kw in c.lower()), None)
        if m:
            return m
    return None


def to_num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def compute_summary(sheets: pd.DataFrame, crm: pd.DataFrame) -> dict:
    s = {}

    # ── CRM metrics ──────────────────────────────────────────────
    if not crm.empty:
        col_status = col(crm.columns.tolist(), "crm_column", "columnname", "tags")

        s["total_alunos_crm"] = len(crm)

        if col_status:
            status_series = crm[col_status].fillna("").str.strip()
            s["finalizados"] = int((status_series.str.lower() == "finalizado").sum())

            nao_cont_mask = status_series.str.lower().isin(NAO_CONTATADOS)
            s["contatados"] = int((~nao_cont_mask).sum())

            s["crm_por_status"] = status_series.replace("", "sem status").value_counts().to_dict()
        else:
            s["finalizados"] = 0
            s["contatados"]  = len(crm)

    # ── Sheets metrics ────────────────────────────────────────────
    if not sheets.empty:
        cols = sheets.columns.tolist()
        col_dep    = col(cols, "deposito")
        col_broker = col(cols, "broker")
        col_date   = col(cols, "data_de_deposito", "deposito_data")

        if col_dep:
            dep_vals   = to_num(sheets[col_dep])
            dep_mask   = dep_vals > 0
            qtd_dep    = int(dep_mask.sum())
            total_dep  = round(float(dep_vals[dep_mask].sum()), 2)
            media_dep  = round(total_dep / qtd_dep, 2) if qtd_dep else 0

            s["qtd_depositos"]    = qtd_dep
            s["total_depositos"]  = total_dep
            s["media_depositos"]  = media_dep

            # Depósitos por dia (contagem)
            if col_date:
                dep_df = sheets[dep_mask].copy()
                dep_df[col_date] = dep_df[col_date].astype(str).str[:10]
                dep_df = dep_df[dep_df[col_date].str.len() == 10]
                s["depositos_por_dia"] = (
                    dep_df.groupby(col_date).size()
                    .sort_index().to_dict()
                )

            # Por broker
            if col_broker:
                grp = sheets.groupby(sheets[col_broker].fillna("sem broker"))
                broker_stats = {}
                for broker, g in grp:
                    vals   = to_num(g[col_dep])
                    mask_b = vals > 0
                    qtd    = int(mask_b.sum())
                    total  = round(float(vals[mask_b].sum()), 2)
                    broker_stats[broker] = {
                        "qtd":   qtd,
                        "total": total,
                        "media": round(total / qtd, 2) if qtd else 0,
                    }
                s["por_broker"] = broker_stats

    return s


def main():
    creds   = build_credentials()
    project = (os.environ.get("GCP_PROJECT_ID") or "leads-ts").strip()
    client  = bigquery.Client(credentials=creds, project=project)

    sheets_df = run_query(client, BQ_QUERY_SHEETS, "sheets_mentoria_tonho")
    crm_df    = run_query(client, BQ_QUERY_CRM,    "vw_crm_staging")

    summary = compute_summary(sheets_df, crm_df)

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "alunos":  safe_records(sheets_df),
        "crm":     safe_records(crm_df),
    }

    out_path = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("data.json salvo: %s", out_path)


if __name__ == "__main__":
    main()
