import streamlit as st
import pandas as pd
import io

st.title("Analyse de données Hydro-Québec – 15 min")

# 📁 Téléversement de fichiers
uploaded_files = st.file_uploader("Importer vos fichiers (12 mois, 15 min)", type="csv", accept_multiple_files=True)

if uploaded_files:
    dfs = []

    for file in uploaded_files:
        try:
            # Lire le fichier avec gestion des encodages
            content = file.getvalue()
            try:
                df = pd.read_csv(io.StringIO(content.decode('utf-8')))
            except UnicodeDecodeError:
                df = pd.read_csv(io.StringIO(content.decode('ISO-8859-1')))

            # Nettoyer les noms de colonnes
            df.columns = df.columns.str.strip()

            # 🔍 Afficher les colonnes disponibles (pour debug)
            st.write(f"📄 Colonnes dans {file.name} :", df.columns.tolist())

            # Trouver dynamiquement la colonne de date
            date_col = next((col for col in df.columns if 'date' in col.lower()), None)

            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.set_index(date_col)
                dfs.append(df)
            else:
                st.warning(f"⚠️ Le fichier {file.name} ne contient pas de colonne de date identifiable. Ignoré.")
        except Exception as e:
            st.error(f"❌ Erreur lors du traitement de {file.name} : {e}")

    if dfs:
        df_final = pd.concat(dfs).sort_index()
        df_final = df_final[~df_final.index.duplicated(keep='first')]
        st.success(f"✅ {len(uploaded_files)} fichiers fusionnés – {len(df_final)} lignes totales.")
        st.dataframe(df_final.head())
    else:
        st.error("🚫 Aucun fichier valide n’a été chargé.")
