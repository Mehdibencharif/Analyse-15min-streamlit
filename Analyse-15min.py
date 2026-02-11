import os
import re
import unicodedata
import pandas as pd
import numpy as np
from datetime import datetime

# ==========================================================
# CONFIG À MODIFIER SELON TON CAS (TEST / PROD)
# ==========================================================
INPUT_FOLDER = r"C:\temp\hydro"  # <-- Mets ton dossier ici (ou chemin réseau)
OUTPUT_EXCEL = os.path.join(INPUT_FOLDER, "Synthese_Hydro.xlsx")
LOG_FILE = os.path.join(INPUT_FOLDER, "log_erreurs_nettoyage.txt")

SUPPORTED_EXT = (".xlsx", ".csv")


# ==========================================================
# OUTILS
# ==========================================================
def norm_col(s: str) -> str:
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def detect_columns(df: pd.DataFrame):
    cols = list(df.columns)

    # Date
    date_candidates = []
    for c in cols:
        cn = norm_col(c)
        if any(k in cn for k in ["date", "heure", "horodate", "timestamp", "periode", "période"]):
            date_candidates.append(c)

    date_col = None
    for c in date_candidates:
        cn = norm_col(c)
        if any(k in cn for k in ["date et heure", "horodate", "timestamp", "heure"]):
            date_col = c
            break
    if date_col is None and date_candidates:
        date_col = date_candidates[0]

    # Puissance
    power_col = None
    power_candidates = []
    for c in cols:
        cn = norm_col(c)
        if ("kw" in cn) and any(k in cn for k in ["puissance", "power", "appel", "demande", "charge"]):
            power_candidates.append(c)

    for c in power_candidates:
        cn = norm_col(c)
        if any(k in cn for k in ["reel", "reelle", "mesuree", "mesurée"]):
            power_col = c
            break
    if power_col is None and power_candidates:
        power_col = power_candidates[0]

    if power_col is None:
        for c in cols:
            if "kw" in norm_col(c):
                power_col = c
                break

    return date_col, power_col

def compute_dynamic_palier(pmax: float) -> float:
    if pmax <= 500:
        return 500.0
    if pmax <= 700:
        return 700.0
    if pmax <= 1000:
        return 1000.0
    return float((int(pmax // 100) + 1) * 100)

def add_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """
    kWh = kW * Δt(h)
    => robuste même si trous ou pas exactement 15min.
    """
    d = df.sort_index().copy()
    delta_h = d.index.to_series().diff().dt.total_seconds().div(3600).fillna(0)
    d["delta_h"] = delta_h
    d["kWh"] = d["Puissance réelle (kW)"] * d["delta_h"]
    return d

def read_file(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, encoding="ISO-8859-1", sep=";")
    return pd.read_excel(path)

def log_error(msg: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

def list_files(folder: str):
    all_files = []
    for root, _, filenames in os.walk(folder):
        for fn in sorted(filenames):
            if fn.endswith(SUPPORTED_EXT) and not fn.startswith("~$"):
                all_files.append(os.path.join(root, fn))
    return all_files


# ==========================================================
# NETTOYAGE D’UN FICHIER
# ==========================================================
def clean_file(filepath: str) -> pd.DataFrame | None:
    try:
        df = read_file(filepath)

        date_col, power_col = detect_columns(df)
        if date_col is None or power_col is None:
            raise ValueError(f"Colonnes non détectées. Colonnes: {list(df.columns)}")

        df = df[[date_col, power_col]].copy()
        df.rename(columns={date_col: "Date et heure", power_col: "Puissance réelle (kW)"}, inplace=True)

        df["Puissance réelle (kW)"] = (
            df["Puissance réelle (kW)"].astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        df["Puissance réelle (kW)"] = pd.to_numeric(df["Puissance réelle (kW)"], errors="coerce")
        df["Date et heure"] = pd.to_datetime(df["Date et heure"], errors="coerce")

        df = df.dropna(subset=["Date et heure", "Puissance réelle (kW)"])
        df = df.drop_duplicates(subset=["Date et heure"]).sort_values("Date et heure")

        df["Nom fichier"] = os.path.basename(filepath)

        return df

    except Exception as e:
        log_error(f"ERREUR dans {os.path.basename(filepath)} : {e}")
        return None


# ==========================================================
# MAIN
# ==========================================================
def run():
    # reset log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    files = list_files(INPUT_FOLDER)
    print(f"🔍 Fichiers détectés : {len(files)}")
    for p in files:
        print("  →", os.path.basename(p))

    cleaned = []
    for fp in files:
        df = clean_file(fp)
        if df is not None and not df.empty:
            cleaned.append(df)

    if not cleaned:
        raise RuntimeError("Aucun fichier valide traité. Voir log.")

    df_final = pd.concat(cleaned, ignore_index=True)
    df_final["Date et heure"] = pd.to_datetime(df_final["Date et heure"], errors="coerce")
    df_final = df_final.dropna(subset=["Date et heure", "Puissance réelle (kW)"])
    df_final = df_final.drop_duplicates(subset=["Date et heure"]).sort_values("Date et heure")
    df_final = df_final.set_index("Date et heure")

    # Energie (kWh)
    df_final = add_energy_kwh(df_final)

    # Infos de pas de temps
    deltas = df_final.index.to_series().diff().dropna()
    median_minutes = deltas.median().total_seconds() / 60 if not deltas.empty else np.nan

    # KPI globaux
    pmax = float(df_final["Puissance réelle (kW)"].max())
    hours = float(df_final["delta_h"].sum())
    e_kwh = float(df_final["kWh"].sum())

    lf_pct = (e_kwh / (pmax * hours) * 100) if (pmax > 0 and hours > 0) else np.nan

    palier = compute_dynamic_palier(pmax)
    util_palier_pct = (e_kwh / (palier * hours) * 100) if (palier > 0 and hours > 0) else np.nan

    # Agrégations correctes
    agg_15min = pd.DataFrame({
        "P max 15min": df_final["Puissance réelle (kW)"].resample("15min").max(),
        "P min 15min": df_final["Puissance réelle (kW)"].resample("15min").min(),
        "P moy 15min": df_final["Puissance réelle (kW)"].resample("15min").mean(),
        "kWh 15min": df_final["kWh"].resample("15min").sum(),
    }).reset_index()

    agg_hour = pd.DataFrame({
        "P max heure": df_final["Puissance réelle (kW)"].resample("H").max(),
        "P min heure": df_final["Puissance réelle (kW)"].resample("H").min(),
        "P moy heure": df_final["Puissance réelle (kW)"].resample("H").mean(),
        "kWh heure": df_final["kWh"].resample("H").sum(),
    }).reset_index()

    agg_day = pd.DataFrame({
        "P max jour": df_final["Puissance réelle (kW)"].resample("D").max(),
        "P min jour": df_final["Puissance réelle (kW)"].resample("D").min(),
        "P moy jour": df_final["Puissance réelle (kW)"].resample("D").mean(),
        "kWh jour": df_final["kWh"].resample("D").sum(),
    }).reset_index().rename(columns={"Date et heure": "Date"})

    agg_month = pd.DataFrame({
        "P max mois": df_final["Puissance réelle (kW)"].resample("ME").max(),
        "P min mois": df_final["Puissance réelle (kW)"].resample("ME").min(),
        "P moy mois": df_final["Puissance réelle (kW)"].resample("ME").mean(),
        "kWh mois": df_final["kWh"].resample("ME").sum(),
    }).reset_index().rename(columns={"Date et heure": "Mois"})

    agg_month["heures_mois"] = agg_month["Mois"].dt.daysinmonth * 24
    agg_month["Load factor mois (%)"] = np.where(
        agg_month["P max mois"] > 0,
        (agg_month["kWh mois"] / (agg_month["P max mois"] * agg_month["heures_mois"])) * 100,
        np.nan
    )
    agg_month.drop(columns=["heures_mois"], inplace=True)

    # Export Excel
    kpi_df = pd.DataFrame([{
        "Pointe globale (kW)": pmax,
        "Énergie totale (kWh)": e_kwh,
        "Énergie totale (MWh)": e_kwh / 1000,
        "Heures couvertes (h)": hours,
        "Pas de temps médian (min)": median_minutes,
        "Load factor global (pointe réelle) (%)": lf_pct,
        "Utilisation globale (palier dynamique) (%)": util_palier_pct,
        "Palier dynamique (kW)": palier,
    }])

    with pd.ExcelWriter(OUTPUT_EXCEL, engine="xlsxwriter") as writer:
        kpi_df.to_excel(writer, sheet_name="KPI", index=False)
        df_final.reset_index().to_excel(writer, sheet_name="Données Nettoyées", index=False)
        agg_15min.to_excel(writer, sheet_name="Stats 15min", index=False)
        agg_hour.to_excel(writer, sheet_name="Stats Heure", index=False)
        agg_day.to_excel(writer, sheet_name="Stats Jour", index=False)
        agg_month.to_excel(writer, sheet_name="Stats Mois", index=False)

    print("✅ Export terminé :", OUTPUT_EXCEL)
    print(f"📌 Load factor global (pointe réelle) ≈ {lf_pct:.2f}%")
    print(f"📌 Utilisation globale (palier {palier:.0f} kW) ≈ {util_palier_pct:.2f}%")
    print("🧾 Log :", LOG_FILE)

if __name__ == "__main__":
    run()
