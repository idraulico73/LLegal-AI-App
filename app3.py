import streamlit as st
import json
from datetime import datetime
from io import BytesIO
import time
import re
import zipfile
import PIL.Image

# --- LIBRERIE ESTERNE ---
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE APP ---
APP_NAME = "LexVantage"
APP_VER = "Rev 41 (JSON Protocol & Pro Formatting)"

st.set_page_config(page_title=f"{APP_NAME} AI", layout="wide", page_icon="⚖️")

# CSS: Stile professionale e correzioni layout
st.markdown("""
<style>
    .stMarkdown { overflow-x: auto; text-align: justify; }
    div[data-testid="stChatMessage"] { 
        background-color: #f8f9fa; 
        border-radius: 12px; 
        padding: 15px; 
        margin-bottom: 10px; 
        border: 1px solid #e9ecef;
    }
    h1, h2, h3 { color: #2c3e50; font-family: 'Helvetica', sans-serif; }
    .stButton>button { 
        width: 100%; 
        border-radius: 8px; 
        height: 3.5em; 
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)

# --- STATE MANAGEMENT ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False
if "nome_cliente" not in st.session_state: st.session_state.nome_cliente = "Cliente_Generico"

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

# --- CORE FUNCTIONS (JSON & FORMATTING) ---

def detect_client_name(text):
    """Cerca cognome cliente nel testo fascicolo."""
    match = re.search(r"(?:sig\.|signor|cliente)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text, re.IGNORECASE)
    if match: return match.group(1).replace(" ", "_")
    return "Cliente"

def parse_markdown_pro(doc, text):
    """
    Parser DOCX Avanzato.
    Gestisce: **Grassetto**, *Corsivo*, # Titoli, - Elenchi, Tabelle Markdown.
    Applica Giustificato e Font Pro.
    """
    lines = text.split('\n')
    iterator = iter(lines)
    in_table = False
    table_data = []

    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)
    style_normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for line in iterator:
        stripped = line.strip()
        
        # --- GESTIONE TABELLE ---
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_data = []
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if all(set(c).issubset({'-', ':'}) for c in cells if c): continue # Salta header separator
            table_data.append(cells)
            continue
        
        if in_table:
            # Renderizza Tabella accumulata
            if table_data:
                rows = len(table_data)
                cols = max(len(r) for r in table_data) if rows > 0 else 0
                if rows > 0 and cols > 0:
                    table = doc.add_table(rows=rows, cols=cols)
                    table.style = 'Table Grid'
                    table.autofit = True
                    for r_idx, row_content in enumerate(table_data):
                        for c_idx, cell_content in enumerate(row_content):
                            if c_idx < cols:
                                cell = table.cell(r_idx, c_idx)
                                cell.text = cell_content
                                # Formatta cella
                                for paragraph in cell.paragraphs:
                                    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                                    paragraph.runs[0].font.size = Pt(10)
            in_table = False
            table_data = []

        if not stripped: continue

        # --- GESTIONE TITOLI ---
        if stripped.startswith('#'):
            level = stripped.count('#')
            clean_text = stripped.lstrip('#').strip()
            heading = doc.add_heading(clean_text, level=min(level, 3))
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
            continue

        # --- GESTIONE ELENCHI PUNTATI ---
        if stripped.startswith('- ') or stripped.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            content = stripped[2:]
        else:
            p = doc.add_paragraph()
            content = stripped

        # --- PARSER BOLD/ITALIC ---
        # Resetta il contenuto del paragrafo per ricostruirlo con i Run formattati
        p.clear() 
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        
        # Regex per trovare **bold**
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                run = p.add_run(part[2:-2])
                run.bold = True
            else:
                p.add_run(part)

def get_file_content(uploaded_files):
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

def interroga_gemini_json(prompt, contesto, input_parts, aggressivita, force_interview=False):
    if not HAS_KEY: return {"titolo": "Errore", "contenuto": "AI Offline"}
    
    mood_map = {1: "Diplomatico", 5: "Tecnico/Fermo", 10: "Aggressivo (Warfare)"}
    mood = mood_map.get(aggressivita, "Fermo")
    if aggressivita < 4: mood = "Diplomatico"
    if aggressivita > 7: mood = "Aggressivo"
    
    # PROTOCOLLO JSON RIGIDO
    sys = f"""
    SEI {APP_NAME}. MOOD: {mood}.
    
    TUO COMPITO: Analizzare il fascicolo e generare OUTPUT IN FORMATO JSON PURO.
    NON SCRIVERE NULLA FUORI DAL BLOCCO JSON.
    
    SCHEMA JSON RICHIESTO:
    {{
        "titolo": "Titolo del Documento/Risposta",
        "contenuto": "Testo completo del documento formattato in Markdown (usa **bold**, - liste, | tabelle |)."
    }}
    
    REGOLE CONTENUTO:
    1. NON INIZIARE MAI con "Ecco...", "Certo...".
    2. Usa tabelle Markdown per i dati numerici.
    3. Cita i documenti con [Doc. X].
    4. Usa un linguaggio giuridico professionale.
    
    DATI CALCOLATORE: {st.session_state.dati_calcolatore}
    STORICO: {contesto}
    """
    
    if force_interview:
        final_prompt = f"UTENTE: '{prompt}'. IGNORA LA DOMANDA. Genera un JSON dove 'contenuto' sono 3 domande strategiche (Budget, Tempi, Obiettivi) per calibrare. Titolo: 'Intervista Strategica'."
    else:
        final_prompt = f"UTENTE: '{prompt}'. Genera il documento richiesto in JSON."

    payload = list(input_parts)
    payload.append(final_prompt)
    
    try:
        m = genai.GenerativeModel(active_model, system_instruction=sys, generation_config={"response_mime_type": "application/json"})
        response = m.generate_content(payload)
        return json.loads(response.text)
    except Exception as e: 
        return {"titolo": "Errore Generazione", "contenuto": f"Errore parsing JSON o API: {e}"}

def crea_output_file_pro(json_data, formato):
    testo = json_data.get("contenuto", "")
    titolo = json_data.get("titolo", "Documento")
    
    if formato == "Word":
        doc = Document()
        # Titolo Principale
        t = doc.add_heading(titolo, 0)
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Meta dati
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = p.add_run(f"Generato il {datetime.now().strftime('%d/%m/%Y')} | {APP_NAME}")
        run.italic = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(100, 100, 100)
        doc.add_paragraph("---")
        
        # Corpo
        parse_markdown_pro(doc, testo)
        
        buf = BytesIO()
        doc.save(buf)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        safe_title = titolo.encode('latin-1','replace').decode('latin-1')
        pdf.cell(0, 10, txt=safe_title, ln=1, align='C')
        pdf.ln(10)
        
        pdf.set_font("Arial", size=11)
        safe_text = testo.replace("€", "EUR").encode('latin-1','replace').decode('latin-1')
        pdf.multi_cell(0, 6, txt=safe_text, align='J')
        
        buf = BytesIO()
        buf.write(pdf.output(dest='S').encode('latin-1'))
        mime = "application/pdf"
        ext = "pdf"
        
    buf.seek(0)
    return buf, mime, ext

def crea_zip_pro(docs):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, info in docs.items():
            # Naming Convention: Tipo_Cliente_Data.ext
            cli = st.session_state.nome_cliente
            ts = datetime.now().strftime("%Y%m%d")
            # Pulizia caratteri illegali filename
            safe_n = re.sub(r'[\\/*?:"<>|]', "", n).replace(" ", "_")
            fname = f"{safe_n}_{cli}_{ts}.{info['ext']}"
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
    if st.button("RESET SESSIONE"):
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

# TAB 2: CHAT (LOGICA UI CORRETTA)
with t2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True, key="up")
    
    # 1. INIT
    parts, log, full_txt = get_file_content(files)
    if full_txt and st.session_state.nome_cliente == "Cliente_Generico":
        st.session_state.nome_cliente = detect_client_name(full_txt[:2000])
        
    # 2. RENDER CHAT
    chat_container = st.container()
    with chat_container:
        if not st.session_state.messages:
            msg = "Carica i documenti." if not files else "Pronto."
            st.info(msg)
            
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                # Rendering pulito Markdown
                st.markdown(m["content"])

    # 3. INTERVISTA CHECK (Prima dell'Input)
    last_role = st.session_state.messages[-1]["role"] if st.session_state.messages else "assistant"
    
    if files and not st.session_state.intervista_fatta and len(st.session_state.messages) < 6 and last_role == "user":
        with st.chat_message("assistant"):
            with st.spinner("Analisi Strategica Iniziale..."):
                q_prompt = st.session_state.messages[-1]["content"]
                json_resp = interroga_gemini_json(q_prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, True)
                
                content = json_resp.get("contenuto", "Errore")
                st.markdown(content)
                st.session_state.messages.append({"role":"assistant", "content":content})
                st.session_state.contesto_chat_text += f"\nAI: {content}"
                st.session_state.intervista_fatta = True
                time.sleep(0.5)
                st.rerun()

    # 4. INPUT (Sempre in fondo)
    prompt = st.chat_input("Scrivi qui...")
    if prompt:
        st.session_state.messages.append({"role":"user", "content":prompt})
        st.session_state.contesto_chat_text += f"\nUser: {prompt}"
        st.rerun()

    # 5. RISPOSTA STANDARD
    if last_role == "user" and (st.session_state.intervista_fatta or not files):
         with st.chat_message("assistant"):
            with st.spinner("..."):
                json_resp = interroga_gemini_json(st.session_state.messages[-1]["content"], st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
                content = json_resp.get("contenuto", "Errore")
                st.markdown(content)
                st.session_state.messages.append({"role":"assistant", "content":content})
                st.session_state.contesto_chat_text += f"\nAI: {content}"

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
        
    if st.button("Genera Fascicolo"):
        parts, _, _ = get_file_content(files) if files else ([],"","")
        tasks = []
        
        # PROMPT JSON SPECIFICI
        if d1: tasks.append(("Sintesi_Esecutiva", "Crea Sintesi Esecutiva. REQUISITI: Inizia con TABELLA 'VALORE TARGET' e 'SEMAFORI RISCHIO' (🔴🟡🟢)."))
        if d2: tasks.append(("Timeline", "Crea Timeline. REQUISITI: Calcola e scrivi 'Delta Temporale' (es. 25 anni)."))
        if d3: tasks.append(("Matrice_Rischi", "Crea Matrice Rischi. REQUISITI: Riga finale con TOTALE SOMMA Euro."))
        if d4: tasks.append(("Punti_Attacco", "Crea Punti Attacco. REQUISITI: Cita [Doc. Pag. X] per ogni punto."))
        if d5: tasks.append(("Analisi_Critica_Nota", "Analizza Nota Avversaria. REQUISITI: Usa termini 'Inammissibile', 'Pretestuoso' se aggressività alta."))
        if d6: tasks.append(("Quesiti_CTU", "Crea Quesiti CTU. REQUISITI: Solo domande numerate, tono inquisitorio."))
        if d7: tasks.append(("Nota_Replica", "Crea Nota Replica. REQUISITI: Integra stringa calcolo matematico."))
        if d8: tasks.append(("Strategia_Processuale", "Crea Strategia A/B. REQUISITI: Tabella costi vivi per scenario."))
        if d9: tasks.append(("Bozza_Transazione", "Crea Transazione. REQUISITI: Clausola di scadenza offerta (7gg) in grassetto."))

        st.session_state.generated_docs = {}
        bar = st.progress(0)
        
        for i, (name, prompt) in enumerate(tasks):
            json_resp = interroga_gemini_json(prompt, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
            buf, mime, ext = crea_output_file_pro(json_resp, fmt)
            st.session_state.generated_docs[name] = {"data":buf, "mime":mime, "ext":ext}
            bar.progress((i+1)/len(tasks))
            
    if st.session_state.generated_docs:
        zip_buf = crea_zip_pro(st.session_state.generated_docs)
        cli = st.session_state.nome_cliente
        ts = datetime.now().strftime("%Y%m%d")
        
        st.success("✅ Generazione Completata. Scarica il pacchetto.")
        st.download_button(
            label=f"📦 SCARICA FASCICOLO COMPLETO ({cli})",
            data=zip_buf,
            file_name=f"Fascicolo_{cli}_{ts}.zip",
            mime="application/zip",
            type="primary"
        )
