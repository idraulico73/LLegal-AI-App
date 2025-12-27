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
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE APP ---
APP_NAME = "LegalTech Pro AI"
APP_VER = "Rev 44 (Universal Core - Multi-Practice)"

st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="⚖️")

# SOSTITUISCI IL BLOCCO CSS CON QUESTO:
st.markdown("""
<style>
    /* Stile Messaggi */
    div[data-testid="stChatMessage"] { 
        background-color: #f8f9fa; 
        border-radius: 8px; 
        padding: 15px; 
        border-left: 4px solid #004e92;
        margin-bottom: 10px;
    }
    
    /* Header e Titoli */
    h1, h2, h3 { color: #003366; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* Bottoni */
    div.stButton > button { width: 100%; font-weight: 600; border-radius: 6px; }
    div.stButton > button:first-child { background-color: #004e92; color: white; }
</style>
""", unsafe_allow_html=True)

# --- STATE MANAGEMENT ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False
if "nome_fascicolo" not in st.session_state: st.session_state.nome_fascicolo = "Fascicolo"

# --- AI SETUP ---
active_model = None
status_text = "Inizializzazione..."
status_color = "off"
HAS_KEY = False

try:
    if "GOOGLE_API_KEY" in st.secrets:
        GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=GENAI_KEY)
        HAS_KEY = True
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            priority = ["models/gemini-1.5-pro-latest", "models/gemini-1.5-pro", "models/gemini-1.5-flash"]
            for cand in priority:
                if cand in models:
                    active_model = cand
                    break
            if not active_model and models: active_model = models[0]
            
            if active_model:
                status_text = f"Ready: {active_model.replace('models/', '')}"
                status_color = "green"
        except:
            status_text = "Err: Model Discovery"
            status_color = "red"
    else:
        status_text = "Manca API KEY"
        status_color = "red"
except Exception as e:
    status_text = f"Err: {e}"
    status_color = "red"

# --- CORE FUNCTIONS ---

def detect_case_name(text):
    """Cerca di identificare il nome del caso/cliente."""
    match = re.search(r"(?:sig\.|signor|cliente|controparte|ditta)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text, re.IGNORECASE)
    if match: return match.group(1).replace(" ", "_")
    return "Nuovo_Caso"

def parse_markdown_pro(doc, text):
    """Parser Universale per DOCX - Versione Blindata Anti-Crash"""
    # FIX SICUREZZA: Se il testo è None o vuoto, esce subito senza crashare
    if text is None: return 
    text = str(text) # Forza conversione in stringa
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
        
        # Tabelle
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

        # Titoli
        if stripped.startswith('#'):
            level = stripped.count('#')
            doc.add_heading(stripped.lstrip('#').strip().replace("**",""), level=min(level, 3))
            continue

        # Liste
        if stripped.startswith('- ') or stripped.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            content = stripped[2:]
        else:
            p = doc.add_paragraph()
            content = stripped

        # Bold Parsing
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
    parts.append("DOCUMENTAZIONE FASCICOLO:\n")
    if not uploaded_files: return [], ""
    for file in uploaded_files:
        try:
            safe = file.name.replace("|", "_")
            if file.type == "application/pdf":
                pdf = PdfReader(file)
                txt = ""
                for p in pdf.pages: txt += p.extract_text() + "\n"
                parts.append(f"\n--- FILE: {safe} ---\n{txt}")
                full_text += txt
            elif "word" in file.type:
                doc = Document(file)
                txt = "\n".join([p.text for p in doc.paragraphs])
                parts.append(f"\n--- FILE: {safe} ---\n{txt}")
                full_text += txt
        except: pass
    return parts, full_text

def interroga_gemini_json(prompt, contesto, input_parts, aggressivita, force_interview=False):
    if not HAS_KEY: return {"titolo": "Errore", "contenuto": "Sistema Offline"}
    
    mood = "Tecnico/Formale"
    if aggressivita > 7: mood = "AGGRESSIVO (Legal Warfare)"
    elif aggressivita < 4: mood = "DIPLOMATICO (Mediazione)"

    sys = f"""
    SEI UN CONSULENTE TECNICO-LEGALE SENIOR (INGEGNERE E STRATEGA FORENSE).
    
    AMBITI DI COMPETENZA (Riconosci il caso dai documenti):
    1. Immobiliare (Vizi, Condoni, Eredità).
    2. Appalti & Lavori (Difformità, Contabilità).
    3. Bancario (Usura, Anatocismo).
    4. Sicurezza sul Lavoro (D.Lgs 81/08).
    5. Esecuzioni Immobiliari (Aste).
    
    MOOD: {mood}.
    
    OUTPUT: SOLO JSON.
    SCHEMA: {{ "titolo": "...", "contenuto": "..." }}
    
    DATI ECONOMICI (DAL CALCOLATORE UTENTE): 
    {st.session_state.dati_calcolatore}
    
    STORICO CHAT: {contesto}
    
    REGOLE:
    1. Nessun preambolo.
    2. Usa Markdown.
    3. Cita i documenti.
    """
    
    if force_interview:
        final_prompt = f"UTENTE: '{prompt}'. IGNORA. Genera JSON con Titolo 'Analisi Strategica Iniziale' e Contenuto: 3 domande chiave per inquadrare questo specifico caso (Budget, Obiettivi, Tempi)."
    else:
        final_prompt = f"UTENTE: '{prompt}'. Genera documento JSON."

    payload = list(input_parts)
    payload.append(final_prompt)
    
    try:
        m = genai.GenerativeModel(active_model, system_instruction=sys, generation_config={"response_mime_type": "application/json"})
        resp = m.generate_content(payload)
        return json.loads(resp.text)
    except Exception as e:
        return {"titolo": "Errore", "contenuto": str(e)}

def crea_output_file(json_data, formato):
    # FIX SICUREZZA: Gestione robusta del NoneType
    raw_content = json_data.get("contenuto", "")
    if raw_content is None: 
        testo = "Nessun contenuto generato per questa sezione."
    else:
        testo = str(raw_content)
        
    titolo = json_data.get("titolo", "Documento Generato")
    
    if formato == "Word":
        doc = Document()
        doc.add_heading(titolo, 0)
        parse_markdown_pro(doc, testo)
        buf = BytesIO()
        doc.save(buf)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        safe_t = titolo.encode('latin-1','replace').decode('latin-1')
        pdf.cell(0, 10, txt=safe_t, ln=1, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", size=11)
        safe_tx = testo.replace("€","EUR").encode('latin-1','replace').decode('latin-1')
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
            cli = st.session_state.nome_fascicolo
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
    st.session_state.livello_aggressivita = st.slider("Livello Aggressività", 1, 10, 5)
    st.session_state.nome_fascicolo = st.text_input("Rif. Fascicolo/Cliente", st.session_state.nome_fascicolo)
    if st.button("RESET FASCICOLO"):
        st.session_state.clear()
        st.rerun()

t1, t2, t3 = st.tabs(["🧮 Calcolatore Universale", "💬 Analisi & Strategia", "📦 Generatore Atti"])

# TAB 1: CALCOLATORE UNIVERSALE (AGNOSTICO)
with t1:
    st.header("Calcolatore Differenziale")
    st.caption("Confronta valori e definisci il delta tecnico per qualsiasi tipo di causa.")
    
    c1, c2 = st.columns(2)
    with c1:
        val_a = st.number_input("Valore Richiesta Controparte / CTU (€)", value=0.0, step=1000.0)
    with c2:
        val_b = st.number_input("Valore Nostra Stima / Obiettivo (€)", value=0.0, step=1000.0)
        
    delta = val_a - val_b
    
    st.markdown("### Note Tecniche & Fattori di Riduzione")
    note = st.text_area("Inserisci qui i motivi del delta (es. Vizi, Abusi, Usura, Errori Contabili):", height=150)
    
    if st.button("Salva Dati Tecnici"):
        report = f"""
        ANALISI ECONOMICA FASCICOLO:
        - Valore Controparte/CTU: € {val_a:,.2f}
        - Valore Nostro/Obiettivo: € {val_b:,.2f}
        - DELTA (Risparmio/Contestazione): € {delta:,.2f}
        
        MOTIVAZIONI TECNICHE:
        {note}
        """
        st.session_state.dati_calcolatore = report
        st.success(f"Dati Salvati. Delta Contestato: € {delta:,.2f}")

# TAB 2: CHAT (LAYOUT FIX)
with t2:
    files = st.file_uploader("Carica Fascicolo (PDF, DOCX, IMG)", accept_multiple_files=True, key="up")
    parts, full_txt = get_file_content(files)
    if full_txt and st.session_state.nome_fascicolo == "Fascicolo":
        st.session_state.nome_fascicolo = detect_case_name(full_txt[:2000])

# CONTAINER STORICO (VERSIONE FIXATA)
    msg_container = st.container()
    with msg_container:
        if not st.session_state.messages:
            st.info("Carica i documenti della causa per iniziare.")
        
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                # FIX CRASH: Assicuriamo che content sia stringa
                content_safe = str(m.get("content", "")) 
                if content_safe == "None": content_safe = ""
                st.markdown(content_safe.replace("|", " - "))

    # LOGICA INTERVISTA (Auto-Run)
    should_run_interview = False
    last_role = st.session_state.messages[-1]["role"] if st.session_state.messages else "assistant"
    
    if files and not st.session_state.intervista_fatta and len(st.session_state.messages) < 6 and last_role == "user":
        with st.spinner("Analisi Strategica del Fascicolo..."):
            last_msg = st.session_state.messages[-1]["content"]
            json_out = interroga_gemini_json(last_msg, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, True)
            cont = json_out.get("contenuto", "Errore")
            st.session_state.messages.append({"role":"assistant", "content":cont})
            st.session_state.contesto_chat_text += f"\nAI: {cont}"
            st.session_state.intervista_fatta = True
            st.rerun()

    # INPUT UTENTE
    prompt = st.chat_input("Scrivi qui la tua richiesta...")
    if prompt:
        st.session_state.messages.append({"role":"user", "content":prompt})
        st.session_state.contesto_chat_text += f"\nUser: {prompt}"
        st.rerun()

# RISPOSTA STANDARD (VERSIONE FIXATA)
    if last_role == "user" and st.session_state.intervista_fatta:
        with st.chat_message("assistant"):
            with st.spinner("Elaborazione..."):
                last_msg = st.session_state.messages[-1]["content"]
                json_out = interroga_gemini_json(last_msg, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
                
                # FIX CRASH: Gestione robusta del None
                cont = json_out.get("contenuto", "")
                if cont is None: cont = "L'AI non ha generato contenuto testuale."
                
                st.markdown(str(cont).replace("|", " - ")) # Force string
                
                st.session_state.messages.append({"role":"assistant", "content":cont})
                st.session_state.contesto_chat_text += f"\nAI: {cont}"

# TAB 3: DOCS GENERATOR (UNIVERSAL)
with t3:
    st.header("Generazione Atti")
    fmt = st.radio("Formato Output", ["Word", "PDF"])
    
    st.caption("Seleziona i documenti da generare in base alla tipologia di causa:")
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**Analisi & Sintesi**")
        d1 = st.checkbox("Sintesi Esecutiva (Status)", help="Quadro generale e semafori rischio")
        d2 = st.checkbox("Timeline Cronologica", help="Ricostruzione temporale eventi")
        d3 = st.checkbox("Matrice dei Rischi", help="Tabella Evento/Probabilità/Impatto")
    with col_b:
        st.markdown("**Tecnica & Difesa**")
        d4 = st.checkbox("Punti di Attacco Tecnici", help="Contestazione vizi/errori controparte")
        d5 = st.checkbox("Analisi Critica Documenti", help="Smontaggio tesi avversaria")
        d6 = st.checkbox("Quesiti Tecnici / CTU", help="Domande per il perito/CTU")
    with col_c:
        st.markdown("**Strategia & Chiusura**")
        d7 = st.checkbox("Atto/Nota Difensiva", help="Documento formale di replica")
        d8 = st.checkbox("Strategia Processuale", help="Scenari A vs B (Costi/Benefici)")
        d9 = st.checkbox("Bozza Transazione/Accordo", help="Proposta di chiusura")
        
    if st.button("GENERA FASCICOLO DOCUMENTALE"):
        parts, _ = get_file_content(files) if files else ([],"")
        tasks = []
        
        # Prompt Generici adattabili dall'AI
        if d1: tasks.append(("Sintesi_Esecutiva", "Crea una Sintesi Esecutiva del caso. REQ: Box iniziale con i Valori del Calcolatore. Usa Bullet Points semaforici."))
        if d2: tasks.append(("Timeline", "Crea una Timeline rigorosa degli eventi. REQ: Calcola il tempo trascorso tra le date chiave."))
        if d3: tasks.append(("Matrice_Rischi", "Crea una Matrice dei Rischi. REQ: Tabella con colonne Evento, Probabilità, Impatto Economico. Riga Totale in fondo."))
        if d4: tasks.append(("Punti_Attacco", "Elenca i Punti di Attacco Tecnici/Legali. REQ: Cita precisamente i documenti (Pagina X). Usa i dati del Calcolatore."))
        if d5: tasks.append(("Analisi_Critica", "Analizza criticamente le tesi/documenti avversari. REQ: Tono fermo/aggressivo se richiesto."))
        if d6: tasks.append(("Quesiti_Tecnici", "Formula Quesiti Tecnici o per il CTU. REQ: Domande numerate, senza preamboli."))
        if d7: tasks.append(("Nota_Difensiva", "Redigi una Nota Difensiva/Replica completa. REQ: Integra i calcoli economici e le contestazioni tecniche."))
        if d8: tasks.append(("Strategia", "Definisci la Strategia. REQ: Confronta Scenario A (Accordo) vs Scenario B (Contenzioso) con costi stimati."))
        if d9: tasks.append(("Bozza_Accordo", "Redigi una Bozza di Accordo/Transazione. REQ: Inserisci clausola di validità temporale dell'offerta."))

        st.session_state.generated_docs = {}
        pbar = st.progress(0)
        
        for i, (n, p) in enumerate(tasks):
            j = interroga_gemini_json(p, st.session_state.contesto_chat_text, parts, st.session_state.livello_aggressivita, False)
            d, m, e = crea_output_file(j, fmt)
            st.session_state.generated_docs[n] = {"data":d, "mime":m, "ext":e}
            pbar.progress((i+1)/len(tasks))
            
    if st.session_state.generated_docs:
        st.divider()
        zip_data = crea_zip(st.session_state.generated_docs)
        nome_zip = f"Fascicolo_{st.session_state.nome_fascicolo}_{datetime.now().strftime('%Y%m%d')}.zip"
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.download_button("📦 SCARICA TUTTO (ZIP)", zip_data, nome_zip, "application/zip", type="primary")
        
        st.caption("Anteprima singoli file:")
        cols = st.columns(4)
        for k, v in st.session_state.generated_docs.items():
            st.download_button(f"📥 {k}", v["data"], f"{k}.{v['ext']}")


