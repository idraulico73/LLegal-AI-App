import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# Librerie Esterne
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE ---
APP_NAME = "LexVantage"
APP_VERSION = "v4.1 (Dynamic Supervisor & Full Calc)"
APP_ICON = "⚖️"

st.set_page_config(page_title=APP_NAME, layout="wide", page_icon=APP_ICON)

# --- CSS (ANTI-TABELLA & LAYOUT) ---
st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    .chat-message { padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex; gap: 10px; }
    .chat-message.user { background-color: #f0f2f6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; }
    .status-box { padding: 15px; border-radius: 5px; margin-bottom: 10px; border-left: 5px solid #f1c40f; background-color: #fef9e7; }
    /* Fallback estremo per tabelle */
    .stMarkdown table { display: block; overflow-x: auto; white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

# --- API & MODELLI ---
HAS_KEY = False
try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
    
    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    smart = next((m for m in ["models/gemini-1.5-pro", "models/gemini-1.5-pro-latest"] if m in models), models[0])
    fast = next((m for m in ["models/gemini-1.5-flash", "models/gemini-1.5-flash-latest"] if m in models), smart)
    
    ACTIVE_MODEL = smart
    FAST_MODEL = fast
    STATUS_TEXT = f"Motore: {smart.split('/')[-1]}"
except:
    STATUS_TEXT = "Errore API Key"

# --- STATO ---
if "messages" not in st.session_state: st.session_state.messages = []
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato."
if "doc_queue" not in st.session_state: st.session_state.doc_queue = []
if "sup_hist" not in st.session_state: st.session_state.sup_hist = []
if "ready" not in st.session_state: st.session_state.ready = False
if "gen_docs" not in st.session_state: st.session_state.gen_docs = {}

# --- FUNZIONI UTILI ---

def nuke_tables(text):
    """Distrugge le tabelle nell'output chat sostituendo i pipe."""
    return text.replace("|", " - ")

def clean_doc(text):
    lines = text.split('\n')
    out = []
    skip = True
    for l in lines:
        if skip:
            if any(x in l for x in ["Assolutamente", "Ecco", "Generato", "Analizzo"]): continue
            if l.strip() == "---": continue
            skip = False
        out.append(l)
    return "\n".join(out)

def read_files(files):
    parts = []
    log = ""
    for f in files:
        try:
            if f.type == "application/pdf":
                pdf = PdfReader(f)
                txt = "\n".join([p.extract_text() for p in pdf.pages])
                parts.append(f"FILE {f.name}:\n{txt}")
                log += f"📄 {f.name}\n"
            elif f.name.endswith(".docx"):
                doc = Document(f)
                txt = "\n".join([p.text for p in doc.paragraphs])
                parts.append(f"FILE {f.name}:\n{txt}")
                log += f"📘 {f.name}\n"
            else:
                if "image" in f.type:
                    img = PIL.Image.open(f)
                    parts.append(img)
                    log += f"🖼️ {f.name}\n"
                else:
                    parts.append(f"FILE {f.name}:\n{str(f.read(), 'utf-8')}")
                    log += f"📝 {f.name}\n"
        except: log += f"❌ Err {f.name}\n"
    return parts, log

def create_docx(text, title):
    doc = Document()
    doc.add_heading(title, 0)
    lines = text.split('\n')
    tbl_rows = []
    in_tbl = False
    
    for line in lines:
        l = line.strip()
        if l.startswith('|') and l.endswith('|'):
            in_tbl = True
            tbl_rows.append(l)
        else:
            if in_tbl:
                rows = [r for r in tbl_rows if not set(r) <= {'|','-',' ',':'}]
                if rows:
                    cols = len(rows[0].split('|')) - 2
                    if cols > 0:
                        tbl = doc.add_table(rows=len(rows), cols=cols)
                        tbl.style = 'Table Grid'
                        for i, r_txt in enumerate(rows):
                            cells = r_txt.split('|')[1:-1]
                            for j, c_txt in enumerate(cells):
                                if j < cols: tbl.cell(i, j).text = c_txt.strip()
                tbl_rows = []
                in_tbl = False
            
            if l.startswith('# '): doc.add_heading(l[2:], 1)
            elif l.startswith('## '): doc.add_heading(l[3:], 2)
            elif l.startswith('### '): doc.add_heading(l[4:], 3)
            elif l.startswith('- '): doc.add_paragraph(l[2:], style='List Bullet')
            elif l: doc.add_paragraph(l)
            
    if in_tbl and tbl_rows:
        rows = [r for r in tbl_rows if not set(r) <= {'|','-',' ',':'}]
        if rows:
            cols = len(rows[0].split('|')) - 2
            if cols > 0:
                tbl = doc.add_table(rows=len(rows), cols=cols)
                tbl.style = 'Table Grid'
                for i, r_txt in enumerate(rows):
                    cells = r_txt.split('|')[1:-1]
                    for j, c_txt in enumerate(cells):
                        if j < cols: tbl.cell(i, j).text = c_txt.strip()
    b = BytesIO()
    doc.save(b)
    b.seek(0)
    return b

# --- PROMPTS ---
PROMPTS = {
    "Sintesi": "TIMELINE (Causa-Effetto) e SINTESI ESECUTIVA.",
    "Strategia": "STRATEGIA (Game Theory) e MATRICE RISCHI.",
    "Attacco": "PUNTI DI ATTACCO e QUESITI CTU.",
    "Transazione": "BOZZA TRANSAZIONE e NOTA REPLICA."
}

# --- AGENTI ---

def supervisor(ctx, queue, hist):
    if not HAS_KEY: return "READY", ""
    
    model = genai.GenerativeModel(FAST_MODEL)
    txt_ctx = "\n".join([p for p in ctx if isinstance(p, str)])[:25000]
    
    # Prompt Dinamico: Valuta la completezza reale
    prompt = f"""
    SEI UN SUPERVISORE LEGALE.
    DOC RICHIESTI: {queue}.
    CONTESTO: {txt_ctx}.
    STORICO DOMANDE: {hist}.
    
    CRITERI DI COMPLETEZZA:
    1. Abbiamo chiaro l'obiettivo strategico (es. chiudere subito vs massimizzare profitto)?
    2. Abbiamo i dati economici essenziali (valori, date)?
    3. Abbiamo compreso la posizione della controparte?
    
    ISTRUZIONI:
    - Se manca una di queste info critiche, FAI UNA DOMANDA specifica.
    - Se hai tutto il necessario per redigere documenti di alto livello, rispondi SOLO "READY".
    - Non fare domande di cortesia. Sii chirurgico.
    """
    try:
        res = model.generate_content(prompt).text.strip()
        return ("READY", "") if "READY" in res.upper() else ("ASK", res)
    except: return "READY", ""

def generator(task, ctx, hist, posture, calc):
    if not HAS_KEY: return "Err"
    model = genai.GenerativeModel(ACTIVE_MODEL)
    chat_txt = "\n".join([f"{m['role']}: {m['content']}" for m in hist])
    full_prompt = f"""
    SEI LEXVANTAGE. RUOLO: STRATEGA LEGALE. POSTURA: {postura}/10.
    DATI CALCOLATORE: {calc}
    TASK: {task}
    FORMATO: Markdown con tabelle (| A | B |). NO PREMESSE.
    """
    payload = list(ctx)
    payload.append(f"STORICO:\n{chat_txt}\n\nESEGUI: {full_prompt}")
    try: return clean_doc(model.generate_content(payload).text)
    except Exception as e: return str(e)

def chat_reply(q, ctx, hist):
    if not HAS_KEY: return "Err"
    model = genai.GenerativeModel(ACTIVE_MODEL)
    sys = "SEI UN ASSISTENTE. RISPONDI ALLA DOMANDA. NON USARE TABELLE MARKDOWN (NO PIPES |). USA ELENCHI."
    chat_txt = "\n".join([f"{m['role']}: {m['content']}" for m in hist])
    payload = list(ctx)
    payload.append(f"{sys}\nSTORICO:{chat_txt}\nUSER:{q}")
    try:
        txt = model.generate_content(payload).text
        return nuke_tables(txt)
    except Exception as e: return str(e)

# --- INTERFACCIA ---

with st.sidebar:
    st.title(f"{APP_ICON} {APP_NAME}")
    st.caption("v4.1")
    if st.button("🔄 Reset"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    st.success(STATUS_TEXT) if HAS_KEY else st.error("No API Key")
    postura = st.slider("Aggressività", 1, 10, 7)

tab1, tab2, tab3 = st.tabs(["🧮 Calcolatore", "💬 Chat & Upload", "🚀 Workflow"])

# TAB 1: CALCOLATORE (RIPRISTINATO COMPLETO)
with tab1:
    st.header("📉 Calcolatore Deprezzamento")
    st.info("I dati calcolati qui verranno usati dall'AI per i documenti.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        valore_base = st.number_input("Valore Base CTU/Mercato (€)", value=354750.0, step=1000.0)
        st.markdown("### Coefficienti")
        c1 = st.checkbox("Irregolarità urbanistica grave (30%)", value=True)
        c2 = st.checkbox("Superfici non abitabili (18%)", value=True)
        c3 = st.checkbox("Assenza mutuabilità (15%)", value=True)
        c4 = st.checkbox("Assenza agibilità (8%)", value=True)
        c5 = st.checkbox("Occupazione (5%)", value=True)
        btn_calcola = st.button("Calcola & Invia all'AI", type="primary")

    with col2:
        if btn_calcola:
            fattore_residuo = 1.0
            dettaglio = []
            
            if c1: fattore_residuo *= (1 - 0.30); dettaglio.append("-30% (Irregolarità)")
            if c2: fattore_residuo *= (1 - 0.18); dettaglio.append("-18% (Sup. non abitabili)")
            if c3: fattore_residuo *= (1 - 0.15); dettaglio.append("-15% (No Mutuo)")
            if c4: fattore_residuo *= (1 - 0.08); dettaglio.append("-8% (No Agibilità)")
            if c5: fattore_residuo *= (1 - 0.05); dettaglio.append("-5% (Occupazione)")
            
            valore_finale = valore_base * fattore_residuo
            deprezzamento_valore = valore_base - valore_finale
            deprezzamento_perc = (1 - fattore_residuo) * 100
            
            report = f"""
            VALORE BASE: € {valore_base:,.2f}
            COEFFICIENTI APPLICATI: {', '.join(dettaglio)}
            FATTORE RESIDUO: {fattore_residuo:.4f}
            VALORE NETTO: € {valore_finale:,.2f}
            """
            st.session_state.dati_calcolatore = report
            
            st.success(f"### Valore Netto: € {valore_finale:,.2f}")
            st.metric("Deprezzamento", f"- {deprezzamento_perc:.2f}%", f"- € {deprezzamento_valore:,.2f}")
            st.caption("✅ Dati inviati alla memoria dell'AI.")

# TAB 2: CHAT & UPLOAD
with tab2:
    st.write("### 1. Upload")
    up = st.file_uploader("File", accept_multiple_files=True)
    ctx = []
    if up:
        ctx, log = read_files(up)
        with st.expander("Log"): st.text(log)
        
    st.divider()
    st.write("### 2. Chat (Safe Mode)")
    for m in st.session_state.messages:
        role = "user" if m['role']=='user' else "bot"
        st.markdown(f"<div class='chat-message {role}'>{m['content']}</div>", unsafe_allow_html=True)
        
    if q := st.chat_input("..."):
        st.session_state.messages.append({"role":"user", "content":q})
        st.rerun()
        
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.spinner("..."):
            ans = chat_reply(st.session_state.messages[-1]["content"], ctx, st.session_state.messages[:-1])
            st.session_state.messages.append({"role":"assistant", "content":ans})
            st.rerun()

# TAB 3: WORKFLOW
with tab3:
    if not up: st.info("Carica file nel Tab 2")
    else:
        st.header("Generazione")
        c1, c2 = st.columns(2)
        with c1:
            s1 = st.checkbox("Sintesi & Timeline")
            s2 = st.checkbox("Attacco & Quesiti")
        with c2:
            s3 = st.checkbox("Strategia & Rischi")
            s4 = st.checkbox("Transazione & Replica")
            
        if st.button("AVVIA ANALISI"):
            q = []
            if s1: q.append(("01_Analisi", PROMPTS["Sintesi"]))
            if s2: q.append(("02_Attacco", PROMPTS["Attacco"]))
            if s3: q.append(("03_Strategia", PROMPTS["Strategia"]))
            if s4: q.append(("04_Chiusura", PROMPTS["Transazione"]))
            
            if q:
                st.session_state.doc_queue = q
                st.session_state.ready = False
                st.session_state.sup_hist = []
                st.rerun()
                
        if st.session_state.doc_queue and not st.session_state.ready:
            st.divider()
            
            # Logic Supervisor
            last_role = st.session_state.sup_hist[-1]['role'] if st.session_state.sup_hist else 'user'
            if last_role == 'user':
                with st.spinner("Il Supervisore analizza la completezza..."):
                    stat, msg = supervisor(ctx, st.session_state.doc_queue, st.session_state.sup_hist)
                    if stat == "READY": st.session_state.ready = True
                    else: st.session_state.sup_hist.append({"role":"assistant", "content":msg})
                    st.rerun()
            
            # Chat Supervisor
            st.markdown(f"<div class='status-box'><b>SUPERVISORE ATTIVO</b></div>", unsafe_allow_html=True)
            for m in st.session_state.sup_hist:
                icon = "👤" if m['role']=='user' else "⚖️"
                st.write(f"**{icon}**: {m['content']}")
                
            ans = st.text_input("Risposta:", key="sup_in")
            if st.button("Invia"):
                st.session_state.sup_hist.append({"role":"user", "content":ans})
                st.rerun()
                
        if st.session_state.ready:
            st.divider()
            st.success("Tutte le informazioni acquisite. Generazione...")
            pbar = st.progress(0)
            for i, (n, p) in enumerate(st.session_state.doc_queue):
                txt = generator(p, ctx, st.session_state.sup_hist, postura, st.session_state.dati_calcolatore)
                docx = create_docx(txt, n)
                st.session_state.gen_docs[n] = docx
                pbar.progress((i+1)/len(st.session_state.doc_queue))
            st.session_state.doc_queue = []
            st.rerun()
            
        if st.session_state.gen_docs:
            st.write("### Download")
            cols = st.columns(3)
            for i, (k, v) in enumerate(st.session_state.gen_docs.items()):
                with cols[i%3]: st.download_button(f"📄 {k}", v, f"{k}.docx")
