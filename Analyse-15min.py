import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import io
import streamlit as st

import streamlit as st
import pandas as pd

# Configuration de la page pour une meilleure lisibilité
st.set_page_config(layout="wide")
st.title("🔎 Analyse de puissance - Données Hydro-Québec (15 min ou journalières)")

# 📂 Téléversement des fichiers CSV ou Excel
uploaded_files = st.file_uploader(
    "Importez vos fichiers de consommation (formats acceptés : CSV ou Excel)",
    type=["csv", "xlsx"],
    accept_multiple_files=True
)

# 📋 Vérification et affichage des fichiers importés
if uploaded_files:
    st.success(f"{len(uploaded_files)} fichier(s) téléchargé(s) avec succès :")
    for file in uploaded_files:
        st.markdown(f"- `{file.name}`")
else:
    st.warning("⚠️ Veuillez importer au moins un fichier pour démarrer l’analyse.")
    st.stop()


### Bloc 2 Nettoyage et harmonisation des fichiers #####
from datetime import datetime
import os

def clean_uploaded_file(uploaded_file):
    try:
        file_name = uploaded_file.name
        st.write(f"📄 Traitement : `{file_name}`")

        # Lecture du fichier selon extension
        if file_name.endswith('.csv'):
            df = pd.read_csv(uploaded_file, encoding='ISO-8859-1', sep=';')
        else:
            df = pd.read_excel(uploaded_file)

        # Détection du type de fichier
        if "15min" in file_name.lower():
            date_col = 'Date et heure'
        elif "jour" in file_name.lower():
            date_col = 'Date'
        else:
            st.warning(f"❌ Format non reconnu dans le nom de fichier : `{file_name}`")
            return None

        # Harmonisation des noms
        if 'Puissance réelle (kW)' not in df.columns:
            for col in df.columns:
                if 'puissance' in col.lower() and 'kW' in col:
                    df.rename(columns={col: 'Puissance réelle (kW)'}, inplace=True)
                    break

        # Vérification des colonnes essentielles
        if date_col not in df.columns or 'Puissance réelle (kW)' not in df.columns:
            st.warning(f"⚠️ Colonnes essentielles manquantes dans : `{file_name}`")
            return None

        # Nettoyage
        df['Puissance réelle (kW)'] = (
            df['Puissance réelle (kW)'].astype(str).str.replace(' ', '').str.replace(',', '.')
        )
        df['Puissance réelle (kW)'] = pd.to_numeric(df['Puissance réelle (kW)'], errors='coerce')
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        df = df[[date_col, 'Puissance réelle (kW)']].dropna().drop_duplicates(subset=[date_col])
        df.rename(columns={date_col: 'Date et heure'}, inplace=True)
        df['Nom fichier'] = file_name

        # Calcul du palier dynamique
        p_max = df['Puissance réelle (kW)'].max()
        if p_max <= 500:
            palier = 500
        elif p_max <= 700:
            palier = 700
        elif p_max <= 1000:
            palier = 1000
        else:
            palier = (int(p_max // 100) + 1) * 100

        df['Écart au palier (kW)'] = (palier - df['Puissance réelle (kW)']).clip(lower=0)
        df["Facteur d'utilisation (%)"] = df['Puissance réelle (kW)'] / palier * 100

        return df

    except Exception as e:
        st.error(f"❌ Erreur dans le fichier `{uploaded_file.name}` : {str(e)}")
        return None

# === BLOC 3 : Agrégation, indicateurs et export Excel ===

# === BLOC 3 : Agrégation, indicateurs et export Excel ===
import pandas as pd
from io import BytesIO

if 'df_final' in locals() and isinstance(df_final, pd.DataFrame) and not df_final.empty:
    df_15min = df_final.copy()
    df_15min.index = pd.to_datetime(df_15min.index, errors='coerce')

    if df_15min.index.tz is not None:
        df_15min = df_15min.tz_convert(None)
    if not df_15min.index.is_monotonic_increasing:
        df_15min.sort_index(inplace=True)

    # Agrégation 15 min
    agg_15min = df_15min.resample('15min').agg({
        'Puissance réelle (kW)': ['max', 'min', 'mean', 'sum'],
        'Écart au palier (kW)': 'mean',
        'Facteur d\'utilisation (%)': 'mean'
    }).reset_index()
    agg_15min.columns = ['Date et heure', 'P max 15min', 'P min 15min', 'P moy 15min', 'Somme Puissance 15min',
                         'Écart moyen 15min', 'Facteur utilisation 15min (%)']
    agg_15min['kWh 15min'] = agg_15min['Somme Puissance 15min'] * 0.25

    # Agrégation horaire
    agg_hour = df_15min.resample('h').agg({
        'Puissance réelle (kW)': ['max', 'min', 'mean', 'sum'],
        'Écart au palier (kW)': 'mean',
        'Facteur d\'utilisation (%)': 'mean'
    }).reset_index()
    agg_hour.columns = ['Date et heure', 'P max heure', 'P min heure', 'P moy heure', 'Somme Puissance heure',
                        'Écart moyen heure', 'Facteur utilisation heure (%)']
    agg_hour['kWh heure'] = agg_hour['Somme Puissance heure'] * 0.25

    # Agrégation journalière
    agg_day = df_15min.resample('D').agg({
        'Puissance réelle (kW)': ['max', 'min', 'mean', 'sum'],
        'Écart au palier (kW)': 'mean',
        'Facteur d\'utilisation (%)': 'mean'
    }).reset_index()
    agg_day.columns = ['Date', 'P max jour', 'P min jour', 'P moy jour', 'Somme Puissance jour',
                       'Écart moyen jour', 'Facteur utilisation jour (%)']
    agg_day['kWh jour'] = agg_day['Somme Puissance jour'] * 0.25

    # Agrégation mensuelle
    agg_month = df_15min.resample('ME').agg({  # ⚠️ Utilise 'ME' pour éviter le warning
        'Puissance réelle (kW)': ['max', 'min', 'mean', 'sum'],
        'Écart au palier (kW)': 'mean',
        'Facteur d\'utilisation (%)': 'mean'
    }).reset_index()
    agg_month.columns = ['Mois', 'P max mois', 'P min mois', 'P moy mois', 'Somme Puissance mois',
                         'Écart moyen mois', 'Facteur utilisation mois (%)']
    agg_month['kWh mois'] = agg_month['Somme Puissance mois'] * 0.25
    agg_month['Année'] = agg_month['Mois'].dt.year

    # Facteur d'utilisation global
    if (agg_month['P max mois'] > 0).all():
        agg_month['Facteur utilisation global (%)'] = (
            agg_month['kWh mois'] / (agg_month['P max mois'] * 24 * agg_month['Mois'].dt.daysinmonth)
        ) * 100
    else:
        agg_month['Facteur utilisation global (%)'] = None

    # Puissance moyenne restante
    agg_month['Puissance moyenne restante (kW)'] = (
        (1 - agg_month['Facteur utilisation mois (%)'] / 100) * agg_month['P max mois']
    )

    # Export Excel
    output_excel = BytesIO()
    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
        agg_15min.to_excel(writer, sheet_name='Stats 15min', index=False)
        agg_hour.to_excel(writer, sheet_name='Stats Heure', index=False)
        agg_day.to_excel(writer, sheet_name='Stats Jour', index=False)
        agg_month.to_excel(writer, sheet_name='Stats Mois', index=False)
        df_final.reset_index().to_excel(writer, sheet_name='Données Nettoyées', index=False)

    st.success("📊 Données agrégées avec succès.")

    # Téléchargement du fichier Excel
    st.download_button(
        label="📥 Télécharger le fichier Excel",
        data=output_excel.getvalue(),
        file_name="Synthese_Efficacite_Energetique.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.error("⛔ `df_final` est vide ou non défini. Aucune agrégation possible.")
    
# === BLOC 4 : Visualisations graphiques ===
import matplotlib.pyplot as plt

st.header("📈 Visualisation des données agrégées")

# --- Graphique 1 : Puissance moyenne journalière
if 'agg_day' in locals() and not agg_day.empty:
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(agg_day['Date'], agg_day['P moy jour'], label='Puissance moyenne', color='blue')
    ax1.set_ylabel("Puissance (kW)")
    ax1.set_xlabel("Date")
    ax1.set_title("Puissance moyenne journalière")
    ax1.legend()
    ax1.grid(True)
    st.pyplot(fig1)
else:
    st.warning("Aucune donnée journalière disponible pour afficher le graphique de puissance moyenne.")

# --- Graphique 2 : Facteur d’utilisation mensuel
if 'agg_month' in locals() and not agg_month.empty:
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    ax2.bar(agg_month['Mois'].dt.strftime('%Y-%m'), agg_month['Facteur utilisation mois (%)'], color='green')
    ax2.set_ylabel("Facteur d'utilisation (%)")
    ax2.set_xlabel("Mois")
    ax2.set_title("Facteur d'utilisation mensuel")
    plt.xticks(rotation=45)
    ax2.grid(True)
    st.pyplot(fig2)
else:
    st.warning("Aucune donnée mensuelle disponible pour afficher le graphique de facteur d’utilisation.")



