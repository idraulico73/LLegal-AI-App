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

# Recupero prezzo base per visualizzazione sidebar
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

# Variabile per condividere i file tra i tab (se caricati)
file_parts_global = []

# TAB 1: CALCOLATORE
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

# TAB 2: CHAT STRATEGICA
with t2:
    st.header("Analisi Strategica")
    # --- INSERIRE IN app3.py DENTRO 'with t2:' ---
    
    # VISUALIZZATORE STORICO (Nuova Feature)
    storico_docs = f_curr.get('documenti_generati')
    if storico_docs and isinstance(storico_docs, list) and len(storico_docs) > 0:
        with st.expander("🗄️ Archivio Documenti Generati (Sessioni Precedenti)", expanded=False):
            st.caption("Documenti e Trascrizioni Chat salvati.")
            # Mostriamo dal più recente
            for doc in reversed(storico_docs):
                col_d1, col_d2 = st.columns([4, 1])
                icon = "💬" if doc.get('tipo') == 'trascrizione_chat' else "📄"
                
                # Titolo e Data
                lbl = f"{icon} **{doc.get('titolo')}**"
                if 'data_creazione' in doc: lbl += f" - *{doc['data_creazione']}*"
                col_d1.markdown(lbl)
                
                # Download Button Diretto
                col_d2.download_button(
                    label="Scarica",
                    data=doc.get('contenuto', ''),
                    file_name=f"{doc.get('titolo')}.txt", # Upgrade futuro: converti in docx al volo se serve
                    key=f"hist_{doc.get('titolo')}_{doc.get('data_creazione')}"
                )
        st.divider()
    
    # ... (qui sotto continua il codice esistente 'uploaded = st.file_uploader...') ...
    uploaded = st.file_uploader("Carica documenti", accept_multiple_files=True)
    
    # Estrazione testo
    file_parts, full_txt = doc_renderer.extract_text_from_files(uploaded)
    if file_parts:
        file_parts_global = file_parts # Salviamo per eventuale uso
    
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
            
            # Se la fase è 'strategia' o se l'utente ha confermato esplicitamente
            if ai_phase == "strategia":
                st.success("💡 Strategia Definita.")
                if st.button("✅ VAI ALLA GENERAZIONE", key="smart_btn_strategy"):
                    st.session_state.workflow_step = "PAYMENT"
                    st.rerun()

# TAB 3: GENERAZIONE DOCUMENTI
# --- SOSTITUIRE TUTTO IL BLOCCO 'with t3:' IN app3.py ---

with t3:
    st.header("Generazione e Chiusura Sessione")
    
    # 1. Recupero Tipi Documento
    materia = f_curr.get('tipo_causa', 'immobiliare')
    # Fallback sicuro se la materia non esiste nel config
    if materia not in config.CASE_TYPES_FALLBACK: materia = 'immobiliare'
    
    doc_list_info = config.CASE_TYPES_FALLBACK[materia]
    default_docs = doc_list_info['docs']
    
    # 2. Selezione Documenti
    st.info("Seleziona i documenti da produrre in questa sessione.")
    sel = st.multiselect("Documenti Standard:", default_docs, default=default_docs)
    
    # Checkbox per documenti dinamici (Feature 'Jolly')
    add_custom = st.checkbox("Aggiungi documento su richiesta (es. Diffida specifica)")
    custom_name = "Documento_Dinamico"
    if add_custom:
        custom_name_input = st.text_input("Nome Documento Personalizzato", value="Diffida_Ad_Hoc")
        custom_name = custom_name_input
        if custom_name not in sel:
            sel.append(custom_name)

# --- IN app3.py (Tab 3) ---

    # 3. CONFIGURAZIONE INTELLIGENZA E PREVENTIVO
    st.markdown("---")
    c_conf1, c_conf2 = st.columns([1, 1])
    
    # Variabile per il moltiplicatore visuale
    current_multiplier = 1.0 
    
    with c_conf1:
        st.write("### 🧠 Intelligenza Artificiale")
        try:
            # Recupera modelli completi (incluso moltiplicatore)
            # Nota: Assumiamo che get_active_gemini_models ora ritorni tutto (*) o modificala per farlo
            active_models = supabase.table("gemini_models").select("*").eq("is_active", True).execute().data
        except: 
            active_models = []
            
        if active_models:
            # Mappa per selectbox
            map_models = {m['display_name']: m for m in active_models}
            sel_label = st.selectbox("Seleziona Potenza:", list(map_models.keys()))
            
            selected_obj = map_models[sel_label]
            SELECTED_MODEL_ID = selected_obj['model_name']
            current_multiplier = float(selected_obj.get('price_multiplier', 1.0))
            
            # Feedback visivo immediato
            if current_multiplier > 1.0:
                st.info(f"⚡ Modalità Elite: I costi variabili sono moltiplicati x{current_multiplier}")
        else:
            st.warning("⚠️ Listino modelli offline. Uso Default.")
            SELECTED_MODEL_ID = "models/gemini-1.5-flash"

    with c_conf2:
        st.write("### 🧾 Stima Costi")
        totale_stimato_min = 0.0
        totale_stimato_max = 0.0
        
        listino = database.get_listino_completo(supabase)
        
        for d_name in sel:
            row = listino.get(d_name) or listino.get("Documento_Dinamico") or {}
            p_fisso = float(row.get('prezzo_fisso', 0) or 50.0)
            
            # Recuperiamo i costi base calcolati nel DB (0.5% e 5%)
            c_in = float(row.get('prezzo_per_1k_input_token', 0.0))
            c_out = float(row.get('prezzo_per_1k_output_token', 0.0))
            
            # Simulazione: 5k input (medio), 1k output (medio)
            var_base = (5 * c_in) + (1 * c_out)
            
            # Applichiamo moltiplicatore del modello scelto
            var_final = var_base * current_multiplier
            
            costo_probabile = p_fisso + var_final
            
            totale_stimato_min += costo_probabile
            st.caption(f"- {d_name}: ~€ {costo_probabile:.2f}")
            
        st.markdown(f"#### Totale Stimato: € {totale_stimato_min:.2f}")
        
        if st.session_state.workflow_step == "CHAT":
            if st.button("💳 CONFERMA E GENERA", type="primary", use_container_width=True):
                st.session_state.workflow_step = "GENERATING"
                st.rerun()
                
# --- IN app3.py, DENTRO 'with t3:' ---

    # ... (Codice esistente selezione documenti) ...

    st.markdown("---")
    st.write("### 🧠 Intelligenza & Costi")
    
    # 1. SELECTBOX MODELLO (Dinamica dal DB)
    active_models = database.get_active_gemini_models(supabase)
    
    # Mappa nomi visualizzati -> ID modello
    # Esempio structure: {"Gemini Flash (Veloce)": "models/gemini-1.5-flash"}
    if active_models:
        map_models = {m['display_name']: m['model_name'] for m in active_models}
        sel_label = st.selectbox("Seleziona Modello AI:", list(map_models.keys()))
        SELECTED_MODEL_ID = map_models[sel_label]
    else:
        # Fallback se tabella vuota
        st.warning("Listino modelli non trovato, uso default.")
        SELECTED_MODEL_ID = "models/gemini-1.5-flash"

    # ... (Codice esistente preventivo stimato visuale... puoi lasciarlo come stima) ...
    
    # --- PROCESSO DI GENERAZIONE MODIFICATO ---
    if st.session_state.workflow_step == "GENERATING":
        prog = st.progress(0, "Inizializzazione AI...")
        
        # A. Preparazione Task (come prima)
        tasks = []
        for d in sel:
            meta = config.DOCS_METADATA.get(d, "Documento legale professionale.")
            if d == custom_name and add_custom:
                meta = "Genera il documento specifico richiesto..."
            tasks.append((d, meta))
            
        # B. Recupero Chat History
        hist_txt = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
        
        # C. Generazione (Passando il MODELLO SELEZIONATO)
        res_docs = ai_engine.genera_docs_json_batch(
            tasks, hist_txt, [], st.session_state.dati_calc, SELECTED_MODEL_ID
        )
        
        prog.progress(60, "Calcolo Prezzi e Salvataggio...")
        
        # D. Calcolo Pricing Reale e Aggiornamento DB
        if supabase:
            # Recuperiamo storico attuale per appendere
            # Nota: per semplicità facciamo una logica di update robusta
            res_fascicolo = supabase.table("fascicoli").select("documenti_generati, costo_stimato").eq("id", f_curr['id']).execute()
            current_docs = res_fascicolo.data[0].get("documenti_generati") or []
            if not isinstance(current_docs, list): current_docs = []
            
            current_cost = float(res_fascicolo.data[0].get("costo_stimato") or 0.0)
            
            # Iteriamo sui documenti generati dall'AI
            for doc_key, doc_data in res_docs.items():
                # Estraiamo le metriche che abbiamo iniettato in ai_engine
                metrics = doc_data.pop("_metrics", {"tokens_input": 0, "tokens_output": 0})
                
                # Calcoliamo il prezzo preciso
                prezzo_doc, snapshot_partial = database.registra_transazione_doc(
                    supabase, 
                    f_curr['id'], 
                    doc_key, 
                    SELECTED_MODEL_ID, 
                    metrics['tokens_input'], 
                    metrics['tokens_output']
                )
                
                # Completiamo lo snapshot con il contenuto reale
                snapshot_partial["contenuto"] = doc_data.get("contenuto", "")
                
                # Aggiungiamo alla lista e al totale
                current_docs.append(snapshot_partial)
                current_cost += prezzo_doc
                
            # Aggiungiamo anche la trascrizione chat (costo 0 o a piacere)
            chat_doc_title = f"Trascrizione_Chat_{datetime.now().strftime('%d%m_%H%M')}"
            current_docs.append({
                "titolo": chat_doc_title,
                "contenuto": f"# TRASCRIZIONE\n\n{hist_txt}",
                "tipo": "trascrizione_chat",
                "data_creazione": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "metadata_pricing": {"final_price": 0.0} # Gratis
            })

            # SALVATAGGIO UNICO NEL DB
            supabase.table("fascicoli").update({
                "documenti_generati": current_docs,
                "costo_stimato": current_cost
            }).eq("id", f_curr['id']).execute()
            
            # Refresh stato locale
            st.session_state.current_fascicolo['documenti_generati'] = current_docs

        prog.progress(90, "Creazione ZIP...")
        st.session_state.generated_docs_zip = doc_renderer.create_zip(res_docs, st.session_state.sanitizer)
        
        # F. Reset Sessione
        st.session_state.messages = [] 
        st.session_state.contesto_chat = ""
        st.session_state.workflow_step = "DONE"
        
        prog.progress(100, "Fatto!")
        st.rerun()
