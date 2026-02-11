import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

# ----------------------------
# CONFIG
# ----------------------------
st.set_page_config(layout="wide")
st.title("🔎 Analyse Hydro-Québec — Profil 15 min (12 mois)")

# ----------------------------
# UPLOAD
# ----------------------------
uploaded_files = st.file_uploader(
    "Importez vos fichiers Hydro (CSV ou Excel). Idéalement 15 min. (Vous pouvez en mettre plusieurs)",
    type=["csv", "xlsx"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.warning("⚠️ Veuillez importer au moins un fichier pour démarrer l’analyse.")
    st.stop()

st.success(f"{len(uploaded_files)} fichier(s) téléchargé(s) :")
for f in uploaded_files:
    st.markdown(f"- `{f.name}`")

# ----------------------------
# CLEANING
# ----------------------------
import unicodedata
import re
import pandas as pd
import streamlit as st

def _norm(s: str) -> str:
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def clean_uploaded_file(uploaded_file):
    try:
        file_name = uploaded_file.name
        st.write(f"📄 Traitement : `{file_name}`")

        # Lecture
        if file_name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded_file, encoding="ISO-8859-1", sep=";")
        else:
            df = pd.read_excel(uploaded_file)

        # --- Normaliser les noms de colonnes
        col_map = {c: _norm(c) for c in df.columns}
        inv_map = {v: k for k, v in col_map.items()}  # norm -> original

        # Affiche colonnes (utile au debug)
        st.caption(f"Colonnes: {list(df.columns)}")

        # --- Détecter colonne date
        date_candidates = []
        for c in df.columns:
            cn = _norm(c)
            if ("date" in cn) or ("heure" in cn) or ("horodate" in cn) or ("timestamp" in cn) or ("periode" in cn):
                date_candidates.append(c)

        date_col = None
        # Priorité à une colonne qui contient date+heure
        for c in date_candidates:
            cn = _norm(c)
            if ("heure" in cn) or ("horodate" in cn) or ("timestamp" in cn) or ("date et heure" in cn):
                date_col = c
                break
        if date_col is None and date_candidates:
            date_col = date_candidates[0]

        # --- Détecter colonne puissance kW
        p_candidates = []
        for c in df.columns:
            cn = _norm(c)
            if ("kw" in cn) and ("puissance" in cn or "power" in cn or "appel" in cn or "demande" in cn):
                p_candidates.append(c)

        p_col = None
        if p_candidates:
            # prioriser "reelle"
            for c in p_candidates:
                if "reel" in _norm(c) or "reelle" in _norm(c):
                    p_col = c
                    break
            if p_col is None:
                p_col = p_candidates[0]
        else:
            # fallback : toute colonne qui contient "kw"
            for c in df.columns:
                if "kw" in _norm(c):
                    p_col = c
                    break

        # --- Fallback UI si détection échoue
        if date_col is None or p_col is None:
            st.warning(f"⚠️ Détection automatique impossible pour `{file_name}`. Choisis les colonnes manuellement :")
            date_col = st.selectbox(f"Colonne DATE pour {file_name}", options=list(df.columns), key=f"date_{file_name}")
            p_col = st.selectbox(f"Colonne PUISSANCE (kW) pour {file_name}", options=list(df.columns), key=f"p_{file_name}")

        # --- Nettoyage valeurs
        df = df[[date_col, p_col]].copy()

        df[p_col] = (
            df[p_col].astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        df[p_col] = pd.to_numeric(df[p_col], errors="coerce")

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

        df = df.dropna().drop_duplicates(subset=[date_col])
        df.rename(columns={date_col: "Date et heure", p_col: "Puissance réelle (kW)"}, inplace=True)
        df["Nom fichier"] = file_name

        # Calcul palier
        p_max = df["Puissance réelle (kW)"].max()
        if p_max <= 500:
            palier = 500
        elif p_max <= 700:
            palier = 700
        elif p_max <= 1000:
            palier = 1000
        else:
            palier = (int(p_max // 100) + 1) * 100

        df["Écart au palier (kW)"] = (palier - df["Puissance réelle (kW)"]).clip(lower=0)
        df["Facteur d'utilisation (%)"] = df["Puissance réelle (kW)"] / palier * 100

        return df

    except Exception as e:
        st.error(f"❌ Erreur dans le fichier `{uploaded_file.name}` : {str(e)}")
        return None

# ----------------------------
# CALCULS ROBUSTES
# ----------------------------
df = df_final.copy()

# kWh sur 15 minutes (fondamental)
df["kWh_15min"] = df["kW"] * 0.25

peak_kw = float(df["kW"].max())
peak_ts = df["kW"].idxmax()

# Palier
if palier_mode == "Manuel":
    palier_kw = float(palier_manual)
else:
    palier_kw = float(np.ceil(peak_kw / 100) * 100)

# Durée totale (heures) pour facteur global
hours_total = (df.index.max() - df.index.min()).total_seconds() / 3600
fu_pct = float((df["kWh_15min"].sum() / (palier_kw * hours_total)) * 100) if hours_total > 0 else np.nan

annual_mwh = float(df["kWh_15min"].sum() / 1000)

# Potentiel batterie (simple indicateur)
shave_level = (shave_ratio / 100.0) * peak_kw
df["kW_ecretable"] = (df["kW"] - shave_level).clip(lower=0)
ecretable_kwh = float((df["kW_ecretable"] * 0.25).sum())
ecretable_kw_peak = float(df["kW_ecretable"].max())

# Agrégations correctes (à partir de kWh)
agg_15min = pd.DataFrame({
    "kW": df["kW"].resample("15min").mean(),
    "kWh": df["kWh_15min"].resample("15min").sum(),
    "kW_max": df["kW"].resample("15min").max(),
}).reset_index()

agg_hour = pd.DataFrame({
    "kWh": df["kWh_15min"].resample("H").sum(),
    "kW_max": df["kW"].resample("H").max(),
    "kW_moy": df["kW"].resample("H").mean(),
}).reset_index()

agg_day = pd.DataFrame({
    "kWh": df["kWh_15min"].resample("D").sum(),
    "kW_max": df["kW"].resample("D").max(),
    "kW_moy": df["kW"].resample("D").mean(),
}).reset_index()

agg_month = pd.DataFrame({
    "kWh": df["kWh_15min"].resample("ME").sum(),
    "kW_max": df["kW"].resample("ME").max(),
    "kW_moy": df["kW"].resample("ME").mean(),
}).reset_index()

# Facteur d’utilisation mensuel (défendable) = kWh / (kW_max * heures du mois)
agg_month["Mois"] = pd.to_datetime(agg_month["Date et heure"])
agg_month["heures_mois"] = agg_month["Mois"].dt.daysinmonth * 24
agg_month["Facteur utilisation mois (%)"] = np.where(
    agg_month["kW_max"] > 0,
    (agg_month["kWh"] / (agg_month["kW_max"] * agg_month["heures_mois"])) * 100,
    np.nan
)
agg_month["Mois_str"] = agg_month["Mois"].dt.strftime("%Y-%m")
agg_month = agg_month.drop(columns=["heures_mois"])

# Profil horaire moyen
df_hour_profile = df.copy()
df_hour_profile["Heure"] = df_hour_profile.index.hour
hour_profile = df_hour_profile.groupby("Heure")["kW"].mean()

# ----------------------------
# DASHBOARD (visuel type capture)
# ----------------------------
st.subheader("📌 Tableau de bord")

k1, k2, k3, k4 = st.columns(4)

with k1:
    st.metric("APPEL DE POINTE", f"{peak_kw:,.1f} kW", help=f"Date/heure: {peak_ts}")
with k2:
    st.metric("FACTEUR D'UTILISATION", f"{fu_pct:.1f} %", help=f"Palier utilisé: {palier_kw:,.0f} kW")
with k3:
    st.metric("CONSOMMATION (PÉRIODE)", f"{annual_mwh:,.1f} MWh")
with k4:
    pot = "Faible"
    if ecretable_kwh > 5_000:
        pot = "Moyen"
    if ecretable_kwh > 20_000:
        pot = "Haut"
    st.metric("POTENTIEL BATTERIE", pot, help=f"Énergie écrêtable: {ecretable_kwh:,.0f} kWh | Pic écrêtable: {ecretable_kw_peak:,.1f} kW")

left, right = st.columns(2)

with left:
    st.markdown("### Consommation et Pointes par Mois")
    # Bar = énergie, line = pointe
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(agg_month["Mois_str"], agg_month["kWh"])
    ax1.set_ylabel("Énergie (kWh)")
    ax1.set_xlabel("Mois")
    ax1.tick_params(axis='x', rotation=45)
    ax1.grid(True, axis="y", alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(agg_month["Mois_str"], agg_month["kW_max"], marker="o")
    ax2.set_ylabel("Appel (kW)")

    plt.tight_layout()
    st.pyplot(fig)

with right:
    st.markdown("### Profil de Charge Horaire Moyen")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(hour_profile.index, hour_profile.values, marker="o")
    ax.set_xlabel("Heure")
    ax.set_ylabel("Puissance (kW)")
    ax.set_xticks(range(0, 24))
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    st.pyplot(fig)

# ----------------------------
# EXPORT EXCEL (lien Streamlit)
# ----------------------------
st.subheader("⬇️ Export")

excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
    df.reset_index().to_excel(writer, sheet_name="Données 15min", index=False)
    agg_15min.to_excel(writer, sheet_name="Stats 15min", index=False)
    agg_hour.to_excel(writer, sheet_name="Stats Heure", index=False)
    agg_day.to_excel(writer, sheet_name="Stats Jour", index=False)
    agg_month[["Mois_str", "kWh", "kW_max", "kW_moy", "Facteur utilisation mois (%)"]].to_excel(writer, sheet_name="Stats Mois", index=False)

    kpi_df = pd.DataFrame([{
        "Pointe (kW)": peak_kw,
        "Date/heure pointe": str(peak_ts),
        "Palier (kW)": palier_kw,
        "Facteur d'utilisation global (%)": fu_pct,
        "Conso période (MWh)": annual_mwh,
        f"Seuil écrêtage ({shave_ratio}% pointe) (kW)": shave_level,
        "Énergie écrêtable (kWh)": ecretable_kwh,
        "Pic écrêtable (kW)": ecretable_kw_peak,
    }])
    kpi_df.to_excel(writer, sheet_name="KPI", index=False)

excel_buffer.seek(0)

st.download_button(
    label="📥 Télécharger la synthèse Excel",
    data=excel_buffer.getvalue(),
    file_name="Synthese_Hydro_15min.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# (Optionnel) aperçu tableau
with st.expander("🔍 Aperçu des données mensuelles"):
    st.dataframe(agg_month[["Mois_str", "kWh", "kW_max", "Facteur utilisation mois (%)"]], use_container_width=True)

