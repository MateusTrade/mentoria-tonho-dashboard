import os
import json
import logging
from datetime import datetime, timezone

import pandas as pd
from google.oauth2.service_account import Credentials
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

BQ_QUERY_SHEETS = "SELECT * EXCEPT(synced_at) FROM `leads-ts.Unnichat_Mentorias.sheets_mentoria_tonho`"
BQ_QUERY_CRM    = "SELECT * FROM `leads-ts.Unnichat_Mentorias.vw_crm_mentoriaTS_Tonho2026_staging`"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")
SCOPES = ["https://www.googleapis.com/auth/bigquery.readonly"]

NAO_CONTATADO = {"não contatado", "nao contatado", "não responderam", "nao responderam",
                 "não respondeu", "nao respondeu", "sem resposta"}


def build_credentials():
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not raw:
        raise EnvironmentError("GOOGLE_CREDENTIALS não definida.")
    return Credentials.from_service_account_info(
        json.loads(raw.encode("utf-8").decode("utf-8-sig")), scopes=SCOPES
    )


def run_query(client, query, label):
    log.info("Consultando BQ: %s...", label)
    try:
        df = client.query(query).to_dataframe()
        log.info("%s: %d linhas.", label, len(df))
        return df
    except Exception as e:
        log.error("Erro em %s: %s", label, e)
        return pd.DataFrame()


def safe_records(df):
    if df.empty:
        return []
    df = df.where(pd.notna(df), None)
    for c in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]", "datetimetz"]):
        df[c] = df[c].astype(str)
    return df.to_dict(orient="records")


def find(cols, *kws):
    for kw in kws:
        m = next((c for c in cols if kw in c.lower()), None)
        if m:
            return m
    return None


def to_num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)


def compute_summary(sheets, crm):
    s = {}

    # ── CRM ──────────────────────────────────────────────────────
    if not crm.empty:
        col_st   = find(crm.columns.tolist(), "crm_column", "columnname")
        col_date = find(crm.columns.tolist(), "event_date", "created_at")

        total = len(crm)
        s["total_contatados"] = total

        if col_st:
            st = crm[col_st].fillna("").str.strip()
            nao_mask      = st.str.lower().isin(NAO_CONTATADO)
            s["retorno"]  = int((~nao_mask).sum())
            s["promessas"]= int(st.str.lower().str.contains("promessa").sum())
            s["finalizados"] = int((st.str.lower() == "finalizado").sum())
            s["crm_por_status"] = (
                st.replace("", "sem status").value_counts().to_dict()
            )
        else:
            s["retorno"]     = total
            s["promessas"]   = 0
            s["finalizados"] = 0

        # Retorno por dia (contagem de registros CRM por data)
        if col_date:
            crm_cp = crm.copy()
            crm_cp["_dt"] = pd.to_datetime(crm_cp[col_date], errors="coerce").dt.date.astype(str)
            crm_cp = crm_cp[crm_cp["_dt"] != "NaT"]
            s["retorno_por_dia"] = crm_cp.groupby("_dt").size().sort_index().to_dict()

    # ── Sheets ───────────────────────────────────────────────────
    if not sheets.empty:
        cols     = sheets.columns.tolist()
        col_dep  = find(cols, "deposito")
        col_brok = find(cols, "broker")
        col_dt   = find(cols, "data_de_deposito", "deposito_data")

        if col_dep:
            vals     = to_num(sheets[col_dep])
            mask     = vals > 0
            qtd      = int(mask.sum())
            total_v  = round(float(vals[mask].sum()), 2)

            s["qtd_depositos"]   = qtd
            s["total_depositos"] = total_v
            s["media_depositos"] = round(total_v / qtd, 2) if qtd else 0

            # Depósitos por dia — soma do valor por data
            if col_dt:
                dep_df = sheets[mask].copy()
                dep_df["_dt"] = dep_df[col_dt].astype(str).str[:10]
                dep_df = dep_df[dep_df["_dt"].str.len() == 10]
                s["depositos_por_dia"] = (
                    dep_df.groupby("_dt")[col_dep]
                    .apply(lambda x: round(float(to_num(x).sum()), 2))
                    .sort_index().to_dict()
                )

            # Por broker
            if col_brok:
                out = {}
                for broker, g in sheets.groupby(sheets[col_brok].fillna("sem broker")):
                    v = to_num(g[col_dep])
                    m = v > 0
                    q = int(m.sum())
                    t = round(float(v[m].sum()), 2)
                    out[broker] = {"qtd": q, "total": t, "media": round(t / q, 2) if q else 0}
                s["por_broker"] = out

    return s


def main():
    creds   = build_credentials()
    project = (os.environ.get("GCP_PROJECT_ID") or "leads-ts").strip()
    client  = bigquery.Client(credentials=creds, project=project)

    sheets_df = run_query(client, BQ_QUERY_SHEETS, "sheets")
    crm_df    = run_query(client, BQ_QUERY_CRM,    "crm")

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "summary": compute_summary(sheets_df, crm_df),
        "alunos": safe_records(sheets_df),
        "crm":    safe_records(crm_df),
    }

    out = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info("Salvo: %s", out)


if __name__ == "__main__":
    main()
