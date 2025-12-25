import streamlit as st
from datetime import datetime
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
try:
    openai.api_key = st.secrets["OPENAI_API_KEY"]
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    st.warning("⚠️ Chiave API OpenAI non trovata. Le funzioni AI non andranno.")
    client = None

# --- FUNZIONI DI UTILITÀ ---

def prepara_input_multimodale(uploaded_files):
    """Prepara il payload misto (Testo + Immagini)"""
    contenuto_messaggio = []
    contenuto_messaggio.append({"type": "text", "text": "Analizza i seguenti documenti (testi e immagini):"})

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
            st.error(f"Errore file {file.name}: {e}")
    return contenuto_messaggio

def interroga_llm_multimodale(prompt_sistema, contesto_chat, payload_files, modello_scelto):
    """Chiamata a OpenAI con modello dinamico"""
    if not client: return "ERRORE: API Key mancante."
    
    messaggio_utente = list(payload_files)
    istruzioni = f"\n\nRUOLO: {prompt_sistema}\nCONTESTO CHAT: {contesto_chat}\nGenera il documento richiesto."
    messaggio_utente.append({"type": "text", "text": istruzioni})

    try:
        response = client.chat.completions.create(
            model=modello_scelto, # Qui usiamo il modello passato come parametro
            messages=[{"role": "user", "content": messaggio_utente}],
            temperature=0.4, 
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore AI ({modello_scelto}): {e}"

def crea_word(testo, titolo):
    doc = Document()
    doc.add_heading(titolo, 0)
    doc.add_paragraph(f"Data: {datetime.now().strftime('%d/%m/%Y')}")
    doc.add_paragraph(testo)
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
    testo_safe = testo.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=testo_safe)
    buffer = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    buffer.write(pdf_string)
    buffer.seek(0)
    return buffer

# --- GESTIONE STATO ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""

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
    
    # ADMIN PANEL AVANZATO
    with st.expander("🛠️ Admin / Debug"):
        pwd = st.text_input("Password", type="password")
        is_admin = (pwd == st.secrets.get("ADMIN_PASSWORD", "admin"))
        
        if is_admin:
            st.success("Admin Logged In")
            st.markdown("**Override Motore AI**")
            # L'admin può forzare un modello specifico indipendentemente dalla scelta utente
            override_model = st.selectbox("Forza Modello (Debug)", ["Nessuno (Usa Logica App)", "gpt-4o", "gpt-4o-mini"])
        else:
            override_model = "Nessuno (Usa Logica App)"

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
# TAB 2: CHATBOT (Ottimizzato sui Costi)
# ==============================================================================
with tab2:
    st.write("### 1. Carica il Fascicolo")
    uploaded_files = st.file_uploader("Trascina file (PDF, IMG, TXT)", accept_multiple_files=True, type=["pdf", "txt", "jpg", "png", "jpeg"], key="uploader")
    
    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} file caricati.")
        st.divider()
        st.subheader("🤖 Assistente Strategico")
        
        if not st.session_state.messages:
            st.session_state.messages.append({"role": "assistant", "content": "Ho ricevuto i file. Qual è l'obiettivo? (Es. Transare, Attaccare CTU...)"})

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Scrivi la tua strategia..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.contesto_chat_text += f"\nUtente: {prompt}"
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Analisi..."):
                    payload = prepara_input_multimodale(uploaded_files)
                    prompt_sys = "Sei un Perito Forense. Intervista l'avvocato per capire la strategia. Fai domande brevi."
                    
                    # QUI USIAMO IL MODELLO ECONOMICO PER LA CHAT
                    modello_chat = "gpt-4o-mini"
                    if override_model != "Nessuno (Usa Logica App)":
                        modello_chat = override_model
                        
                    risposta = interroga_llm_multimodale(prompt_sys, st.session_state.contesto_chat_text, payload, modello_chat)
                    st.markdown(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    st.session_state.contesto_chat_text += f"\nAI: {risposta}"

# ==============================================================================
# TAB 3: GENERAZIONE DOCUMENTI (Prezzi Dinamici)
# ==============================================================================
with tab3:
    if not uploaded_files:
        st.warning("⚠️ Carica prima i file nel Tab 'Analisi Strategica'.")
    else:
        st.header("🛒 Generazione Prodotti")
        st.write("Configura la profondità dell'analisi e il costo.")

        # --- SELETTORE LIVELLO ANALISI ---
        livello_analisi = st.radio(
            "Seleziona Livello di Analisi:",
            ["STANDARD (Veloce ed Economica)", "PREMIUM (Strategica e Approfondita)"],
            index=1,
            help="Standard usa AI rapida. Premium usa il modello più potente al mondo per ragionamenti complessi."
        )

        # LOGICA PREZZI E MODELLO
        if "STANDARD" in livello_analisi:
            modello_doc = "gpt-4o-mini"
            prezzi = {"timeline": 29, "sintesi": 29, "attacco": 89, "strategia": 149}
            desc_modello = "Analisi effettuata con motore rapido (GPT-4o Mini)."
        else:
            modello_doc = "gpt-4o"
            prezzi = {"timeline": 90, "sintesi": 90, "attacco": 190, "strategia": 390}
            desc_modello = "Analisi effettuata con motore Top di Gamma (GPT-4o) per massima precisione giuridica."

        # Override Admin
        if override_model != "Nessuno (Usa Logica App)":
            modello_doc = override_model
            st.warning(f"⚠️ MODALITÀ DEBUG: Forzato modello {modello_doc} indipendentemente dal livello scelto.")

        st.caption(f"ℹ️ {desc_modello}")
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            p1 = st.checkbox(f"Timeline Cronologica (€ {prezzi['timeline']})")
            p2 = st.checkbox(f"Sintesi Vicende (€ {prezzi['sintesi']})")
        with c2:
            p3 = st.checkbox(f"Punti Attacco Tecnici (€ {prezzi['attacco']})")
            p4 = st.checkbox(f"Strategia Processuale (€ {prezzi['strategia']})")
            
        selected = []
        totale = 0
        if p1: 
            selected.append("timeline")
            totale += prezzi['timeline']
        if p2: 
            selected.append("sintesi")
            totale += prezzi['sintesi']
        if p3: 
            selected.append("attacco")
            totale += prezzi['attacco']
        if p4: 
            selected.append("strategia")
            totale += prezzi['strategia']
        
        if selected:
            st.write(f"### Totale Ordine: € {totale}")
            
            can_dl = is_admin or "session_id" in st.query_params
            if is_admin: st.success("🔓 Admin Mode (Download Gratis)")
            elif can_dl: st.success("✅ Pagamento Verificato")
            else: st.info("Demo Mode: Inserisci password Admin per procedere.")
            
            if can_dl:
                if st.button("🚀 Genera Documenti"):
                    payload = prepara_input_multimodale(uploaded_files)
                    
                    prompts = {
                        "timeline": "Crea Timeline Cronologica rigorosa. Data | Evento | Rif. Doc.",
                        "sintesi": "Redigi Sintesi Tecnica formale.",
                        "attacco": "Agisci come CTP aggressivo. Trova errori CTU/Controparte (Norme UNI/Cassazione).",
                        "strategia": "Elabora Strategia (Ottimistica/Pessimistica) e Next Best Action."
                    }
                    
                    for item in selected:
                        with st.status(f"Generazione {item} con {modello_doc}...", expanded=True) as s:
                            # Passiamo il modello corretto alla funzione
                            txt = interroga_llm_multimodale(prompts[item], st.session_state.contesto_chat_text, payload, modello_doc)
                            
                            ext = "docx" if formato_output == "Word (.docx)" else "pdf"
                            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else "application/pdf"
                            buf = crea_word(txt, item) if ext == "docx" else crea_pdf(txt, item)
                            
                            st.download_button(f"📥 Scarica {item}", data=buf, file_name=f"{item}.{ext}", mime=mime)
                            s.update(label="Fatto!", state="complete")
