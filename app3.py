import streamlit as st
from datetime import datetime
import time
from io import BytesIO
import base64

# Librerie per gestione file e AI
import openai
from pypdf import PdfReader
from docx import Document
from fpdf import FPDF

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Ingegneria Forense & Strategy AI", layout="wide")

# Recupera la chiave API dai secrets
# Assicurati di avere in .streamlit/secrets.toml:
# OPENAI_API_KEY = "sk-..."
# ADMIN_PASSWORD = "tua_password"
try:
    openai.api_key = st.secrets["OPENAI_API_KEY"]
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    st.warning("⚠️ Chiave API OpenAI non trovata nei Secrets. L'app non potrà generare testi reali.")
    client = None

# --- FUNZIONI DI UTILITÀ: LETTURA E GENERAZIONE ---

def prepara_input_multimodale(uploaded_files):
    """
    Prepara il payload misto (Testo + Immagini) per GPT-4o Vision.
    Legge PDF (come testo) e Immagini (come base64).
    """
    contenuto_messaggio = []
    
    # Testo introduttivo per l'AI
    contenuto_messaggio.append({
        "type": "text", 
        "text": "Ecco i documenti del fascicolo (testi estratti e scansioni). Analizzali con attenzione tecnica:"
    })

    for file in uploaded_files:
        try:
            # CASO A: Immagini (JPG, PNG) -> Usa GPT Vision
            if file.type in ["image/jpeg", "image/png", "image/jpg"]:
                # Reset pointer e lettura
                file.seek(0)
                base64_image = base64.b64encode(file.read()).decode('utf-8')
                contenuto_messaggio.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{file.type};base64,{base64_image}",
                        "detail": "high" # 'low' costa meno, 'high' legge meglio le scritte piccole
                    }
                })
            
            # CASO B: PDF -> Estrai testo
            elif file.type == "application/pdf":
                pdf_reader = PdfReader(file)
                text_buffer = f"\n--- INIZIO FILE PDF: {file.name} ---\n"
                for page in pdf_reader.pages:
                    estratto = page.extract_text()
                    if estratto:
                        text_buffer += estratto + "\n"
                
                # Aggiungiamo il testo del PDF
                contenuto_messaggio.append({
                    "type": "text", 
                    "text": text_buffer
                })
                
            # CASO C: TXT
            elif file.type == "text/plain":
                text_content = str(file.read(), "utf-8")
                contenuto_messaggio.append({
                    "type": "text", 
                    "text": f"\n--- FILE TXT: {file.name} ---\n{text_content}"
                })
                
        except Exception as e:
            st.error(f"Errore lettura file {file.name}: {e}")
            
    return contenuto_messaggio

def interroga_llm_multimodale(prompt_sistema, contesto_chat, payload_files):
    """
    Chiamata a GPT-4o.
    Combina: Payload File + Prompt Sistema + Chat History
    """
    if not client:
        return "ERRORE: API Key mancante."

    # Clona il payload per non modificare l'originale
    messaggio_utente = list(payload_files)

    # Aggiungi le istruzioni specifiche in fondo
    istruzioni_finali = f"""
    \n\n--- ISTRUZIONI PER L'AI ---
    RUOLO: {prompt_sistema}
    
    CONTESTO STRATEGICO (DALLA CHAT CON L'UTENTE):
    {contesto_chat}
    
    COMPITO: Genera il documento richiesto basandoti SUI FILE forniti e sulla STRATEGIA definita in chat.
    """
    
    messaggio_utente.append({
        "type": "text",
        "text": istruzioni_finali
    })

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Fondamentale per vedere le immagini
            messages=[
                {"role": "user", "content": messaggio_utente}
            ],
            temperature=0.4, # Abbastanza preciso
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore durante la generazione AI: {e}"

def crea_word(testo, titolo):
    """Genera file .docx"""
    doc = Document()
    doc.add_heading(titolo, 0)
    doc.add_paragraph(f"Generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    doc.add_paragraph(testo)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crea_pdf(testo, titolo):
    """Genera file .pdf"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=titolo, ln=1, align='C')
    pdf.ln(10)
    # Gestione encoding basic
    testo_safe = testo.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=testo_safe)
    buffer = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    buffer.write(pdf_string)
    buffer.seek(0)
    return buffer

# --- GESTIONE STATO CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "contesto_chat_text" not in st.session_state:
    st.session_state.contesto_chat_text = ""

# --- UI SIDEBAR ---
with st.sidebar:
    st.markdown("### ⚙️ Opzioni Produzione")
    formato_output = st.radio("Formato Documenti:", ["Word (.docx)", "PDF (.pdf)"])
    
    st.divider()
    st.markdown("### 📞 Contatti")
    st.markdown("""
    <div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px;'>
        <p>📱 <a href='https://wa.me/393758269561'>WhatsApp</a></p>
        <p>✉️ <a href='mailto:info@periziedilizie.it'>info@periziedilizie.it</a></p>
    </div>""", unsafe_allow_html=True)
    
    # BACKDOOR ADMIN
    with st.expander("🛠️ Admin Area"):
        pwd = st.text_input("Password", type="password")
        # Usa i secrets per la password reale
        admin_secret = st.secrets.get("ADMIN_PASSWORD", "admin")
        is_admin = (pwd == admin_secret)

# --- MAIN APP ---
st.title("⚖️ Ingegneria Forense & Strategy AI")

tab1, tab2 = st.tabs(["💬 1. Caricamento & Strategia", "📄 2. Generazione Documenti"])

# ==============================================================================
# TAB 1: CHATBOT INTERVISTATORE
# ==============================================================================
with tab1:
    st.write("### Carica il fascicolo")
    st.info("L'AI legge PDF, Testi e Immagini (Scansioni, Foto, Planimetrie).")
    
    uploaded_files = st.file_uploader(
        "Trascina qui i file", 
        accept_multiple_files=True, 
        type=["pdf", "txt", "jpg", "png", "jpeg"]
    )
    
    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} file pronti per l'analisi.")
        st.divider()
        
        st.subheader("🤖 Assistente Strategico")
        st.markdown("Chatta con l'AI per definire la linea difensiva. L'AI ha 'letto' i tuoi file.")

        # Messaggio di benvenuto se la chat è vuota
        if not st.session_state.messages:
            msg_start = "Ho analizzato preliminarmente i documenti. Qual è l'obiettivo principale? (Es. Transare al ribasso, Attaccare la CTU, Invalidare tutto...)"
            st.session_state.messages.append({"role": "assistant", "content": msg_start})

        # Visualizza Chat History
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Input Utente
        if prompt_utente := st.chat_input("Es. Vogliamo dimostrare che l'immobile non è abitabile..."):
            
            # 1. Salva messaggio utente
            st.session_state.messages.append({"role": "user", "content": prompt_utente})
            st.session_state.contesto_chat_text += f"\nUtente: {prompt_utente}"
            with st.chat_message("user"):
                st.markdown(prompt_utente)
            
            # 2. Risposta AI
            with st.chat_message("assistant"):
                with st.spinner("L'AI sta analizzando i file e la tua richiesta..."):
                    
                    # Prepariamo i file per la chat (così l'AI sa di cosa parli)
                    payload_chat = prepara_input_multimodale(uploaded_files)
                    
                    prompt_chat_system = """
                    Sei un Perito Forense Senior. 
                    Il tuo compito ORA è intervistare l'avvocato.
                    NON scrivere ancora la perizia completa.
                    Fai domande brevi e strategiche basate sui documenti che vedi e sulla risposta dell'utente.
                    Lo scopo è raccogliere informazioni per redigere poi i documenti finali.
                    """
                    
                    risposta_ai = interroga_llm_multimodale(prompt_chat_system, st.session_state.contesto_chat_text, payload_chat)
                    
                    st.markdown(risposta_ai)
                    st.session_state.messages.append({"role": "assistant", "content": risposta_ai})
                    st.session_state.contesto_chat_text += f"\nAI: {risposta_ai}"

# ==============================================================================
# TAB 2: GENERAZIONE DOCUMENTI
# ==============================================================================
with tab2:
    if not uploaded_files:
        st.warning("⚠️ Torna al Tab 1 e carica prima i file.")
    else:
        st.header("🛒 Generazione Prodotti")
        st.write("L'AI utilizzerà i documenti caricati E la strategia discussa in chat.")

        col1, col2 = st.columns(2)
        with col1:
            p1 = st.checkbox("Timeline Cronologica (€ 90)")
            p2 = st.checkbox("Sintesi del Fatto (€ 90)")
        with col2:
            p3 = st.checkbox("Punti di Attacco Tecnici (€ 190)")
            p4 = st.checkbox("Strategia Processuale (€ 390)")
            
        selected_items = []
        if p1: selected_items.append("timeline")
        if p2: selected_items.append("sintesi")
        if p3: selected_items.append("attacco")
        if p4: selected_items.append("strategia")
        
        prezzi = {"timeline": 90, "sintesi": 90, "attacco": 190, "strategia": 390}
        totale = sum([prezzi[k] for k in selected_items])
        
        if selected_items:
            st.divider()
            st.subheader(f"Totale: € {totale}")
            
            # Verifica permessi (Admin o Pagamento)
            can_download = False
            if is_admin:
                st.success("🔓 Modalità Admin Attiva")
                can_download = True
            elif "session_id" in st.query_params:
                st.success("✅ Pagamento Confermato")
                can_download = True
            else:
                st.info("Demo Mode: Inserisci la password Admin nella barra laterale per sbloccare.")
            
            if can_download:
                if st.button("🚀 Genera Documenti"):
                    
                    # Prepariamo i file una volta sola
                    payload_doc = prepara_input_multimodale(uploaded_files)
                    
                    for item in selected_items:
                        with st.status(f"Generazione {item.upper()} in corso...", expanded=True) as status:
                            
                            # PROMPT SYSTEM SPECIFICI
                            prompts = {
                                "timeline": "Crea una TIMELINE CRONOLOGICA rigorosa. Data | Evento | Rif. Doc. Evidenzia termini prescrizione.",
                                "sintesi": "Redigi una SINTESI TECNICA dei fatti rilevanti per la causa. Linguaggio formale e oggettivo.",
                                "attacco": "Agisci come CTP aggressivo. Trova vizi, difformità, errori nella controparte/CTU basandoti sui file (norme UNI/ISO/Cassazione).",
                                "strategia": "Elabora 3 Scenari (Ottimistico, Realistico, Pessimistico) e consiglia la Next Best Action legale/tecnica."
                            }
                            
                            # Generazione AI
                            testo_out = interroga_llm_multimodale(prompts[item], st.session_state.contesto_chat_text, payload_doc)
                            
                            # Creazione File
                            status.write("Formattazione file...")
                            if formato_output == "Word (.docx)":
                                buffer = crea_word(testo_out, f"Report: {item.upper()}")
                                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                ext = "docx"
                            else:
                                buffer = crea_pdf(testo_out, f"Report: {item.upper()}")
                                mime = "application/pdf"
                                ext = "pdf"
                                
                            # Download
                            st.download_button(
                                label=f"📥 Scarica {item.upper()}",
                                data=buffer,
                                file_name=f"Cavalaglio_{item}.{ext}",
                                mime=mime,
                                key=f"dl_{item}"
                            )
                            status.update(label=f"✅ {item.upper()} Completato!", state="complete")
