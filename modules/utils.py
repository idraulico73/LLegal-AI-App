# modules/utils.py
import smtplib
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- EMAIL SYSTEM ---
def send_email(to_email, subject, body):
    """Funzione generica invio mail SMTP"""
    if "smtp" not in st.secrets: return False, "No SMTP config"
    try:
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = st.secrets["smtp"]["email"]
        msg['To'] = to_email
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(st.secrets["smtp"]["server"], st.secrets["smtp"]["port"])
        server.starttls()
        server.login(st.secrets["smtp"]["email"], st.secrets["smtp"]["password"])
        server.sendmail(st.secrets["smtp"]["email"], to_email, msg.as_string())
        server.quit()
        return True, "OK"
    except Exception as e:
        return False, str(e)

def send_admin_alert(new_user_email):
    """Avvisa admin di nuova registrazione"""
    admin_mail = st.secrets["smtp"]["email"]
    body = f"Utente {new_user_email} richiede accesso. Vai al pannello Admin."
    return send_email(admin_mail, "🔔 Nuovo Iscritto LexVantage", body)

def send_approval_email(user_email):
    """Avvisa utente attivazione account"""
    body = "Il tuo account LexVantage è stato attivato. Puoi ora accedere."
    return send_email(user_email, "✅ Account Attivo", body)

# --- STRIPE HELPERS ---
def get_stripe_payment_link(amount_eur):
    """Mockup per link pagamento (o implementazione reale)"""
    # In futuro qui integrerai stripe.checkout.Session.create
    return "#"
