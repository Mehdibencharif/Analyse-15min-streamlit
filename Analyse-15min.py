import re
import unicodedata
import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

from openpyxl.drawing.image import Image as XLImage

# =========================
# CONFIG PAGE
# =========================
st.set_page_config(layout="wide")
st.title("🔎 Analyse Hydro-Québec — 15 min / Jour (Upload)")

# =========================
# HELPERS (nettoyage)
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

    # --- Date
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

    # --- Puissance kW
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
        # fallback : première colonne contenant "kw"
        for c in cols:
            if "kw" in norm_col(c):
                power_col = c
                break

    return date_col, power_col

def clean_uploaded(df: pd.DataFrame, date_col: str, power_col: str) -> pd.DataFrame:
    d = df[[date_col, power_col]].copy()
    d.rename(columns={date_col: "Date et heure", power_col: "Puissance réelle (kW)"}, inplace=True)

    # Nettoyage puissance (virgules -> points, enlève espaces)
    d["Puissance réelle (kW)"] = (
        d["Puissance réelle (kW)"].astype(str)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    d["Puissance réelle (kW)"] = pd.to_numeric(d["Puissance réelle (kW)"], errors="coerce")

    # Date
    d["Date et heure"] = pd.to_datetime(d["Date et heure"], errors="coerce")

    # Drop NA
    d = d.dropna(subset=["Date et heure", "Puissance réelle (kW)"])

    # Doublons timestamp
    d = d.drop_duplicates(subset=["Date et heure"]).sort_values("Date et heure")

    # Index temps
    d = d.set_index("Date et heure")
    return d

# =========================
# HELPERS (énergie + palier + FU)
# =========================
def add_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule delta_h entre timestamps et kWh = kW * delta_h.
    IMPORTANT: si tes données sont à 15 minutes, delta_h ~ 0.25.
    """
    d = df.sort_index().copy()
    delta_h = d.index.to_series().diff().dt.total_seconds().div(3600)
    delta_h = delta_h.fillna(0)

    # si jamais un intervalle négatif ou zéro (rare), on clip à 0
    delta_h = delta_h.clip(lower=0)

    d["delta_h"] = delta_h
    d["kWh"] = d["Puissance réelle (kW)"] * d["delta_h"]
    return d

def compute_palier(puissance_max: float) -> int:
    """
    Même logique que ton script:
    <=500 -> 500
    <=700 -> 700
    <=1000 -> 1000
    sinon palier arrondi au 100 supérieur
    """
    if puissance_max <= 500:
        return 500
    elif puissance_max <= 700:
        return 700
    elif puissance_max <= 1000:
        return 1000
    else:
        return (int(puissance_max // 100) + 1) * 100

def add_palier_and_fu(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Ajoute:
    - Palier (kW)
    - Écart au palier (kW) = max(palier - P, 0)
    - Facteur d'utilisation (%) = P/palier*100
    """
    d = df.copy()
    pmax_local = float(d["Puissance réelle (kW)"].max())
    palier = compute_palier(pmax_local)

    d["Palier (kW)"] = palier
    d["Écart au palier (kW)"] = (palier - d["Puissance réelle (kW)"]).clip(lower=0)
    d["Facteur d'utilisation (%)"] = (d["Puissance réelle (kW)"] / palier) * 100
    return d, palier

def median_timestep_minutes(index: pd.DatetimeIndex) -> float:
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return float("nan")
    return float(deltas.median().total_seconds() / 60)

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
    st.error("⛔ Aucun fichier valide après nettoyage.")
    st.stop()

# =========================
# CONCAT + CALCULS
# =========================
df_final = pd.concat(cleaned_list).sort_index()

# kWh (delta_h + kWh)
df_final = add_kwh(df_final)

# Palier + colonnes FU (%), écart au palier, etc.
df_final, palier = add_palier_and_fu(df_final)

# =========================
# FACTEUR D'UTILISATION (même logique que ton script)
# =========================
# A) Recommandé : moyenne pondérée par le temps (robuste si trous/doublons)
den = df_final["delta_h"].sum()
fu_global_script_like = (
    (df_final["Facteur d'utilisation (%)"] * df_final["delta_h"]).sum() / den
) if den > 0 else np.nan

# B) Identique au .mean() du script (moins rigoureux)
fu_global_simple_mean = df_final["Facteur d'utilisation (%)"].mean()

# =========================
# KPI
# =========================
median_minutes = median_timestep_minutes(df_final.index)

pmax = float(df_final["Puissance réelle (kW)"].max())
hours = float(df_final["delta_h"].sum())
e_kwh = float(df_final["kWh"].sum())

# Affichage (choisis A ou B)
# st.metric("FACTEUR D’UTILISATION (mean)", f"{fu_global_simple_mean:,.1f} %")
st.metric("FACTEUR D’UTILISATION (comme script - pondéré temps)", f"{fu_global_script_like:,.1f} %")

st.success(
    f"✅ Données prêtes — lignes: {len(df_final):,} | pas médian: {median_minutes:.2f} min | palier: {palier} kW"
)

# =========================
# DASHBOARD
# =========================
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric("APPEL DE POINTE (mesuré)", f"{pmax:,.1f} kW")

with c2:
    st.metric("PALIER (kW)", f"{palier:,.0f} kW")

with c3:
    st.metric("ÉNERGIE TOTALE", f"{e_kwh/1000:,.1f} MWh")

with c4:
    st.metric("HEURES COUVERTES", f"{hours:,.0f} h")

with c5:
    # ✅ même logique que ton script (recommandé)
    st.metric("FACTEUR D’UTILISATION (comme script)", f"{fu_global_script_like:,.1f} %")
    # Si tu veux EXACTEMENT le mean du script, utilise plutôt :
    # st.metric("FACTEUR D’UTILISATION (mean)", f"{fu_global_simple_mean:,.1f} %")


# =========================
# TABLEAU MENSUEL (comme ton bloc 2)
# =========================
mon = pd.DataFrame({
    "Energie_kWh": df_final["kWh"].resample("ME").sum(),
    "P max mois": df_final["Puissance réelle (kW)"].resample("ME").max(),
    "P moy mois": df_final["Puissance réelle (kW)"].resample("ME").mean(),
    "FU moy mois (%)": df_final["Facteur d'utilisation (%)"].resample("ME").mean(),
}).dropna()

# FU global mensuel (ta formule script bloc 2)
# Énergie / (Pmax_mois * 24 * jours_du_mois) * 100
if not mon.empty:
    mon["FU global mois (%)"] = (mon["Energie_kWh"] / (mon["P max mois"] * 24 * mon.index.daysinmonth)) * 100

# =========================
# GRAPHIQUES + BUFFERS (pour Excel)
# =========================
fig_buffers = {}

def save_fig_to_buffer(fig, key: str):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    buf.seek(0)
    fig_buffers[key] = buf
    plt.close(fig)  # évite l'accumulation mémoire

left, right = st.columns(2)

# --- Graph 1 : facturée vs consommée (mensuel)
with left:
    st.subheader("Évolution mensuelle : puissance facturée vs consommée")
    if mon.empty:
        st.info("Pas assez de données pour une vue mensuelle.")
    else:
        df_plot = mon.copy()
        df_plot.index = df_plot.index.strftime("%Y-%m")

        fig1, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df_plot.index, df_plot["P max mois"], marker="o", label="Puissance facturée (P max)")
        ax.plot(df_plot.index, df_plot["P moy mois"], marker="o", label="Puissance consommée (P moy)")
        ax.set_title("Évolution mensuelle de la puissance facturée vs consommée")
        ax.set_xlabel("Mois")
        ax.set_ylabel("Puissance (kW)")
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", rotation=45)
        ax.legend()
        plt.tight_layout()
        st.pyplot(fig1)
        save_fig_to_buffer(fig1, "01_Puissance_facturee_vs_consommee")

# --- Graph 2 : profil horaire
with right:
    st.subheader("Profil horaire moyen (si données ~15 min)")
    if not (10 <= median_minutes <= 20):
        st.info("⚠️ Le profil horaire est fiable seulement si tes données sont vraiment en 15 minutes.")

    tmp = df_final.copy()
    tmp["Heure"] = tmp.index.hour
    hour_profile = tmp.groupby("Heure")["Puissance réelle (kW)"].mean()

    fig2, ax = plt.subplots(figsize=(10, 5))
    ax.plot(hour_profile.index, hour_profile.values, marker="o")
    ax.set_title("Profil horaire moyen")
    ax.set_xlabel("Heure")
    ax.set_ylabel("Puissance (kW)")
    ax.set_xticks(range(0, 24))
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    st.pyplot(fig2)
    save_fig_to_buffer(fig2, "02_Profil_horaire_moyen")

st.divider()

# =========================
# Répartition des puissances (graph propre + tables Excel)
# =========================
st.subheader("Répartition des puissances (tranches de 10 kW)")

bin_width = 10
pmax_local = float(df_final["Puissance réelle (kW)"].max())
end = int(np.ceil(pmax_local / bin_width) * bin_width) + bin_width
bins = np.arange(0, end + bin_width, bin_width)

values = df_final["Puissance réelle (kW)"].dropna().values

# --- Graph 3 : histogramme lisible (% du temps)
fig3, ax = plt.subplots(figsize=(14, 5))
ax.hist(
    values,
    bins=bins,
    weights=np.ones_like(values) * 100.0 / len(values),
    rwidth=0.9
)
ax.set_title("Répartition des puissances (tranches de 10 kW)")
ax.set_xlabel("Puissance (kW)")
ax.set_ylabel("Pourcentage de temps (%)")
ax.grid(True, axis="y", alpha=0.3)

tick_step = 100
ax.set_xticks(np.arange(0, end + 1, tick_step))

plt.tight_layout()
st.pyplot(fig3)
save_fig_to_buffer(fig3, "03_Repartition_puissance_10kW")

# --- Table 10 kW (détaillée) pour Excel (TOUJOURS définie)
df_tmp = df_final.copy()
df_tmp["Classe 10kW"] = pd.cut(
    df_tmp["Puissance réelle (kW)"],
    bins=bins,
    right=False,
    include_lowest=True
)
rep10 = df_tmp["Classe 10kW"].value_counts(normalize=True).sort_index() * 100
df_repartition = rep10.reset_index()
df_repartition.columns = ["Classe puissance (10 kW)", "Pourcentage (%)"]

# --- Table 50 kW (lisible) pour Excel
bin_width_excel = 50
end_e = int(np.ceil(pmax_local / bin_width_excel) * bin_width_excel) + bin_width_excel
bins_e = np.arange(0, end_e + bin_width_excel, bin_width_excel)

df_tmp2 = df_final.copy()
df_tmp2["Classe 50kW"] = pd.cut(
    df_tmp2["Puissance réelle (kW)"],
    bins=bins_e,
    right=False,
    include_lowest=True
)
rep50 = df_tmp2["Classe 50kW"].value_counts(normalize=True).sort_index() * 100
df_repartition_50 = rep50.reset_index()
df_repartition_50.columns = ["Classe puissance (50 kW)", "Pourcentage (%)"]

# =========================
# Puissance max mensuelle
# =========================
st.subheader("Puissances maximales mensuelles")
if mon.empty:
    st.info("Pas de données mensuelles.")
else:
    df_plot2 = mon.copy()
    df_plot2.index = df_plot2.index.strftime("%Y-%m")

    fig4, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df_plot2.index, df_plot2["P max mois"], marker="o")
    ax.set_title("Puissances maximales mensuelles")
    ax.set_xlabel("Mois")
    ax.set_ylabel("Puissance max (kW)")
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    st.pyplot(fig4)
    save_fig_to_buffer(fig4, "04_Puissance_max_mensuelle")

# =========================
# EXPORT EXCEL (avec images)
# =========================
st.subheader("⬇️ Export Excel (tableaux + graphiques)")

excel_buffer = io.BytesIO()

with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
    # Sheets data
    df_final.reset_index().to_excel(writer, sheet_name="Donnees_nettoyees", index=False)
    mon.reset_index().to_excel(writer, sheet_name="Stats_Mois", index=False)
    df_repartition.to_excel(writer, sheet_name="Repartition_10kW", index=False)
    df_repartition_50.to_excel(writer, sheet_name="Repartition_50kW", index=False)

    kpi_df = pd.DataFrame([{
        "Palier (kW)": palier,
        "Pointe mesurée (kW)": pmax,
        "Energie totale (kWh)": e_kwh,
        "Energie totale (MWh)": e_kwh / 1000,
        "Heures couvertes (h)": hours,
        "Pas median (min)": median_minutes,
        "FU global au palier (%)": fu_global_pct,
    }])
    kpi_df.to_excel(writer, sheet_name="KPI", index=False)

    # Add "Graphiques" sheet + images
    wb = writer.book
    ws = wb.create_sheet("Graphiques")

    row = 1
    for title, buf in fig_buffers.items():
        ws.cell(row=row, column=1, value=title)
        row += 1

        img = XLImage(buf)
        img.anchor = f"A{row}"
        ws.add_image(img)

        row += 28  # espace vertical entre images

excel_buffer.seek(0)

st.download_button(
    "📥 Télécharger la synthèse Excel",
    data=excel_buffer,
    file_name="Synthese_Hydro.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)








