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
    with t_prices:
        st.subheader("Listino Dinamico")
        prices = supabase.table("listino_prezzi").select("*").execute().data
        for p in prices:
            with st.form(f"price_{p['id']}"):
                st.write(f"### {p['tipo_documento']}")
                nf = st.number_input("Prezzo Fisso (€)", value=float(p.get('prezzo_fisso', 0)))
                desc = st.text_input("Descrizione", value=p.get('descrizione', ''))
                if st.form_submit_button("Salva"):
                    supabase.table("listino_prezzi").update({
                        "prezzo_fisso": nf,
                        "descrizione": desc
                    }).eq("id", p['id']).execute()
                    st.success("Aggiornato")
                    time.sleep(1)
                    st.rerun()

    # --- TAB AUDIT ---
    with t_audit:
        fascicoli = supabase.table("fascicoli").select("*").order("created_at", desc=True).limit(20).execute().data
        st.dataframe(fascicoli)
