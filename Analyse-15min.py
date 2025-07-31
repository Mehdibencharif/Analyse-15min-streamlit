import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

# Titre
st.title("Analyse des fichiers de consommation (15 min)")

# 📁 Téléversement de fichiers
uploaded_files = st.file_uploader("Importer vos fichiers (12 mois, 15 min)", type="csv", accept_multiple_files=True)

if uploaded_files:
    dfs = []

    for file in uploaded_files:
        df = pd.read_csv(file, encoding='utf-8', errors='replace')
        df['Date et heure'] = pd.to_datetime(df['Date et heure'], errors='coerce')
        df = df.set_index('Date et heure')
        dfs.append(df)

    # Fusion
    df_final = pd.concat(dfs).sort_index()
    df_final = df_final[~df_final.index.duplicated(keep='first')]  # enlever doublons éventuels

    st.success(f"{len(uploaded_files)} fichiers fusionnés. {len(df_final)} lignes totales.")

    # Analyse rapide
    st.subheader("Aperçu des données")
    st.dataframe(df_final.head())

    # Agrégation journalière
    agg_day = df_final.resample('D').agg({
        'Puissance réelle (kW)': ['max', 'mean', 'sum']
    }).dropna()

    agg_day.columns = ['P max', 'P moy', 'P totale']

    st.subheader("Graphique : Puissance quotidienne")
    st.line_chart(agg_day['P moy'])

    # Export Excel si demandé
    if st.button("📥 Exporter l'analyse en Excel"):
        output_path = "analyse_15min_export.xlsx"
        agg_day.to_excel(output_path)
        with open(output_path, "rb") as f:
            st.download_button("Télécharger le fichier", f, file_name=output_path)
