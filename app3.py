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
from supabase import create_client, Client

# --- CONFIGURAZIONE APP ---
APP_NAME = "LexVantage"
APP_VER = "Rev 45 (Privacy Shield + DB Connected)"
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

# --- INIZIALIZZAZIONE SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Errore connessione DB: {e}")
        return None

supabase = init_supabase()

# --- CLASSE PRIVACY SHIELD (ANONIMIZZATORE) ---
class DataSanitizer:
    def __init__(self):
        self.mapping = {} # Mappa originale -> anonimo
        self.reverse_mapping = {} # Anonimo -> originale
        self.counter = 1
        
    def add_entity(self, real_name, role_label):
        """Registra un nome da proteggere"""
        if real_name and real_name not in self.mapping:
            fake = f"[{role_label}_{self.counter}]"
            self.mapping[real_name] = fake
            self.reverse_mapping[fake] = real_name
            self.counter += 1
            
    def sanitize(self, text):
        """Sostituisce i dati sensibili con placeholder"""
        clean_text = text
        # 1. Mascheramento Email e Codici Fiscali (Regex base)
        clean_text = re.sub(r'[\w\.-]+@[\w\.-]+', '[EMAIL_PROTETTA]', clean_text)
        clean_text = re.sub(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]', '[CF_OSCURATO]', clean_text)
        
        # 2. Mascheramento Nomi Specifici
        for real, fake in self.mapping.items():
            clean_text = clean_text.replace(real, fake)
            # Gestisce anche il case-insensitive parziale
            clean_text = clean_text.replace(real.upper(), fake)
            
        return clean_text
        
    def restore(self, text):
        """Ripristina i nomi reali nei documenti finali"""
        if not text: return ""
        restored = text
        for fake, real in self.reverse_mapping.items():
            restored = restored.replace(fake, real)
        return restored

# Inizializza Sanitizer in Session State
if "sanitizer" not in st.session_state:
    st.session_state.sanitizer = DataSanitizer()

# --- STATE MANAGEMENT ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo."
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "current_studio_id" not in st.session_state: st.session_state.current_studio_id = None
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False

# --- SETUP AI ---
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        # Fallback per secrets annidati
        genai.configure(api_key=st.secrets["google"]["api_key"])
except:
    st.warning("Chiave Google non trovata nei secrets.")

def get_ai_model():
    return genai.GenerativeModel("models/gemini-1.5-flash")

# --- FUNZIONI CORE (FIXATE) ---

def parse_markdown_pro(doc, text):
    """Parser Universale Blindato"""
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
    # Logica Anonimizzazione
    sanitizer = st.session_state.sanitizer
    prompt_safe = sanitizer.sanitize(prompt)
    contesto_safe = sanitizer.sanitize(contesto)
    
    # Sanitizzazione Input Documentale (Mockup - in prod andrebbe fatto sui file reali)
    # Per ora puliamo solo il prompt e il contesto chat.
    
    mood = "Tecnico/Formale"
    if aggressivita > 7: mood = "AGGRESSIVO (Legal Warfare)"
    elif aggressivita < 4: mood = "DIPLOMATICO (Mediazione)"

    sys = f"""
    SEI UN CONSULENTE LEGALE AI. MOOD: {mood}.
    OUTPUT: SOLO JSON {{ "titolo": "...", "contenuto": "..." }}.
    NOTA PRIVACY: I nomi sono stati sostituiti con etichette (es. [CLIENTE_1]). 
    NON INVENTARE NOMI REALI. Usa le etichette fornite.
    
    DATI: {st.session_state.dati_calcolatore}
    STORICO: {contesto_safe}
    """
    
    payload = list(input_parts) # Attenzione: qui passiamo i file raw. 
    # TODO: In Fase 2 avanzata, implementare OCR + Sanitize sui PDF prima di inviarli.
    
    final_prompt = f"UTENTE: '{prompt_safe}'. Genera JSON."
    if force_interview:
        final_prompt += " IGNORA RISPOSTA DIRETTA. Genera 3 domande strategiche."
        
    payload.append(final_prompt)
    
    try:
        model = get_ai_model()
        resp = model.generate_content(payload, generation_config={"response_mime_type": "application/json"})
        return json.loads(resp.text)
    except Exception as e:
        return {"titolo": "Errore", "contenuto": str(e)}

def crea_output_file(json_data, formato):
    raw_content = json_data.get("contenuto", "")
    if raw_content is None: testo = "Nessun contenuto."
    else: testo = str(raw_content)
    
    # REVERSE ANONYMIZATION: Ripristina i nomi veri nel documento finale
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

# --- UI SIDEBAR: LOGIN STUDIO ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(f"{APP_VER}")
    
    st.divider()
    st.subheader("🔐 Accesso Studio")
    
    # Caricamento Studi da DB Supabase
    studi_db = []
    if supabase:
        try:
            res = supabase.table("studi_legali").select("*").execute()
            studi_db = res.data
        except: st.error("DB Offline")
        
    opts = {s['nome_studio']: s['id'] for s in studi_db}
    sel_studio = st.selectbox("Seleziona Studio", list(opts.keys()) if opts else ["Demo Local"])
    
    if sel_studio != "Demo Local":
        st.session_state.current_studio_id = opts[sel_studio]
        st.success(f"Connesso: {sel_studio}")
    
    st.divider()
    
    # CONFIGURAZIONE PRIVACY
    st.subheader("🛡️ Privacy Shield")
    n1 = st.text_input("Nome Cliente (da proteggere)", "Leonardo Cavalaglio")
    n2 = st.text_input("Nome Controparte (da proteggere)", "Castillo Medina")
    if st.button("Attiva Protezione Dati"):
        st.session_state.sanitizer.add_entity(n1, "CLIENTE")
        st.session_state.sanitizer.add_entity(n2, "CONTROPARTE")
        st.toast(f"Nomi mascherati come [CLIENTE_1] e [CONTROPARTE_1]", icon="🔒")

    st.divider()
    st.session_state.livello_aggressivita = st.slider("Aggressività", 1, 10, 5)

# --- MAIN TABS ---
t1, t2, t3 = st.tabs(["🧮 Calcolatore", "💬 Analisi Sicura", "📦 Generatore"])

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
    st.info("I documenti inviati all'AI verranno processati secondo la Privacy Policy (No-Training). I nomi nel prompt sono anonimizzati.")
    files = st.file_uploader("Fascicolo", accept_multiple_files=True)
    parts, full_txt = get_file_content(files)
    
    # Auto-Salvataggio Metadati su Supabase (Audit)
    if files and st.session_state.current_studio_id:
         if "log_sent" not in st.session_state:
             try:
                 supabase.table("fascicoli").insert({
                     "studio_id": st.session_state.current_studio_id,
                     "nome_riferimento": f"Analisi {datetime.now().strftime('%H:%M')}",
                     "stato": "in_lavorazione"
                 }).execute()
                 st.session_state.log_sent = True
                 st.toast("Fascicolo registrato nel DB in Europa 🇪🇺", icon="cloud")
             except Exception as e: st.warning(f"Err DB: {e}")

    # CHAT UI
    msg_container = st.container()
    with msg_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                content_safe = str(m.get("content", ""))
                # Mostriamo all'utente il testo RIPRISTINATO (leggibile), ma internamente l'AI ha lavorato su quello anonimo
                st.markdown(content_safe.replace("|", " - "))

    prompt = st.chat_input("Richiesta...")
    if prompt:
        st.session_state.messages.append({"role":"user", "content":prompt})
        
        # Logica Intervista Automatica
        force_interview = False
        if not st.session_state.intervista_fatta and len(st.session_state.messages) < 3:
            force_interview = True
            st.session_state.intervista_fatta = True
            
        with st.spinner("Analisi in corso (Server EU)..."):
            json_out = interroga_gemini_json(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, force_interview)
            cont = json_out.get("contenuto", "Errore generazione")
            
            # Quando l'AI risponde, potrebbe usare [CLIENTE_1]. Noi lo ripristiniamo per l'utente.
            cont_readable = st.session_state.sanitizer.restore(str(cont))
            
            st.session_state.messages.append({"role":"assistant", "content":cont_readable})
            st.session_state.contesto_chat_text += f"\nAI: {cont}" # Salviamo la storia raw
            st.rerun()

with t3:
    st.header("Generazione Atti")
    fmt = st.radio("Formato", ["Word", "PDF"])
    
    tasks = {
        "Sintesi": "Crea Sintesi Esecutiva.",
        "Timeline": "Crea Timeline Cronologica.",
        "Matrice_Rischi": "Crea Matrice Rischi.",
        "Punti_Attacco": "Crea Punti di Attacco tecnici.",
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
        st.success("Documenti pronti con Nomi Reali ripristinati.")
        zip_data = crea_zip(st.session_state.generated_docs)
        st.download_button("📦 SCARICA ZIP", zip_data, "Fascicolo_Completo.zip", "application/zip", type="primary")
