import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
st.title("Analyse de données Hydro-Québec – 15 min")

# 📁 Téléversement de fichiers multiples
uploaded_files = st.file_uploader("Importer vos fichiers (12 mois, 15 min)", type="csv", accept_multiple_files=True)

if uploaded_files:
    dfs = []

    for uploaded_file in uploaded_files:
        try:
            # Tentative de décodage en UTF-8
            content = uploaded_file.getvalue().decode('utf-8')
        except UnicodeDecodeError:
            # Si UTF-8 échoue, essayer ISO-8859-1
            content = uploaded_file.getvalue().decode('ISO-8859-1')

        # Lire le CSV à partir du contenu décodé
        df = pd.read_csv(io.StringIO(content))

        # Conversion de la colonne date
        if 'Date et heure' in df.columns:
            df['Date et heure'] = pd.to_datetime(df['Date et heure'], errors='coerce')
            df = df.set_index('Date et heure')
            dfs.append(df)
        else:
            st.warning(f"⚠️ Le fichier « {uploaded_file.name} » ne contient pas la colonne 'Date et heure'.")

    # Fusion et tri
    if dfs:
        df_final = pd.concat(dfs).sort_index()
        df_final = df_final[~df_final.index.duplicated(keep='first')]

        st.success(f"{len(uploaded_files)} fichiers fusionnés. {len(df_final)} lignes au total.")
        st.dataframe(df_final.head())
    else:
        st.error("Aucun fichier valide n’a pu être traité."


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
