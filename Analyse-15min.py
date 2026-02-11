import re
import unicodedata
import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

# =========================
# CONFIG PAGE
# =========================
st.set_page_config(layout="wide")
st.title("🔎 Analyse Hydro-Québec — 15 min / Jour (Upload)")

# =========================
# HELPERS
# =========================
def norm_col(s: str) -> str:
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, encoding="ISO-8859-1", sep=";")
    return pd.read_excel(uploaded_file)

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

    # Puissance kW
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

def clean_uploaded(df: pd.DataFrame, date_col: str, power_col: str) -> pd.DataFrame:
    d = df[[date_col, power_col]].copy()
    d.rename(columns={date_col: "Date et heure", power_col: "Puissance réelle (kW)"}, inplace=True)

    d["Puissance réelle (kW)"] = (
        d["Puissance réelle (kW)"].astype(str)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    d["Puissance réelle (kW)"] = pd.to_numeric(d["Puissance réelle (kW)"], errors="coerce")
    d["Date et heure"] = pd.to_datetime(d["Date et heure"], errors="coerce")

    d = d.dropna(subset=["Date et heure", "Puissance réelle (kW)"])
    d = d.drop_duplicates(subset=["Date et heure"]).sort_values("Date et heure")
    d = d.set_index("Date et heure")
    return d

def add_kwh(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_index().copy()
    delta_h = d.index.to_series().diff().dt.total_seconds().div(3600).fillna(0)
    d["delta_h"] = delta_h
    d["kWh"] = d["Puissance réelle (kW)"] * d["delta_h"]
    return d

# =========================
# UPLOAD
# =========================
uploaded_files = st.file_uploader(
    "Importe tes fichiers Hydro (CSV/XLSX). Tu peux en mettre plusieurs.",
    type=["csv", "xlsx"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("⬆️ Importe au moins 1 fichier pour commencer.")
    st.stop()

# =========================
# LECTURE + NETTOYAGE
# =========================
cleaned_list = []
rejected = []

for uf in uploaded_files:
    try:
        df_raw = read_uploaded_file(uf)
        st.write(f"📄 `{uf.name}` — colonnes détectées : {list(df_raw.columns)}")

        date_col, power_col = detect_columns(df_raw)

        # fallback manuel si non détecté
        if date_col is None or power_col is None:
            st.warning(f"⚠️ Détection auto impossible pour `{uf.name}`. Choisis manuellement :")
            date_col = st.selectbox(f"Colonne DATE — {uf.name}", options=list(df_raw.columns), key=f"d_{uf.name}")
            power_col = st.selectbox(f"Colonne kW — {uf.name}", options=list(df_raw.columns), key=f"p_{uf.name}")

        df_clean = clean_uploaded(df_raw, date_col, power_col)
        if df_clean.empty:
            rejected.append((uf.name, "Nettoyage = dataframe vide (dates/kW non valides)"))
            continue

        df_clean["Nom fichier"] = uf.name
        cleaned_list.append(df_clean)

        with st.expander(f"Aperçu `{uf.name}`"):
            st.dataframe(df_clean.reset_index().head(20), use_container_width=True)

    except Exception as e:
        rejected.append((uf.name, str(e)))

if rejected:
    st.warning("Certains fichiers ont été rejetés :")
    for name, reason in rejected:
        st.write(f"- {name} → {reason}")

if not cleaned_list:
    st.error("⛔ Aucun fichier valide après nettoyage. Tes colonnes date/kW ne matchent pas ou les valeurs sont illisibles.")
    st.stop()

# =========================
# CONCAT
# =========================
df_final = pd.concat(cleaned_list).sort_index()
df_final = add_kwh(df_final)

# Pas de temps médian
deltas = df_final.index.to_series().diff().dropna()
median_minutes = deltas.median().total_seconds() / 60 if not deltas.empty else np.nan

# KPI
pmax = float(df_final["Puissance réelle (kW)"].max())
hours = float(df_final["delta_h"].sum())
e_kwh = float(df_final["kWh"].sum())
load_factor_pct = (e_kwh / (pmax * hours) * 100) if (pmax > 0 and hours > 0) else np.nan

st.success(f"✅ Données prêtes — lignes: {len(df_final):,} | pas médian: {median_minutes:.2f} min")

# =========================
# DASHBOARD
# =========================
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("APPEL DE POINTE", f"{pmax:,.1f} kW")
with c2:
    st.metric("ÉNERGIE TOTALE", f"{e_kwh/1000:,.1f} MWh")
with c3:
    st.metric("HEURES COUVERTES", f"{hours:,.0f} h")
with c4:
    st.metric("FACTEUR D’UTILISATION (Load Factor)", f"{load_factor_pct:,.1f} %")

# =========================
# GRAPHIQUES
# =========================
left, right = st.columns(2)

with left:
    st.subheader("Consommation & pointe par mois")
    mon = pd.DataFrame({
        "Energie_kWh": df_final["kWh"].resample("ME").sum(),
        "Appel_kW": df_final["Puissance réelle (kW)"].resample("ME").max()
    }).dropna()
    if mon.empty:
        st.info("Pas assez de données pour une vue mensuelle.")
    else:
        mon_plot = mon.copy()
        mon_plot.index = mon_plot.index.strftime("%Y-%m")

        fig, ax1 = plt.subplots(figsize=(10, 5))
        ax1.bar(mon_plot.index, mon_plot["Energie_kWh"])
        ax1.set_ylabel("Énergie (kWh)")
        ax1.tick_params(axis="x", rotation=45)
        ax1.grid(True, axis="y", alpha=0.3)

        ax2 = ax1.twinx()
        ax2.plot(mon_plot.index, mon_plot["Appel_kW"], marker="o")
        ax2.set_ylabel("Appel (kW)")

        plt.tight_layout()
        st.pyplot(fig)

with right:
    st.subheader("Profil horaire moyen (si 15 min)")
    if not (10 <= median_minutes <= 20):
        st.info("Le profil horaire moyen est fiable seulement si tes données sont vraiment en 15 minutes.")
    tmp = df_final.copy()
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
# EXPORT EXCEL
# =========================
st.subheader("⬇️ Export Excel")
excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
    df_final.reset_index().to_excel(writer, sheet_name="Données nettoyées", index=False)
    mon.reset_index().to_excel(writer, sheet_name="Stats Mois", index=False)
    pd.DataFrame([{
        "Pointe (kW)": pmax,
        "Énergie totale (kWh)": e_kwh,
        "Énergie totale (MWh)": e_kwh/1000,
        "Heures couvertes (h)": hours,
        "Pas médian (min)": median_minutes,
        "Load factor (%)": load_factor_pct
    }]).to_excel(writer, sheet_name="KPI", index=False)

excel_buffer.seek(0)

st.download_button(
    "📥 Télécharger la synthèse Excel",
    data=excel_buffer.getvalue(),
    file_name="Synthese_Hydro.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
