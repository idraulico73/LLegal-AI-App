import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# --- LIBRERIE ESTERNE (Requisiti: streamlit, google-generativeai, pypdf, python-docx, fpdf) ---
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE APP & CSS ---
APP_NAME = "LexVantage"
APP_VER = "Rev Finale (Gold)"

st.set_page_config(page_title=f"{APP_NAME} AI", layout="wide", page_icon="⚖️")

# CSS per layout sicuro e gestione overflow
st.markdown("""
<style>
    /* Impedisce alle tabelle troppo larghe di rompere il layout */
    .stMarkdown { overflow-x: auto; }
    div[data-testid="stChatMessage"] { overflow-x: hidden; }
    
    /* Stile Headers */
    h1, h2, h3 { color: #2c3e50; }
    
    /* Evidenziazione messaggi sistema */
    .system-msg { background-color: #f0f2f6; padding: 10px; border-radius: 5px; border-left: 4px solid #ff4b4b; }
</style>
""", unsafe_allow_html=True)

# --- MEMORIA DI SESSIONE (Persistence Layer) ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5

# --- MOTORE AI (Auto-Discovery & Auth) ---
active_model = None
status_text = "Inizializzazione..."
status_color = "off"
HAS_KEY = False

try:
    # Gestione sicura API KEY da secrets
    if "GOOGLE_API_KEY" in st.secrets:
        GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=GENAI_KEY)
        HAS_KEY = True
        
        # Discovery Modelli (Fallback intelligente)
        try:
            list_models = genai.list_models()
            all_models = [m.name for m in list_models if 'generateContent' in m.supported_generation_methods]
        except:
            all_models = []

        # Priorità di selezione (aggiornata per evitare 404)
        priority_list = [
            "models/gemini-1.5-pro-latest",
            "models/gemini-1.5-pro",
            "models/gemini-1.5-flash",
            "models/gemini-2.0-flash-exp" # Sperimentale
        ]
        
        for candidate in priority_list:
            if candidate in all_models:
                active_model = candidate
                break
        
        # Fallback estremo se la lista prioritaria fallisce ma c'è qualcosa
        if not active_model and all_models:
            active_model = all_models[0]
            
        if active_model:
            clean_name = active_model.replace('models/', '')
            status_text = f"Online: {clean_name}"
            status_color = "green"
        else:
            status_text = "Errore: Nessun modello compatibile trovato."
            status_color = "red"
    else:
        status_text = "Manca API KEY nei secrets."
        status_color = "red"

except Exception as e:
    HAS_KEY = False
    status_text = f"Errore Connessione: {str(e)}"
    status_color = "red"

# --- UTILITÀ DI SANITIZZAZIONE E PARSING ---

def sterilizza_output_chat(text):
    """
    NUCLEAR OPTION: Rimuove ogni possibilità che Streamlit veda una tabella.
    Sostituisce TUTTI i pipe '|' con un carattere grafico innocuo.
    """
    if not text: return ""
    
    # Sostituiamo il pipe '|' (che crea la tabella) con una freccia.
    # Streamlit ora vedrà solo testo normale e non proverà a impaginarlo.
    safe_text = text.replace("|", " ➤ ")
    
    # Rimuoviamo anche le righe che servono solo a definire la tabella (es: ---|---|---)
    lines = safe_text.split('\n')
    clean_lines = []
    for line in lines:
        # Se la riga contiene quasi solo trattini e frecce, è spazzatura della tabella: via.
        if set(line.strip()).issubset({'-', ' ', ':', '➤'}):
            continue
        clean_lines.append(line)
        
    return "\n".join(clean_lines)

def pulisci_header_ai(text):
    """Rimuove i convenevoli dell'AI (Sure, Ecco il documento, ecc.)"""
    # Regex per rimuovere frasi introduttive comuni
    patterns = [
        r"^Ecco .*?:", r"^Certo, .*?:", r"^Here is .*?:", 
        r"^Spero che .*?\.", r"Sure, I can help.*?\n"
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text.strip()

def advanced_markdown_to_docx(doc, text):
    """
    Parser AVANZATO: Gestisce grassetti, bullet points e converte Tabelle Markdown in Tabelle Word Reali.
    """
    lines = text.split('\n')
    iterator = iter(lines)
    
    in_table = False
    table_data = []

    for line in iterator:
        stripped = line.strip()
        
        # Rilevamento Tabelle Markdown
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_data = []
            
            # Parsing riga tabella (rimuove primo e ultimo pipe vuoto)
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            
            # Salta la riga di separazione (es: |---|---|)
            if all(set(c).issubset({'-', ':'}) for c in cells if c):
                continue
                
            table_data.append(cells)
            continue
        
        # Fine tabella rilevata (riga che non è tabella)
        if in_table:
            # Renderizza la tabella accumulata
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

        # Gestione Titoli
        if stripped.startswith('#'):
            level = stripped.count('#')
            content = stripped.lstrip('#').strip()
            if level > 3: level = 3 
            try: doc.add_heading(content, level=level)
            except: doc.add_paragraph(content, style='Heading 3')
            continue

        # Gestione Bullet Points
        if stripped.startswith('- ') or stripped.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            content = stripped[2:]
        else:
            p = doc.add_paragraph()
            content = stripped

        # Formattazione Grassetto (**text**) all'interno del paragrafo
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                run = p.add_run(part[2:-2])
                run.bold = True
            else:
                p.add_run(part)

def prepara_input_gemini(uploaded_files):
    input_parts = []
    input_parts.append("ANALISI FASCICOLO TECNICO/LEGALE:\n")
    log_debug = ""

    for file in uploaded_files:
        try:
            # Sanitizzazione Input: Rimuove i caratteri tabella dai nomi file per sicurezza
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
                    # Context Sanitization: Rimuove le tabelle grezze dal testo estratto per non confondere l'AI
                    raw_text = page.extract_text()
                    safe_text = raw_text.replace("|", " ") 
                    text_buffer += safe_text + "\n"
                input_parts.append(text_buffer)
                log_debug += f"📄 {safe_name} ({len(pdf_reader.pages)} pag)\n"
            
            elif file.type == "text/plain":
                text = str(file.read(), "utf-8")
                input_parts.append(f"\n--- TXT: {safe_name} ---\n{text}")
                log_debug += f"📝 {safe_name}\n"
                
            elif "word" in file.type: # Supporto base DOCX input
                 doc = Document(file)
                 fullText = []
                 for para in doc.paragraphs:
                     fullText.append(para.text)
                 text = "\n".join(fullText)
                 input_parts.append(f"\n--- DOCX: {safe_name} ---\n{text}")
                 log_debug += f"📘 {safe_name}\n"

        except Exception as e:
            st.error(f"Errore lettura {file.name}: {e}")
            
    return input_parts, log_debug

def interroga_gemini(prompt_utente, contesto_chat, input_parts, modello, livello_aggressivita, is_chat_mode=True):
    if not HAS_KEY or not modello: return "ERRORE CRITICO: Sistema AI non disponibile."

    dati_calc = st.session_state.dati_calcolatore
    
    # Mappatura Slider Aggressività
    if livello_aggressivita <= 3:
        mood = "DIPLOMATICO (Focus: Transazione, Toni pacati, Ricerca accordo)"
    elif livello_aggressivita <= 7:
        mood = "FERMO/PROFESSIONALE (Focus: Tecnicismo, Toni decisi, Nessuna concessione non necessaria)"
    else:
        mood = "AGGRESSIVO/LEGAL WARFARE (Focus: Demolizione avversario, Toni perentori, Minaccia azioni legali)"

    # Prompt Socratico per Chat vs Output Diretto per Documenti
    if is_chat_mode:
        instruction_suffix = """
        SEI IN MODALITÀ CHAT (CONSULENZA):
        - Usa elenchi puntati per chiarezza.
        - Non usare tabelle Markdown (rompono la UI), usa elenchi.
        - Se mancano informazioni strategiche (date, cifre, intenti), CHIEDILE all'utente prima di dare risposte vaghe.
        """
    else:
        instruction_suffix = """
        SEI IN MODALITÀ REDAZIONE DOCUMENTI (WORD/PDF):
        - Qui PUOI e DEVI usare tabelle Markdown se servono per comparare dati.
        - Non inserire saluti o commenti ("Ecco il documento"), scrivi solo il contenuto finale del documento.
        """

    system_instruction = f"""
    SEI {APP_NAME}, ARCHITETTO LEGALE SENIOR.
    
    CONFIGURAZIONE STRATEGICA:
    - Livello Aggressività: {livello_aggressivita}/10
    - Postura: {mood}
    
    DATI TECNICI CERTIFICATI (DAL CALCOLATORE):
    {dati_calc}
    (Questi dati sono FATTI. Non allucinarli. Usali come base matematica inattaccabile).
    
    CONTESTO STORICO: {contesto_chat}
    
    {instruction_suffix}
    """
    
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Calibrazione Automatica (Il "Supervisore")
    if is_chat_mode and len(contesto_chat) < 10:
        prompt_finale = f"{prompt_utente}\n\n[NOTA SISTEMA: Lo storico è vuoto. Se la richiesta dell'utente è vaga, inizia facendo 3 domande di calibrazione strategica (Obiettivo, Budget, Tempi) prima di rispondere.]"
    else:
        prompt_finale = prompt_utente

    payload = list(input_parts)
    payload.append(prompt_finale)

    try:
        model_instance = genai.GenerativeModel(modello, system_instruction=system_instruction)
        response = model_instance.generate_content(payload, safety_settings=safety_settings)
        return response.text
    except Exception as e:
        return f"Errore Gemini API: {e}"

def crea_word(testo, titolo):
    testo = pulisci_header_ai(testo) # Sanitizzazione
    doc = Document()
    doc.add_heading(titolo, 0)
    
    # Dati meta
    p = doc.add_paragraph()
    run = p.add_run(f"Generato da {APP_NAME} | {datetime.now().strftime('%d/%m/%Y')}")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(128, 128, 128)
    doc.add_paragraph("---")
    
    advanced_markdown_to_docx(doc, testo) # Nuovo engine tabelle
    
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crea_pdf_safe(testo, titolo):
    """Versione PDF Safe che gestisce Euro e encoding"""
    testo = pulisci_header_ai(testo)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Titolo Safe
    safe_title = titolo.encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(200, 10, txt=safe_title, ln=1, align='C')
    pdf.ln(10)
    
    # Replace caratteri problematici per FPDF standard
    replacements = {
        "€": "EUR", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"
    }
    for old, new in replacements.items():
        testo = testo.replace(old, new)
        
    safe_text = testo.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=safe_text)
    
    buffer = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    buffer.write(pdf_string)
    buffer.seek(0)
    return buffer

# --- SIDEBAR ---
with st.sidebar:
    st.title(f"🏛️ {APP_NAME}")
    st.caption(f"Ver: {APP_VER}")
    
    st.markdown("### 🧠 Neural Engine")
    if status_color == "green":
        st.success(status_text)
    else:
        st.error(status_text)
    
    st.divider()
    st.markdown("### 🎚️ Strategia")
    # Slider Aggressività (Richiesta To-Do 5)
    aggressivita = st.slider("Livello Aggressività", 1, 10, 5, help="1: Diplomatico, 10: Guerra Legale")
    st.session_state.livello_aggressivita = aggressivita
    
    st.divider()
    with st.expander("🔐 Admin & Debug"):
        pwd = st.text_input("Password", type="password")
        is_admin = (pwd == st.secrets.get("ADMIN_PASSWORD", "admin"))
        if is_admin:
            st.write(f"Model: {active_model}")

# --- MAIN LAYOUT (3 TAB) ---
st.title(f"{APP_NAME}: Piattaforma Forense AI")

tab1, tab2, tab3 = st.tabs(["🧮 1. Calcolatore Tecnico", "💬 2. Chat & Analisi", "📄 3. Generazione Atti"])

# ==============================================================================
# TAB 1: CALCOLATORE (LOGICA PERSISTENTE)
# ==============================================================================
with tab1:
    st.header("Calcolo Deprezzamento Immobiliare")
    st.caption("I dati calcolati qui diventeranno 'Verità Tecnica' per l'AI.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        valore_base = st.number_input("Valore Base CTU (€)", value=354750.0, step=1000.0)
        st.markdown("#### Coefficienti Riduttivi (Standard)")
        # Checkbox Specifici richiesti nella To-Do List
        c1 = st.checkbox("Irregolarità urbanistica grave (-30%)", value=True)
        c2 = st.checkbox("Superfici non abitabili (-18%)", value=True)
        c3 = st.checkbox("Assenza mutuabilità (-15%)", value=True)
        c4 = st.checkbox("Assenza agibilità (-8%)", value=True)
        c5 = st.checkbox("Occupazione (-5%)", value=False)
        
        btn_calcola = st.button("💾 Calcola & Salva in Memoria", type="primary")

    with col2:
        if btn_calcola:
            fattore = 1.0
            log_calcolo = []
            txt_report = ""
            
            if c1: 
                fattore *= 0.70
                log_calcolo.append("-30% (Abuso Grave)")
                txt_report += "- Irregolarità Urbanistica Grave: -30%\n"
            if c2: 
                fattore *= 0.82
                log_calcolo.append("-18% (Non Abitabile)")
                txt_report += "- Superfici Non Abitabili: -18%\n"
            if c3: 
                fattore *= 0.85
                log_calcolo.append("-15% (No Mutuo)")
                txt_report += "- Assenza Mutuabilità: -15%\n"
            if c4: 
                fattore *= 0.92
                log_calcolo.append("-8% (No Agibilità)")
                txt_report += "- Assenza Agibilità: -8%\n"
            if c5: 
                fattore *= 0.95
                log_calcolo.append("-5% (Occupato)")
                txt_report += "- Occupazione: -5%\n"
            
            valore_finale = valore_base * fattore
            delta = valore_base - valore_finale
            
            # Persistenza Session State
            full_report = f"""
            --- DATI CALCOLATORE TECNICO ---
            VALORE BASE: € {valore_base:,.2f}
            COEFFICIENTI APPLICATI:
            {txt_report}
            FATTORE RISULTANTE: {fattore:.4f}
            DEPREZZAMENTO: € {delta:,.2f}
            VALORE FINALE TARGET: € {valore_finale:,.2f}
            --- FINE DATI CALCOLATORE ---
            """
            st.session_state.dati_calcolatore = full_report
            
            st.success("✅ Dati salvati nella memoria dell'AI.")
            st.metric("Valore Stimato", f"€ {valore_finale:,.2f}", delta_color="inverse", delta=f"- € {delta:,.2f}")
            st.info(f"Formula: {' * '.join(log_calcolo)}")
        else:
            if st.session_state.dati_calcolatore != "Nessun calcolo tecnico effettuato.":
                st.info("Dati presenti in memoria dal calcolo precedente.")
                st.code(st.session_state.dati_calcolatore)

# ==============================================================================
# TAB 2: CHAT GEMINI (REVISIONE "ANTI-TABELLA" TOTALE)
# ==============================================================================
with tab2:
    st.header("Analisi Fascicolo & Strategia")
    
    # --- 1. FUNZIONE DI PULIZIA LOCALE AGGRESSIVA ---
    def rimuovi_tabelle_forzato(testo):
        """
        Questa funzione distrugge la sintassi Markdown delle tabelle.
        Sostituisce i pipe '|' con trattini ' - ' per impedire il rendering HTML.
        """
        if not testo: return ""
        # Sostituisce ogni pipe con un trattino. Streamlit NON PUÒ fare tabelle senza pipe.
        return testo.replace("|", " - ")

    # --- 2. GESTIONE UPLOAD ---
    st.write("### 1. Carica il Fascicolo")
    uploaded_files = st.file_uploader("Upload Documenti", accept_multiple_files=True, key="up_chat_fixed")
    
    if uploaded_files:
        _, log_debug = prepara_input_gemini(uploaded_files)
        with st.expander("✅ Log Lettura File", expanded=False):
            st.text(log_debug)
        
    # Inizializza messaggio di benvenuto se vuoto
    if not st.session_state.messages:
        welcome = "Ho letto il fascicolo. I dati del calcolatore sono in memoria. Come procediamo?"
        st.session_state.messages.append({"role": "assistant", "content": welcome})
    
    # --- 3. RENDERING STORICO (IL PUNTO CRITICO) ---
    # Qui sta il trucco: applichiamo la pulizia OGNI VOLTA che leggiamo dalla memoria.
    # Anche se in memoria c'è una tabella, qui viene distrutta prima di essere mostrata.
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                # PULIZIA IN TEMPO REALE SULLO STORICO
                contenuto_sicuro = rimuovi_tabelle_forzato(msg["content"])
                st.markdown(contenuto_sicuro)
            else:
                st.markdown(msg["content"])
            
    # --- 4. NUOVA RICHIESTA ---
    if prompt := st.chat_input("Es: Analizza i rischi..."):
        # Mostra subito input utente
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.contesto_chat_text += f"\nUtente: {prompt}"
        with st.chat_message("user"): 
            st.markdown(prompt)
        
        # Generazione risposta AI
        with st.chat_message("assistant"):
            with st.spinner("Analisi in corso..."):
                parts_dossier, _ = prepara_input_gemini(uploaded_files) if uploaded_files else ([], "")
                
                # Ottieni risposta grezza (che potrebbe contenere tabelle)
                risposta_grezza = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts_dossier, active_model, postura)
                
                # --- PASSAGGIO FONDAMENTALE ---
                # 1. Pulisci la risposta ORA per mostrarla
                risposta_pulita = rimuovi_tabelle_forzato(risposta_grezza)
                st.markdown(risposta_pulita)
                
                # 2. Salva in memoria la versione PULITA (così non si ripresenta il problema al refresh)
                #    NOTA: Salviamo 'risposta_pulita', NON 'risposta_grezza'
                st.session_state.messages.append({"role": "assistant", "content": risposta_pulita})
                st.session_state.contesto_chat_text += f"\nGemini: {risposta_pulita}"
# ==============================================================================
# TAB 3: GENERAZIONE ATTI (PRO MODE)
# ==============================================================================
with tab3:
    st.header("Redazione Documenti Ufficiali")
    
    if not uploaded_files and st.session_state.dati_calcolatore == "Nessun calcolo tecnico effettuato.":
        st.warning("⚠️ Manca il contesto! Carica file nel Tab 2 o esegui il calcolo nel Tab 1.")
    
    st.subheader("Seleziona Output")
    
    col_a, col_b = st.columns(2)
    with col_a:
        doc_sintesi = st.checkbox("Sintesi Esecutiva", help="Riassunto strutturato")
        doc_matrice = st.checkbox("Matrice Rischi", help="Genera Tabella Scenari")
        doc_attacco = st.checkbox("Lista Vizi Tecnici", help="Usa i dati del calcolatore")
    with col_b:
        doc_transazione = st.checkbox("Bozza Transattiva", help="Proposta saldo e stralcio")
        doc_replica = st.checkbox("Nota di Replica", help="Risposta alla controparte")
    
    fmt = st.radio("Formato Output:", ["Word (.docx)", "PDF (.pdf)"], horizontal=True)
    
    if st.button("🚀 Genera Documenti Selezionati", type="primary"):
        input_payload = input_parts_chat if uploaded_files else []
        
        tasks = []
        if doc_sintesi: tasks.append(("Sintesi_Esecutiva", "Redigi una Sintesi Esecutiva professionale."))
        if doc_matrice: tasks.append(("Matrice_Rischi", "Crea una Matrice dei Rischi in tabella (Scenario | Probabilità | Impatto)."))
        if doc_attacco: tasks.append(("Vizi_Tecnici", "Elenca i Vizi Tecnici usando i dati del calcolatore per contestare la CTU."))
        if doc_transazione: tasks.append(("Proposta_Transattiva", "Redigi una Proposta Transattiva formale."))
        if doc_replica: tasks.append(("Nota_Replica", "Scrivi una Nota di Replica tecnica e legale."))
        
        st.session_state.generated_docs = {}
        bar = st.progress(0)
        
        for i, (fname, prompt_task) in enumerate(tasks):
            with st.status(f"Generazione {fname} in corso...", expanded=False):
                # Qui usiamo is_chat_mode=False per permettere le TABELLE nel DOCX
                raw_text = interroga_gemini(
                    prompt_task, 
                    st.session_state.contesto_chat_text, 
                    input_payload, 
                    active_model, 
                    st.session_state.livello_aggressivita,
                    is_chat_mode=False 
                )
                
                if "Word" in fmt:
                    data = crea_word(raw_text, fname.replace("_", " "))
                    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ext = "docx"
                else:
                    data = crea_pdf_safe(raw_text, fname.replace("_", " "))
                    mime = "application/pdf"
                    ext = "pdf"
                
                st.session_state.generated_docs[fname] = {"data": data, "ext": ext, "mime": mime}
            bar.progress((i + 1) / len(tasks))
            
    # Download Area
    if st.session_state.generated_docs:
        st.divider()
        st.success("Documenti pronti per il download:")
        cols = st.columns(len(st.session_state.generated_docs))
        for idx, (key, val) in enumerate(st.session_state.generated_docs.items()):
            cols[idx % 4].download_button(
                f"📥 {key}.{val['ext']}",
                data=val['data'],
                file_name=f"{key}.{val['ext']}",
                mime=val['mime']
            )

