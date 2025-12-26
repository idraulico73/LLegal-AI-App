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
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE ---
APP_NAME = "LexVantage"
APP_VERSION = "v5.0 (Golden Master)"
APP_ICON = "⚖️"

st.set_page_config(page_title=APP_NAME, layout="wide", page_icon=APP_ICON)

# --- CSS AVANZATO (FIX LAYOUT & TABELLE) ---
st.markdown("""
<style>
    /* Stile Bottoni */
    .stButton>button { width: 100%; border-radius: 6px; height: 3.5em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    
    /* Chat Message Styling */
    .chat-message { padding: 1.2rem; border-radius: 8px; margin-bottom: 1rem; display: flex; gap: 15px; font-family: 'Source Sans Pro', sans-serif; }
    .chat-message.user { background-color: #f0f2f6; border-left: 4px solid #95a5a6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; border-left: 4px solid #3498db; }
    
    /* Supervisor Box */
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #f1c40f; background-color: #fef9e7; color: #7d6608; }
    
    /* FALLBACK ESTREMO: Se una tabella HTML sopravvive, nascondi l'header e rendila scrollabile */
    .stMarkdown table { display: block; overflow-x: auto; white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

# --- 1. GESTIONE API & AUTO-DISCOVERY ---
HAS_KEY = False
STATUS_TEXT = "Inizializzazione..."

try:
    # Tenta di leggere dai secrets
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
    
    # Auto-Discovery dei Modelli disponibili
    all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    # Logica di fallback per il modello "Smart" (Documenti)
    smart_candidates = ["models/gemini-1.5-pro", "models/gemini-1.5-pro-latest", "models/gemini-1.0-pro"]
    ACTIVE_MODEL = next((m for m in smart_candidates if m in all_models), all_models[0])
    
    # Logica di fallback per il modello "Fast" (Chat/Supervisor)
    fast_candidates = ["models/gemini-1.5-flash", "models/gemini-1.5-flash-latest", "models/gemini-1.5-flash-001"]
    FAST_MODEL = next((m for m in fast_candidates if m in all_models), ACTIVE_MODEL)
    
    STATUS_TEXT = f"Brain: {ACTIVE_MODEL.split('/')[-1]} | Speed: {FAST_MODEL.split('/')[-1]}"

except Exception as e:
    STATUS_TEXT = f"Errore API Key: {e}"
    HAS_KEY = False

# --- MEMORIA DI SESSIONE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato."
if "doc_queue" not in st.session_state: st.session_state.doc_queue = []
if "sup_hist" not in st.session_state: st.session_state.sup_hist = []
if "ready" not in st.session_state: st.session_state.ready = False
if "gen_docs" not in st.session_state: st.session_state.gen_docs = {}

# --- FUNZIONI CORE (SANITIZER & DOCS) ---

def nuke_tables_from_orbit(text):
    """
    LIVELLO 2 PROTEZIONE:
    Intercetta qualsiasi stringa che assomigli a una tabella Markdown o HTML
    e la distrugge visivamente per la Chat.
    """
    # 1. Sostituisce i pipe '|' con una freccia '►'
    # Solo se la riga contiene pipe, altrimenti lascia stare
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        if "|" in line:
            # Rimuove le righe divisorie tipiche (es. |---|---|)
            if set(line.strip()) <= {'|', '-', ':', ' '}:
                continue
            # Sostituisce
            cleaned = line.replace("|", " ► ").strip(" ►")
            clean_lines.append(f"• {cleaned}")
        else:
            clean_lines.append(line)
    
    text = "\n".join(clean_lines)
    
    # 2. Rimuove Tag HTML Table (Regex brutale)
    text = re.sub(r'<table.*?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</table>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<tr.*?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<td.*?>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'</td>', ' ', text, flags=re.IGNORECASE)
    
    return text

def clean_doc_chatter(text):
    """Pulisce i saluti dell'AI dai documenti DOCX"""
    patterns = [r"^Assolutamente.*", r"^Certo.*", r"^Ecco.*", r"^Analizzo.*", r"Spero che.*", r"Dimmi se.*"]
    lines = text.split('\n')
    out = []
    skip = True
    for l in lines:
        if skip:
            if any(re.match(p, l, re.IGNORECASE) for p in patterns) or not l.strip() or l.strip() == "---": continue
            skip = False
        out.append(l)
    return "\n".join(out).strip()

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

def create_docx_native(text, title):
    """
    Converte il Markdown in DOCX creando VERE tabelle Word quando trova i pipe.
    """
    doc = Document()
    doc.add_heading(title, 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generato da {APP_NAME} - {datetime.now().strftime('%d/%m/%Y')}")
    
    lines = text.split('\n')
    table_buffer = []
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        
        # Rilevamento inizio/fine tabella
        if stripped.startswith('|') and stripped.endswith('|'):
            in_table = True
            table_buffer.append(stripped)
        else:
            # Se la tabella è finita, scrivila nel DOCX
            if in_table:
                # Filtra righe divisorie
                rows = [r for r in table_buffer if not set(r) <= {'|', '-', ':', ' '}]
                if rows:
                    # Calcola colonne
                    cols = len(rows[0].strip('|').split('|'))
                    tbl = doc.add_table(rows=len(rows), cols=cols)
                    tbl.style = 'Table Grid'
                    
                    for i, row_text in enumerate(rows):
                        cells = row_text.strip('|').split('|')
                        for j, cell_text in enumerate(cells):
                            if j < cols:
                                tbl.cell(i, j).text = cell_text.strip()
                                # Grassetto per la prima riga
                                if i == 0:
                                    for run in tbl.cell(i, j).paragraphs[0].runs:
                                        run.font.bold = True
                
                table_buffer = []
                in_table = False
            
            # Scrittura testo normale
            if stripped.startswith('### '): doc.add_heading(stripped[4:], 3)
            elif stripped.startswith('## '): doc.add_heading(stripped[3:], 2)
            elif stripped.startswith('# '): doc.add_heading(stripped[2:], 1)
            elif stripped.startswith('- ') or stripped.startswith('* '):
                doc.add_paragraph(stripped[2:], style='List Bullet')
            elif stripped:
                p = doc.add_paragraph()
                # Gestione basilare del grassetto **text**
                parts = re.split(r'(\*\*.*?\*\*)', stripped)
                for part in parts:
                    if part.startswith('**') and part.endswith('**'):
                        run = p.add_run(part[2:-2])
                        run.font.bold = True
                    else:
                        p.add_run(part)
    
    # Flush finale se il documento finisce con una tabella
    if in_table and table_buffer:
        rows = [r for r in table_buffer if not set(r) <= {'|', '-', ':', ' '}]
        if rows:
            cols = len(rows[0].strip('|').split('|'))
            tbl = doc.add_table(rows=len(rows), cols=cols)
            tbl.style = 'Table Grid'
            for i, r in enumerate(rows):
                cells = r.strip('|').split('|')
                for j, c in enumerate(cells):
                    if j < cols: tbl.cell(i, j).text = c.strip()

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# --- AGENTI AI (CHAT, SUPERVISOR, GENERATOR) ---

def agent_chat(user_input, context, history):
    if not HAS_KEY: return "Errore: API Key mancante."
    
    # SYSTEM PROMPT: Safe Mode
    sys = """
    SEI LEXVANTAGE, UN ASSISTENTE LEGALE STRATEGICO.
    
    REGOLE DI OUTPUT:
    1. NON USARE MAI TABELLE (Niente caratteri '|').
    2. Usa elenchi puntati per strutturare i dati.
    3. Sii sintetico e professionale.
    """
    model = genai.GenerativeModel(ACTIVE_MODEL, system_instruction=sys)
    
    # Costruzione Prompt
    hist_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    payload = list(context)
    payload.append(f"STORICO:\n{hist_text}\n\nDOMANDA UTENTE: {user_input}")
    
    try:
        response = model.generate_content(payload).text
        # SANITIZZAZIONE FORZATA PRIMA DEL RITORNO
        return nuke_tables_from_orbit(response)
    except Exception as e: return f"Errore generazione: {e}"

def agent_supervisor(context, doc_queue, history):
    if not HAS_KEY: return "READY", ""
    
    # LOGICA OBBLIGO DOMANDA INIZIALE
    if len(history) == 0:
        return "ASK", "Ho analizzato il fascicolo. Prima di procedere, definisci l'obiettivo strategico: puntiamo a una Transazione Rapida (minimizzando i rischi) o a una Guerra Processuale (massimizzando il risultato)? Ci sono scadenze imminenti?"

    model = genai.GenerativeModel(FAST_MODEL)
    txt_ctx = "\n".join([p for p in context if isinstance(p, str)])[:25000]
    
    prompt = f"""
    SEI IL SUPERVISORE. DOC RICHIESTI: {doc_queue}.
    CONTESTO: {txt_ctx}.
    STORICO: {history}.
    
    COMPITO:
    Identifica se mancano dati cruciali (date, cifre, controparti).
    - Se manca qualcosa -> FAI UNA DOMANDA.
    - Se hai tutto -> Rispondi SOLO "READY".
    """
    try:
        res = model.generate_content(prompt).text.strip()
        return ("READY", "") if "READY" in res.upper() else ("ASK", res)
    except: return "READY", ""

def agent_generator(doc_name, task_prompt, context, history, posture, calc_data):
    if not HAS_KEY: return "Err"
    
    tones = {1: "Diplomatico/Conciliante", 5: "Fermo/Professionale", 7: "Aggressivo", 10: "Guerra Totale/Distruttivo"}
    sel_tone = tones.get(postura, "Professionale")
    
    model = genai.GenerativeModel(ACTIVE_MODEL)
    hist_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    
    full_prompt = f"""
    SEI LEXVANTAGE. RUOLO: STRATEGA FORENSE.
    TONO: {sel_tone}.
    DATI TECNICI (Dal Calcolatore): {calc_data}
    
    TASK: Redigi il documento '{doc_name}'.
    ISTRUZIONI: {task_prompt}
    
    FORMATTAZIONE:
    - Usa Markdown.
    - USA TABELLE per i dati numerici (qui sono permesse).
    - Inizia col Titolo. Niente premesse.
    """
    
    payload = list(context)
    payload.append(f"STORICO:\n{hist_text}\n\nESEGUI: {full_prompt}")
    
    try:
        return clean_doc_chatter(model.generate_content(payload).text)
    except Exception as e: return f"Errore: {e}"

# --- UI & LAYOUT ---

with st.sidebar:
    st.title(f"{APP_ICON} {APP_NAME}")
    st.caption(f"{APP_VERSION}")
    
    if st.button("🗑️ Reset Totale"):
        st.session_state.clear()
        st.rerun()
        
    st.divider()
    
    # Fix UI: If/Else pulito
    if HAS_KEY:
        st.success(STATUS_TEXT)
    else:
        st.error("⚠️ Manca API Key nei secrets")
        
    st.markdown("### ⚙️ Tattica")
    postura = st.slider("Livello Aggressività", 1, 10, 7, help="Modifica il tono dei documenti generati")

tab1, tab2, tab3 = st.tabs(["🧮 Calcolatore", "💬 Chat & Upload", "🚀 Workflow"])

# --- TAB 1: CALCOLATORE (LOGICA DETTAGLIATA) ---
with tab1:
    st.header("📉 Calcolatore Deprezzamento Immobiliare")
    st.info("I dati qui calcolati diventano la 'Verità Tecnica' per l'AI.")
    
    c1, c2 = st.columns([1, 2])
    with c1:
        val_base = st.number_input("Valore Base (€)", value=350000.0, step=1000.0)
        st.markdown("**Coefficienti Riduttivi:**")
        chk_irreg = st.checkbox("Irregolarità Grave (-30%)", value=True)
        chk_noabit = st.checkbox("Sup. Non Abitabili (-18%)", value=True)
        chk_nomutuo = st.checkbox("Assenza Mutuabilità (-15%)", value=True)
        chk_noagib = st.checkbox("Assenza Agibilità (-8%)", value=True)
        chk_occup = st.checkbox("Occupazione (-5%)", value=True)
        
        btn_calc = st.button("Calcola & Salva", type="primary")
        
    with c2:
        if btn_calc:
            f = 1.0
            log_calc = []
            
            if chk_irreg: f *= 0.70; log_calc.append("- Irregolarità Grave (-30%)")
            if chk_noabit: f *= 0.82; log_calc.append("- Sup. Non Abitabili (-18%)")
            if chk_nomutuo: f *= 0.85; log_calc.append("- Assenza Mutuabilità (-15%)")
            if chk_noagib: f *= 0.92; log_calc.append("- Assenza Agibilità (-8%)")
            if chk_occup: f *= 0.95; log_calc.append("- Occupazione (-5%)")
            
            val_netto = val_base * f
            depr_tot = val_base - val_netto
            perc_tot = (1 - f) * 100
            
            report = f"""
            VALORE BASE: € {val_base:,.2f}
            COEFFICIENTI: {', '.join(log_calc)}
            FATTORE RESIDUO: {f:.4f}
            VALORE NETTO: € {val_netto:,.2f}
            """
            st.session_state.dati_calcolatore = report
            
            st.success(f"### Valore Netto: € {val_netto:,.2f}")
            st.metric("Deprezzamento Totale", f"-{perc_tot:.2f}%", f"- € {depr_tot:,.2f}")
            st.caption("✅ Dati salvati in memoria.")

# --- TAB 2: CHAT & UPLOAD (SAFE MODE) ---
with tab2:
    st.write("### 1. Upload Fascicolo")
    files = st.file_uploader("Trascina qui PDF, Immagini, DOCX", accept_multiple_files=True)
    ctx = []
    if files:
        ctx, log = read_files(files)
        with st.expander("Log Lettura File"): st.text(log)
        
    st.divider()
    st.write("### 2. Chat Strategica")
    
    # Rendering Cronologia (CON SANITIZER APPLICATO ANCHE QUI)
    for m in st.session_state.messages:
        role = "user" if m['role']=='user' else "bot"
        content_safe = m['content']
        if role == "bot":
            content_safe = nuke_tables_from_orbit(content_safe)
        
        st.markdown(f"<div class='chat-message {role}'>{content_safe}</div>", unsafe_allow_html=True)
        
    if prompt := st.chat_input("Chiedi a LexVantage..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()
        
    # Risposta Bot
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.spinner("Analisi in corso..."):
            ans = agent_chat(st.session_state.messages[-1]["content"], ctx, st.session_state.messages[:-1])
            st.session_state.messages.append({"role": "assistant", "content": ans})
            st.rerun()

# --- TAB 3: WORKFLOW (SUPERVISOR & DOCS) ---
with tab3:
    if not files:
        st.info("⚠️ Carica prima i file nel Tab 2.")
    else:
        st.header("Generazione Documenti Guidata")
        
        c1, c2 = st.columns(2)
        with c1:
            s1 = st.checkbox("Sintesi Esecutiva & Timeline")
            s2 = st.checkbox("Punti di Attacco & Quesiti CTU")
        with c2:
            s3 = st.checkbox("Strategia Processuale & Rischi")
            s4 = st.checkbox("Bozza Transazione & Nota Replica")
            
        PROMPTS = {
            "Sintesi": "Crea TIMELINE NARRATIVA e SINTESI ESECUTIVA.",
            "Attacco": "Elenca PUNTI DI ATTACCO tecnici e QUESITI CTU.",
            "Strategia": "Definisci STRATEGIA (Game Theory) e MATRICE RISCHI.",
            "Chiusura": "Redigi BOZZA TRANSAZIONE (Valore Reale) e NOTA REPLICA."
        }
        
        if st.button("AVVIA PROCESSO"):
            q = []
            if s1: q.append(("01_Analisi", PROMPTS["Sintesi"]))
            if s2: q.append(("02_Attacco", PROMPTS["Attacco"]))
            if s3: q.append(("03_Strategia", PROMPTS["Strategia"]))
            if s4: q.append(("04_Chiusura", PROMPTS["Chiusura"]))
            
            if q:
                st.session_state.doc_queue = q
                st.session_state.ready = False
                st.session_state.sup_hist = []
                st.rerun()
                
        # LOOP SUPERVISORE
        if st.session_state.doc_queue and not st.session_state.ready:
            st.divider()
            
            # Step AI: Analizza
            last_role = st.session_state.sup_hist[-1]['role'] if st.session_state.sup_hist else 'user'
            if last_role == 'user':
                with st.spinner("Il Supervisore sta valutando la completezza dei dati..."):
                    stat, msg = agent_supervisor(ctx, st.session_state.doc_queue, st.session_state.sup_hist)
                    if stat == "READY":
                        st.session_state.ready = True
                    else:
                        st.session_state.sup_hist.append({"role": "assistant", "content": msg})
                    st.rerun()
            
            # Step Utente: Risponde
            if not st.session_state.ready:
                st.markdown(f"<div class='status-box'><b>AVVOCATO SUPERVISORE</b></div>", unsafe_allow_html=True)
                for m in st.session_state.sup_hist:
                    icon = "👤" if m['role']=='user' else "⚖️"
                    st.write(f"**{icon}**: {m['content']}")
                    
                ans = st.text_input("Risposta:", key="sup_ans")
                if st.button("Invia Risposta"):
                    st.session_state.sup_hist.append({"role": "user", "content": ans})
                    st.rerun()
        
        # GENERAZIONE DOCUMENTI
        if st.session_state.ready:
            st.divider()
            st.success("✅ Strategia definita. Generazione documenti in corso...")
            bar = st.progress(0)
            
            for i, (name, prompt) in enumerate(st.session_state.doc_queue):
                docx_text = agent_generator(name, prompt, ctx, st.session_state.sup_hist, postura, st.session_state.dati_calcolatore)
                file_data = create_docx_native(docx_text, name)
                st.session_state.gen_docs[name] = file_data
                bar.progress((i+1)/len(st.session_state.doc_queue))
            
            st.session_state.doc_queue = []
            st.rerun()
            
        # DOWNLOAD
        if st.session_state.gen_docs:
            st.write("### 📥 Documenti Pronti")
            cols = st.columns(3)
            for i, (k, v) in enumerate(st.session_state.gen_docs.items()):
                with cols[i%3]:
                    st.download_button(f"📄 Scarica {k}", v, f"{k}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
