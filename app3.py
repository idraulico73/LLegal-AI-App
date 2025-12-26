import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# Librerie
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from fpdf import FPDF

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Ingegneria Forense AI (Rev 33 - Hybrid Master)", layout="wide", page_icon="⚖️")

# --- CSS MIGLIORATO (REV 31 STYLE) ---
st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    .chat-message { padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex; align-items: flex-start; gap: 10px; }
    .chat-message.user { background-color: #f0f2f6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; }
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #3498db; background-color: #e8f4f8; }
</style>
""", unsafe_allow_html=True)

# --- RECUPERO SECRETS (REV 31) ---
try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
except Exception:
    st.error("⚠️ Manca 'GOOGLE_API_KEY' nei secrets.toml")
    st.stop()

# --- MEMORIA DI SESSIONE (FUSA REV 25 + REV 31) ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato ancora."
# Stati per il Supervisor (Rev 31)
if "sufficiency_check" not in st.session_state: st.session_state.sufficiency_check = False
if "ready_to_generate" not in st.session_state: st.session_state.ready_to_generate = False
if "question_count" not in st.session_state: st.session_state.question_count = 0
if "doc_queue" not in st.session_state: st.session_state.doc_queue = [] # Coda documenti selezionati
if "supervisor_history" not in st.session_state: st.session_state.supervisor_history = []

# --- PROMPT LIBRARY AGNOSTICA (REV 31) ---
DOC_PROMPTS = {
    "Sintesi_Esecutiva": """
        TASK: Crea DUE sezioni distinte.
        1. TIMELINE NARRATIVA (Visual Legal Design): Non un elenco di date, ma una narrazione Causa -> Effetto -> Danno.
        2. SINTESI ESECUTIVA: Usa box per i 'Numeri Chiave' (Valore Richiesto vs Valore Reale).
    """,
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
        2. Calcola il 'Valore Nominale' dei beni assegnati.
        3. Sottrai i 'Fattori di Deprezzamento' (vizi, abusi, costi occulti).
        4. Dimostra che il 'Valore Netto Reale' < 'Quota di Diritto' -> Cliente deve ricevere soldi o pagare meno.
    """
}

# --- FUNZIONI CORE ---

def clean_ai_response(text):
    """(Rev 31) Rimuove convenevoli AI"""
    patterns = [r"^Assolutamente.*", r"^Certo.*", r"^Ecco.*", r"^Analizzo.*", r"^In base ai.*", r"^Generato il.*", r"Spero che.*", r"Dimmi se.*", r"Resto a.*"]
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
    """(Rev 31) Crea tabelle Word vere"""
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
    except: pass # Fallback se la tabella è malformata

def markdown_to_docx_advanced(text, title):
    """(Rev 31) Parser Avanzato"""
    doc = Document()
    doc.add_heading(title, 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
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
                    if part.startswith('**') and part.endswith('**'):
                        p.add_run(part.replace('**', '')).bold = True
                    else:
                        p.add_run(part)
    
    if in_table: create_word_table(doc, table_lines)
    
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def prepara_input_gemini(uploaded_files):
    """(Rev 25) Lettura File Reale"""
    input_parts = []
    log = ""
    for file in uploaded_files:
        try:
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- IMG: {file.name} ---\n")
                input_parts.append(img)
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

def check_sufficiency(context_parts, doc_queue, history):
    """(Rev 31) Agente Supervisore"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    # Estraiamo solo il testo per il check (Gemini Flash non gestisce troppe immagini nel check rapido)
    text_context = [p for p in context_parts if isinstance(p, str)]
    context_str = "".join(text_context)[:30000] # Limite char per velocità
    
    docs_to_gen = ", ".join([d[0] for d in doc_queue])
    hist_txt = "\n".join([f"{r}: {m}" for r, m in history])
    
    prompt = f"""
    SEI UN SUPERVISORE LEGALE.
    Devo generare: {docs_to_gen}.
    
    CONTESTO FORNITO:
    {context_str}
    
    STORICO DOMANDE:
    {hist_txt}
    
    Analizza se mancano dati CRITICI (nomi, cifre, date) per redigere questi documenti.
    Se mancano, fai 1 domanda specifica.
    Se è sufficiente, rispondi READY.
    """
    try:
        res = model.generate_content(prompt).text.strip()
        return ("READY", "") if "READY" in res.upper() else ("ASK", res)
    except: return "READY", ""

def genera_documento_finale(nome_doc, prompt_speciale, context_parts, postura_val, dati_calc, history):
    """(Rev 31) Generatore Potenziato"""
    model = genai.GenerativeModel("gemini-1.5-pro-latest")
    
    # Conversione Slider 1-10 in descrittivo per il prompt
    if postura_val <= 3: post_desc = "DIPLOMATICA/SOFT"
    elif postura_val <= 7: post_desc = "FERMA/PROFESSIONALE"
    else: post_desc = "AGGRESSIVA/NUCLEAR (Usa termini demolitori)"
    
    chat_ctx = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history if m['role'] == 'user'])
    
    sys_prompt = f"""
    SEI GEMINI, STRATEGA FORENSE SENIOR.
    POSTURA: {post_desc}.
    
    DATI CALCOLATORE: {dati_calc}
    
    REGOLE TASSATIVE:
    1. NO PREMESSE/SALUTI. Inizia col titolo.
    2. USA MARKDOWN.
    3. USA TABELLE MARKDOWN (| A | B |) per i dati.
    4. Cita le fonti dai documenti se possibile.
    
    ISTRUZIONE SPECIFICA PER '{nome_doc}':
    {prompt_speciale}
    """
    
    payload = list(context_parts)
    payload.append(f"\n\nINFO UTENTE EXTRA:\n{chat_ctx}\n\nGENERA IL DOCUMENTO ORA.")
    
    try:
        res = model.generate_content(payload, request_options={"timeout": 600})
        return clean_ai_response(res.text)
    except Exception as e: return f"Errore generazione: {e}"

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/8/8a/Google_Gemini_logo.svg", width=150)
    st.markdown("### ⚙️ Configurazione Tattica")
    
    # Slider Rev 31
    postura_level = st.slider("Aggressività", 1, 10, 7, help="1: Diplomatico - 10: Guerra Totale")
    if postura_level > 7: st.caption("🔥 Modalità: NUCLEAR")
    elif postura_level < 4: st.caption("🕊️ Modalità: SOFT")
    else: st.caption("⚖️ Modalità: HARD")
    
    formato_output = st.radio("Output:", ["Word", "PDF"])

# --- MAIN APP ---
st.title("⚖️ Ingegneria Forense & Strategy AI (Rev 33)")
st.caption("Integrated Core (Rev 25) + Visual Legal Design & Supervisor (Rev 31)")

tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore", "💬 Chat & Upload", "📄 Generazione Documenti"])

# ==============================================================================
# TAB 1: CALCOLATORE (REV 25 - INALTERATO)
# ==============================================================================
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
            f = 1.0
            det = ""
            if c1: f*=(1-0.30); det+="- Irregolarità: -30%\n"
            if c2: f*=(1-0.18); det+="- Sup. Non Abit.: -18%\n"
            if c3: f*=(1-0.15); det+="- No Mutuo: -15%\n"
            if c4: f*=(1-0.08); det+="- No Agibilità: -8%\n"
            if c5: f*=(1-0.05); det+="- Occupazione: -5%\n"
            
            v_fin = valore_base * f
            depr = valore_base - v_fin
            
            st.session_state.dati_calcolatore = f"""
            VALORE BASE: € {valore_base}
            COEFFICIENTI:
            {det}
            VALORE FINALE STIMATO: € {v_fin}
            DEPREZZAMENTO TOTALE: € {depr} (-{(1-f)*100:.1f}%)
            """
            st.success(f"Valore Netto: € {v_fin:,.2f}")
            st.caption("Dati salvati in memoria AI.")

# ==============================================================================
# TAB 2: CHAT & UPLOAD (REV 25 + LOGICA REV 31)
# ==============================================================================
with tab2:
    st.write("### 1. Caricamento Fascicolo")
    uploaded_files = st.file_uploader("Trascina qui PDF, Immagini, TXT", accept_multiple_files=True, key="up_chat")
    
    parts_dossier = []
    if uploaded_files:
        parts_dossier, log = prepara_input_gemini(uploaded_files)
        with st.expander("Log File"): st.text(log)

    st.divider()
    st.write("### 2. Chat Strategica")
    
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "bot"
        icon = "👤" if msg["role"] == "user" else "🤖"
        st.markdown(f"<div class='chat-message {role}'><b>{icon}:</b> {msg['content']}</div>", unsafe_allow_html=True)

    if prompt := st.chat_input("Chiedi qualcosa al fascicolo..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.write(prompt)
        
        with st.spinner("Analisi..."):
            # Usa il generatore Rev 31 per la chat
            risposta = genera_documento_finale("Risposta Chat", prompt, parts_dossier, postura_level, st.session_state.dati_calcolatore, [])
            st.session_state.messages.append({"role": "assistant", "content": risposta})
            st.rerun()

# ==============================================================================
# TAB 3: GENERAZIONE DOCUMENTI (REV 33 - SUPERVISORE INTEGRATO)
# ==============================================================================
with tab3:
    if not uploaded_files:
        st.warning("⚠️ Carica prima i file nel Tab 2.")
    else:
        st.header("🛒 Generazione Documenti (con Supervisore AI)")
        
        # 1. SELEZIONE (REV 25 CHECKBOXES)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Analisi")
            d1 = st.checkbox("Sintesi_Esecutiva")
            d2 = st.checkbox("Timeline")
            st.subheader("Attacco")
            d3 = st.checkbox("Punti_Attacco")
            d4 = st.checkbox("Quesiti_CTU")
        with c2:
            st.subheader("Strategia")
            d5 = st.checkbox("Strategia_Processuale")
            d6 = st.checkbox("Matrice_Rischi")
            st.subheader("Chiusura")
            d7 = st.checkbox("Bozza_Transazione")
            d8 = st.checkbox("Nota_Replica")

        # Costruzione Coda
        queue = []
        if d1: queue.append(("Sintesi_Esecutiva", DOC_PROMPTS["Sintesi_Esecutiva"]))
        if d2: queue.append(("Timeline", DOC_PROMPTS["Timeline"]))
        if d3: queue.append(("Punti_Attacco", DOC_PROMPTS["Punti_Attacco"]))
        if d4: queue.append(("Quesiti_CTU", DOC_PROMPTS["Quesiti_CTU"]))
        if d5: queue.append(("Strategia_Processuale", DOC_PROMPTS["Strategia_Processuale"]))
        if d6: queue.append(("Matrice_Rischi", DOC_PROMPTS["Matrice_Rischi"]))
        if d7: queue.append(("Bozza_Transazione", DOC_PROMPTS["Bozza_Transazione"]))
        if d8: queue.append(("Nota_Replica", DOC_PROMPTS["Nota_Replica"]))

        # 2. LOGICA SUPERVISORE (REV 31)
        if queue:
            if st.button("🚀 AVVIA PROCEDURA DI GENERAZIONE"):
                st.session_state.doc_queue = queue
                st.session_state.sufficiency_check = False
                st.session_state.ready_to_generate = False
                st.session_state.question_count = 0
                st.session_state.supervisor_history = []
                st.rerun()

        # Interfaccia Supervisore (appare se c'è una coda attiva)
        if st.session_state.doc_queue and not st.session_state.ready_to_generate:
            st.markdown("---")
            
            # Check Sufficienza
            if not st.session_state.sufficiency_check:
                with st.spinner("🕵️‍♂️ Il Supervisore sta controllando se mancano dati..."):
                    status, msg = check_sufficiency(parts_dossier, st.session_state.doc_queue, st.session_state.supervisor_history)
                    if status == "READY":
                        st.session_state.ready_to_generate = True
                        st.session_state.sufficiency_check = True
                        st.rerun()
                    else:
                        st.session_state.supervisor_history.append({"role": "assistant", "content": msg})
                        st.session_state.sufficiency_check = True
                        st.rerun()

            # Chat Loop
            if st.session_state.sufficiency_check and not st.session_state.ready_to_generate:
                st.markdown(f"""<div class='status-box'><b>🤖 Supervisore:</b> Sto preparando {len(st.session_state.doc_queue)} documenti.<br>Domanda {st.session_state.question_count}/10</div>""", unsafe_allow_html=True)
                
                for m in st.session_state.supervisor_history:
                    role = "👤" if m['role'] == "user" else "🤖"
                    st.markdown(f"**{role}:** {m['content']}")

                ans = st.text_input("Rispondi al Supervisore (o scrivi 'Salta'):", key="sup_ans")
                if st.button("Invia Risposta"):
                    if ans.lower() in ['salta', 'basta']:
                        st.session_state.ready_to_generate = True
                    else:
                        st.session_state.supervisor_history.append({"role": "user", "content": ans})
                        st.session_state.question_count += 1
                        if st.session_state.question_count >= 10:
                            st.session_state.ready_to_generate = True
                        else:
                            # Re-check
                            stat, nxt = check_sufficiency(parts_dossier, st.session_state.doc_queue, st.session_state.supervisor_history)
                            if stat == "READY": st.session_state.ready_to_generate = True
                            else: st.session_state.supervisor_history.append({"role": "assistant", "content": nxt})
                    st.rerun()

        # 3. GENERAZIONE MASSIVA FINALE
        if st.session_state.ready_to_generate and st.session_state.doc_queue:
            st.markdown("---")
            st.success("✅ Dati completi. Avvio generazione documenti...")
            
            prog = st.progress(0)
            st.session_state.generated_docs = {}
            
            for i, (nome, prompt_spec) in enumerate(st.session_state.doc_queue):
                with st.status(f"Scrivendo {nome}...", expanded=False):
                    txt = genera_documento_finale(
                        nome, prompt_spec, parts_dossier, 
                        postura_level, st.session_state.dati_calcolatore, 
                        st.session_state.supervisor_history # Passiamo anche le risposte date al supervisore!
                    )
                    
                    if formato_output == "Word":
                        buf = markdown_to_docx_advanced(txt, nome)
                        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        ext = "docx"
                    else: # PDF Semplice
                        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12)
                        pdf.multi_cell(0, 10, txt.encode('latin-1','replace').decode('latin-1'))
                        buf = BytesIO(pdf.output(dest='S').encode('latin-1'))
                        mime = "application/pdf"
                        ext = "pdf"
                        
                    st.session_state.generated_docs[nome] = {"data": buf, "ext": ext, "mime": mime}
                prog.progress((i+1)/len(st.session_state.doc_queue))
            
            # Reset coda per evitare loop
            st.session_state.doc_queue = [] 
            st.session_state.ready_to_generate = False
            st.session_state.sufficiency_check = False
            st.rerun()

        # 4. DOWNLOAD AREA
        if st.session_state.generated_docs:
            st.write("### 📥 Documenti Pronti")
            cols = st.columns(3)
            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):
                with cols[i % 3]:
                    st.download_button(f"Scarica {k}", v["data"], f"{k}.{v['ext']}", v["mime"])
