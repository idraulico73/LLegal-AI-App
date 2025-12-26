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

# --- CONFIGURAZIONE GLOBALE ---
APP_NAME = "LexVantage"
APP_SUBTITLE = "Ingegneria Forense & Strategia"
APP_VERSION = "v3.0 (Strict Enforcement)"
APP_ICON = "⚖️"

st.set_page_config(
    page_title=f"{APP_NAME} - {APP_SUBTITLE}", 
    layout="wide", 
    page_icon=APP_ICON
)

# --- CSS AVANZATO (FIX LAYOUT) ---
st.markdown("""
<style>
    /* Bottoni */
    .stButton>button { width: 100%; border-radius: 6px; height: 3.5em; font-weight: 600; text-transform: uppercase; transition: all 0.3s ease; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
    
    /* Chat Message */
    .chat-message { padding: 1.2rem; border-radius: 8px; margin-bottom: 1rem; display: flex; align-items: flex-start; gap: 15px; font-family: 'Source Sans Pro', sans-serif; }
    .chat-message.user { background-color: #f0f2f6; border-left: 4px solid #95a5a6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; border-left: 4px solid #3498db; }
    
    /* Supervisor Box */
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #f1c40f; background-color: #fcf3cf; color: #7d6608; }
    
    /* FALLBACK: Se una tabella passa il filtro, rendila scorrevole invece di rompere il layout */
    .stMarkdown table { display: block; overflow-x: auto; white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

# --- GESTIONE API E MODELLI ---
HAS_KEY = False
ACTIVE_MODEL = None
FAST_MODEL = None
STATUS_TEXT = "Init..."

try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
    
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    # Selezione prioritaria modelli
    smart_candidates = ["models/gemini-1.5-pro", "models/gemini-1.5-pro-latest", "models/gemini-1.0-pro"]
    fast_candidates = ["models/gemini-1.5-flash", "models/gemini-1.5-flash-latest"]
    
    ACTIVE_MODEL = next((m for m in smart_candidates if m in available_models), available_models[0])
    FAST_MODEL = next((m for m in fast_candidates if m in available_models), ACTIVE_MODEL)
    
    STATUS_TEXT = f"Brain: {ACTIVE_MODEL.split('/')[-1]} | Fast: {FAST_MODEL.split('/')[-1]}"

except Exception as e:
    st.error(f"Errore API: {e}")

# --- MEMORIA SESSIONE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato."
if "sufficiency_check" not in st.session_state: st.session_state.sufficiency_check = False
if "ready_to_generate" not in st.session_state: st.session_state.ready_to_generate = False
if "question_count" not in st.session_state: st.session_state.question_count = 0
if "doc_queue" not in st.session_state: st.session_state.doc_queue = [] 
if "supervisor_history" not in st.session_state: st.session_state.supervisor_history = []
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {}

# --- FUNZIONI DI SANITIZZAZIONE (IL "TRITA-TABELLE") ---

def destroy_markdown_tables(text):
    """
    Funzione brutale che riscrive le tabelle Markdown in elenchi puntati.
    Intercetta le righe che iniziano con '|' e le converte.
    """
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        # Rileva la sintassi tabella Markdown
        if stripped.startswith('|'):
            # Ignora le righe di separazione (es: |---|---|)
            if set(stripped) <= {'|', '-', ':', ' '}:
                continue
            
            # Trasforma le celle in elementi di lista
            # Esempio: "| A | B |" -> "• A - B"
            content = stripped.replace('|', ' - ').strip(' -')
            clean_lines.append(f"• {content}")
        else:
            clean_lines.append(line)
    return "\n".join(clean_lines)

def clean_doc_header(text):
    """Pulisce i convenevoli per i documenti DOCX"""
    patterns = [r"^Assolutamente.*", r"^Certo.*", r"^Ecco.*", r"^Analizzo.*", r"Spero che.*", r"Dimmi se.*"]
    lines = text.split('\n')
    cleaned = []
    skip = True
    for line in lines:
        if skip:
            if any(re.match(p, line, re.IGNORECASE) for p in patterns) or not line.strip() or line.strip() == "---": continue
            skip = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()

def prepara_input_gemini(uploaded_files):
    input_parts = []
    log = ""
    for file in uploaded_files:
        try:
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(img)
                log += f"🖼️ {file.name}\n"
            elif file.type == "application/pdf":
                reader = PdfReader(file)
                txt = "\n".join([p.extract_text() for p in reader.pages])
                input_parts.append(f"\nFILE: {file.name}\n{txt}")
                log += f"📄 {file.name}\n"
            elif file.type == "text/plain":
                input_parts.append(f"\nFILE: {file.name}\n{str(file.read(), 'utf-8')}")
                log += f"📝 {file.name}\n"
            elif file.name.endswith(".docx"):
                doc = Document(file)
                txt = "\n".join([p.text for p in doc.paragraphs])
                input_parts.append(f"\nFILE: {file.name}\n{txt}")
                log += f"📘 {file.name}\n"
        except Exception as e: st.error(f"Errore lettura {file.name}: {e}")
    return input_parts, log

# --- CERVELLO AI ---

def check_sufficiency_forced(context_parts, doc_queue, history):
    """
    AGENTE SUPERVISORE PARANOICO.
    Se siamo sotto le 3 domande, FORZA una richiesta di chiarimento.
    """
    if not HAS_KEY: return "READY", ""
    model = genai.GenerativeModel(FAST_MODEL)
    
    # Recupera testo per analisi
    text_context = [p for p in context_parts if isinstance(p, str)]
    context_str = "".join(text_context)[:25000] # Limite char
    
    q_count = len([x for x in history if x['role'] == 'assistant'])
    
    # LOGICA DI FORZATURA: Minimo 3 domande di raffinamento
    force_question = q_count < 3
    
    prompt = f"""
    SEI IL SUPERVISORE LEGALE DI LEXVANTAGE.
    DOC RICHIESTI: {', '.join([d[0] for d in doc_queue])}.
    
    CONTESTO: {context_str}
    
    TUO COMPITO:
    Non devi dire che va tutto bene. DEVI trovare rischi, ambiguità o mancanze strategiche.
    
    REGOLE:
    1. Se abbiamo fatto meno di 3 domande finora, DEVI ASSOLUTAMENTE fare una nuova domanda specifica per raffinare la strategia (es. su budget, tempi, aggressività, controparti).
    2. Solo se hai un quadro PERFETTO e sono passate almeno 3 interazioni, rispondi "READY".
    
    OUTPUT RICHIESTO: Solo la domanda o la stringa "READY".
    """
    
    try:
        res = model.generate_content(prompt).text.strip()
        # Override se il modello è pigro ma siamo all'inizio
        if "READY" in res.upper() and force_question:
            return "ASK", "Per massimizzare l'efficacia, ho bisogno di una conferma strategica: qual è il punto di caduta minimo che il cliente accetterebbe nella transazione?"
        
        return ("READY", "") if "READY" in res.upper() else ("ASK", res)
    except: return "READY", ""

def genera_risposta_chat(prompt_utente, context_parts, history):
    """GENERATORE CHAT CON SANITIZZAZIONE FORZATA"""
    if not HAS_KEY: return "Errore API Key."
    
    model = genai.GenerativeModel(ACTIVE_MODEL)
    chat_ctx = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history if m['role'] == 'user'])
    
    # Prompt specifico anti-tabelle
    sys_prompt = "SEI UN ASSISTENTE LEGALE. NON USARE MAI TABELLE. USA SOLO ELENCHI PUNTATI."
    
    payload = list(context_parts)
    payload.append(f"{sys_prompt}\nSTORICO: {chat_ctx}\nDOMANDA: {prompt_utente}")
    
    try:
        raw = model.generate_content(payload).text
        # Passaggio nel trita-tabelle Python
        return destroy_markdown_tables(raw)
    except Exception as e: return f"Errore: {e}"

def genera_docx(nome_doc, prompt_spec, context_parts, postura, dati_calc, history):
    """GENERATORE DOCX (Tabelle Ammesse)"""
    if not HAS_KEY: return "Errore API."
    
    tones = {1: "Diplomatico", 5: "Fermo", 7: "Aggressivo", 10: "Guerra Totale"}
    sel_tone = tones.get(postura, "Professionale")
    
    sys_prompt = f"""
    SEI L'AI DI LEXVANTAGE. RUOLO: Stratega Forense.
    TONO: {sel_tone}.
    DATI CALCOLATORE: {dati_calc}
    
    FORMATTAZIONE:
    - Usa Markdown.
    - USA TABELLE per i dati numerici (qui sono permesse).
    - Niente saluti iniziali.
    
    TASK: {prompt_spec}
    """
    model = genai.GenerativeModel(ACTIVE_MODEL, system_instruction=sys_prompt)
    chat_ctx = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history if m['role'] == 'user'])
    payload = list(context_parts)
    payload.append(f"\nINFO UTENTE:\n{chat_ctx}\nGENERA DOC.")
    
    try:
        res = model.generate_content(payload)
        return clean_doc_header(res.text)
    except Exception as e: return f"Errore: {e}"

def create_word_file(text, title):
    """Converte Markdown in DOCX preservando le tabelle"""
    doc = Document()
    doc.add_heading(title, 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generato da {APP_NAME} il {datetime.now().strftime('%d/%m/%Y')}")
    
    lines = text.split('\n')
    table_buffer = []
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        # Rilevamento tabelle
        if stripped.startswith('|') and stripped.endswith('|'):
            in_table = True; table_buffer.append(stripped)
        else:
            if in_table:
                # Disegna tabella accumulata
                rows = [r for r in table_buffer if not re.search(r'\|\s*:?-+:?\s*\|', r)]
                if rows:
                    cols = len(rows[0].strip('|').split('|'))
                    tbl = doc.add_table(rows=len(rows), cols=cols)
                    tbl.style = 'Table Grid'
                    for i, row_txt in enumerate(rows):
                        cells = row_txt.strip('|').split('|')
                        for j, cell_txt in enumerate(cells):
                            if j < cols: tbl.cell(i, j).text = cell_txt.strip()
                table_buffer = []; in_table = False
            
            # Elementi normali
            if stripped.startswith('### '): doc.add_heading(stripped[4:], 3)
            elif stripped.startswith('## '): doc.add_heading(stripped[3:], 2)
            elif stripped.startswith('# '): doc.add_heading(stripped[2:], 1)
            elif stripped.startswith('- ') or stripped.startswith('* '): 
                doc.add_paragraph(stripped[2:], style='List Bullet')
            elif stripped:
                p = doc.add_paragraph(stripped)
                    
    # Flush finale
    if in_table and table_buffer:
        rows = [r for r in table_buffer if not re.search(r'\|\s*:?-+:?\s*\|', r)]
        if rows:
            cols = len(rows[0].strip('|').split('|'))
            tbl = doc.add_table(rows=len(rows), cols=cols)
            tbl.style = 'Table Grid'
            for i, row_txt in enumerate(rows):
                cells = row_txt.strip('|').split('|')
                for j, cell_txt in enumerate(cells):
                    if j < cols: tbl.cell(i, j).text = cell_txt.strip()

    buf = BytesIO(); doc.save(buf); buf.seek(0)
    return buf

# --- INTERFACCIA UTENTE ---

DOC_PROMPTS = {
    "Sintesi_Esecutiva": "1. TIMELINE NARRATIVA. 2. SINTESI ESECUTIVA (Numeri Chiave).",
    "Timeline": "Timeline Cronologica. Evidenzia in GRASSETTO le date.",
    "Punti_Attacco": "Elenca i Punti di Attacco tecnici basati sui dati.",
    "Analisi_Critica_Nota": "Analizza la nota avversaria.",
    "Quesiti_CTU": "Formula quesiti 'binari' o trappola.",
    "Nota_Replica": "RISCRIVI la nota in tono aggressivo.",
    "Strategia_Processuale": "Definisci la Strategia (Game Theory).",
    "Matrice_Rischi": "Crea una Tabella Matrice dei Rischi.",
    "Bozza_Transazione": "Scrivi una BOZZA TRANSATTIVA. Logica: Valore Reale vs Nominale."
}

with st.sidebar:
    st.markdown(f"## {APP_ICON} {APP_NAME}")
    st.caption(f"{APP_VERSION}")
    
    if st.button("🗑️ RESET SESSIONE"):
        for key in st.session_state.keys(): del st.session_state[key]
        st.rerun()
        
    st.divider()
    if HAS_KEY: st.success(STATUS_TEXT)
    else: st.error("Manca API Key")
    
    postura = st.slider("Livello Aggressività", 1, 10, 7)
    out_fmt = st.radio("Formato Output", ["Word (.docx)"])

st.title(f"{APP_ICON} {APP_NAME}")

tab1, tab2, tab3 = st.tabs(["🧮 Calcolatore", "💬 Chat & Upload", "🚀 Generazione & Supervisor"])

# TAB 1
with tab1:
    st.header("Stima Rapida Deprezzamento")
    c1, c2 = st.columns(2)
    with c1:
        v_base = st.number_input("Valore Mercato (€)", 350000.0, step=5000.0)
        k1 = st.checkbox("Abusi Gravi (-30%)", True)
        k2 = st.checkbox("No Abitabilità (-18%)", True)
        if st.button("Calcola"):
            f = 1.0; log = []
            if k1: f*=0.7; log.append("Abusi")
            if k2: f*=0.82; log.append("No Abit.")
            res = v_base * f
            st.session_state.dati_calcolatore = f"Base: {v_base}€. Fattori: {log}. Netto: {res:.2f}€"
            st.success(f"Valore Netto: € {res:,.2f}")

# TAB 2
with tab2:
    st.write("### 1. Carica Fascicolo")
    files = st.file_uploader("Trascina file qui", accept_multiple_files=True)
    ctx = []
    if files:
        ctx, log = prepara_input_gemini(files)
        with st.expander("Log Lettura"): st.text(log)
    
    st.divider(); st.write("### 2. Chat Strategica")
    for m in st.session_state.messages:
        role = "user" if m['role']=="user" else "bot"
        st.markdown(f"<div class='chat-message {role}'>{m['content']}</div>", unsafe_allow_html=True)
        
    if q := st.chat_input("Chiedi a LexVantage..."):
        st.session_state.messages.append({"role":"user","content":q})
        st.rerun()
        
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.spinner("Analisi in corso..."):
            ans = genera_risposta_chat(st.session_state.messages[-1]["content"], ctx, st.session_state.messages[:-1])
            st.session_state.messages.append({"role":"assistant","content":ans})
            st.rerun()

# TAB 3
with tab3:
    if not files: st.info("Carica i file nel Tab 2 per iniziare.")
    else:
        st.header("Generazione Documenti")
        cols = st.columns(2)
        with cols[0]:
            sel1 = st.checkbox("Sintesi Esecutiva"); sel2 = st.checkbox("Timeline"); sel3 = st.checkbox("Punti Attacco"); sel4 = st.checkbox("Quesiti CTU")
        with cols[1]:
            sel5 = st.checkbox("Strategia"); sel6 = st.checkbox("Matrice Rischi"); sel7 = st.checkbox("Bozza Transazione"); sel8 = st.checkbox("Nota Replica")
            
        if st.button("AVVIA PROCESSO"):
            q = []
            if sel1: q.append(("Sintesi_Esecutiva", DOC_PROMPTS["Sintesi_Esecutiva"]))
            if sel2: q.append(("Timeline", DOC_PROMPTS["Timeline"]))
            if sel3: q.append(("Punti_Attacco", DOC_PROMPTS["Punti_Attacco"]))
            if sel4: q.append(("Quesiti_CTU", DOC_PROMPTS["Quesiti_CTU"]))
            if sel5: q.append(("Strategia_Processuale", DOC_PROMPTS["Strategia_Processuale"]))
            if sel6: q.append(("Matrice_Rischi", DOC_PROMPTS["Matrice_Rischi"]))
            if sel7: q.append(("Bozza_Transazione", DOC_PROMPTS["Bozza_Transazione"]))
            if sel8: q.append(("Nota_Replica", DOC_PROMPTS["Nota_Replica"]))
            
            if q:
                st.session_state.doc_queue = q
                st.session_state.sufficiency_check = False
                st.session_state.ready_to_generate = False
                st.session_state.question_count = 0
                st.session_state.supervisor_history = []
                st.rerun()

        # SUPERVISOR LOOP
        if st.session_state.doc_queue and not st.session_state.ready_to_generate:
            st.divider()
            if not st.session_state.sufficiency_check:
                with st.spinner("Il Supervisore sta analizzando i dati..."):
                    stat, msg = check_sufficiency_forced(ctx, st.session_state.doc_queue, st.session_state.supervisor_history)
                    if stat == "READY":
                        st.session_state.ready_to_generate = True
                    else:
                        st.session_state.supervisor_history.append({"role":"assistant", "content":msg})
                    st.session_state.sufficiency_check = True
                    st.rerun()
            
            # Chat Interattiva
            st.markdown(f"<div class='status-box'><b>AVVOCATO SUPERVISORE:</b> Domanda {st.session_state.question_count+1}</div>", unsafe_allow_html=True)
            
            for m in st.session_state.supervisor_history:
                icon = "👤" if m['role']=="user" else "⚖️"
                st.write(f"**{icon}**: {m['content']}")
            
            ans = st.text_input("La tua risposta (o scrivi 'SKIP' per generare subito):", key="sup_in")
            if st.button("Invia Risposta"):
                if ans.upper() == "SKIP":
                    st.session_state.ready_to_generate = True
                else:
                    st.session_state.supervisor_history.append({"role":"user", "content":ans})
                    st.session_state.question_count += 1
                    # Stop condition (Max 10 domande)
                    if st.session_state.question_count >= 10:
                        st.session_state.ready_to_generate = True
                    else:
                        # Check iterativo
                        stat, msg = check_sufficiency_forced(ctx, st.session_state.doc_queue, st.session_state.supervisor_history)
                        if stat == "READY": st.session_state.ready_to_generate = True
                        else: st.session_state.supervisor_history.append({"role":"assistant", "content":msg})
                st.rerun()

        # GENERAZIONE FINALE
        if st.session_state.ready_to_generate and st.session_state.doc_queue:
            st.divider()
            st.success("Analisi completata. Generazione documenti...")
            bar = st.progress(0)
            
            for i, (name, prompt) in enumerate(st.session_state.doc_queue):
                with st.status(f"Scrivendo: {name}...", expanded=False):
                    txt = genera_docx(name, prompt, ctx, postura, st.session_state.dati_calcolatore, st.session_state.supervisor_history)
                    docx_data = create_word_file(txt, name)
                    st.session_state.generated_docs[name] = docx_data
                bar.progress((i+1)/len(st.session_state.doc_queue))
            
            st.session_state.doc_queue = [] 
            st.rerun()

        if st.session_state.generated_docs:
            st.write("### 📥 Documenti Pronti per il Download")
            cols = st.columns(3)
            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):
                with cols[i%3]:
                    st.download_button(f"📄 {k}", v, f"{k}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
