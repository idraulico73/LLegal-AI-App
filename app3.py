import streamlit as st
import json
import re
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
APP_VER = "Rev 45.1 (Privacy Shield + Fallback Mode)"
st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="⚖️")

# --- CSS & UI ---
st.markdown("""
<style>
    div[data-testid="stChatMessage"] { 
        background-color: #f8f9fa; border-radius: 8px; padding: 15px; 
        border-left: 4px solid #004e92; margin-bottom: 10px;
    }
    h1, h2, h3 { color: #003366; font-family: 'Segoe UI', sans-serif; }
    div.stButton > button { width: 100%; font-weight: 600; border-radius: 6px; }
    div.stButton > button:first-child { background-color: #004e92; color: white; }
    .privacy-badge { background-color: #d4edda; color: #155724; padding: 5px 10px; border-radius: 15px; font-size: 0.8em; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- INIZIALIZZAZIONE SUPABASE (CON DEBUG) ---
@st.cache_resource
def init_supabase():
    if not SUPABASE_AVAILABLE:
        return None, "Libreria 'supabase' non installata."
    
    try:
        # Verifica se i secrets esistono
        if "supabase" not in st.secrets:
            return None, "Sezione [supabase] mancante in secrets.toml"
            
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        
        # Test connessione immediato
        client = create_client(url, key)
        return client, None
    except Exception as e:
        return None, str(e)

supabase, db_error = init_supabase()

# --- CLASSE PRIVACY SHIELD ---
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
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo."
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "current_studio_id" not in st.session_state: st.session_state.current_studio_id = "local_demo"
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False

# --- SETUP AI ---
HAS_KEY = False
try:
    # Supporto per doppia configurazione (Globale o Annidata)
    if "GOOGLE_API_KEY" in st.secrets:
        GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    elif "google" in st.secrets:
        GENAI_KEY = st.secrets["google"]["api_key"]
    else:
        GENAI_KEY = None

    if GENAI_KEY:
        genai.configure(api_key=GENAI_KEY)
        HAS_KEY = True
except Exception as e:
    st.error(f"Errore Chiave AI: {e}")

def get_ai_model():
    return genai.GenerativeModel("models/gemini-1.5-flash")

# --- FUNZIONI CORE (Parse, Files, AI) ---
def parse_markdown_pro(doc, text):
    if text is None: return 
    text = str(text)
    if not text.strip(): return
    lines = text.split('\n')
    iterator = iter(lines)
    in_table = False
    table_data = []
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(11)
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for line in iterator:
        stripped = line.strip()
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_data = []
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if all(set(c).issubset({'-', ':', ' '}) for c in cells if c): continue
            table_data.append(cells)
            continue
        if in_table:
            if table_data:
                rows = len(table_data)
                cols = max(len(r) for r in table_data) if rows > 0 else 0
                if rows > 0 and cols > 0:
                    table = doc.add_table(rows=rows, cols=cols)
                    table.style = 'Table Grid'
                    for r_idx, row_content in enumerate(table_data):
                        for c_idx, cell_content in enumerate(row_content):
                            if c_idx < cols:
                                cell = table.cell(r_idx, c_idx)
                                cell.text = cell_content
            in_table = False
            table_data = []
        if not stripped: continue
        if stripped.startswith('#'):
            level = stripped.count('#')
            doc.add_heading(stripped.lstrip('#').strip().replace("**",""), level=min(level, 3))
            continue
        if stripped.startswith('- ') or stripped.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            content = stripped[2:]
        else:
            p = doc.add_paragraph()
            content = stripped
        p.clear()
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                run = p.add_run(part[2:-2])
                run.bold = True
            else:
                p.add_run(part)

def get_file_content(uploaded_files):
    parts = []
    full_text = ""
    parts.append("FASCICOLO:\n")
    if not uploaded_files: return [], ""
    for file in uploaded_files:
        try:
            safe = file.name.replace("|", "_")
            txt = ""
            if file.type == "application/pdf":
                pdf = PdfReader(file)
                for p in pdf.pages: txt += p.extract_text() + "\n"
            elif "word" in file.type:
                doc = Document(file)
                txt = "\n".join([p.text for p in doc.paragraphs])
            parts.append(f"\n--- FILE: {safe} ---\n{txt}")
            full_text += txt
        except: pass
    return parts, full_text

def interroga_gemini_json(prompt, contesto, input_parts, aggressivita, force_interview=False):
    if not HAS_KEY: return {"titolo": "Errore", "contenuto": "Manca API Key Google nei secrets."}
    
    sanitizer = st.session_state.sanitizer
    prompt_safe = sanitizer.sanitize(prompt)
    contesto_safe = sanitizer.sanitize(contesto)
    
    mood = "Tecnico"
    if aggressivita > 7: mood = "AGGRESSIVO"
    elif aggressivita < 4: mood = "DIPLOMATICO"

    sys = f"""
    SEI UN LEGAL AI ASSISTANT. MOOD: {mood}.
    OUTPUT: SOLO JSON {{ "titolo": "...", "contenuto": "..." }}.
    NOTA: Usa i placeholder [CLIENTE_1] etc. se presenti.
    DATI: {st.session_state.dati_calcolatore}
    STORICO: {contesto_safe}
    """
    
    payload = list(input_parts)
    final_prompt = f"UTENTE: '{prompt_safe}'. Genera JSON."
    if force_interview: final_prompt += " IGNORA RISPOSTA DIRETTA. Genera 3 domande strategiche."
    payload.append(final_prompt)
    
    try:
        model = get_ai_model()
        resp = model.generate_content(payload, generation_config={"response_mime_type": "application/json"})
        return json.loads(resp.text)
    except Exception as e:
        return {"titolo": "Errore AI", "contenuto": str(e)}

def crea_output_file(json_data, formato):
    raw_content = json_data.get("contenuto", "")
    if raw_content is None: testo = "Nessun contenuto."
    else: testo = str(raw_content)
    testo_reale = st.session_state.sanitizer.restore(testo)
    titolo = json_data.get("titolo", "Doc")
    
    if formato == "Word":
        doc = Document()
        doc.add_heading(titolo, 0)
        parse_markdown_pro(doc, testo_reale)
        buf = BytesIO()
        doc.save(buf)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, txt=titolo.encode('latin-1','replace').decode('latin-1'), ln=1, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", size=11)
        safe_tx = testo_reale.replace("€","EUR").encode('latin-1','replace').decode('latin-1')
        pdf.multi_cell(0, 6, txt=safe_tx)
        buf = BytesIO()
        buf.write(pdf.output(dest='S').encode('latin-1'))
        mime = "application/pdf"
        ext = "pdf"
    buf.seek(0)
    return buf, mime, ext

def crea_zip(docs):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, info in docs.items():
            ts = datetime.now().strftime("%Y%m%d")
            fname = f"{n}_{ts}.{info['ext']}"
            z.writestr(fname, info['data'].getvalue())
    buf.seek(0)
    return buf

# --- UI SIDEBAR ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(APP_VER)
    
    # SETUP DB CON FALLBACK
    st.divider()
    st.subheader("🔐 Accesso")
    
    studi_options = {}
    
    if supabase:
        try:
            # Prova a leggere dal DB
            res = supabase.table("studi_legali").select("*").execute()
            studi_data = res.data
            studi_options = {s['nome_studio']: s['id'] for s in studi_data}
            st.success("✅ DB Connesso")
        except Exception as e:
            st.warning(f"⚠️ Errore Query DB: {e}")
            studi_options = {"Modalità Offline (Locale)": "local_demo"}
    else:
        st.error(f"❌ DB Offline: {db_error}")
        studi_options = {"Modalità Offline (Locale)": "local_demo"}
        
    sel_studio = st.selectbox("Seleziona Studio", list(studi_options.keys()))
    st.session_state.current_studio_id = studi_options[sel_studio]

    st.divider()
    # PRIVACY
    st.subheader("🛡️ Privacy")
    n1 = st.text_input("Nome Cliente", "Leonardo Cavalaglio")
    n2 = st.text_input("Nome Controparte", "Castillo Medina")
    if st.button("Attiva Protezione"):
        st.session_state.sanitizer.add_entity(n1, "CLIENTE")
        st.session_state.sanitizer.add_entity(n2, "CONTROPARTE")
        st.toast(f"Dati mascherati attivata.", icon="🔒")
        
    st.divider()
    st.session_state.livello_aggressivita = st.slider("Aggressività", 1, 10, 5)

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
        st.success("Salvato.")

with t2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True)
    parts, full_txt = get_file_content(files)
    
    # Audit Log (Solo se DB connesso)
    if files and supabase and st.session_state.current_studio_id != "local_demo":
         if "log_sent" not in st.session_state:
             try:
                 supabase.table("fascicoli").insert({
                     "studio_id": st.session_state.current_studio_id,
                     "nome_riferimento": f"Analisi {datetime.now().strftime('%H:%M')}",
                     "stato": "in_lavorazione"
                 }).execute()
                 st.session_state.log_sent = True
                 st.toast("Audit salvato su DB", icon="cloud")
             except: pass

    msg_container = st.container()
    with msg_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(str(m.get("content", "")).replace("|", " - "))

    prompt = st.chat_input("Richiesta...")
    if prompt:
        st.session_state.messages.append({"role":"user", "content":prompt})
        force_interview = False
        if not st.session_state.intervista_fatta and len(st.session_state.messages) < 3:
            force_interview = True
            st.session_state.intervista_fatta = True
            
        with st.spinner("Elaborazione..."):
            json_out = interroga_gemini_json(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, force_interview)
            cont = json_out.get("contenuto", "Errore")
            cont_readable = st.session_state.sanitizer.restore(str(cont))
            st.session_state.messages.append({"role":"assistant", "content":cont_readable})
            st.session_state.contesto_chat_text += f"\nAI: {cont}"
            st.rerun()

with t3:
    st.header("Generazione Atti")
    fmt = st.radio("Formato", ["Word", "PDF"])
    tasks = {
        "Sintesi": "Crea Sintesi Esecutiva.", "Timeline": "Crea Timeline Cronologica.",
        "Matrice_Rischi": "Crea Matrice Rischi.", "Punti_Attacco": "Crea Punti di Attacco tecnici.",
        "Nota_Difensiva": "Redigi Nota Difensiva completa."
    }
    selected_docs = []
    cols = st.columns(3)
    for i, (key, val) in enumerate(tasks.items()):
        with cols[i % 3]:
            if st.checkbox(key): selected_docs.append((key, val))
            
    if st.button("GENERA DOCUMENTI"):
        parts, _ = get_file_content(files)
        st.session_state.generated_docs = {}
        bar = st.progress(0)
        for i, (name, prompt_task) in enumerate(selected_docs):
            j = interroga_gemini_json(prompt_task, st.session_state.contesto_chat_text, parts, 5, False)
            d, m, e = crea_output_file(j, fmt)
            st.session_state.generated_docs[name] = {"data":d, "mime":m, "ext":e}
            bar.progress((i+1)/len(selected_docs))
            
    if st.session_state.generated_docs:
        zip_data = crea_zip(st.session_state.generated_docs)
        st.download_button("📦 SCARICA ZIP", zip_data, "Fascicolo.zip", "application/zip", type="primary")
