import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# --- LIBRERIE ESTERNE ---
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE APP & CSS ---
APP_NAME = "LexVantage"
APP_VER = "Rev 35 (Full Suite & Logic Fix)"

st.set_page_config(page_title=f"{APP_NAME} AI", layout="wide", page_icon="⚖️")

# CSS per layout sicuro
st.markdown("""
<style>
    .stMarkdown { overflow-x: auto; }
    div[data-testid="stChatMessage"] { overflow-x: hidden; }
    h1, h2, h3 { color: #2c3e50; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .success-box { padding: 10px; background-color: #d4edda; color: #155724; border-radius: 5px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- MEMORIA DI SESSIONE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5
# Flag per forzare l'intervista iniziale
if "intervista_fatta" not in st.session_state: st.session_state.intervista_fatta = False

# --- MOTORE AI ---
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
            list_models = genai.list_models()
            all_models = [m.name for m in list_models if 'generateContent' in m.supported_generation_methods]
        except:
            all_models = []

        priority_list = [
            "models/gemini-1.5-pro-latest",
            "models/gemini-1.5-pro",
            "models/gemini-1.5-flash",
            "models/gemini-2.0-flash-exp"
        ]
        
        for candidate in priority_list:
            if candidate in all_models:
                active_model = candidate
                break
        if not active_model and all_models: active_model = all_models[0]
            
        if active_model:
            status_text = f"Online: {active_model.replace('models/', '')}"
            status_color = "green"
        else:
            status_text = "Errore: Nessun modello trovato."
            status_color = "red"
    else:
        status_text = "Manca API KEY."
        status_color = "red"
except Exception as e:
    status_text = f"Errore: {str(e)}"
    status_color = "red"

# --- FUNZIONI DI UTILITÀ ---

def rimuovi_tabelle_forzato(text):
    """NUCLEAR OPTION: Rimuove tabelle per la chat."""
    if not text: return ""
    return text.replace("|", " - ")

def pulisci_header_ai(text):
    patterns = [r"^Ecco .*?:", r"^Certo, .*?:", r"^Here is .*?:", r"Sure, I can help.*?\n", r"^\*\*.*?\*\*$"]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text.strip()

def advanced_markdown_to_docx(doc, text):
    """Parser che gestisce tabelle reali per DOCX."""
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

def prepara_input_gemini(uploaded_files):
    input_parts = []
    input_parts.append("ANALISI FASCICOLO TECNICO/LEGALE:\n")
    log_debug = ""
    for file in uploaded_files:
        try:
            safe_name = file.name.replace("|", "_")
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- IMG: {safe_name} ---\n")
                input_parts.append(img)
                log_debug += f"🖼️ {safe_name}\n"
            elif file.type == "application/pdf":
                pdf_reader = PdfReader(file)
                text_buffer = f"\n--- PDF: {safe_name} ---\n"
                for page in pdf_reader.pages:
                    text_buffer += page.extract_text().replace("|", " ") + "\n"
                input_parts.append(text_buffer)
                log_debug += f"📄 {safe_name}\n"
            elif "word" in file.type:
                 doc = Document(file)
                 text = "\n".join([p.text for p in doc.paragraphs])
                 input_parts.append(f"\n--- DOCX: {safe_name} ---\n{text}")
                 log_debug += f"📘 {safe_name}\n"
        except Exception as e:
            st.error(f"Errore file {file.name}: {e}")
    return input_parts, log_debug

def interroga_gemini(prompt_utente, contesto_chat, input_parts, modello, livello_aggressivita, is_chat_mode=True, force_interview=False):
    if not HAS_KEY or not modello: return "ERRORE: AI Offline."
    dati_calc = st.session_state.dati_calcolatore
    
    # 1. Definizione Mood
    mood_map = {
        1: "DIPLOMATICO: Cerca accordo, toni morbidi, evita scontro.",
        5: "PROFESSIONALE FERMO: Tecnico, deciso, non fa regali ma non insulta.",
        10: "LEGAL WARFARE (AGGRESSIVO): Demolisci la controparte, usa termini ultimativi, minaccia azioni."
    }
    mood = mood_map.get(livello_aggressivita, mood_map[5]) if livello_aggressivita <= 10 else mood_map[5]
    if livello_aggressivita < 4: mood = mood_map[1]
    elif livello_aggressivita > 7: mood = mood_map[10]

    # 2. Suffissi Tecnici
    chat_rules = """
    REGOLA CHAT:
    - VIETATO USARE TABELLE O PIPE '|'. Usa elenchi puntati.
    - Sii sintetico e diretto.
    """
    doc_rules = """
    REGOLA DOCUMENTI:
    - DEVI USARE TABELLE per comparare dati (es. Valori CTU vs CTP).
    - Usa un linguaggio giuridico formale di alto livello.
    - Non mettere saluti iniziali, vai dritto al contenuto dell'atto.
    """
    
    # 3. Logica "Intervista Forzata"
    if force_interview:
        prompt_finale = f"""
        L'utente ha chiesto: "{prompt_utente}"
        
        TUTTAVIA, ignora la richiesta di risposta immediata.
        Hai appena letto il fascicolo. Prima di dare consigli, DEVI fare una "Intervista Strategica".
        
        OUTPUT RICHIESTO:
        Non rispondere alla domanda dell'utente.
        Genera invece una lista di 3-4 DOMANDE CRUCIALI (Bullet points) che devi fare all'utente per capire la strategia (es: Budget reale? Tempi massimi? Obiettivo: transazione o causa lunga?).
        Sii breve. Chiedi solo quello che manca.
        """
    else:
        prompt_finale = prompt_utente

    system_instruction = f"""
    SEI {APP_NAME}, STRATEGA LEGALE & INGEGNERE FORENSE.
    
    CONFIGURAZIONE:
    - Aggressività: {livello_aggressivita}/10 ({mood})
    - Obiettivo: Minimizzare conguaglio o Massimizzare risultato.
    
    DATI CALCOLATORE (VERITÀ TECNICA):
    {dati_calc}
    (Usa questi numeri per confutare ogni stima avversa).
    
    CONTESTO PRECEDENTE: {contesto_chat}
    
    {chat_rules if is_chat_mode else doc_rules}
    """
    
    payload = list(input_parts)
    payload.append(prompt_finale)

    try:
        model = genai.GenerativeModel(modello, system_instruction=system_instruction)
        response = model.generate_content(payload)
        return response.text
    except Exception as e:
        return f"Errore API: {e}"

def crea_word(testo, titolo):
    testo = pulisci_header_ai(testo)
    doc = Document()
    doc.add_heading(titolo, 0)
    advanced_markdown_to_docx(doc, testo)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crea_pdf_safe(testo, titolo):
    testo = pulisci_header_ai(testo)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=titolo.encode('latin-1','replace').decode('latin-1'), ln=1, align='C')
    replacements = {"€": "EUR", "’": "'", "“": '"', "”": '"', "–": "-"}
    for k,v in replacements.items(): testo = testo.replace(k,v)
    pdf.multi_cell(0, 10, txt=testo.encode('latin-1','replace').decode('latin-1'))
    buffer = BytesIO()
    buffer.write(pdf.output(dest='S').encode('latin-1'))
    buffer.seek(0)
    return buffer

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚖️ LexVantage")
    st.caption(APP_VER)
    if status_color == "green": st.success(status_text)
    else: st.error(status_text)
    st.divider()
    aggressivita = st.slider("Livello Aggressività", 1, 10, 5)
    st.session_state.livello_aggressivita = aggressivita
    
    if st.button("🗑️ Reset Totale"):
        st.session_state.messages = []
        st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
        st.session_state.intervista_fatta = False
        st.rerun()

# --- TAB LAYOUT ---
tab1, tab2, tab3 = st.tabs(["🧮 Calcolatore", "💬 Chat Strategica", "📄 Generazione Atti (Full)"])

# TAB 1: CALCOLATORE
with tab1:
    st.header("Calcolo Deprezzamento Tecnico")
    c1, c2 = st.columns([1,2])
    with c1:
        base = st.number_input("Valore Base CTU (€)", value=354750.0)
        chk_abuso = st.checkbox("Irregolarità Grave (-30%)", True)
        chk_sup = st.checkbox("Sup. Non Abitabili (-18%)", True)
        chk_mutuo = st.checkbox("No Mutuabilità (-15%)", True)
        chk_agib = st.checkbox("No Agibilità (-8%)", True)
        chk_occ = st.checkbox("Occupazione (-5%)", False)
        if st.button("Calcola e Salva", type="primary"):
            f = 1.0
            log = ""
            if chk_abuso: f *= 0.70; log+="- Abuso Grave (-30%)\n"
            if chk_sup: f *= 0.82; log+="- Sup. Non Abitabili (-18%)\n"
            if chk_mutuo: f *= 0.85; log+="- No Mutuo (-15%)\n"
            if chk_agib: f *= 0.92; log+="- No Agibilità (-8%)\n"
            if chk_occ: f *= 0.95; log+="- Occupato (-5%)\n"
            
            val_fin = base * f
            report = f"VALORE BASE: € {base:,.2f}\nCRITICITÀ:\n{log}FATTORE: {f:.4f}\nVALORE FINALE: € {val_fin:,.2f}"
            st.session_state.dati_calcolatore = report
            st.success("✅ Dati Salvati!")
    with c2:
        if st.session_state.dati_calcolatore != "Nessun calcolo tecnico effettuato.":
            st.info("Dati in Memoria:")
            st.code(st.session_state.dati_calcolatore)

# TAB 2: CHAT
with tab2:
    st.header("Analisi Strategica")
    files = st.file_uploader("Carica Fascicolo", accept_multiple_files=True, key="chat_up")
    
    # Check Iniziale Intelligente
    if not st.session_state.messages:
        if not files:
            msg_init = "Benvenuto. Carica i documenti per iniziare l'analisi."
        else:
            msg_init = "Documenti ricevuti. Analizzo il fascicolo..."
        st.session_state.messages.append({"role": "assistant", "content": msg_init})

    # Render Storico (con rimozione tabelle per sicurezza visuale)
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(rimuovi_tabelle_forzato(m["content"]) if m["role"]=="assistant" else m["content"])

    if prompt := st.chat_input("Scrivi qui..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.contesto_chat_text += f"\nUtente: {prompt}"
        with st.chat_message("user"): st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Elaborazione..."):
                parts, _ = prepara_input_gemini(files) if files else ([], "")
                
                # LOGICA "INTERVISTA FORZATA"
                # Se è la prima domanda vera e non abbiamo ancora fatto l'intervista:
                force_interview = False
                if len(st.session_state.messages) < 4 and not st.session_state.intervista_fatta:
                    force_interview = True
                    st.session_state.intervista_fatta = True # Segna come fatta per il futuro
                
                resp = interroga_gemini(
                    prompt, 
                    st.session_state.contesto_chat_text, 
                    parts, 
                    active_model, 
                    st.session_state.livello_aggressivita, 
                    is_chat_mode=True,
                    force_interview=force_interview
                )
                
                # Salvataggio e Display
                resp_clean = rimuovi_tabelle_forzato(resp)
                st.markdown(resp_clean)
                st.session_state.messages.append({"role": "assistant", "content": resp_clean})
                st.session_state.contesto_chat_text += f"\nAI: {resp_clean}"

# TAB 3: GENERAZIONE DOCUMENTI (FIX COMPLETO)
with tab3:
    st.header("Generazione Atti & Strategie (Full Suite)")
    
    # Check presenza file
    if not files and st.session_state.dati_calcolatore == "Nessun calcolo tecnico effettuato.":
        st.warning("⚠️ Carica file nel Tab 2 o usa il Calcolatore nel Tab 1 prima di generare atti.")
    
    st.subheader("Seleziona Documenti da Generare (9 Tipologie)")
    
    # Layout 3 Colonne per i 9 Documenti
    col_a, col_b, col_c = st.columns(3)
    
    with col_a:
        st.markdown("**1. Analisi & Studio**")
        d1 = st.checkbox("Sintesi Esecutiva", help="Analisi semaforica dei rischi")
        d2 = st.checkbox("Timeline Processuale", help="Date chiave e decadenze")
        d3 = st.checkbox("Matrice dei Rischi", help="Tabella scenari e impatti")
        
    with col_b:
        st.markdown("**2. Attacco & Difesa**")
        d4 = st.checkbox("Punti di Attacco (Vizi)", help="Errori della controparte/CTU")
        d5 = st.checkbox("Analisi Critica Nota", help="Smontaggio tesi avversaria")
        d6 = st.checkbox("Quesiti per CTU", help="Domande trappola")
        
    with col_c:
        st.markdown("**3. Strategia & Chiusura**")
        d7 = st.checkbox("Nota di Replica", help="Atto formale completo")
        d8 = st.checkbox("Strategia Processuale", help="Scenario A vs B")
        d9 = st.checkbox("Bozza Transazione", help="Lettera saldo e stralcio")

    fmt = st.radio("Formato:", ["Word (.docx)", "PDF (.pdf)"], horizontal=True)

    if st.button("🚀 Genera Documenti Selezionati", type="primary"):
        # FIX NAMEERROR: Ricalcoliamo input_payload qui nel Tab 3
        # Usiamo 'files' che è definito nel Tab 2 ma visibile allo script se caricato
        input_payload, _ = prepara_input_gemini(files) if files else ([], "")
        
        # Mappatura Prompt Specializzati
        tasks = []
        if d1: tasks.append(("Sintesi_Esecutiva", "Crea una Sintesi Esecutiva. Usa bullet points. Evidenzia: Valore CTU vs Valore Nostro. Rischi principali."))
        if d2: tasks.append(("Timeline", "Crea una Timeline rigorosa. Evidenzia in GRASSETTO le date di decadenza o prescrizione."))
        if d3: tasks.append(("Matrice_Rischi", "Crea una Matrice Rischi (Tabella). Colonne: Evento, Probabilità (%), Impatto Economico (€)."))
        if d4: tasks.append(("Punti_Attacco", "Elenca i Punti di Attacco. Cita, se possibile, le pagine dei documenti. Usa i numeri del calcolatore per mostrare l'errore economico."))
        if d5: tasks.append(("Analisi_Critica_Nota", "Analizza la nota avversaria. Sii spietato se aggressività alta. Evidenzia fallacie logiche."))
        if d6: tasks.append(("Quesiti_CTU", "Scrivi 5 Quesiti 'Trappola' per il CTU. Devono costringerlo ad ammettere i vizi (es. mancata verifica condono)."))
        if d7: tasks.append(("Nota_Replica", "Scrivi una Nota di Replica Tecnica completa. Integra i calcoli di deprezzamento nel testo. Linguaggio giuridico formale."))
        if d8: tasks.append(("Strategia_Processuale", "Definisci Strategia Scenario A (Transazione) vs Scenario B (Giudizio). Costi e Benefici per entrambi."))
        if d9: tasks.append(("Bozza_Transazione", "Scrivi una Bozza di Transazione formale. Ancora l'offerta al nostro Valore Tecnico (falla sembrare una concessione)."))

        st.session_state.generated_docs = {}
        prog = st.progress(0)
        
        for i, (fname, prompt_spec) in enumerate(tasks):
            with st.status(f"Generazione {fname}...", expanded=False):
                # Generazione con AI (is_chat_mode=False per permettere tabelle nei DOC)
                text_out = interroga_gemini(
                    prompt_spec, 
                    st.session_state.contesto_chat_text, 
                    input_payload, 
                    active_model, 
                    st.session_state.livello_aggressivita, 
                    is_chat_mode=False # Qui le tabelle sono permesse!
                )
                
                if "Word" in fmt:
                    data = crea_word(text_out, fname.replace("_", " "))
                    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ext = "docx"
                else:
                    data = crea_pdf_safe(text_out, fname.replace("_", " "))
                    mime = "application/pdf"
                    ext = "pdf"
                    
                st.session_state.generated_docs[fname] = {"data": data, "ext": ext, "mime": mime}
            prog.progress((i+1)/len(tasks))
            
    # Download
    if st.session_state.generated_docs:
        st.divider()
        st.success("Documenti Pronti:")
        cols = st.columns(4)
        for idx, (k, v) in enumerate(st.session_state.generated_docs.items()):
            cols[idx % 4].download_button(
                f"📥 {k}.{v['ext']}", 
                v['data'], 
                f"{k}.{v['ext']}", 
                v['mime']
            )
