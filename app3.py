import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image
import zipfile

# --- LIBRERIE ESTERNE ---
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor
from fpdf import FPDF

# --- CONFIGURAZIONE APP ---
APP_NAME = "LexVantage"
APP_VER = "Rev 40 (Marker Sanitizer & Logic Fix)"

st.set_page_config(page_title=f"{APP_NAME} AI", layout="wide", page_icon="⚖️")

# CSS: Nascondiamo elementi di disturbo e fissiamo layout
st.markdown("""
<style>
    .stMarkdown { overflow-x: auto; }
    div[data-testid="stChatMessage"] { overflow-x: hidden; }
    h1, h2, h3 { color: #2c3e50; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    /* Evidenziazione box intervista */
    div[data-testid="stChatMessage"] { background-color: #f9f9f9; border-radius: 10px; padding: 10px; margin-bottom: 5px;}
</style>
""", unsafe_allow_html=True)

# --- STATE MANAGEMENT ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False
if "nome_cliente" not in st.session_state: st.session_state.nome_cliente = "Cliente"

# --- AI SETUP ---
active_model = None
status_text = "Init..."
status_color = "off"
HAS_KEY = False

try:
    if "GOOGLE_API_KEY" in st.secrets:
        GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=GENAI_KEY)
        HAS_KEY = True
        try:
            list_models = genai.list_models()
            all_models = [m.name for m in list_models if 'generateContent' in m.supported_generation_methods]
        except: all_models = []
        
        # Priorità modello
        priority = ["models/gemini-1.5-pro-latest", "models/gemini-1.5-pro", "models/gemini-1.5-flash"]
        for cand in priority:
            if cand in all_models:
                active_model = cand
                break
        if not active_model and all_models: active_model = all_models[0]
        
        if active_model:
            status_text = f"Ready: {active_model.replace('models/', '')}"
            status_color = "green"
        else:
            status_text = "No Models Found"
            status_color = "red"
except Exception as e:
    status_text = f"Error: {e}"
    status_color = "red"

# --- CORE FUNCTIONS ---

def detect_client_name(text):
    """Cerca cognome cliente nel testo fascicolo."""
    match = re.search(r"(?:sig\.|signor|cliente)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text, re.IGNORECASE)
    if match: return match.group(1).replace(" ", "_")
    return "Cliente"

def sterilizza_chat(text):
    """Chat Mode: Toglie tabelle."""
    return text.replace("|", " - ") if text else ""

def sterilizza_doc_marker(text):
    """
    DOC MODE (INFALLIBILE):
    Cerca il marker ###START_DOC###.
    Tutto quello che c'è prima viene cancellato.
    Tutto quello che c'è dopo (domande finali) viene pulito via regex.
    """
    if not text: return ""
    
    # 1. MARKER CUT
    if "###START_DOC###" in text:
        text = text.split("###START_DOC###")[1].strip()
    else:
        # Fallback se l'AI sbaglia marker (raro ma possibile, usiamo regex vecchia)
        kill_list = [r"^Assolutamente.*?\n", r"^Ecco.*?\n", r"^Perfetto.*?\n", r"^Certo.*?\n"]
        for p in kill_list: text = re.sub(p, "", text, count=1, flags=re.IGNORECASE|re.DOTALL)

    # 2. END CUT (Domande finali)
    patterns_end = [r"Vuoi che proceda.*?$", r"Fammi sapere.*?$", r"Resto a disposizione.*?$"]
    for p in patterns_end:
        text = re.sub(p, "", text, flags=re.IGNORECASE|re.MULTILINE)
        
    return text.strip()

def advanced_markdown_to_docx(doc, text):
    """Engine Tabelle DOCX."""
    lines = text.split('\n')
    iterator = iter(lines)
    in_table = False
    table_data = []

    for line in iterator:
        stripped = line.strip()
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_data = []
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if all(set(c).issubset({'-', ':'}) for c in cells if c): continue
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
                                table.cell(r_idx, c_idx).text = cell_content
            in_table = False
            table_data = []

        if not stripped: continue
        if stripped.startswith('#'):
            level = stripped.count('#')
            doc.add_heading(stripped.lstrip('#').strip(), level=min(level, 3))
        elif stripped.startswith('- ') or stripped.startswith('* '):
            doc.add_paragraph(stripped[2:], style='List Bullet')
        else:
            doc.add_paragraph(stripped)

def get_file_content(uploaded_files):
    """Estrae testo e metadati dai file."""
    parts = []
    log = ""
    full_text = ""
    parts.append("FASCICOLO:\n")
    
    if not uploaded_files: return [], "", ""

    for file in uploaded_files:
        try:
            safe = file.name.replace("|", "_")
            if file.type == "application/pdf":
                pdf = PdfReader(file)
                txt = ""
                for p in pdf.pages: txt += p.extract_text().replace("|", " ") + "\n"
                parts.append(f"\n--- PDF: {safe} ---\n{txt}")
                full_text += txt
                log += f"PDF: {safe}\n"
            elif "word" in file.type:
                doc = Document(file)
                txt = "\n".join([p.text for p in doc.paragraphs])
                parts.append(f"\n--- DOCX: {safe} ---\n{txt}")
                full_text += txt
                log += f"DOCX: {safe}\n"
            elif "image" in file.type:
                img = PIL.Image.open(file)
                parts.append(f"\n--- IMG: {safe} ---\n")
                parts.append(img)
                log += f"IMG: {safe}\n"
        except: log += f"ERR: {file.name}\n"
        
    return parts, log, full_text

def interroga_gemini(prompt, contesto, input_parts, aggressivita, is_chat=True, force_interview=False):
    if not HAS_KEY: return "AI Offline."
    
    # Mood Setting
    mood_map = {1: "Diplomatico", 5: "Tecnico/Fermo", 10: "Aggressivo (Warfare)"}
    mood = mood_map.get(aggressivita, "Fermo")
    if aggressivita < 4: mood = "Diplomatico"
    if aggressivita > 7: mood = "Aggressivo"
    
    # Prompt Engineering "The Marker"
    doc_rules = """
    REGOLA CRUCIALE DOCUMENTI:
    1. DEVI INIZIARE IL DOCUMENTO ESATTAMENTE CON LA STRINGA: ###START_DOC###
    2. SUBITO DOPO IL MARKER, SCRIVI IL TITOLO.
    3. TUTTO CIÒ CHE SCRIVI PRIMA DEL MARKER VERRÀ CANCELLATO.
    4. USA TABELLE per dati numerici.
    5. NIENTE DOMANDE FINALI.
    """
    chat_rules = "USA ELENCHI PUNTATI. NO TABELLE."

    if force_interview:
        final_prompt = f"UTENTE: '{prompt}'. IGNORA LA DOMANDA. Fai 3 domande strategiche (Budget, Tempi, Obiettivi) per calibrare. Rispondi SOLO con le domande."
    else:
        final_prompt = prompt

    sys = f"""
    SEI {APP_NAME}. MOOD: {mood}.
    DATI CALCOLATORE: {st.session_state.dati_calcolatore}
    STORICO: {contesto}
    {chat_rules if is_chat else doc_rules}
    """
    
    payload = list(input_parts)
    payload.append(final_prompt)
    
    try:
        m = genai.GenerativeModel(active_model, system_instruction=sys)
        return m.generate_content(payload).text
    except Exception as e: return f"Error: {e}"

def crea_output_file(testo, nome, formato):
    testo = sterilizza_doc_marker(testo) # MARKER CUT
    
    if formato == "Word":
        doc = Document()
        doc.add_heading(nome, 0)
        advanced_markdown_to_docx(doc, testo)
        buf = BytesIO()
        doc.save(buf)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        safe_title = nome.encode('latin-1','replace').decode('latin-1')
        pdf.cell(0, 10, txt=safe_title, ln=1, align='C')
        safe_text = testo.replace("€", "EUR").encode('latin-1','replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt=safe_text)
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
            # Nome File: Tipo_Cliente_Data.ext
            cli = st.session_state.nome_cliente
            ts = datetime.now().strftime("%Y%m%d")
            fname = f"{n}_{cli}_{ts}.{info['ext']}"
            z.writestr(fname, info['data'].getvalue())
    buf.seek(0)
    return buf

# --- UI SIDEBAR ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(APP_VER)
    if status_color=="green": st.success(status_text)
    else: st.error(status_text)
    st.divider()
    st.session_state.livello_aggressivita = st.slider("Aggressività", 1, 10, 5)
    st.session_state.nome_cliente = st.text_input("Cliente", st.session_state.nome_cliente)
    if st.button("RESET"):
        st.session_state.clear()
        st.rerun()

# --- MAIN TABS ---
t1, t2, t3 = st.tabs(["🧮 Calc", "💬 Chat", "📦 Docs"])

# TAB 1: CALCOLATORE
with t1:
    st.header("Calcolatore Tecnico")
    base = st.number_input("Valore Base CTU (€)", value=354750.0)
    c1,c2,c3 = st.columns(3)
    with c1: chk_a = st.checkbox("Abuso (-30%)", True)
    with c2: chk_b = st.checkbox("No Abitabile (-18%)", True)
    with c3: chk_c = st.checkbox("No Mutuo (-15%)", True)
    
    if st.button("Calcola"):
        f = 1.0 * (0.7 if chk_a else 1) * (0.82 if chk_b else 1) * (0.85 if chk_c else 1)
        fin = base * f
        st.session_state.dati_calcolatore = f"BASE: {base} -> TARGET: {fin:.2f} (Fattore {f:.3f})"
        st.success(f"Salvato. Target: € {fin:,.2f}")

# TAB 2: CHAT (LOGIC FIX)
with t2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True, key="up")
    
    # 1. INIT: Lettura Files e Rilevamento Nome
    parts, log, full_txt = get_file_content(files)
    if full_txt and st.session_state.nome_cliente == "Cliente":
        st.session_state.nome_cliente = detect_client_name(full_txt[:2000])
        
    # 2. RENDER STORICO
    if not st.session_state.messages:
        msg = "Carica i documenti." if not files else "Pronto."
        st.session_state.messages.append({"role":"assistant", "content":msg})
        
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(sterilizza_chat(m["content"]) if m["role"]=="assistant" else m["content"])

    # 3. LOGICA INTERVISTA (PRIMA DELL'INPUT)
    # Se l'utente ha appena parlato e serve intervista, la generiamo ORA e facciamo Rerun.
    # Così l'input box non appare nel ciclo sbagliato.
    last_role = st.session_state.messages[-1]["role"] if st.session_state.messages else "assistant"
    
    if files and not st.session_state.intervista_fatta and len(st.session_state.messages) < 6 and last_role == "user":
        # È il momento dell'intervista!
        with st.chat_message("assistant"):
            with st.spinner("Analisi Strategica Iniziale..."):
                q_prompt = st.session_state.messages[-1]["content"] # Prendi l'ultima domanda utente
                resp = interroga_gemini(q_prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, True, True)
                
                clean = sterilizza_chat(resp)
                st.markdown(clean)
                st.session_state.messages.append({"role":"assistant", "content":clean})
                st.session_state.contesto_chat_text += f"\nAI: {clean}"
                st.session_state.intervista_fatta = True
                time.sleep(0.5) # Piccolo delay per UX
                st.rerun() # RIAVVIA PER MOSTRARE LA NUOVA STORIA E SPOSTARE L'INPUT SOTTO

    # 4. INPUT (Viene mostrato solo se non stiamo facendo il rerun sopra)
    if prompt := st.chat_input("Scrivi..."):
        st.session_state.messages.append({"role":"user", "content":prompt})
        st.session_state.contesto_chat_text += f"\nUser: {prompt}"
        st.rerun() # Rerun per mostrare il messaggio utente e triggerare la risposta AI nel prossimo ciclo

    # 5. RISPOSTA STANDARD (Se l'ultimo è user e non serve intervista)
    if last_role == "user" and (st.session_state.intervista_fatta or not files):
         with st.chat_message("assistant"):
            with st.spinner("..."):
                resp = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, True, False)
                clean = sterilizza_chat(resp)
                st.markdown(clean)
                st.session_state.messages.append({"role":"assistant", "content":clean})
                st.session_state.contesto_chat_text += f"\nAI: {clean}"

# TAB 3: DOCUMENTI
with t3:
    st.header("Generazione Atti")
    fmt = st.radio("Formato", ["Word", "PDF"])
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        d1 = st.checkbox("Sintesi Esecutiva")
        d2 = st.checkbox("Timeline")
        d3 = st.checkbox("Matrice Rischi")
    with col_b:
        d4 = st.checkbox("Punti Attacco")
        d5 = st.checkbox("Analisi Nota")
        d6 = st.checkbox("Quesiti CTU")
    with col_c:
        d7 = st.checkbox("Nota Replica")
        d8 = st.checkbox("Strategia A/B")
        d9 = st.checkbox("Bozza Transazione")
        
    if st.button("Genera"):
        parts, _, _ = get_file_content(files) if files else ([],"","")
        tasks = []
        
        # PROMPT SPECIALE CON MARKER
        if d1: tasks.append(("Sintesi_Esecutiva", "Crea Sintesi. REQUISITO: BOX VALORE TARGET IN CIMA. Emoji semaforici."))
        if d2: tasks.append(("Timeline", "Crea Timeline. REQUISITO: Scrivi 'Trascorsi X anni' tra le date."))
        if d3: tasks.append(("Matrice_Rischi", "Crea Matrice. REQUISITO: Riga Totale SOMMA in fondo."))
        if d4: tasks.append(("Punti_Attacco", "Crea Punti Attacco. REQUISITO: Citazioni precise."))
        if d5: tasks.append(("Analisi_Critica_Nota", "Analizza Nota. REQUISITO: Se Aggr>7 usa termini 'Inammissibile'."))
        if d6: tasks.append(("Quesiti_CTU", "Crea Quesiti. REQUISITO: Nessun preambolo."))
        if d7: tasks.append(("Nota_Replica", "Crea Nota Replica. REQUISITO: Inserisci il calcolo matematico."))
        if d8: tasks.append(("Strategia_Processuale", "Crea Strategia A/B. REQUISITO: Stima costi per scenario."))
        if d9: tasks.append(("Bozza_Transazione", "Crea Transazione. REQUISITO: Scadenza offerta 7 giorni."))

        st.session_state.generated_docs = {}
        bar = st.progress(0)
        
        for i, (name, prompt) in enumerate(tasks):
            raw = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
            buf, mime, ext = crea_output_file(raw, name, fmt)
            st.session_state.generated_docs[name] = {"data":buf, "mime":mime, "ext":ext}
            bar.progress((i+1)/len(tasks))
            
    if st.session_state.generated_docs:
        zip_buf = crea_zip(st.session_state.generated_docs)
        cli = st.session_state.nome_cliente
        ts = datetime.now().strftime("%Y%m%d")
        
        st.download_button(f"📦 SCARICA FASCICOLO ZIP", zip_buf, f"Fascicolo_{cli}_{ts}.zip", "application/zip", type="primary")
        
        st.caption("Singoli:")
        cols = st.columns(4)
        for i, (k,v) in enumerate(st.session_state.generated_docs.items()):
            # Nome file singolo con timestamp
            cli = st.session_state.nome_cliente
            ts = datetime.now().strftime("%Y%m%d")
            fname = f"{k}_{cli}_{ts}.{v['ext']}"
            cols[i%4].download_button(f"📥 {k}", v["data"], fname)
