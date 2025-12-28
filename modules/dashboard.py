import streamlit as st
from . import database, config

def render_dashboard(supabase, user_id):
    st.markdown("## 📂 Dashboard Fascicoli")
    
    # 1. Recupera Fascicoli
    fascicoli = database.get_fascicoli_utente(supabase, user_id)
    
    # 2. BOX CREAZIONE NUOVO
    with st.expander("➕ CREA NUOVO FASCICOLO", expanded=not fascicoli):
        with st.form("new_case_form"):
            st.write("Dati generali del caso")
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome Riferimento (es. Causa Rossi c/ Bianchi)")
            
            # Select Tipo Causa da config fallback o DB
            opts_map = config.CASE_TYPES_FALLBACK
            try:
                db_types = database.get_config_tipi_causa(supabase)
                if db_types:
                    opts_map = {t['codice']: {"label": t['nome_visualizzato']} for t in db_types}
            except: pass
            
            tipo = c2.selectbox("Materia Giuridica", list(opts_map.keys()), format_func=lambda x: opts_map[x]['label'])
            
            cli = c1.text_input("Nome Cliente")
            ctr = c2.text_input("Nome Controparte")
            
            if st.form_submit_button("Crea Fascicolo", type="primary"):
                if nome and cli:
                    new_f = database.crea_fascicolo(supabase, user_id, nome, tipo, cli, ctr)
                    if new_f:
                        st.success(f"Fascicolo '{nome}' creato!")
                        st.session_state.current_fascicolo = new_f
                        # Reset stato chat per il nuovo caso
                        st.session_state.messages = []
                        st.session_state.contesto_chat = ""
                        st.session_state.dati_calc = "Nessun calcolo effettuato."
                        st.session_state.generated_docs_zip = None
                        st.rerun()
                else:
                    st.warning("Inserisci almeno Nome Riferimento e Cliente.")

    st.divider()

    # 3. LISTA FASCICOLI ESISTENTI
    if not fascicoli:
        st.info("Non hai ancora creato nessun fascicolo.")
        return

    st.subheader("I tuoi casi aperti")
    for f in fascicoli:
        with st.container():
            col_icon, col_info, col_act = st.columns([0.5, 4, 1.5])
            
            with col_icon:
                st.markdown("### 📁")
            
            with col_info:
                st.markdown(f"**{f['nome_riferimento']}**")
                aggr = f.get('livello_aggressivita', 5)
                st.caption(f"Cliente: {f.get('nome_cliente','-')} | Materia: {f.get('tipo_causa','-')} | Mood: {aggr}/10")
                
            with col_act:
                # Bottone APRI
                if st.button("APRI", key=f"open_{f['id']}", type="primary", use_container_width=True):
                    st.session_state.current_fascicolo = f
                    # Caricamento Stato
                    st.session_state.dati_calc = f.get('dati_tecnici') or "Nessun calcolo."
                    # NB: Qui in futuro caricheremo la chat history dal DB
                    st.session_state.messages = [] 
                    st.rerun()
                    
                # Bottone ELIMINA
                if st.button("Elimina", key=f"del_{f['id']}", use_container_width=True):
                    database.elimina_fascicolo(supabase, f['id'])
                    st.toast("Fascicolo eliminato")
                    st.rerun()
        st.markdown("---")
