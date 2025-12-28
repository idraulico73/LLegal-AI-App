# modules/admin.py
import streamlit as st
import time
from . import utils

def render_admin_panel(supabase):
    st.markdown("## 🛠️ Admin Dashboard")
    st.info(f"Superuser: {st.session_state.user_email}")
    
    t_users, t_prices, t_audit = st.tabs(["👥 Utenti", "💰 Prezzi", "📂 Audit"])
    
    if not supabase:
        st.error("DB Offline")
        return

    # --- TAB UTENTI ---
    with t_users:
        st.subheader("Richieste in Attesa")
        pending = supabase.table("profili_utenti").select("*").eq("stato_account", "in_attesa").execute().data
        if not pending: st.success("Nessuna richiesta.")
        
        for u in pending:
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{u['nome_studio']}** ({u['email']})")
            if c2.button("✅ APPROVA", key=u['id']):
                supabase.table("profili_utenti").update({"stato_account": "attivo"}).eq("id", u['id']).execute()
                utils.send_approval_email(u['email'])
                st.toast("Utente attivato")
                time.sleep(1)
                st.rerun()

    # --- TAB PREZZI ---
# --- SOSTITUIRE IL BLOCCO 'with t_prices:' IN modules/admin.py ---
    with t_prices:
        st.subheader("💰 Listino Prezzi Granulare")
        st.caption("Definisci prezzi fissi e variabili per ogni tipo di documento.")
        
        # 1. Recupera listino attuale dal DB
        db_prices_list = supabase.table("listino_prezzi").select("*").execute().data
        db_map = {row['tipo_documento']: row for row in db_prices_list}
        
        # 2. Elenco di tutti i documenti gestiti (da Config + Jolly)
        from . import config # Import locale per sicurezza
        all_doc_types = set()
        for cat in config.CASE_TYPES_FALLBACK.values():
            for d in config.DOCS_METADATA.keys(): # Prende tutte le chiavi note
                all_doc_types.add(d)
        all_doc_types.add("Documento_Dinamico") # Prezzo per richieste custom
        all_doc_types.add("pacchetto_base") # Prezzo legacy
        
        # 3. Genera griglia di edit
        for doc_type in sorted(all_doc_types):
            row_data = db_map.get(doc_type, {})
            
            with st.expander(f"Prezzo: {doc_type}", expanded=False):
                with st.form(f"price_form_{doc_type}"):
                    c1, c2, c3 = st.columns(3)
                    p_fisso = c1.number_input("Fisso (€)", value=float(row_data.get('prezzo_fisso', 0.0)))
                    p_tok_out = c2.number_input("Costo x 1k Token Out (€)", value=float(row_data.get('prezzo_per_1k_output_token', 0.05)), format="%.3f")
                    molt = c3.number_input("Moltiplicatore Complessità", value=float(row_data.get('moltiplicatore_complessita', 1.0)))
                    
                    desc = st.text_input("Descrizione / Note", value=row_data.get('descrizione', ''))
                    
                    if st.form_submit_button("💾 Salva Prezzo"):
                        upsert_data = {
                            "tipo_documento": doc_type,
                            "prezzo_fisso": p_fisso,
                            "prezzo_per_1k_input_token": 0.01, # Default basso fisso
                            "prezzo_per_1k_output_token": p_tok_out,
                            "moltiplicatore_complessita": molt,
                            "descrizione": desc
                        }
                        
                        if 'id' in row_data:
                            supabase.table("listino_prezzi").update(upsert_data).eq("id", row_data['id']).execute()
                        else:
                            supabase.table("listino_prezzi").insert(upsert_data).execute()
                        
                        st.success(f"Aggiornato: {doc_type}")
                        time.sleep(1)
                        st.rerun()

    # --- TAB AUDIT ---
    with t_audit:
        fascicoli = supabase.table("fascicoli").select("*").order("created_at", desc=True).limit(20).execute().data
        st.dataframe(fascicoli)
