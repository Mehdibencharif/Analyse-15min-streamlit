import streamlit as st
import pandas as pd
import io

# Titre principal
st.title("🔍 Analyse des données Hydro-Québec – Intervalles de 15 minutes")

# Section : Téléversement de fichiers
st.header("📁 Importer vos fichiers (12 mois, 15 min)")
uploaded_files = st.file_uploader("Sélectionnez un ou plusieurs fichiers CSV", type=["csv"], accept_multiple_files=True)

# Traitement des fichiers
if uploaded_files:
    dfs = []
    for file in uploaded_files:
        try:
            # Décodage avec gestion d’erreurs
            content = file.getvalue()
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                decoded = content.decode("ISO-8859-1")

            df = pd.read_csv(io.StringIO(decoded))

            # Nettoyage et validation de la structure
            if 'Date et heure' not in df.columns:
                st.warning(f"⛔ Le fichier **{file.name}** ne contient pas la colonne 'Date et heure'. Ignoré.")
                continue

            df['Date et heure'] = pd.to_datetime(df['Date et heure'], errors='coerce')
            df.dropna(subset=['Date et heure'], inplace=True)
            df = df.set_index('Date et heure')
            dfs.append(df)

        except Exception as e:
            st.error(f"Erreur lors du traitement du fichier **{file.name}** : {e}")

    # Fusion et affichage
    if dfs:
        df_final = pd.concat(dfs).sort_index()
        df_final = df_final[~df_final.index.duplicated(keep='first')]  # suppression des doublons temporels
        st.success(f"✅ {len(uploaded_files)} fichiers fusionnés avec succès ({len(df_final)} lignes).")
        st.dataframe(df_final.head(100))
    else:
        st.error("❌ Aucun fichier valide n’a été chargé.")
