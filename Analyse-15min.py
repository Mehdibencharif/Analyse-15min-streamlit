import io
import re
import unicodedata
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

# =========================
# CONFIG PAGE
# =========================
st.set_page_config(layout="wide")
st.title("🔎 Analyse Hydro-Québec — Données 15 min / journalières")

# =========================
# HELPERS
# =========================
def norm_col(s: str) -> str:
    """Normalise un nom de colonne (sans accents, minuscule, espaces propres)."""
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def read_uploaded_file(uploaded_file: st.runtime.uploaded_file_manager.UploadedFile) -> pd.DataFrame:
    """Lit CSV (HQ souvent ; séparateur ;) ou Excel."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, encoding="ISO-8859-1", sep=";")
    return pd.read_excel(uploaded_file)

def detect_columns(df: pd.DataFrame):
    """
    Détecte automatiquement:
    - colonne date/datetime
    - colonne puissance (kW)
    Retourne (date_col, power_col) ou (None, None) si échec.
    """
    cols = list(df.columns)

    # ---- Date candidates
    date_candidates = []
    for c in cols:
        cn = norm_col(c)
        if any(k in cn for k in ["date", "heure", "horodate", "timestamp", "periode", "période"]):
            date_candidates.append(c)

    date_col = None
    # Priorité aux colonnes date+heure
    for c in date_candidates:
        cn = norm_col(c)
        if any(k in cn for k in ["date et heure", "horodate", "timestamp", "heure"]):
            date_col = c
            break
    if date_col is None and date_candidates:
        date_col = date_candidates[0]

    # ---- Power candidates
    power_col = None
    power_candidates = []
    for c in cols:
        cn = norm_col(c)
        # puissance / power / demande / appel + kw
        if ("kw" in cn) and any(k in cn for k in ["puissance", "power", "appel", "demande", "charge"]):
            power_candidates.append(c)

    # prioriser "reel/le"
    for c in power_candidates:
        cn = norm_col(c)
        if any(k in cn for k in ["reel", "reelle", "réel", "réelle", "mesuree", "mesuree"]):
            power_col = c
            break
    if power_col is None and power_candidates:
        power_col = power_candidates[0]

    # fallback: toute colonne contenant kw
    if power_col is None:
        for c in cols:
            if "kw" in norm_col(c):
                power_col = c
                break

    return date_col, power_col

def clean_one_file(uploaded_file) -> pd.DataFrame | None:
    """
    Nettoie un fichier:
    - identifie colonnes
    - convertit date
    - convertit puissance en float
    - renomme en format standard
    Retourne un DF standard avec colonnes:
      Date et heure (datetime),
      Puissance réelle (kW),
      Nom fichier
    """
    try:
        file_name = uploaded_file.name
        st.write(f"📄 Traitement : `{file_name}`")
        df = read_uploaded_file(uploaded_file)

        # Affiche les colonnes pour debug
        st.caption(f"Colonnes détectées : {list(df.columns)}")

        date_col, power_col = detect_columns(df)

        # Fallback manuel si la détection échoue
        if date_col is None or power_col is None:
            st.warning(f"⚠️ Colonnes non détectées automatiquement pour `{file_name}`. Sélection manuelle :")
            date_col = st.selectbox(
                f"Choisir la colonne DATE pour {file_name}",
                options=list(df.columns),
                key=f"date_{file_name}"
            )
            power_col = st.selectbox(
                f"Choisir la colonne PUISSANCE (kW) pour {file_name}",
                options=list(df.columns),
                key=f"pow_{file_name}"
            )

        # Sous-ensemble
        df = df[[date_col, power_col]].copy()

        # Nettoyage puissance
        df[power_col] = (
            df[power_col].astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        df[power_col] = pd.to_numeric(df[power_col], errors="coerce")

        # Nettoyage date
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

        df = df.dropna().drop_duplicates(subset=[date_col])
        df.rename(columns={date_col: "Date et heure", power_col: "Puissance réelle (kW)"}, inplace=True)
        df["Nom fichier"] = file_name

        return df

    except Exception as e:
        st.error(f"❌ Erreur dans `{uploaded_file.name}` : {e}")
        return None

def compute_paliers(df: pd.DataFrame) -> float:
    """Palier dynamique basé sur la pointe."""
    p_max = float(df["Puissance réelle (kW)"].max())
    if p_max <= 500:
        return 500.0
    if p_max <= 700:
        return 700.0
    if p_max <= 1000:
        return 1000.0
    return float((int(p_max // 100) + 1) * 100)

def add_kwh_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute kWh.
    Hypothèse:
    - si données 15 min => 0.25 h par point
    - sinon (journalier/irrégulier) => on approx via delta_t (robuste)
    """
    d = df.copy()
    d = d.sort_index()

    # Estimation pas de temps médian
    deltas = d.index.to_series().diff().dropna()
    if deltas.empty:
        d["kWh"] = np.nan
        return d

    median_minutes = deltas.median().total_seconds() / 60

    if 10 <= median_minutes <= 20:
        # 15 min typique
        d["kWh"] = d["Puissance réelle (kW)"] * 0.25
        d.attrs["mode"] = "15min"
    elif 1300 <= median_minutes <= 1600:
        # ~24h
        d["kWh"] = d["Puissance réelle (kW)"] * 24.0
        d.attrs["mode"] = "jour"
    else:
        # Générique : kWh = kW * (delta_h)
        delta_h = d.index.to_series().diff().dt.total_seconds().div(3600)
        d["kWh"] = d["Puissance réelle (kW)"] * delta_h
        d.attrs["mode"] = "irregulier"

    return d

# =========================
# UPLOAD UI
# =========================
uploaded_files = st.file_uploader(
    "Importez vos fichiers (CSV/XLSX). Vous pouvez en mettre plusieurs (15 min ou journaliers).",
    type=["csv", "xlsx"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.warning("⚠️ Importe au moins un fichier pour démarrer.")
    st.stop()

st.success(f"{len(uploaded_files)} fichier(s) téléchargé(s) :")
for f in uploaded_files:
    st.markdown(f"- `{f.name}`")

# =========================
# NETTOYAGE + CONCAT
# =========================
cleaned = []
for uf in uploaded_files:
    df_clean = clean_one_file(uf)
    if df_clean is not None and not df_clean.empty:
        cleaned.append(df_clean)

if not cleaned:
    st.error("⛔ Aucun fichier valide après nettoyage.")
    st.stop()

df_final = pd.concat(cleaned, ignore_index=True)
df_final["Date et heure"] = pd.to_datetime(df_final["Date et heure"], errors="coerce")
df_final = df_final.dropna(subset=["Date et heure", "Puissance réelle (kW)"])
df_final = df_final.drop_duplicates(subset=["Date et heure"]).sort_values("Date et heure")
df_final = df_final.set_index("Date et heure")

st.info(f"📈 Plage temporelle : {df_final.index.min()} → {df_final.index.max()} | Lignes: {len(df_final):,}")

# =========================
# PARAMS DASHBOARD
# =========================
st.subheader("⚙️ Paramètres d’analyse")
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    palier_mode = st.selectbox("Palier (pour facteur utilisation)", ["Auto", "Manuel"], index=0)
with c2:
    palier_manual = st.number_input("Palier manuel (kW)", min_value=0.0, value=700.0, step=50.0, disabled=(palier_mode != "Manuel"))
with c3:
    shave_ratio = st.slider("Seuil d’écrêtage batterie (% de la pointe)", 50, 95, 90, 5)

# =========================
# CALCULS KPI
# =========================
df_work = df_final.copy()

# Palier
if palier_mode == "Manuel":
    palier_kw = float(palier_manual)
else:
    palier_kw = compute_paliers(df_work)

# KPI pointe
peak_kw = float(df_work["Puissance réelle (kW)"].max())
peak_ts = df_work["Puissance réelle (kW)"].idxmax()

# kWh robuste
df_work = add_kwh_column(df_work)

mode_data = df_work.attrs.get("mode", "inconnu")

# Energie totale
total_kwh = float(df_work["kWh"].sum()) if df_work["kWh"].notna().any() else np.nan
total_mwh = total_kwh / 1000 if np.isfinite(total_kwh) else np.nan

# Facteur d’utilisation global (sur la période)
hours_total = (df_work.index.max() - df_work.index.min()).total_seconds() / 3600
fu_pct = (total_kwh / (palier_kw * hours_total) * 100) if (hours_total > 0 and np.isfinite(total_kwh)) else np.nan

# Potentiel batterie (indicateur simple)
shave_level = (shave_ratio / 100.0) * peak_kw
kW_ecretable = (df_work["Puissance réelle (kW)"] - shave_level).clip(lower=0)
ecretable_kwh = float((kW_ecretable * 0.25).sum()) if mode_data == "15min" else np.nan
ecretable_kw_peak = float(kW_ecretable.max()) if mode_data == "15min" else np.nan

# =========================
# DASHBOARD (KPI CARDS)
# =========================
st.subheader("📌 Tableau de bord")

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("APPEL DE POINTE", f"{peak_kw:,.1f} kW", help=f"Date/heure: {peak_ts}")
with k2:
    st.metric("FACTEUR D’UTILISATION", f"{fu_pct:.1f} %", help=f"Palier: {palier_kw:,.0f} kW")
with k3:
    st.metric("CONSOMMATION (PÉRIODE)", f"{total_mwh:,.1f} MWh", help=f"Mode données détecté: {mode_data}")
with k4:
    if mode_data != "15min":
        st.metric("POTENTIEL BATTERIE", "N/A", help="Le calcul d’écrêtage batterie exige des données 15 minutes.")
    else:
        pot = "Faible"
        if ecretable_kwh > 5_000:
            pot = "Moyen"
        if ecretable_kwh > 20_000:
            pot = "Haut"
        st.metric("POTENTIEL BATTERIE", pot, help=f"Énergie écrêtable: {ecretable_kwh:,.0f} kWh | Pic écrêtable: {ecretable_kw_peak:,.1f} kW")

# =========================
# GRAPHIQUES (style capture)
# =========================
left, right = st.columns(2)

# Consommation et pointes par mois
with left:
    st.markdown("### Consommation et Pointes par mois")
    # Mois: énergie (kWh) + pointe (kW)
    mon = pd.DataFrame({
        "Energie_kWh": df_work["kWh"].resample("ME").sum(),
        "Appel_kW": df_work["Puissance réelle (kW)"].resample("ME").max()
    }).dropna()

    if mon.empty:
        st.warning("Aucune donnée mensuelle calculable.")
    else:
        mon.index = mon.index.strftime("%Y-%m")

        fig, ax1 = plt.subplots(figsize=(10, 5))
        ax1.bar(mon.index, mon["Energie_kWh"])
        ax1.set_ylabel("Énergie (kWh)")
        ax1.set_xlabel("Mois")
        ax1.tick_params(axis="x", rotation=45)
        ax1.grid(True, axis="y", alpha=0.3)

        ax2 = ax1.twinx()
        ax2.plot(mon.index, mon["Appel_kW"], marker="o")
        ax2.set_ylabel("Appel (kW)")

        plt.tight_layout()
        st.pyplot(fig)

# Profil horaire moyen (seulement si 15min)
with right:
    st.markdown("### Profil de charge horaire moyen")
    if mode_data != "15min":
        st.info("Profil horaire moyen indisponible sans données 15 minutes.")
    else:
        tmp = df_work.copy()
        tmp["Heure"] = tmp.index.hour
        hour_profile = tmp.groupby("Heure")["Puissance réelle (kW)"].mean()

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(hour_profile.index, hour_profile.values, marker="o")
        ax.set_xlabel("Heure")
        ax.set_ylabel("Puissance (kW)")
        ax.set_xticks(range(0, 24))
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        st.pyplot(fig)

# =========================
# EXPORT EXCEL (LIEN STREAMLIT)
# =========================
st.subheader("⬇️ Export Excel")

excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
    df_work.reset_index().to_excel(writer, sheet_name="Données nettoyées", index=False)

    # Stats mois
    mon_out = mon.reset_index().rename(columns={"index": "Mois"}) if "mon" in locals() and not mon.empty else pd.DataFrame()
    if not mon_out.empty:
        mon_out.to_excel(writer, sheet_name="Stats Mois", index=False)

    # KPI
    kpi_df = pd.DataFrame([{
        "Pointe (kW)": peak_kw,
        "Date/heure pointe": str(peak_ts),
        "Palier (kW)": palier_kw,
        "Facteur utilisation global (%)": fu_pct,
        "Consommation totale (kWh)": total_kwh,
        "Consommation totale (MWh)": total_mwh,
        "Mode données": mode_data,
        "Seuil écrêtage (% pointe)": shave_ratio,
        "Seuil écrêtage (kW)": shave_level,
        "Énergie écrêtable (kWh) (si 15min)": ecretable_kwh,
        "Pic écrêtable (kW) (si 15min)": ecretable_kw_peak
    }])
    kpi_df.to_excel(writer, sheet_name="KPI", index=False)

excel_buffer.seek(0)

st.download_button(
    label="📥 Télécharger la synthèse Excel",
    data=excel_buffer.getvalue(),
    file_name="Synthese_Hydro.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

with st.expander("🔍 Aperçu des données (10 premières lignes)"):
    st.dataframe(df_work.reset_index().head(10), use_container_width=True)
