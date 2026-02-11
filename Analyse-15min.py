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
def clean_uploaded_file(uploaded_file) -> pd.DataFrame | None:
    """
    Retourne un DF avec:
    - Date et heure (datetime)
    - kW (float)
    - Nom fichier
    """
    try:
        file_name = uploaded_file.name
        name_low = file_name.lower()
        st.write(f"📄 Traitement : `{file_name}`")

        # Lecture
        if name_low.endswith(".csv"):
            df = pd.read_csv(uploaded_file, encoding="ISO-8859-1", sep=";")
        else:
            df = pd.read_excel(uploaded_file)

        # Détection colonne date
        # (Ne te bloque pas sur le nom du fichier; on check aussi les colonnes)
        date_col = None
        if "Date et heure" in df.columns:
            date_col = "Date et heure"
        elif "Date" in df.columns:
            date_col = "Date"

        if date_col is None:
            st.warning(f"⚠️ Colonne date introuvable dans `{file_name}` (attendu: 'Date et heure' ou 'Date').")
            return None

        # Détection colonne puissance
        p_col = None
        if "Puissance réelle (kW)" in df.columns:
            p_col = "Puissance réelle (kW)"
        else:
            for col in df.columns:
                c = col.lower()
                if ("puissance" in c) and ("kw" in c):
                    p_col = col
                    break

        if p_col is None:
            st.warning(f"⚠️ Colonne puissance introuvable dans `{file_name}`.")
            return None

        # Nettoyage puissance
        df[p_col] = (
            df[p_col].astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        df[p_col] = pd.to_numeric(df[p_col], errors="coerce")

        # Date -> datetime
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

        df = df[[date_col, p_col]].dropna().drop_duplicates(subset=[date_col]).copy()
        df.rename(columns={date_col: "Date et heure", p_col: "kW"}, inplace=True)
        df["Nom fichier"] = file_name

        return df

    except Exception as e:
        st.error(f"❌ Erreur dans `{uploaded_file.name}` : {e}")
        return None


cleaned_list = []
for uf in uploaded_files:
    out = clean_uploaded_file(uf)
    if out is not None and not out.empty:
        cleaned_list.append(out)

if not cleaned_list:
    st.error("⛔ Aucun fichier valide après nettoyage.")
    st.stop()

df_final = pd.concat(cleaned_list, ignore_index=True)
df_final["Date et heure"] = pd.to_datetime(df_final["Date et heure"], errors="coerce")
df_final = df_final.dropna(subset=["Date et heure", "kW"])
df_final = df_final.drop_duplicates(subset=["Date et heure"])
df_final = df_final.sort_values("Date et heure")
df_final = df_final.set_index("Date et heure")

# Assurer index naïf (sans timezone)
if df_final.index.tz is not None:
    df_final = df_final.tz_convert(None)

st.info(f"📈 Plage temporelle : {df_final.index.min()} → {df_final.index.max()} | Lignes: {len(df_final):,}")

# ----------------------------
# PARAMS KPI
# ----------------------------
st.subheader("⚙️ Paramètres")
cA, cB, cC = st.columns([1, 1, 2])

with cA:
    palier_mode = st.selectbox("Palier pour facteur d’utilisation", ["Auto (basé sur la pointe)", "Manuel"], index=0)
with cB:
    palier_manual = st.number_input("Palier (kW)", min_value=0.0, value=700.0, step=50.0, disabled=(palier_mode != "Manuel"))
with cC:
    shave_ratio = st.slider("Seuil écrêtage batterie (% de la pointe)", min_value=50, max_value=95, value=90, step=5)

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
