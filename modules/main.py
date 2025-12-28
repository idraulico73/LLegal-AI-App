# main.py
import streamlit as st
from datetime import datetime
from modules import config, database, auth, admin, ai_engine, doc_renderer, utils

# 1. SETUP
st.set_page_config(page_title=config.APP_NAME, layout="wide", page_icon="⚖️")
supabase = database.init_supabase()
ai_engine.init_ai()

# 2. SESSION STATE INIT
vars_init = {
    "auth_status": "logged_out", "sanitizer": ai_engine.DataSanitizer(),
    "messages": [], "contesto_chat": "", "dati_calc": "Nessun dato.",
    "workflow_step": "CHAT", "selected_case_type": "immobiliare",
    "generated_docs_zip": None
}
for k, v in vars_init.items():
    if k not in st.session_state: st.session_state[k] = v

# 3. ROUTING
if st.session_state.auth_status != "logged_in":
    auth.render_login(supabase)
else:
    # --- ADMIN MODE ---
    if st.session_state.user_role == "admin":
        with st.sidebar:
            if st.button("Logout"): st.session_state.auth_status = "logged_out"; st.rerun()
        admin.render_admin_panel(supabase)
        st.stop()

    # --- USER MODE ---
    # Recupero Configurazione (DB > Fallback)
    db_types = database.get_config_tipi_causa(supabase)
    
    # Mapping Tipi Causa
    case_types_map = config.CASE_TYPES_FALLBACK
    if db_types:
        case_types_map = {
            t['codice']: {"label": t['nome_visualizzato'], "docs": t['documenti_standard']} 
            for t in db_types
        }

    # Recupero Prezzo
    price_info = database.get_pricing(supabase)
    prezzo = float(price_info['prezzo_fisso']) if price_info else config.PRICING_CONFIG_FALLBACK['pacchetto_base']

    with st.sidebar:
        st.title(config.APP_NAME)
        st.caption(f"Ver: {config.APP_VER}")
        st.write(f"👤 {st.session_state.user_email}")
        
        # Gestione Fascicoli
        if supabase:
            st.subheader("📂 Fascicoli")
            f_res = supabase.table("fascicoli").select("*").eq("user_id", st.session_state.user_id).execute()
            opts = {f['nome_riferimento']: f for f in f_res.data}
            opts["➕ Nuovo"] = None
            sel = st.selectbox("Seleziona", list(opts.keys()))
            if sel != "➕ Nuovo" and sel:
                st.session_state.messages = [] # Qui andrebbe il restore della chat history
                st.session_state.dati_calc = opts[sel]['dati_tecnici'] or ""

        st.divider()
        st.session_state.selected_case_type = st.selectbox(
            "Materia", list(case_types_map.keys()),
            format_func=lambda x: case_types_map[x]['label']
        )
        
        # Privacy
        n1 = st.text_input("Cliente", "Rossi")
        n2 = st.text_input("Controparte", "Bianchi")
        if st.button("Maschera"):
            st.session_state.sanitizer.add(n1, "CLIENTE_X")
            st.session_state.sanitizer.add(n2, "CONTROPARTE_Y")
            st.toast("Dati Protetti 🔒")

        if st.button("Logout"):
            st.session_state.auth_status = "logged_out"; st.rerun()

    t1, t2, t3 = st.tabs(["🧮 1. Calcoli", "💬 2. Strategia", "📦 3. Documenti"])

    with t1:
        st.header("Dati Tecnici")
        c1, c2 = st.columns(2)
        v1 = c1.number_input("Valore CTU", 0.0)
        v2 = c1.number_input("Valore Target", 0.0)
        nt = c2.text_area("Note Tecniche")
        if st.button("💾 Salva Contesto"):
            st.session_state.dati_calc = f"CTU: {v1} | Target: {v2} | Delta: {v1-v2} | Note: {nt}"
            st.success("Salvato")

    with t2:
        files = st.file_uploader("Documenti", accept_multiple_files=True)
        f_parts, full_txt = doc_renderer.extract_text(files)
        
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
            
        if p := st.chat_input("..."):
            st.session_state.messages.append({"role":"user","content":p})
            st.session_state.contesto_chat += f"\nUSR: {p}"
            with st.chat_message("user"): st.write(p)
            
            is_close = any(x in p.lower() for x in ["genera", "acquisto", "compra"])
            
            with st.spinner("..."):
                reply = ai_engine.interroga_gemini(
                    "models/gemini-1.5-flash", p, st.session_state.contesto_chat,
                    f_parts, st.session_state.dati_calc, is_close,
                    st.session_state.sanitizer, f"Prezzo: {prezzo}€"
                )
            
            st.session_state.messages.append({"role":"assistant","content":reply})
            st.session_state.contesto_chat += f"\nAI: {reply}"
            with st.chat_message("assistant"): st.markdown(reply)
            
            if is_close and "€" in reply:
                st.session_state.workflow_step = "PAYMENT"
                st.rerun()

    with t3:
        if st.session_state.workflow_step == "PAYMENT":
            st.info(f"Sblocca il fascicolo completo per € {prezzo}")
            if st.button("Simula Pagamento OK"):
                st.session_state.workflow_step = "UNLOCKED"
                st.rerun()
                
        elif st.session_state.workflow_step == "UNLOCKED":
            st.success("✅ Generazione Abilitata")
            
            curr_config = case_types_map[st.session_state.selected_case_type]
            docs_req = curr_config['docs']
            
            sel = st.multiselect("Documenti", docs_req, default=docs_req)
            
            if st.button("Genera"):
                tasks = [(d, config.DOCS_METADATA.get(d, "")) for d in sel]
                full_hist = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
                
                res = ai_engine.genera_docs_json_batch(
                    tasks, full_hist, f_parts, st.session_state.dati_calc, "models/gemini-1.5-flash"
                )
                
                st.session_state.generated_docs_zip = doc_renderer.create_zip(res, st.session_state.sanitizer)
                
                # Auto-Save Fascicolo
                if supabase:
                    database.save_fascicolo(
                        supabase, st.session_state.user_id, 
                        f"AutoSave_{datetime.now().strftime('%H%M')}",
                        st.session_state.selected_case_type,
                        st.session_state.dati_calc, full_hist
                    )

            if st.session_state.generated_docs_zip:
                st.download_button(
                    "📦 Scarica ZIP", 
                    st.session_state.generated_docs_zip.getvalue(),
                    "Fascicolo.zip", "application/zip"
                )
