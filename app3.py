import streamlit as st
import json
import re
import stripe
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from io import BytesIO
import zipfile
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# Tenta di importare Supabase, se manca usa modalità offline
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# --- CONFIGURAZIONE APP ---
APP_NAME = "LexVantage"
APP_VER = "Rev 50 (SaaS Complete: Privacy Shield + Payment)"
st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="⚖️")

# --- CSS & UI PREMIUM ---
st.markdown("""
<style>
    div[data-testid="stChatMessage"] { 
        background-color: #f8f9fa; border-radius: 8px; padding: 15px; 
        border-left: 4px solid #004e92; margin-bottom: 10px;
        font-family: 'Segoe UI', sans-serif;
    }
    h1, h2, h3 { color: #003366; }
    div.stButton > button { width: 100%; font-weight: 600; border-radius: 6px; }
    .premium-box { padding: 20px; border: 2px solid #ffd700; background-color: #fffdf0; border-radius: 10px; text-align: center; margin-top: 10px;}
    .success-box { padding: 10px; border: 1px solid #28a745; background-color: #d4edda; color: #155724; border-radius: 5px; text-align: center; margin-bottom: 10px;}
</style>
""", unsafe_allow_html=True)

# --- INIZIALIZZAZIONE SUPABASE ---
@st.cache_resource
def init_supabase():
    if not SUPABASE_AVAILABLE: return None, "Libreria mancante"
    try:
        if "supabase" not in st.secrets: return None, "Secrets mancanti"
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key), None
    except Exception as e: return None, str(e)

supabase, db_error = init_supabase()

# --- CLASSE PRIVACY SHIELD (Dalla Rev 48) ---
class DataSanitizer:
    def __init__(self):
        self.mapping = {} 
        self.reverse_mapping = {} 
        self.counter = 1
        
    def add_entity(self, real_name, role_label):
        if real_name and real_name not in self.mapping:
            fake = f"[{role_label}_{self.counter}]"
            self.mapping[real_name] = fake
            self.reverse_mapping[fake] = real_name
            self.counter += 1
            
    def sanitize(self, text):
        clean_text = text
        clean_text = re.sub(r'[\w\.-]+@[\w\.-]+', '[EMAIL_PROTETTA]', clean_text)
        clean_text = re.sub(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]', '[CF_OSCURATO]', clean_text)
        for real, fake in self.mapping.items():
            clean_text = clean_text.replace(real, fake)
            clean_text = clean_text.replace(real.upper(), fake)
        return clean_text
        
    def restore(self, text):
        if not text: return ""
        restored = text
        for fake, real in self.reverse_mapping.items():
            restored = restored.replace(fake, real)
        return restored

if "sanitizer" not in st.session_state: st.session_state.sanitizer = DataSanitizer()

# --- STATE MANAGEMENT ---
if "user_status" not in st.session_state: st.session_state.user_status = "FREE"
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo."
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "current_studio_id" not in st.session_state: st.session_state.current_studio_id = "local_demo"
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False
if "nome_fascicolo" not in st.session_state: st.session_state.nome_fascicolo = "Nuovo_Caso"

# --- CONFIGURAZIONE SERVIZI ESTERNI (Rev 50) ---
HAS_KEY = False
active_model = None
PAYMENT_ENABLED = False
EMAIL_ENABLED = False

try:
    # 1. AI SETUP
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        HAS_KEY = True
        active_model = "models/gemini-1.5-flash" # Default fallback
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            if "models/gemini-1.5-pro" in models: active_model = "models/gemini-1.5-pro"
        except: pass
    
    # 2. STRIPE SETUP
    if "stripe" in st.secrets:
        stripe.api_key = st.secrets["stripe"]["secret_key"]
        STRIPE_PUB_KEY = st.secrets["stripe"]["publishable_key"]
        PAYMENT_ENABLED = True

    # 3. EMAIL SETUP
    if "smtp" in st.secrets:
        EMAIL_ENABLED = True
        
except Exception as e:
    st.error(f"Errore Config: {e}")

# --- FUNZIONI BACKEND (EMAIL & PAYMENTS) ---
def invia_email(destinatario, oggetto, corpo, allegato_bytes=None, nome_allegato="doc.zip"):
    if not EMAIL_ENABLED: return "Servizio Email non configurato"
    try:
        msg = MIMEMultipart()
        msg['From'] = st.secrets["smtp"]["email"]
        msg['To'] = destinatario
        msg['Subject'] = oggetto
        msg.attach(MIMEText(corpo, 'plain'))
        if allegato_bytes:
            part = MIMEApplication(allegato_bytes.read(), Name=nome_allegato)
            part['Content-Disposition'] = f'attachment; filename="{nome_allegato}"'
            msg.attach(part)
        server = smtplib.SMTP(st.secrets["smtp"]["server"], st.secrets["smtp"]["port"])
        server.starttls()
        server.login(st.secrets["smtp"]["email"], st.secrets["smtp"]["password"])
        server.sendmail(st.secrets["smtp"]["email"], destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e: return str(e)

def crea_checkout_session():
    if not PAYMENT_ENABLED: return "#"
    try:
        # Rileva URL base automaticamente (locale o cloud)
        base_url = "http://localhost:8501" # Default locale
        # Se siamo su Streamlit Cloud, l'URL cambia, ma per ora usiamo questo per test
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price_data': {'currency': 'eur', 'product_data': {'name': 'LexVantage Premium'}, 'unit_amount': 4900}, 'quantity': 1}],
            mode='payment',
            success_url=base_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base_url,
        )
        return session.url
    except Exception as e: return str(e)

# Gestione Ritorno Stripe
try:
    qp = st.query_params
    if "session_id" in qp and st.session_state.user_status == "FREE":
        st.session_state.user_status = "PREMIUM"
        st.balloons()
        st.toast("Pagamento Confermato! Account Premium Attivo.", icon="💎")
except: pass

# --- FUNZIONI CORE AI (Dalla Rev 48) ---

def clean_json_text(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    start = text.find('{'); end = text.rfind('}')
    if start != -1 and end != -1: text = text[start:end+1]
    return text.strip()

def universal_json_flattener(data, level=0):
    text = ""
    indent = "  " * level
    if isinstance(data, dict):
        if "titolo" in data and "contenuto" in data and len(data) == 2:
            return f"### {data['titolo']}\n\n{universal_json_flattener(data['contenuto'], level)}"
        for k, v in data.items():
            key_clean = k.replace("_", " ").title()
            if isinstance(v, (dict, list)): text += f"\n{indent}**{key_clean}**:\n{universal_json_flattener(v, level+1)}"
            else: text += f"\n{indent}- **{key_clean}**: {v}"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)): text += f"\n{indent}{universal_json_flattener(item, level+1)}"
            else: text += f"\n{indent}* {item}"
    else: return str(data).replace("|", " - ")
    return text.strip()

def parse_markdown_pro(doc, text):
    if not text: return
    lines = str(text).split('\n')
    in_table = False; table_data = []
    for line in lines:
        stripped = line.strip()
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|"):
            if not in_table: in_table = True; table_data = []
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if not all(set(c).issubset({'-', ':', ' '}) for c in cells if c): table_data.append(cells)
            continue
        if in_table:
            if table_data:
                rows = len(table_data); cols = max(len(r) for r in table_data) if rows > 0 else 0
                if rows > 0 and cols > 0:
                    tbl = doc.add_table(rows=rows, cols=cols); tbl.style = 'Table Grid'
                    for i, r in enumerate(table_data):
                        for j, c in enumerate(r): 
                            if j < cols: tbl.cell(i, j).text = c
            in_table = False; table_data = []
        if not stripped: continue
        if stripped.startswith('#'): doc.add_heading(stripped.lstrip('#').strip().replace("**",""), level=min(stripped.count('#'), 3))
        elif stripped.startswith('- ') or stripped.startswith('* '): doc.add_paragraph(stripped[2:], style='List Bullet')
        else: doc.add_paragraph(stripped).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

def get_file_content(uploaded_files):
    parts = []; full_text = ""; parts.append("FASCICOLO:\n")
    if not uploaded_files: return [], ""
    for file in uploaded_files:
        try:
            safe = file.name.replace("|", "_")
            if file.type == "application/pdf":
                pdf = PdfReader(file); txt = "".join([p.extract_text() for p in pdf.pages])
            elif "word" in file.type:
                doc = Document(file); txt = "\n".join([p.text for p in doc.paragraphs])
            else: txt = ""
            if txt: parts.append(f"\n--- FILE: {safe} ---\n{txt}"); full_text += txt
        except: pass
    return parts, full_text

def interroga_gemini_json(prompt, contesto, input_parts, aggressivita, force_interview=False):
    if not HAS_KEY: return {"titolo": "Errore", "contenuto": "AI Offline."}
    sanitizer = st.session_state.sanitizer
    prompt_safe = sanitizer.sanitize(prompt)
    contesto_safe = sanitizer.sanitize(contesto)
    mood = "AGGRESSIVO" if aggressivita > 7 else "DIPLOMATICO"
    sys = f"SEI UN LEGAL AI. MOOD: {mood}. OUTPUT: JSON. DATI: {st.session_state.dati_calcolatore}. STORICO: {contesto_safe}"
    payload = list(input_parts)
    payload.append(f"UTENTE: '{prompt_safe}'. Genera JSON {{'titolo': '...', 'contenuto': '...'}}.")
    try:
        model = genai.GenerativeModel(active_model, system_instruction=sys, generation_config={"response_mime_type": "application/json"})
        resp = model.generate_content(payload)
        cleaned = clean_json_text(resp.text)
        try: parsed = json.loads(cleaned)
        except: return {"titolo": "Risposta", "contenuto": cleaned}
        
        final_content = parsed.get("contenuto", "")
        if not isinstance(final_content, str): final_content = universal_json_flattener(final_content if final_content else parsed)
        return {"titolo": parsed.get("titolo", "Analisi"), "contenuto": final_content}
    except Exception as e: return {"titolo": "Errore", "contenuto": str(e)}

def crea_output_file(json_data, formato):
    raw = json_data.get("contenuto", ""); testo = st.session_state.sanitizer.restore(str(raw))
    titolo = json_data.get("titolo", "Doc")
    if formato == "Word":
        doc = Document(); doc.add_heading(titolo, 0); parse_markdown_pro(doc, testo); buf = BytesIO(); doc.save(buf)
        return buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
    else:
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, titolo.encode('latin-1','replace').decode('latin-1'), ln=1, align='C')
        pdf.set_font("Arial", size=11); pdf.multi_cell(0, 6, testo.encode('latin-1','replace').decode('latin-1'))
        return BytesIO(pdf.output(dest='S').encode('latin-1')), "application/pdf", "pdf"

def crea_zip(docs):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, info in docs.items():
            fname = f"{n}_{st.session_state.nome_fascicolo.replace(' ', '_')}.{info['ext']}"
            z.writestr(fname, info['data'].getvalue())
    buf.seek(0)
    return buf

# --- UI SIDEBAR ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(APP_VER)
    
    # PREMIUM STATUS BOX
    if st.session_state.user_status == "PREMIUM":
        st.markdown("<div class='success-box'>💎 PREMIUM ACTIVE</div>", unsafe_allow_html=True)
    else:
        st.warning("Versione FREE")
        if PAYMENT_ENABLED:
            url = crea_checkout_session()
            if "http" in url: st.link_button("🚀 Acquista Premium (€49)", url)
            else: st.error(f"Err Payment: {url}")
        else: st.info("Pagamenti Disabilitati (Configura Secrets)")

    st.divider()
    if HAS_KEY: st.success(f"AI Online: {active_model}")
    else: st.error("AI Offline")
    
    # PRIVACY
    st.divider()
    st.subheader("🛡️ Privacy Shield")
    n1 = st.text_input("Nome Cliente", "Leonardo Cavalaglio")
    n2 = st.text_input("Controparte", "Castillo Medina")
    if st.button("Maschera Dati"):
        st.session_state.sanitizer.add_entity(n1, "CLIENTE")
        st.session_state.sanitizer.add_entity(n2, "CONTROPARTE")
        st.toast("Dati sensibili mascherati per l'AI.", icon="🔒")
        
    st.session_state.livello_aggressivita = st.slider("Aggressività", 1, 10, 5)
    st.session_state.nome_fascicolo = st.text_input("Rif. Fascicolo", st.session_state.nome_fascicolo)

# --- MAIN UI ---
t1, t2, t3 = st.tabs(["🧮 Calcolatore", "💬 Analisi", "📦 Generatore"])

with t1:
    st.header("Calcolatore Differenziale")
    c1, c2 = st.columns(2)
    with c1: val_a = st.number_input("Valore CTU (€)", 0.0)
    with c2: val_b = st.number_input("Valore Obiettivo (€)", 0.0)
    delta = val_a - val_b
    note = st.text_area("Note Tecniche:")
    if st.button("Salva Dati"):
        st.session_state.dati_calcolatore = f"CTU: {val_a} | TARGET: {val_b} | DELTA: {delta}. Note: {note}"
        st.success("Dati iniettati nel contesto AI.")

with t2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True)
    parts, full_txt = get_file_content(files)
    
    msg_container = st.container()
    with msg_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                titolo = m.get("titolo_doc", "")
                if titolo: st.markdown(f"### {titolo}")
                if isinstance(m["content"], str): st.markdown(m["content"].replace("|", " - "))

    prompt = st.chat_input("Scrivi qui...")
    if prompt:
        st.session_state.messages.append({"role":"user", "content":prompt})
        with msg_container:
            with st.chat_message("user"): st.markdown(prompt)
        
        force_interview = False
        if not st.session_state.intervista_fatta and len(st.session_state.messages) < 4 and len(prompt.split()) < 20:
            force_interview = True; st.session_state.intervista_fatta = True
            
        with st.spinner("Elaborazione..."):
            json_out = interroga_gemini_json(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, force_interview)
            cont = json_out.get("contenuto", "Errore")
            titolo_doc = json_out.get("titolo", "Analisi")
            
            cont_readable = st.session_state.sanitizer.restore(str(cont))
            st.session_state.messages.append({"role":"assistant", "content":cont_readable, "titolo_doc": titolo_doc})
            st.session_state.contesto_chat_text += f"\nAI: {cont}"
            
            with msg_container:
                with st.chat_message("assistant"):
                    st.markdown(f"### {titolo_doc}")
                    st.markdown(cont_readable.replace("|", " - "))

with t3:
    st.header("Generazione Atti")
    fmt = st.radio("Formato", ["Word", "PDF"])
    col_a, col_b, col_c = st.columns(3)
    tasks = []
    
    with col_a:
        st.markdown("**Analisi**")
        if st.checkbox("Sintesi Esecutiva"): tasks.append(("Sintesi", "Crea una Sintesi Esecutiva con Valori del Calcolatore."))
        if st.checkbox("Timeline"): tasks.append(("Timeline", "Crea Timeline cronologica eventi."))
        if st.checkbox("Matrice Rischi"): tasks.append(("Matrice_Rischi", "Crea Matrice Rischi (Evento, Probabilità, Impatto)."))
    with col_b:
        st.markdown("**Tecnica**")
        if st.checkbox("Punti Attacco"): tasks.append(("Punti_Attacco", "Elenca Punti di Attacco Tecnici con citazioni."))
        if st.checkbox("Analisi Critica"): tasks.append(("Analisi_Critica", "Analizza criticamente controparte."))
        if st.checkbox("Quesiti CTU"): tasks.append(("Quesiti_Tecnici", "Formula Quesiti Tecnici per CTU."))
    with col_c:
        st.markdown("**Chiusura**")
        if st.checkbox("Replica"): tasks.append(("Nota_Difensiva", "Redigi Nota Difensiva completa."))
        if st.checkbox("Strategia"): tasks.append(("Strategia", "Definisci Strategia (Scenario A vs B)."))
        if st.checkbox("Transazione"): tasks.append(("Bozza_Accordo", "Redigi Bozza Transattiva aggressiva."))

    if st.button("GENERA ANTEPRIMA (Gratis)"):
        parts, _ = get_file_content(files)
        st.session_state.generated_docs = {}
        bar = st.progress(0)
        for i, (name, prompt_task) in enumerate(tasks):
            j = interroga_gemini_json(prompt_task, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
            d, m, e = crea_output_file(j, fmt)
            st.session_state.generated_docs[name] = {"data":d, "mime":m, "ext":e}
            bar.progress((i+1)/len(tasks))
        st.success("Documenti generati in memoria!")

    # AREA DOWNLOAD (PROTETTA DAL PAYWALL)
    if st.session_state.generated_docs:
        st.divider()
        st.subheader("📥 Download & Delivery")
        
        if st.session_state.user_status == "FREE":
            st.markdown(f"""
            <div class='premium-box'>
                <h3>🔒 {len(st.session_state.generated_docs)} DOCUMENTI PRONTI</h3>
                <p>I documenti sono stati generati e sono pronti per la consegna.</p>
                <p><b>Sblocca il download e l'invio email con Premium.</b></p>
            </div>
            """, unsafe_allow_html=True)
            if PAYMENT_ENABLED:
                u = crea_checkout_session()
                st.link_button("SBLOCCA ORA (€49)", u, type="primary")
        else:
            # UTENTE PREMIUM
            zip_data = crea_zip(st.session_state.generated_docs)
            n_zip = f"Fascicolo_{st.session_state.nome_fascicolo.replace(' ', '_')}.zip"
            
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📦 SCARICA TUTTO (ZIP)", zip_data, n_zip, "application/zip", type="primary")
                for k, v in st.session_state.generated_docs.items():
                    st.download_button(f"📄 {k}", v["data"], f"{k}.{v['ext']}", v["mime"])
            
            with c2:
                st.write("**Invia al Cliente**")
                dest = st.text_input("Email destinatario")
                if st.button("📧 Invia Email"):
                    zip_data.seek(0)
                    res = invia_email(dest, f"Fascicolo {st.session_state.nome_fascicolo}", "In allegato i documenti.", zip_data, n_zip)
                    if res is True: st.success("Email inviata!")
                    else: st.error(f"Errore: {res}")
