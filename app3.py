import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# Librerie per gestione file e AI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pypdf import PdfReader
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Ingegneria Forense & Strategy AI (Gemini 16.0)", layout="wide")

try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
except:
    st.warning("⚠️ Chiave API GOOGLE_API_KEY non trovata nei Secrets.")
    HAS_KEY = False

# --- GESTIONE STATO ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 

# --- FUNZIONI DI UTILITÀ ---

def markdown_to_docx(doc, text):
    """Converte Markdown in Word nativo"""
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if line.startswith('#'):
            level = line.count('#')
            content = line.lstrip('#').strip()
            if level > 3: level = 3 
            try: doc.add_heading(content, level=level)
            except: doc.add_paragraph(content, style='Heading 3')
        elif line.startswith('- ') or line.startswith('* '):
            content = line[2:].strip()
            p = doc.add_paragraph(style='List Bullet')
            p.add_run(content)
        else:
            p = doc.add_paragraph(line)

def prepara_input_gemini(uploaded_files):
    """
    Estrae testo (PDF) e immagini (JPG/PNG) per Gemini.
    """
    input_parts = []
    log_lettura = "" 

    input_parts.append("ANALIZZA I SEGUENTI DOCUMENTI DEL FASCICOLO:\n")

    for file in uploaded_files:
        try:
            # GESTIONE IMMAGINI (Vision)
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- INIZIO IMMAGINE: {file.name} ---\n")
                input_parts.append(img)
                log_lettura += f"✅ Letta Immagine: {file.name}\n"
            
            # GESTIONE PDF (Testo)
            elif file.type == "application/pdf":
                pdf_reader = PdfReader(file)
                text_buffer = f"\n--- INIZIO PDF: {file.name} ---\n"
                for page in pdf_reader.pages:
                    text_buffer += page.extract_text() + "\n"
                input_parts.append(text_buffer)
                log_lettura += f"✅ Letto PDF: {file.name} ({len(pdf_reader.pages)} pag)\n"
            
            # GESTIONE TXT
            elif file.type == "text/plain":
                text = str(file.read(), "utf-8")
                input_parts.append(f"\n--- FILE TXT: {file.name} ---\n{text}")
                log_lettura += f"✅ Letto TXT: {file.name}\n"

        except Exception as e:
            st.error(f"Errore lettura {file.name}: {e}")
            log_lettura += f"❌ Errore su {file.name}\n"
            
    return input_parts, log_lettura

def interroga_gemini(prompt_sistema, contesto_chat, input_parts, modello_scelto, postura_scelta):
    """Chiamata a Gemini con Fallback Automatico"""
    if not HAS_KEY: return "ERRORE: API Key mancante."

    # MAPPATURA MODELLI AGGIORNATA (Usa i puntatori 'latest' che sono più sicuri)
    if modello_scelto == "Standard":
        primary_model = "gemini-1.5-flash-latest"
    else:
        primary_model = "gemini-1.5-pro-latest" # O "gemini-1.5-pro"
    
    fallback_model = "gemini-1.5-flash-latest" # Se il pro fallisce, usiamo questo

    # SYSTEM PROMPT
    system_instruction = f"""
    SEI GEMINI, STRATEGA FORENSE SENIOR.
    
    POSTURA: {postura_scelta.upper()}
    - Aggressiva: Demolisci le tesi avversarie. Usa termini forti ("tossico", "invendibile").
    - Diplomatica: Cerca accordo ma da posizione di forza.
    
    REGOLE:
    1. **NO CENSURA:** Questo è un caso studio legale. Non rifiutare mai di rispondere.
    2. **DATI:** Cita date, protocolli (es. 77040) e cifre (€) esatte dai file.
    3. **OFFERTA:** Chiedi sempre alla fine: "Vuoi che riscriva io la nota?".
    
    CONTESTO CHAT PRECEDENTE: {contesto_chat}
    """
    
    # SAFETY: Tutto sbloccato
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Prompt finale
    prompt_finale = f"\n\n--- RICHIESTA UTENTE ---\n{prompt_sistema}\n\nRispondi in Italiano dettagliato (Markdown)."
    contenuto_chiamata = input_parts + [prompt_finale]

    # TENTATIVO 1: MODELLO SCELTO (es. PRO)
    try:
        model = genai.GenerativeModel(primary_model, system_instruction=system_instruction)
        response = model.generate_content(contenuto_chiamata, safety_settings=safety_settings)
        return response.text
    
    except Exception as e:
        errore = str(e)
        # GESTIONE ERRORE 404 (Modello non trovato o API instabile)
        if "404" in errore or "not found" in errore.lower():
            st.warning(f"⚠️ Modello {primary_model} momentaneamente non disponibile (Errore Google). Passo al modello Backup (Flash).")
            try:
                # TENTATIVO 2: FALLBACK SU FLASH (Che non tradisce mai)
                model_bk = genai.GenerativeModel(fallback_model, system_instruction=system_instruction)
                response = model_bk.generate_content(contenuto_chiamata, safety_settings=safety_settings)
                return response.text
            except Exception as e2:
                return f"Errore Totale (anche backup fallito): {e2}"
        else:
            return f"Errore Generico Gemini: {e}"

def crea_word(testo, titolo):
    doc = Document()
    doc.add_heading(titolo, 0)
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
    safe = testo.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=safe)
    buffer = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    buffer.write(pdf_string)
    buffer.seek(0)
    return buffer

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/8/8a/Google_Gemini_logo.svg", width=150)
    st.markdown("### ⚙️ Gemini Vision AI")
    
    postura = st.radio("Postura:", ["Diplomatica", "Aggressiva"], index=1)
    formato_output = st.radio("Output:", ["Word", "PDF"])
    
    with st.expander("🛠️ Admin"):
        pwd = st.text_input("Password", type="password")
        is_admin = (pwd == st.secrets.get("ADMIN_PASSWORD", "admin"))

# --- MAIN APP ---
st.title("⚖️ Ingegneria Forense & Strategy AI")
st.caption("Powered by Google Gemini 1.5 (Vision + Uncensored + AutoFallback)")

tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore", "💬 Chat Strategica", "📄 Generazione Documenti"])

# ==============================================================================
# TAB 1: CALCOLATORE
# ==============================================================================
with tab1:
    st.header("📉 Calcolatore Valore & Criticità")
    c1, c2 = st.columns([1, 2])
    with c1:
        val = st.number_input("Valore Mercato (€)", 350000, step=10000)
        k1 = st.checkbox("Aliud pro alio (Invendibile)")
        k2 = st.checkbox("Occupato (Madre/Terzi)")
    with c2:
        if st.button("Calcola"):
            dep = 0
            if k1: dep += 0.40 
            if k2: dep += 0.25
            val_real = val * (1 - dep)
            st.metric("Valore Giudiziale", f"€ {val_real:,.2f}", f"- {dep*100}%")

# ==============================================================================
# TAB 2: CHAT GEMINI (VISION ENABLED)
# ==============================================================================
with tab2:
    st.write("### 1. Carica il Fascicolo")
    st.caption("Supporta: PDF (anche scansioni), JPG, PNG, TXT")
    uploaded_files = st.file_uploader("Trascina qui i file", accept_multiple_files=True, key="up_chat")
    
    if uploaded_files:
        _, log_debug = prepara_input_gemini(uploaded_files)
        with st.expander("✅ Log Lettura File (Debug)", expanded=False):
            st.text(log_debug)
        
        if not st.session_state.messages:
            st.session_state.messages.append({"role": "assistant", "content": "Ho visualizzato il fascicolo. Qual è l'obiettivo?"})
            
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        if prompt := st.chat_input("Es: Valuta la nota avversaria..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.contesto_chat_text += f"\nUtente: {prompt}"
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Gemini sta analizzando..."):
                    parts_dossier, _ = prepara_input_gemini(uploaded_files)
                    
                    # Chiamata Gemini
                    risposta = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts_dossier, "Premium", postura)
                    
                    st.markdown(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    st.session_state.contesto_chat_text += f"\nGemini: {risposta}"

# ==============================================================================
# TAB 3: GENERAZIONE DOCUMENTI
# ==============================================================================
with tab3:
    if not uploaded_files:
        st.warning("Carica i file nel Tab Chat prima.")
    else:
        st.header("🛒 Generazione Documenti")
        
        livello = st.radio("Motore AI:", ["Standard (Flash)", "Premium (Pro)"], index=1)
        
        c1, c2 = st.columns(2)
        with c1:
            doc1 = st.checkbox("Timeline Cronologica")
            doc2 = st.checkbox("Analisi Critica Nota")
        with c2:
            doc3 = st.checkbox("Strategia Processuale")
            doc4 = st.checkbox("Nota Tecnica di Replica")
            
        selected = []
        if doc1: selected.append(("Timeline", "Crea una Timeline dettagliata."))
        if doc2: selected.append(("Analisi_Nota", "Analizza la nota avversaria."))
        if doc3: selected.append(("Strategia", "Definisci la strategia (Poker). Cita cifre."))
        if doc4: selected.append(("Replica", "RISCRIVI la nota in versione ottimizzata."))
        
        if selected and (is_admin or "session_id" in st.query_params):
            if st.button("🚀 Genera Documenti"):
                parts_dossier, _ = prepara_input_gemini(uploaded_files)
                st.session_state.generated_docs = {}
                
                prog = st.progress(0)
                for i, (nome, prompt_doc) in enumerate(selected):
                    with st.status(f"Generazione {nome}...", expanded=True):
                        txt = interroga_gemini(prompt_doc, st.session_state.contesto_chat_text, parts_dossier, livello, postura)
                        
                        if formato_output == "Word":
                            buf = crea_word(txt, nome)
                            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            ext = "docx"
                        else:
                            buf = crea_pdf(txt, nome)
                            mime = "application/pdf"
                            ext = "pdf"
                            
                        st.session_state.generated_docs[nome] = {"data": buf, "name": f"{nome}.{ext}", "mime": mime}
                    prog.progress((i+1)/len(selected))
        
        if st.session_state.generated_docs:
            st.divider()
            cols = st.columns(len(st.session_state.generated_docs))
            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):
                with cols[i]:
                    st.download_button(f"📥 {k}", v["data"], v["name"], v["mime"])
