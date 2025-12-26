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

# --- BRANDING & CONFIGURAZIONE GLOBALE ---
APP_NAME = "LexVantage"
APP_SUBTITLE = "Ingegneria Forense & Strategia Processuale"
APP_VERSION = "v1.1 (Stable)"
APP_ICON = "⚖️"

st.set_page_config(
    page_title=f"{APP_NAME} - {APP_SUBTITLE}", 
    layout="wide", 
    page_icon=APP_ICON
)

# --- CSS MIGLIORATO (STILE PREMIUM) ---
st.markdown("""
<style>
    /* Stile Bottoni */
    .stButton>button { 
        width: 100%; 
        border-radius: 6px; 
        height: 3.5em; 
        font-weight: 600; 
        text-transform: uppercase; 
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* Stile Chat */
    .chat-message { 
        padding: 1.2rem; 
        border-radius: 8px; 
        margin-bottom: 1rem; 
        display: flex; 
        align-items: flex-start; 
        gap: 15px; 
        font-family: 'Source Sans Pro', sans-serif;
    }
    .chat-message.user { background-color: #f0f2f6; border-left: 4px solid #95a5a6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; border-left: 4px solid #3498db; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    
    /* Stile Supervisor */
    .status-box { 
        padding: 15px; 
        border-radius: 8px; 
        margin-bottom: 20px; 
        border-left: 5px solid #2ecc71; 
        background-color: #eafaf1; 
        color: #27ae60;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. GESTIONE MODELLI E API (AUTO-DISCOVERY) ---
ACTIVE_MODEL = None
FAST_MODEL = None
STATUS_TEXT = "Inizializzazione..."
HAS_KEY = False

try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
    
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    # Priority List (Smart & Fast)
    priority_smart = ["models/gemini-1.5-pro", "models/gemini-1.5-pro-latest", "models/gemini-1.0-pro"]
    priority_fast = ["models/gemini-1.5-flash", "models/gemini-1.5-flash-latest", "models/gemini-1.5-flash-001"]

    for m in priority_smart:
        if m in available_models:
            ACTIVE_MODEL = m
            break
    if not ACTIVE_MODEL and available_models: ACTIVE_MODEL = available_models[0]

    for m in priority_fast:
        if m in available_models:
            FAST_MODEL = m
            break
    if not FAST_MODEL: FAST_MODEL = ACTIVE_MODEL

    STATUS_TEXT = f"Motore: {ACTIVE_MODEL.replace('models/', '')} | Supervisor: {FAST_MODEL.replace('models/', '')}"

except Exception as e:
    STATUS_TEXT = f"Errore API: {str(e)}"
    HAS_KEY = False

# --- MEMORIA DI SESSIONE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato."
# Stati Supervisor
if "sufficiency_check" not in st.session_state: st.session_state.sufficiency_check = False
if "ready_to_generate" not in st.session_state: st.session_state.ready_to_generate = False
if "question_count" not in st.session_state: st.session_state.question_count = 0
if "doc_queue" not in st.session_state: st.session_state.doc_queue = [] 
if "supervisor_history" not in st.session_state: st.session_state.supervisor_history = []
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {}

# --- PROMPT LIBRARY (STRATEGIA COMMERCIALE) ---
DOC_PROMPTS = {
    "Sintesi_Esecutiva": "TASK: 1. TIMELINE NARRATIVA (Causa->Effetto). 2. SINTESI ESECUTIVA (Numeri Chiave, Decisioni Urgenti).",
    "Timeline": "Crea una Timeline Cronologica rigorosa. Evidenzia in GRASSETTO le date critiche.",
    "Punti_Attacco": "Elenca i Punti di Attacco tecnici. Usa i dati del calcolatore per dimostrare l'errore di stima.",
    "Analisi_Critica_Nota": "Analizza la nota avversaria. Evidenzia le contraddizioni logiche e tecniche.",
    "Quesiti_CTU": "Formula quesiti 'binari' o trappola per il CTU. Costringilo a smentire documenti ufficiali.",
    "Nota_Replica": "RISCRIVI la nota usando la tecnica 'Reductio ad Absurdum' per smontare le tesi avversarie.",
    "Strategia_Processuale": "Definisci la Strategia (Game Theory). Albero decisionale: Se controparte fa A -> Noi facciamo B.",
    "Matrice_Rischi": "Crea una Tabella Matrice dei Rischi: Scenario | Probabilità % | Impatto € | Valore Ponderato.",
    "Bozza_Transazione": """
        TASK: Scrivi una BOZZA DI ACCORDO TRANSATTIVO.
        LOGICA CONGUAGLIO UNIVERSALE:
        1. Identifica la 'Quota di Diritto' teorica.
        2. Calcola il 'Valore Nominale'.
        3. Sottrai i 'Fattori di Deprezzamento'.
        4. Dimostra che il 'Valore Netto Reale' < 'Quota di Diritto' -> Cliente deve ricevere soldi.
    """
}

# --- FUNZIONI UTILITY ---
def clean_ai_response(text):
    patterns = [r"^Assolutamente.*", r"^Certo.*", r"^Ecco.*", r"^Analizzo.*", r"^Generato il.*", r"Spero che.*", r"Dimmi se.*"]
    lines = text.split('\n')
    cleaned = []
    skip = True
    for line in lines:
        if skip:
            if any(re.match(p, line, re.IGNORECASE) for p in patterns) or not line.strip() or line.strip() == "---": continue
            skip = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()

def create_word_table(doc, table_lines):
    rows = [l for l in table_lines if not re.search(r'\|\s*:?-+:?\s*\|', l)]
    if not rows: return
    try:
        tbl = doc.add_table(rows=len(rows), cols=len(rows[0].strip('|').split('|')))
        tbl.style = 'Table Grid'
        for i, r in enumerate(rows):
            cells = r.strip('|').split('|')
            for j, c in enumerate(cells):
                if j < len(tbl.columns):
                    tbl.cell(i, j).text = c.strip()
                    if i == 0: tbl.cell(i, j).paragraphs[0].runs[0].font.bold = True
    except: pass

def markdown_to_docx_advanced(text, title):
    doc = Document()
    doc.add_heading(title, 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Documento generato da {APP_NAME} il: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines = text.split('\n')
    table_lines, in_table = [], False
    for line in lines:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            table_lines.append(line); in_table = True
        else:
            if in_table: create_word_table(doc, table_lines); table_lines = []; in_table = False
            if line.startswith('### '): doc.add_heading(line.replace('### ', ''), level=3)
            elif line.startswith('## '): doc.add_heading(line.replace('## ', ''), level=2)
            elif line.startswith('# '): doc.add_heading(line.replace('# ', ''), level=1)
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                p = doc.add_paragraph(style='List Bullet')
                p.add_run(line.strip()[2:]).bold = '**' in line
            elif line.strip():
                p = doc.add_paragraph()
                parts = re.split(r'(\*\*.*?\*\*)', line)
                for part in parts:
                    if part.startswith('**') and part.endswith('**'): p.add_run(part.replace('**', '')).bold = True
                    else: p.add_run(part)
    if in_table: create_word_table(doc, table_lines)
    buffer = BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer

def prepara_input_gemini(uploaded_files):
    input_parts = []
    log = ""
    for file in uploaded_files:
        try:
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- IMG: {file.name} ---\n"); input_parts.append(img)
                log += f"🖼️ {file.name}\n"
            elif file.type == "application/pdf":
                reader = PdfReader(file)
                txt = "\n".join([p.extract_text() for p in reader.pages])
                input_parts.append(f"\n--- PDF: {file.name} ---\n{txt}")
                log += f"📄 {file.name} ({len(reader.pages)} pag)\n"
            elif file.type == "text/plain":
                input_parts.append(f"\n--- TXT: {file.name} ---\n{str(file.read(), 'utf-8')}")
                log += f"📝 {file.name}\n"
        except Exception as e: st.error(f"Errore {file.name}: {e}")
    return input_parts, log

# --- FUNZIONI CORE (FIXED) ---

def check_sufficiency(context_parts, doc_queue, history):
    if not HAS_KEY or not FAST_MODEL: return "READY", ""
    model = genai.GenerativeModel(FAST_MODEL)
    text_context = [p for p in context_parts if isinstance(p, str)]
    context_str = "".join(text_context)[:30000]
    docs_to_gen = ", ".join([d[0] for d in doc_queue])
    hist_txt = "\n".join([f"{r}: {m}" for r, m in history])
    prompt = f"SEI IL SUPERVISORE DI {APP_NAME}. Doc da fare: {docs_to_gen}.\nCONTESTO: {context_str}\nSTORICO: {hist_txt}\nMancano dati CRITICI? Se sì, fai 1 domanda. Se no, rispondi READY."
    try:
        res = model.generate_content(prompt).text.strip()
        return ("READY", "") if "READY" in res.upper() else ("ASK", res)
    except: return "READY", ""

def genera_risposta_chat(prompt_utente, context_parts, history):
    if not HAS_KEY or not ACTIVE_MODEL: return "ERRORE: Modello non disponibile."
    
    # SYSTEM PROMPT PER CHAT (NO TABELLE)
    sys_prompt = """
    SEI UN CONSULENTE DI LEXVANTAGE.
    REGOLE TASSATIVE PER LA CHAT:
    1. NON USARE MAI TABELLE MARKDOWN (usa elenchi puntati o numerati).
    2. Sii sintetico, strategico e diretto.
    3. Usa grassetti per evidenziare i concetti chiave.
    """
    
    # Inizializzo il modello CON le istruzioni di sistema (FIX REV 38)
    model = genai.GenerativeModel(ACTIVE_MODEL, system_instruction=sys_prompt)
    
    chat_ctx = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history if m['role'] == 'user'])
    
    payload = list(context_parts)
    payload.append(f"\nINFO PREGRESSE:\n{chat_ctx}\n\nDOMANDA UTENTE: {prompt_utente}")
    
    try: return model.generate_content(payload).text
    except Exception as e: return f"Errore: {e}"

def genera_documento_finale(nome_doc, prompt_speciale, context_parts, postura_val, dati_calc, history):
    if not HAS_KEY or not ACTIVE_MODEL: return "ERRORE: Modello non disponibile."
    
    if postura_val <= 3: post_desc = "DIPLOMATICA/SOFT"
    elif postura_val <= 7: post_desc = "FERMA/PROFESSIONALE"
    else: post_desc = "AGGRESSIVA/NUCLEAR"
    
    # SYSTEM PROMPT PER DOCUMENTI (SI TABELLE)
    sys_prompt = f"""
    SEI L'AI DI {APP_NAME}, STRATEGA FORENSE SENIOR. POSTURA: {post_desc}.
    DATI CALCOLATORE: {dati_calc}
    REGOLE DOC:
    1. NO SALUTI O PREMESSE.
    2. USA MARKDOWN AVANZATO.
    3. USA TABELLE MARKDOWN (| Col1 | Col2 |) per i dati numerici.
    ISTRUZIONE SPECIFICA: {prompt_speciale}
    """
    
    # Inizializzo il modello CON le istruzioni di sistema (FIX REV 38)
    model = genai.GenerativeModel(ACTIVE_MODEL, system_instruction=sys_prompt)
    
    chat_ctx = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history if m['role'] == 'user'])
    
    payload = list(context_parts)
    payload.append(f"\nINFO EXTRA:\n{chat_ctx}\nGENERA DOC.")
    
    try:
        res = model.generate_content(payload)
        return clean_ai_response(res.text)
    except Exception as e: return f"Errore generazione: {e}"

# --- SIDEBAR ---
with st.sidebar:
    st.markdown(f"## {APP_ICON} {APP_NAME}")
    st.caption(f"{APP_SUBTITLE} - {APP_VERSION}")
    st.divider()
    
    st.markdown("### ⚙️ Configurazione")
    if HAS_KEY: st.success(STATUS_TEXT)
    else: st.error("⚠️ Verifica API Key")
    
    postura_level = st.slider("Aggressività", 1, 10, 7)
    formato_output = st.radio("Output:", ["Word", "PDF"])

# --- MAIN LAYOUT ---
st.title(f"{APP_ICON} {APP_NAME}")
st.subheader("Dashboard Strategica")

tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore", "💬 Chat & Upload", "📄 Generazione Documenti"])

# TAB 1: CALCOLATORE
with tab1:
    st.header("📉 Calcolatore Deprezzamento")
    col1, col2 = st.columns([1, 2])
    with col1:
        valore_base = st.number_input("Valore Base (€)", value=354750.0, step=1000.0)
        c1 = st.checkbox("Irregolarità urbanistica grave (30%)", value=True)
        c2 = st.checkbox("Superfici non abitabili (18%)", value=True)
        c3 = st.checkbox("Assenza mutuabilità (15%)", value=True)
        c4 = st.checkbox("Assenza agibilità (8%)", value=True)
        c5 = st.checkbox("Occupazione (5%)", value=True)
        btn_calcola = st.button("Calcola & Salva", type="primary")
    with col2:
        if btn_calcola:
            f = 1.0; det = ""
            if c1: f*=(1-0.30); det+="- Irregolarità: -30%\n"
            if c2: f*=(1-0.18); det+="- Sup. Non Abit.: -18%\n"
            if c3: f*=(1-0.15); det+="- No Mutuo: -15%\n"
            if c4: f*=(1-0.08); det+="- No Agibilità: -8%\n"
            if c5: f*=(1-0.05); det+="- Occupazione: -5%\n"
            v_fin = valore_base * f; depr = valore_base - v_fin
            st.session_state.dati_calcolatore = f"VALORE BASE: €{valore_base}\nCOEFFICIENTI:\n{det}VALORE FINALE: €{v_fin}"
            st.success(f"Valore Netto: € {v_fin:,.2f}"); st.caption("Dati in memoria AI.")

# TAB 2: UPLOAD & CHAT
with tab2:
    st.write("### 1. Caricamento Fascicolo")
    uploaded_files = st.file_uploader("Trascina qui i file", accept_multiple_files=True)
    parts_dossier = []
    if uploaded_files:
        parts_dossier, log = prepara_input_gemini(uploaded_files)
        with st.expander("Log File"): st.text(log)
    
    st.divider(); st.write("### 2. Chat Strategica")
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "bot"
        icon = "👤" if msg["role"] == "user" else "🤖"
        st.markdown(f"<div class='chat-message {role}'><b>{icon}:</b> {msg['content']}</div>", unsafe_allow_html=True)
    
    if prompt := st.chat_input("Chiedi a LexVantage..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.write(prompt)
        with st.spinner("Analisi in corso..."):
            risposta = genera_risposta_chat(prompt, parts_dossier, st.session_state.messages)
            st.session_state.messages.append({"role": "assistant", "content": risposta})
            st.rerun()

# TAB 3: GENERAZIONE & SUPERVISOR
with tab3:
    if not uploaded_files: st.warning("⚠️ Carica file nel Tab 2.")
    else:
        st.header("🛒 Generazione Documenti")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("ANALISI & ATTACCO")
            d1 = st.checkbox("Sintesi_Esecutiva")
            d2 = st.checkbox("Timeline")
            d3 = st.checkbox("Punti_Attacco")
            d4 = st.checkbox("Quesiti_CTU")
        with c2:
            st.caption("STRATEGIA & CHIUSURA")
            d5 = st.checkbox("Strategia_Processuale")
            d6 = st.checkbox("Matrice_Rischi")
            d7 = st.checkbox("Bozza_Transazione")
            d8 = st.checkbox("Nota_Replica")
            
        queue = []
        if d1: queue.append(("Sintesi_Esecutiva", DOC_PROMPTS["Sintesi_Esecutiva"]))
        if d2: queue.append(("Timeline", DOC_PROMPTS["Timeline"]))
        if d3: queue.append(("Punti_Attacco", DOC_PROMPTS["Punti_Attacco"]))
        if d4: queue.append(("Quesiti_CTU", DOC_PROMPTS["Quesiti_CTU"]))
        if d5: queue.append(("Strategia_Processuale", DOC_PROMPTS["Strategia_Processuale"]))
        if d6: queue.append(("Matrice_Rischi", DOC_PROMPTS["Matrice_Rischi"]))
        if d7: queue.append(("Bozza_Transazione", DOC_PROMPTS["Bozza_Transazione"]))
        if d8: queue.append(("Nota_Replica", DOC_PROMPTS["Nota_Replica"]))
        
        if queue and st.button("🚀 AVVIA PROCEDURE"):
            st.session_state.doc_queue = queue
            st.session_state.sufficiency_check = False
            st.session_state.ready_to_generate = False
            st.session_state.question_count = 0
            st.session_state.supervisor_history = []
            st.rerun()
            
        if st.session_state.doc_queue and not st.session_state.ready_to_generate:
            st.markdown("---")
            if not st.session_state.sufficiency_check:
                with st.spinner("🕵️‍♂️ Supervisor attivo..."):
                    status, msg = check_sufficiency(parts_dossier, st.session_state.doc_queue, st.session_state.supervisor_history)
                    if status == "READY": st.session_state.ready_to_generate = True
                    else: st.session_state.supervisor_history.append({"role": "assistant", "content": msg})
                    st.session_state.sufficiency_check = True
                    st.rerun()
            
            st.markdown(f"""<div class='status-box'><b>🤖 Supervisor:</b> Domanda {st.session_state.question_count}/10</div>""", unsafe_allow_html=True)
            for m in st.session_state.supervisor_history:
                role = "👤" if m['role'] == "user" else "🤖"
                st.markdown(f"**{role}:** {m['content']}")
            
            ans = st.text_input("Rispondi (o 'Salta'):", key="sup_ans")
            if st.button("Invia"):
                if ans.lower() in ['salta', 'basta']: st.session_state.ready_to_generate = True
                else:
                    st.session_state.supervisor_history.append({"role": "user", "content": ans})
                    st.session_state.question_count += 1
                    if st.session_state.question_count >= 10: st.session_state.ready_to_generate = True
                    else:
                        stat, nxt = check_sufficiency(parts_dossier, st.session_state.doc_queue, st.session_state.supervisor_history)
                        if stat == "READY": st.session_state.ready_to_generate = True
                        else: st.session_state.supervisor_history.append({"role": "assistant", "content": nxt})
                st.rerun()

        if st.session_state.ready_to_generate and st.session_state.doc_queue:
            st.markdown("---")
            prog = st.progress(0)
            st.session_state.generated_docs = {}
            for i, (nome, prompt_spec) in enumerate(st.session_state.doc_queue):
                with st.status(f"Generazione {nome}...", expanded=False):
                    txt = genera_documento_finale(nome, prompt_spec, parts_dossier, postura_level, st.session_state.dati_calcolatore, st.session_state.supervisor_history)
                    if formato_output == "Word":
                        buf = markdown_to_docx_advanced(txt, nome)
                        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"; ext = "docx"
                    else:
                        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12)
                        pdf.multi_cell(0, 10, txt.encode('latin-1','replace').decode('latin-1'))
                        buf = BytesIO(pdf.output(dest='S').encode('latin-1')); mime = "application/pdf"; ext = "pdf"
                    st.session_state.generated_docs[nome] = {"data": buf, "ext": ext, "mime": mime}
                prog.progress((i+1)/len(st.session_state.doc_queue))
            st.session_state.doc_queue = []; st.session_state.ready_to_generate = False; st.session_state.sufficiency_check = False; st.rerun()

        if st.session_state.generated_docs:
            st.write("### 📥 Download Documenti")
            cols = st.columns(3)
            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):
                with cols[i % 3]: st.download_button(f"Scarica {k}", v["data"], f"{k}.{v['ext']}", v["mime"])
