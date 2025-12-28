import streamlit as st
import json
from datetime import datetime
from modules import config, database, auth, admin, ai_engine, doc_renderer, dashboard, utils

# 1. CONFIGURAZIONE PAGINA
st.set_page_config(page_title=config.APP_NAME, layout="wide", page_icon="⚖️")

# 2. INIZIALIZZAZIONE
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

# SIDEBAR GLOBALE
with st.sidebar:
    st.title(config.APP_NAME)
    st.caption(f"Ver: {config.APP_VER}")
    st.write(f"👤 {st.session_state.user_email}")
    
    if st.button("Esci (Logout)", key="glob_logout"):
        st.session_state.auth_status = "logged_out"
        st.session_state.current_fascicolo = None
        st.rerun()
    st.divider()

# CASO A: ADMIN
if st.session_state.user_role == "admin" and not st.session_state.current_fascicolo:
    if st.button("👀 Passa a Vista Utente"):
        st.session_state.user_role = "user_simulated"; st.rerun()
    admin.render_admin_panel(supabase)
    st.stop()

# CASO B: DASHBOARD (Nessun fascicolo aperto)
if not st.session_state.current_fascicolo:
    dashboard.render_dashboard(supabase, st.session_state.user_id)
    if st.session_state.get("user_role") == "user_simulated":
        if st.sidebar.button("🔧 Admin Panel"): st.session_state.user_role = "admin"; st.rerun()
    st.stop()

# --- WORKSTATION FASCICOLO ---
f_curr = st.session_state.current_fascicolo
if f_curr is None: st.rerun()

price_info = database.get_pricing(supabase)
prezzo_txt = f"€ {price_info['prezzo_fisso']}" if price_info else "€ 150.00"

with st.sidebar:
    st.success(f"📂 {f_curr['nome_riferimento']}")
    
    # Aggressività Dinamica
    aggr_db = f_curr.get('livello_aggressivita', 5) or 5
    new_aggr = st.slider("Livello Aggressività", 1, 10, int(aggr_db))
    if new_aggr != aggr_db and supabase:
        database.aggiorna_fascicolo(supabase, f_curr['id'], {"livello_aggressivita": new_aggr})
        f_curr['livello_aggressivita'] = new_aggr

    st.divider()
    if st.button("⬅️ Torna alla Dashboard", type="primary"):
        st.session_state.current_fascicolo = None
        st.session_state.messages = []
        st.rerun()

    # Privacy
    with st.expander("Privacy Shield"):
        if st.button("Maschera Nomi"):
            if f_curr.get('nome_cliente'): st.session_state.sanitizer.add(f_curr.get('nome_cliente'), "CLIENTE")
            if f_curr.get('nome_controparte'): st.session_state.sanitizer.add(f_curr.get('nome_controparte'), "CONTROPARTE")
            st.toast("Attivato")

# TABS PRINCIPALI
t1, t2, t3 = st.tabs(["🧮 1. Calcoli & Fatti", "💬 2. Strategia", "📦 3. Documenti"])

# TAB 1: CALCOLATORE (RIPRISTINATO)
with t1:
    st.header("Inquadramento Economico")
    c1, c2 = st.columns(2)
    
    with c1:
        val_ctu = st.number_input("Valore CTU / Richiesta (€)", value=0.0, step=1000.0)
        val_target = st.number_input("Valore Target (€)", value=0.0, step=1000.0)
    
    with c2:
        delta = val_ctu - val_target
        color = "green" if delta > 0 else "red"
        st.markdown(f"### Delta: :{color}[€ {delta:,.2f}]")
        st.caption("Differenza tra richiesta avversaria/CTU e nostro obiettivo.")

    st.markdown("---")
    current_calc = st.session_state.dati_calc
    if current_calc == "Nessun dato." and f_curr.get('dati_tecnici'):
        current_calc = f_curr.get('dati_tecnici')

    note_txt = st.text_area("Note Tecniche (Vizi, Date, Difformità)", value=current_calc, height=150)
    
    if st.button("💾 Salva Dati Tecnici"):
        # Costruiamo una stringa ricca per l'AI
        final_calc_str = f"""
        DATI ECONOMICI:
        - Valore CTU/Richiesta: € {val_ctu}
        - Valore Target: € {val_target}
        - Delta (Guadagno/Risparmio potenziale): € {delta}
        
        NOTE TECNICHE AGGIUNTIVE:
        {note_txt}
        """
        st.session_state.dati_calc = final_calc_str
        if supabase:
            database.aggiorna_fascicolo(supabase, f_curr['id'], {"dati_tecnici": final_calc_str})
            st.success("Dati aggiornati e salvati.")

# TAB 2: CHAT
with t2:
    st.header("Analisi Strategica")
    uploaded = st.file_uploader("Carica documenti", accept_multiple_files=True)
    
    # FIX ERRORE: Chiamata corretta alla funzione nel modulo
    file_parts, full_txt = doc_renderer.extract_text_from_files(uploaded)
    
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Scrivi qui..."):
        st.session_state.messages.append({"role":"user", "content":prompt})
        st.session_state.contesto_chat += f"\nUTENTE: {prompt}"
        with st.chat_message("user"): st.write(prompt)
        
        with st.spinner("Analisi..."):
            resp_data = ai_engine.interroga_gemini(
                "models/gemini-1.5-flash", prompt, st.session_state.contesto_chat,
                file_parts, st.session_state.dati_calc, st.session_state.sanitizer,
                f"Prezzo: {prezzo_txt}", f_curr.get('livello_aggressivita', 5)
            )
        
        ai_content = resp_data.get("contenuto", "Errore")
        ai_phase = resp_data.get("fase", "intervista")
        
        st.session_state.messages.append({"role":"assistant", "content": ai_content})
        st.session_state.contesto_chat += f"\nAI: {ai_content}"
        
        with st.chat_message("assistant"):
            if resp_data.get("titolo"): st.markdown(f"### {resp_data['titolo']}")
            st.markdown(ai_content)
            
            if ai_phase == "strategia":
                st.success("💡 Strategia Definita.")
                if st.button("✅ VAI ALLA GENERAZIONE", key="smart_btn"):
                    st.session_state.workflow_step = "PAYMENT"
                    st.rerun()

# TAB 3: GENERAZIONE
with t3:
    st.header("Generazione")
    if st.session_state.workflow_step == "PAYMENT":
        st.warning(f"Sblocca il fascicolo per {prezzo_txt}")
        if st.button("💳 Simula Pagamento"):
            st.session_state.workflow_step = "UNLOCKED"
            st.rerun()
            
    elif st.session_state.workflow_step == "UNLOCKED":
        st.success("Generazione Abilitata")
        materia = f_curr.get('tipo_causa', 'immobiliare')
        doc_list = config.CASE_TYPES_FALLBACK.get(materia, config.CASE_TYPES_FALLBACK['immobiliare'])['docs']
        sel = st.multiselect("Documenti:", doc_list, default=doc_list)
        
        if st.button("🚀 GENERA", type="primary"):
            prog = st.progress(0, "Generazione..."); 
            tasks = [(d, config.DOCS_METADATA.get(d, "")) for d in sel]
            hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
            
            res = ai_engine.genera_docs_json_batch(tasks, hist, file_parts, st.session_state.dati_calc, "models/gemini-1.5-flash")
            prog.progress(90, "Zip...")
            st.session_state.generated_docs_zip = doc_renderer.create_zip(res, st.session_state.sanitizer)
            
            if supabase:
                database.aggiorna_fascicolo(supabase, f_curr['id'], {"documenti_generati": json.dumps(res)})
            prog.progress(100, "Fatto!")

        if st.session_state.generated_docs_zip:
            st.download_button("📦 SCARICA ZIP", st.session_state.generated_docs_zip.getvalue(), f"Fascicolo_{f_curr['nome_riferimento']}.zip", "application/zip", type="primary")
    else:
        st.info("Completa l'analisi nel Tab 2.")
