import streamlit as st
from datetime import datetime
from io import BytesIO
import base64
import time
import re

# Librerie per gestione file e AI
import openai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Ingegneria Forense & Strategy AI", layout="wide")

# Recupera la chiave API dai secrets
try:
    openai.api_key = st.secrets["OPENAI_API_KEY"]
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    st.warning("⚠️ Chiave API OpenAI non trovata. Le funzioni AI non andranno.")
    client = None

# --- GESTIONE STATO (SESSION STATE) ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} # Memoria per i file generati

# --- FUNZIONI DI UTILITÀ AVANZATE ---

def markdown_to_docx(doc, text):
    """
    Converte il testo Markdown (Grassetto, Titoli, Liste) in formattazione Word nativa.
    """
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Gestione Titoli (### o ## o #)
        if line.startswith('#'):
            level = line.count('#')
            content = line.lstrip('#').strip()
            # Word supporta heading level 1-9
            if level > 3: level = 3 
            doc.add_heading(content, level=level)
        
        # Gestione Elenchi Puntati (-)
        elif line.startswith('- ') or line.startswith('* '):
            content = line[2:].strip()
            p = doc.add_paragraph(style='List Bullet')
            _format_paragraph_content(p, content)
            
        # Gestione Elenchi Numerati (1.)
        elif re.match(r'^\d+\.', line):
            content = re.sub(r'^\d+\.\s*', '', line).strip()
            p = doc.add_paragraph(style='List Number')
            _format_paragraph_content(p, content)
            
        # Paragrafo Normale
        else:
            p = doc.add_paragraph()
            _format_paragraph_content(p, line)

def _format_paragraph_content(paragraph, text):
    """Gestisce il grassetto (**text**) all'interno di un paragrafo"""
    parts = re.split(r'(\*\*.*?\*\*)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            paragraph.add_run(part)

def prepara_input_multimodale(uploaded_files):
    """Prepara il payload misto (Testo + Immagini)"""
    contenuto_messaggio = []
    contenuto_messaggio.append({"type": "text", "text": "Analizza i seguenti documenti:"})

    for file in uploaded_files:
        try:
            if file.type in ["image/jpeg", "image/png", "image/jpg"]:
                file.seek(0)
                base64_image = base64.b64encode(file.read()).decode('utf-8')
                contenuto_messaggio.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{file.type};base64,{base64_image}", "detail": "high"}
                })
            elif file.type == "application/pdf":
                pdf_reader = PdfReader(file)
                text_buffer = f"\n--- PDF: {file.name} ---\n"
                for page in pdf_reader.pages:
                    estratto = page.extract_text()
                    if estratto: text_buffer += estratto + "\n"
                contenuto_messaggio.append({"type": "text", "text": text_buffer})
            elif file.type == "text/plain":
                text_content = str(file.read(), "utf-8")
                contenuto_messaggio.append({"type": "text", "text": f"\n--- TXT: {file.name} ---\n{text_content}"})
        except Exception as e:
            st.error(f"Errore lettura file {file.name}: {e}")
    return contenuto_messaggio

def interroga_llm_multimodale(prompt_sistema, contesto_chat, payload_files, modello_scelto):
    """Chiamata a OpenAI con RETRY LOGIC per errore 429"""
    if not client: return "ERRORE: API Key mancante."
    
    messaggio_utente = list(payload_files)
    istruzioni = f"\n\nRUOLO: {prompt_sistema}\nCONTESTO CHAT: {contesto_chat}\nGenera il documento richiesto usando formattazione Markdown (usa **grassetto**, # Titoli, - Elenchi)."
    messaggio_utente.append({"type": "text", "text": istruzioni})

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=modello_scelto,
                messages=[{"role": "user", "content": messaggio_utente}],
                temperature=0.4, 
                max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate limit" in error_msg.lower():
                wait_time = 20 * (attempt + 1) # Backoff: 20s, 40s, 60s
                st.warning(f"⚠️ Traffico elevato (Errore 429). Riprovo tra {wait_time} secondi... (Tentativo {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                return f"Errore Irreversibile AI ({modello_scelto}): {e}"
    
    return "Errore: Impossibile completare la richiesta dopo 3 tentativi."

def crea_word_formattato(testo, titolo):
    doc = Document()
    # Titolo Principale
    main_heading = doc.add_heading(titolo, 0)
    main_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.add_paragraph(f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    doc.add_paragraph("---")
    
    # Usa il parser Markdown
    markdown_to_docx(doc, testo)
    
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crea_pdf(testo, titolo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=titolo, ln=1, align='C')
    pdf.ln(10)
    # Pulizia caratteri base per PDF
    testo_safe = testo.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=testo_safe)
    buffer = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    buffer.write(pdf_string)
    buffer.seek(0)
    return buffer

# --- SIDEBAR & ADMIN ---
with st.sidebar:
    st.markdown("### ⚙️ Configurazione")
    formato_output = st.radio("Formato Output:", ["Word (.docx)", "PDF (.pdf)"])
    
    st.divider()
    st.markdown("### 📞 Contatti")
    st.markdown("""
    <div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px;'>
        <p>📱 <a href='https://wa.me/393758269561'>WhatsApp</a></p>
        <p>📅 <a href='https://calendar.app.google/y4QwPGmH9V7yGpny5' target='_blank'><strong>Prenota Consulenza</strong></a></p>
        <p>✉️ <a href='mailto:info@periziedilizie.it'>info@periziedilizie.it</a></p>
    </div>""", unsafe_allow_html=True)
    
    # ADMIN PANEL
    with st.expander("🛠️ Admin / Debug"):
        pwd = st.text_input("Password", type="password")
        is_admin = (pwd == st.secrets.get("ADMIN_PASSWORD", "admin"))
        if is_admin:
            st.success("Admin Logged In")
            override_model = st.selectbox("Forza Modello", ["Nessuno", "gpt-4o", "gpt-4o-mini"])
        else:
            override_model = "Nessuno"

# --- MAIN APP ---
st.title("⚖️ Ingegneria Forense & Strategy AI")

tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore", "💬 Analisi Strategica (Chat)", "📄 Generazione Documenti"])

# ==============================================================================
# TAB 1: CALCOLATORE (Invariato)
# ==============================================================================
with tab1:
    st.header("📉 Calcolatore Valore & Criticità")
    col1, col2 = st.columns([1, 2])
    with col1:
        valore_mercato = st.number_input("Valore Mercato (€)", min_value=0, value=350000, step=10000)
        c1 = st.checkbox("Assenza Agibilità")
        c2 = st.checkbox("Condono non perfezionato")
        c3 = st.checkbox("Difformità Catastali")
        btn_calcola = st.button("Calcola Deprezzamento", type="primary")

    with col2:
        if btn_calcola:
            deprezzamento = 0
            rischi = []
            if c1: deprezzamento += 0.15 
            if c2: deprezzamento += 0.20
            if c3: deprezzamento += 0.05
            valore_reale = valore_mercato * (1 - deprezzamento)
            st.success(f"### Valore Giudiziale Stimato: € {valore_reale:,.2f}")
            st.metric("Deprezzamento", f"- {deprezzamento*100:.0f}%", f"- € {(valore_mercato - valore_reale):,.2f}")

# ==============================================================================
# TAB 2: CHATBOT STEP-BY-STEP (V7 Logic)
# ==============================================================================
with tab2:
    st.write("### 1. Carica il Fascicolo")
    uploaded_files = st.file_uploader("Trascina file (PDF, IMG, TXT)", accept_multiple_files=True, type=["pdf", "txt", "jpg", "png", "jpeg"], key="uploader")
    
    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} file caricati.")
        st.divider()
        st.subheader("🤖 Consulente Strategico")
        
        if not st.session_state.messages:
            st.session_state.messages.append({"role": "assistant", "content": "Ho ricevuto i file. Qual è l'obiettivo? (Es. Transare, Attaccare CTU...)"})

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Scrivi qui..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.contesto_chat_text += f"\nUtente: {prompt}"
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Riflessione..."):
                    payload = prepara_input_multimodale(uploaded_files)
                    
                    # PROMPT "INTERVISTATORE"
                    prompt_intervistatore = """
                    Sei un Ingegnere Forense Senior.
                    REGOLE:
                    1. NON dare subito la strategia completa.
                    2. Fai UNA domanda alla volta per chiarire budget, obiettivi o dettagli mancanti.
                    3. Solo se l'utente dice "procedi" o se hai tutto chiaro, dai la strategia.
                    Usa il modello veloce per questa chat.
                    """
                    
                    modello_chat = "gpt-4o-mini"
                    if override_model != "Nessuno": modello_chat = override_model
                        
                    risposta = interroga_llm_multimodale(prompt_intervistatore, st.session_state.contesto_chat_text, payload, modello_chat)
                    st.markdown(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    st.session_state.contesto_chat_text += f"\nAI: {risposta}"

# ==============================================================================
# TAB 3: GENERAZIONE DOCUMENTI (Bug Fix & Formatting)
# ==============================================================================
with tab3:
    if not uploaded_files:
        st.warning("⚠️ Carica prima i file nel Tab 'Analisi Strategica'.")
    else:
        st.header("🛒 Generazione Prodotti")
        
        # Selezione Livello
        livello_analisi = st.radio(
            "Livello Analisi:",
            ["STANDARD (Veloce/Economica)", "PREMIUM (Strategica/Approfondita)"],
            index=1
        )
        
        # Configurazione Modello
        if "STANDARD" in livello_analisi:
            modello_doc = "gpt-4o-mini"
            prezzi = {"timeline": 29, "sintesi": 29, "attacco": 89, "strategia": 149}
        else:
            modello_doc = "gpt-4o"
            prezzi = {"timeline": 90, "sintesi": 90, "attacco": 190, "strategia": 390}

        if override_model != "Nessuno":
            modello_doc = override_model
            st.warning(f"🔧 DEBUG MODE: Forzato modello {modello_doc}")

        st.caption(f"Motore AI: {modello_doc}")
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            p1 = st.checkbox(f"Timeline (€ {prezzi['timeline']})")
            p2 = st.checkbox(f"Sintesi (€ {prezzi['sintesi']})")
        with c2:
            p3 = st.checkbox(f"Punti Attacco (€ {prezzi['attacco']})")
            p4 = st.checkbox(f"Strategia (€ {prezzi['strategia']})")
            
        selected = []
        if p1: selected.append("timeline")
        if p2: selected.append("sintesi")
        if p3: selected.append("attacco")
        if p4: selected.append("strategia")
        
        if selected:
            # Check permessi
            can_dl = is_admin or "session_id" in st.query_params
            if is_admin: st.success("🔓 Admin Mode")
            elif can_dl: st.success("✅ Pagato")
            else: st.info("Demo Mode: password Admin richiesta.")
            
            # --- TASTO GENERAZIONE (Crea e Salva in Session State) ---
            if can_dl:
                if st.button("🚀 Genera Documenti"):
                    payload = prepara_input_multimodale(uploaded_files)
                    
                    prompts = {
                        "timeline": "Crea Timeline Cronologica rigorosa. Data | Evento | Rif. Doc.",
                        "sintesi": "Redigi Sintesi Tecnica formale.",
                        "attacco": "Agisci come CTP aggressivo. Trova errori CTU/Controparte (Norme UNI/Cassazione).",
                        "strategia": "Elabora Strategia (Ottimistica/Pessimistica) e Next Best Action."
                    }
                    
                    # Reset o Init del dizionario dei file generati
                    st.session_state.generated_docs = {} 
                    
                    progress_bar = st.progress(0)
                    for idx, item in enumerate(selected):
                        with st.status(f"Generazione {item.upper()} ({modello_doc})...", expanded=True) as s:
                            # Chiamata AI con Retry Logic
                            txt = interroga_llm_multimodale(prompts[item], st.session_state.contesto_chat_text, payload, modello_doc)
                            
                            # Creazione File
                            ext = "docx" if formato_output == "Word (.docx)" else "pdf"
                            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else "application/pdf"
                            
                            if ext == "docx":
                                buf = crea_word_formattato(txt, item.upper()) # Nuova funzione formattata
                            else:
                                buf = crea_pdf
