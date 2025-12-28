# modules/auth.py
import streamlit as st
from . import utils

def render_login(supabase):
    st.markdown("<div class='auth-box'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;'>🔐 LexVantage Login</h2>", unsafe_allow_html=True)
    
    t1, t2 = st.tabs(["Accedi", "Registrati"])
    
    with t1:
        email = st.text_input("Email", key="log_email")
        pwd = st.text_input("Password", type="password", key="log_pwd")
        
        if st.button("Accedi", type="primary"):
            if not supabase:
                # Fallback offline
                if email == "admin" and pwd == "admin":
                    st.session_state.auth_status = "logged_in"
                    st.session_state.user_role = "admin"
                    st.session_state.user_email = "admin@local"
                    st.rerun()
            else:
                res = supabase.table("profili_utenti").select("*").eq("email", email).eq("password", pwd).execute()
                if res.data:
                    user = res.data[0]
                    if user['stato_account'] == 'attivo':
                        st.session_state.auth_status = "logged_in"
                        st.session_state.user_email = user['email']
                        st.session_state.user_id = user['id']
                        st.session_state.user_role = user.get('ruolo', 'user')
                        st.session_state.nome_studio = user.get('nome_studio', '')
                        st.rerun()
                    elif user['stato_account'] == 'in_attesa':
                        st.warning("Account in attesa di approvazione.")
                    else:
                        st.error("Account sospeso.")
                else:
                    st.error("Credenziali errate.")

    with t2:
        reg_email = st.text_input("Email", key="reg_email")
        reg_pwd = st.text_input("Password", type="password", key="reg_pwd")
        reg_studio = st.text_input("Nome Studio", key="reg_studio")
        
        if st.button("Invia Richiesta"):
            if supabase and reg_email and reg_pwd:
                try:
                    supabase.table("profili_utenti").insert({
                        "email": reg_email, "password": reg_pwd, "nome_studio": reg_studio,
                        "ruolo": "user", "stato_account": "in_attesa"
                    }).execute()
                    
                    ok, msg = utils.send_admin_alert(reg_email)
                    if ok: st.success("Richiesta inviata e admin notificato!")
                    else: st.warning(f"Richiesta salvata, ma errore email: {msg}")
                except Exception as e:
                    st.error(f"Errore registrazione: {e}")
    
    st.markdown("</div>", unsafe_allow_html=True)
