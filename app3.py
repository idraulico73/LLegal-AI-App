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
APP_VER = "Rev 46 (Final Merge: DB + Privacy + Full AI)"
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
    if not SUPABASE_AVAILABLE: return None, "Libreria mancante"
    try:
        if "supabase" not in st.secrets: return None, "Secrets mancanti"
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key), None
    except Exception as e: return None, str(e)

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
        # Regex per Email e CF
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
if "nome_fascicolo" not in st.session_state: st.session_state.nome_fascicolo = "Nuovo_Caso"

# --- SETUP AI (REV 44 LOGIC: AUTO-DISCOVERY) ---
HAS_KEY = False
active_model = None
try:
    if "GOOGLE_API_KEY" in st.secrets:
        GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    elif "google" in st.secrets:
        GENAI_KEY = st.secrets["google"]["api_key"]
    else:
        GENAI_KEY = None

    if GENAI_KEY:
        genai.configure(api_key=GENAI_KEY)
        HAS_KEY = True
        # AUTO-DISCOVERY DEL MODELLO (FIX PER ERRORE 404)
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            priority = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-1.5-pro-latest"]
            for cand in priority:
                if cand in models:
                    active_model = cand
                    break
            if not active_model and models: active_model = models[0] # Fallback sul primo disponibile
        except:
            active_model = "models/gemini-1.5-flash" # Estremo tentativo
except Exception as e:
    st.error(f"Errore Chiave AI: {e}")

# --- FUNZIONI CORE ---
def parse_markdown_pro(doc, text):
    """Parser Blindato Anti-Crash"""
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

# --- AGGIUNGI QUESTA FUNZIONE DI PULIZIA ---
def clean_json_text(text):
    """Pulisce l'output dell'AI da Markdown e caratteri illegali per il JSON"""
    # 1. Rimuove i blocchi markdown ```json ... ```
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    
    # 2. Rimuove eventuali commenti o testo fuori dal JSON (cerca la prima { e l'ultima })
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
        
    # 3. Gestione caratteri di controllo (Newline non escapati)
    # Spesso l'AI va a capo dentro le stringhe. Proviamo a sanificare.
    # (Questa è una regex semplificata, per casi gravi serve un parser permissivo)
    return text.strip()

# --- AGGIUNGI QUESTA FUNZIONE DI PULIZIA ---
def clean_json_text(text):
    """Pulisce l'output dell'AI da Markdown e caratteri illegali per il JSON"""
    # 1. Rimuove i blocchi markdown ```json ... ```
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    
    # 2. Rimuove eventuali commenti o testo fuori dal JSON (cerca la prima { e l'ultima })
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
        
    # 3. Gestione caratteri di controllo (Newline non escapati)
    # Spesso l'AI va a capo dentro le stringhe. Proviamo a sanificare.
    # (Questa è una regex semplificata, per casi gravi serve un parser permissivo)
    return text.strip()

# --- SOSTITUISCI LA FUNZIONE INTERROGAZIONE ---
def interroga_gemini_json(prompt, contesto, input_parts, aggressivita, force_interview=False):
    if not HAS_KEY or not active_model: return {"titolo": "Errore", "contenuto": "AI Offline."}
    
    sanitizer = st.session_state.sanitizer
    prompt_safe = sanitizer.sanitize(prompt)
    contesto_safe = sanitizer.sanitize(contesto)
    
    mood = "Tecnico"
    if aggressivita > 7: mood = "ESTREMAMENTE AGGRESSIVO (Legal Warfare)" # Forziamo il mood
    elif aggressivita < 4: mood = "DIPLOMATICO"

    sys = f"""
    SEI UN LEGAL AI ASSISTANT. MOOD: {mood}.
    OBBIETTIVO: {st.session_state.dati_calcolatore}
    OUTPUT: SOLO JSON VALIDISSIMO (senza commenti, senza markdown).
    SCHEMA: {{ "titolo": "...", "contenuto": "..." }}
    """
    
    payload = list(input_parts)
    final_prompt = f"UTENTE: '{prompt_safe}'. Genera JSON."
    if force_interview: final_prompt += " IGNORA RISPOSTA DIRETTA. Genera 3 domande strategiche."
    payload.append(final_prompt)
    
    try:
        model = genai.GenerativeModel(active_model, system_instruction=sys, generation_config={"response_mime_type": "application/json"})
        resp = model.generate_content(payload)
        
        # --- FIX APPLICATO QUI ---
        cleaned_text = clean_json_text(resp.text)
        # strict=False permette caratteri di controllo come \n dentro le stringhe
        return json.loads(cleaned_text, strict=False) 
        
    except Exception as e:
        # Fallback: se fallisce il JSON, restituisce il testo grezzo come contenuto
        return {"titolo": "Errore Parsing (Raw Text Recupertato)", "contenuto": f"L'AI ha risposto ma il formato non era valido. Ecco il testo grezzo:\n\n{resp.text if 'resp' in locals() else str(e)}"}

def crea_output_file(json_data, formato):
    raw_content = json_data.get("contenuto", "")
    if raw_content is None: testo = "Nessun contenuto."
    else: testo = str(raw_content)
    # DE-ANONIMIZZAZIONE
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
            # RIPRISTINATO NOME DINAMICO COMPLETO
            cli = st.session_state.nome_fascicolo.replace(" ", "_")
            ts = datetime.now().strftime("%Y%m%d")
            fname = f"{n}_{cli}_{ts}.{info['ext']}"
            z.writestr(fname, info['data'].getvalue())
    buf.seek(0)
    return buf

# --- UI SIDEBAR ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(APP_VER)
    
    # STATUS AI
    if HAS_KEY and active_model:
        st.success(f"AI: {active_model}")
    else:
        st.error("AI: Disconnessa")

    # SETUP DB
    st.divider()
    st.subheader("🔐 Accesso")
    
    studi_options = {}
    if supabase:
        try:
            res = supabase.table("studi_legali").select("*").execute()
            studi_data = res.data
            studi_options = {s['nome_studio']: s['id'] for s in studi_data}
            st.success("✅ DB Connesso")
        except Exception as e:
            st.warning("Modalità Offline (Cache)")
            studi_options = {"Demo Local": "local_demo"}
    else:
        studi_options = {"Demo Local": "local_demo"}
        
    sel_studio = st.selectbox("Seleziona Studio", list(studi_options.keys()))
    st.session_state.current_studio_id = studi_options[sel_studio]

    st.divider()
    # PRIVACY UI
    st.subheader("🛡️ Privacy")
    n1 = st.text_input("Nome Cliente", "Leonardo Cavalaglio")
    n2 = st.text_input("Nome Controparte", "Castillo Medina")
    if st.button("Attiva Protezione"):
        st.session_state.sanitizer.add_entity(n1, "CLIENTE")
        st.session_state.sanitizer.add_entity(n2, "CONTROPARTE")
        st.toast(f"Dati mascherati attivata.", icon="🔒")
        
    st.divider()
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
        st.success("Salvato.")

with t2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True)
    parts, full_txt = get_file_content(files)
    
    # Audit Log
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
    
    # RIPRISTINATI TUTTI E 9 I DOCUMENTI
    col_a, col_b, col_c = st.columns(3)
    tasks = []
    
    with col_a:
        st.markdown("**Analisi & Sintesi**")
        if st.checkbox("Sintesi Esecutiva"): tasks.append(("Sintesi", "Crea una Sintesi Esecutiva del caso. REQ: Box iniziale con i Valori del Calcolatore. Usa Bullet Points semaforici."))
        if st.checkbox("Timeline Cronologica"): tasks.append(("Timeline", "Crea una Timeline rigorosa degli eventi. REQ: Calcola il tempo trascorso tra le date chiave."))
        if st.checkbox("Matrice dei Rischi"): tasks.append(("Matrice_Rischi", "Crea una Matrice dei Rischi. REQ: Tabella con colonne Evento, Probabilità, Impatto Economico. Riga Totale in fondo."))
    with col_b:
        st.markdown("**Tecnica & Difesa**")
        if st.checkbox("Punti di Attacco"): tasks.append(("Punti_Attacco", "Elenca i Punti di Attacco Tecnici/Legali. REQ: Cita precisamente i documenti (Pagina X). Usa i dati del Calcolatore."))
        if st.checkbox("Analisi Critica"): tasks.append(("Analisi_Critica", "Analizza criticamente le tesi/documenti avversari. REQ: Tono fermo/aggressivo se richiesto."))
        if st.checkbox("Quesiti Tecnici"): tasks.append(("Quesiti_Tecnici", "Formula Quesiti Tecnici o per il CTU. REQ: Domande numerate, senza preamboli."))
    with col_c:
        st.markdown("**Strategia & Chiusura**")
        if st.checkbox("Nota Difensiva"): tasks.append(("Nota_Difensiva", "Redigi una Nota Difensiva/Replica completa. REQ: Integra i calcoli economici e le contestazioni tecniche."))
        if st.checkbox("Strategia"): tasks.append(("Strategia", "Definisci la Strategia. REQ: Confronta Scenario A (Accordo) vs Scenario B (Contenzioso) con costi stimati."))
        if st.checkbox("Bozza Accordo"): tasks.append(("Bozza_Accordo", "Redigi una Bozza di Accordo/Transazione. REQ: Inserisci clausola di validità temporale dell'offerta."))
            
    if st.button("GENERA FASCICOLO COMPLETO"):
        parts, _ = get_file_content(files)
        st.session_state.generated_docs = {}
        bar = st.progress(0)
        for i, (name, prompt_task) in enumerate(tasks):
            j = interroga_gemini_json(prompt_task, st.session_state.contesto_chat_text, parts, 5, False)
            d, m, e = crea_output_file(j, fmt)
            st.session_state.generated_docs[name] = {"data":d, "mime":m, "ext":e}
            bar.progress((i+1)/len(tasks))
            
    if st.session_state.generated_docs:
        zip_data = crea_zip(st.session_state.generated_docs)
        # NOME DINAMICO RIPRISTINATO
        nome_zip = f"Fascicolo_{st.session_state.nome_fascicolo.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.zip"
        st.download_button("📦 SCARICA ZIP", zip_data, nome_zip, "application/zip", type="primary")


