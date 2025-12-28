import streamlit as st
import json
from datetime import datetime
from modules import config, database, auth, admin, ai_engine, doc_renderer, dashboard, utils

# 1. CONFIGURAZIONE PAGINA
st.set_page_config(page_title=config.APP_NAME, layout="wide", page_icon="⚖️")

# 2. INIZIALIZZAZIONE SERVIZI
supabase = database.init_supabase()
ai_engine.init_ai()

# 3. SESSION STATE
init_vars = {
    "auth_status": "logged_out", 
    "sanitizer": ai_engine.DataSanitizer(),
    "messages": [], 
    "contesto_chat": "", 
    "dati_calc": "Nessun dato.",
    "workflow_step": "CHAT", 
    "current_fascicolo": None, 
    "generated_docs_zip": None
}
for k, v in init_vars.items():
    if k not in st.session_state: st.session_state[k] = v

# 4. ROUTING LOGICA
if st.session_state.auth_status != "logged_in":
    auth.render_login(supabase)
    st.stop()

# --- UTENTE LOGGATO ---

# CASO A: NESSUN FASCICOLO SELEZIONATO -> MOSTRA DASHBOARD
if not st.session_state.current_fascicolo and st.session_state.user_role != "admin":
    with st.sidebar:
        st.write(f"Utente: {st.session_state.user_email}")
        if st.button("Esci (Logout)"):
            st.session_state.auth_status = "logged_out"; st.rerun()
    dashboard.render_dashboard(supabase, st.session_state.user_id)
    st.stop()

# CASO B: ADMIN MODE
if st.session_state.user_role == "admin":
    admin.render_admin_panel(supabase)
    st.stop()

# CASO C: FASCICOLO APERTO -> INTERFACCIA DI LAVORO
f_curr = st.session_state.current_fascicolo
if f_curr is None: st.rerun() # Safety check

# Recupero Info Prezzi
price_info = database.get_pricing(supabase)
prezzo_txt = f"€ {price_info['prezzo_fisso']}" if price_info else "€ 150.00"

# --- SIDEBAR FASCICOLO ---
with st.sidebar:
    st.title("⚖️ LexVantage")
    st.success(f"📂 {f_curr['nome_riferimento']}")
    
    st.markdown("### 🎚️ Impostazioni AI")
    # SLIDER AGGRESSIVITÀ (Legato al DB)
    aggr_db = f_curr.get('livello_aggressivita', 5)
    # Gestione None
    if aggr_db is None: aggr_db = 5
    
    new_aggr = st.slider("Livello Aggressività", 1, 10, int(aggr_db), help="1=Diplomatico, 10=Distruttivo")
    
    # Auto-save se cambia
    if new_aggr != aggr_db and supabase:
        database.aggiorna_fascicolo(supabase, f_curr['id'], {"livello_aggressivita": new_aggr})
        f_curr['livello_aggressivita'] = new_aggr
        st.toast(f"Mood aggiornato a {new_aggr}/10")

    st.divider()
    if st.button("⬅️ Torna ai Fascicoli"):
        st.session_state.current_fascicolo = None
        st.rerun()

    # Privacy Shield
    with st.expander("Privacy Shield"):
        if st.button("Maschera Nomi"):
            if f_curr.get('nome_cliente'):
                st.session_state.sanitizer.add(f_curr.get('nome_cliente'), "CLIENTE")
            if f_curr.get('nome_controparte'):
                st.session_state.sanitizer.add(f_curr.get('nome_controparte'), "CONTROPARTE")
            st.toast("Nomi mascherati nella chat")

# --- TABS PRINCIPALI ---
t1, t2, t3 = st.tabs(["🧮 1. Calcoli & Fatti", "💬 2. Strategia & Analisi", "📦 3. Generazione Atti"])

# TAB 1: CALCOLATORE
with t1:
    st.header("Inquadramento Economico")
    st.info("Inserisci qui i dati tecnici e i valori economici che l'AI deve usare per redigere gli atti.")
    
    c1, c2 = st.columns(2)
    # Area di testo libera per massima flessibilità
    new_calc_txt = st.text_area("Note Tecniche, Date, Importi (CTU, Target, ecc.)", value=st.session_state.dati_calc, height=200)
    
    if st.button("💾 Salva Dati Tecnici"):
        st.session_state.dati_calc = new_calc_txt
        if supabase:
            database.aggiorna_fascicolo(supabase, f_curr['id'], {"dati_tecnici": new_calc_txt})
            st.success("Dati salvati nel fascicolo.")

# TAB 2: CHAT STRATEGICA
with t2:
    st.header("Analisi Strategica")
    
    # Upload Documenti
    uploaded = st.file_uploader("Carica documenti (PDF/Word)", accept_multiple_files=True)
    file_parts, full_txt = doc_renderer.extract_text_from_files(uploaded)
    
    # Render Chat History
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # Input Utente
    if prompt := st.chat_input("Scrivi qui la tua domanda o aggiornamento..."):
        # 1. Aggiungi User Message
        st.session_state.messages.append({"role":"user", "content":prompt})
        st.session_state.contesto_chat += f"\nUTENTE: {prompt}"
        with st.chat_message("user"): st.write(prompt)
        
        # 2. Chiama AI
        with st.spinner("L'AI sta analizzando il caso..."):
            resp_data = ai_engine.interroga_gemini(
                "models/gemini-1.5-flash",
                prompt,
                st.session_state.contesto_chat,
                file_parts,
                st.session_state.dati_calc,
                st.session_state.sanitizer,
                f"Prezzo Pacchetto: {prezzo_txt}",
                f_curr.get('livello_aggressivita', 5)
            )
        
        # 3. Gestisci Risposta AI (JSON)
        ai_content = resp_data.get("contenuto", "Errore generazione risposta.")
        ai_phase = resp_data.get("fase", "intervista")
        ai_title = resp_data.get("titolo", "Risposta")

        st.session_state.messages.append({"role":"assistant", "content": ai_content})
        st.session_state.contesto_chat += f"\nAI: {ai_content}"
        
        with st.chat_message("assistant"):
            if ai_title: st.markdown(f"### {ai_title}")
            st.markdown(ai_content)
            
            # 4. LOGICA CHIUSURA INTELLIGENTE ("Smart Close")
            if ai_phase == "strategia":
                st.success("💡 Strategia Definita. Il fascicolo è pronto per essere generato.")
                col_btn, _ = st.columns([1, 2])
                if col_btn.button("✅ APPROVA E VAI AL PAGAMENTO", key="smart_close_btn", type="primary"):
                    st.session_state.workflow_step = "PAYMENT"
                    st.rerun()

# TAB 3: GENERAZIONE
with t3:
    st.header("Generazione Fascicolo")
    
    if st.session_state.workflow_step == "PAYMENT":
        st.warning(f"🔒 Il download dei documenti richiede lo sblocco del fascicolo.")
        st.markdown(f"### Costo Operazione: **{prezzo_txt}**")
        st.write("Il pacchetto include tutti i documenti strategici generati su misura.")
        
        c_pay, _ = st.columns([1, 3])
        if c_pay.button("💳 Simula Pagamento con Carta"):
            with st.spinner("Elaborazione pagamento..."):
                # Qui andrebbe stripe integration
                st.session_state.workflow_step = "UNLOCKED"
                st.balloons()
                st.rerun()
            
    elif st.session_state.workflow_step == "UNLOCKED":
        st.success("✅ Accesso Generazione Abilitato")
        
        # Recupera Documenti suggeriti in base al tipo causa
        materia = f_curr.get('tipo_causa', 'immobiliare')
        doc_list = config.CASE_TYPES_FALLBACK.get(materia, config.CASE_TYPES_FALLBACK['immobiliare'])['docs']
        
        st.subheader("Configura Pacchetto")
        sel_docs = st.multiselect("Seleziona documenti da generare:", doc_list, default=doc_list)
        
        if st.button("🚀 GENERA DOCUMENTI ORA", type="primary"):
            progress_text = "Operazione in corso. Attendi..."
            my_bar = st.progress(0, text=progress_text)
            
            # Preparazione Task
            tasks = [(d, config.DOCS_METADATA.get(d, "")) for d in sel_docs]
            full_hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
            
            # Generazione
            res_dict = ai_engine.genera_docs_json_batch(
                tasks, full_hist, file_parts, st.session_state.dati_calc, "models/gemini-1.5-flash"
            )
            my_bar.progress(80, text="Creazione ZIP...")
            
            # Zip
            st.session_state.generated_docs_zip = doc_renderer.create_zip(res_dict, st.session_state.sanitizer)
            
            # Salvataggio nel DB (Documenti Generati)
            if supabase:
                database.aggiorna_fascicolo(supabase, f_curr['id'], {"documenti_generati": json.dumps(res_dict)})
                
            my_bar.progress(100, text="Fatto!")
            st.toast("Fascicolo salvato e pronto!")

        if st.session_state.generated_docs_zip:
            st.divider()
            st.download_button(
                label="📦 SCARICA FASCICOLO COMPLETO (ZIP)", 
                data=st.session_state.generated_docs_zip.getvalue(),
                file_name=f"Fascicolo_{f_curr['nome_riferimento']}.zip", 
                mime="application/zip",
                type="primary"
            )
    else:
        st.info("Completa l'analisi nel Tab 2 per sbloccare questa sezione.")
