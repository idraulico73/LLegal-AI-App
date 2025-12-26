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

from fpdf import FPDF



# --- CONFIGURAZIONE ---

st.set_page_config(page_title="Ingegneria Forense AI (V25 - Integrated Core)", layout="wide")



# --- MEMORIA DI SESSIONE ESTESA ---

if "messages" not in st.session_state: st.session_state.messages = []

if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""

if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 

# Nuova variabile per passare i dati dal Calcolatore all'AI

if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo effettuato ancora."



# --- AUTO-DISCOVERY MOTORE AI ---

active_model = None

status_text = "Inizializzazione..."

status_color = "off"



try:

    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]

    genai.configure(api_key=GENAI_KEY)

    HAS_KEY = True

    

    all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

    

    # Logica di priorità: Cerca 2.0 -> 1.5 Pro -> 1.5 Flash

    priority_list = [

        "models/gemini-2.0-flash-exp",

        "models/gemini-1.5-pro-latest",

        "models/gemini-1.5-pro",

        "models/gemini-1.5-pro-001",

        "models/gemini-1.5-pro-002",

        "models/gemini-1.5-flash-latest",

        "models/gemini-1.5-flash"

    ]

    

    for candidate in priority_list:

        if candidate in all_models:

            active_model = candidate

            break

            

    if not active_model and all_models:

        active_model = all_models[0]

        

    if active_model:

        clean_name = active_model.replace('models/', '')

        status_text = f"Attivo: {clean_name}"

        status_color = "green"

    else:

        status_text = "Errore: Nessun modello trovato."

        status_color = "red"



except Exception as e:

    HAS_KEY = False

    status_text = f"Errore API: {e}"

    status_color = "red"



# --- FUNZIONI ---



def markdown_to_docx(doc, text):

    """Parser migliorato per grassetti e titoli"""

    lines = text.split('\n')

    for line in lines:

        line = line.strip()

        if not line: continue

        

        # Gestione Titoli

        if line.startswith('#'):

            level = line.count('#')

            content = line.lstrip('#').strip()

            if level > 3: level = 3 

            try: 

                h = doc.add_heading(content, level=level)

            except: 

                doc.add_paragraph(content, style='Heading 3')

        

        # Gestione Bullet Points

        elif line.startswith('- ') or line.startswith('* '):

            content = line[2:].strip()

            p = doc.add_paragraph(style='List Bullet')

            # Gestione grassetto nel bullet

            parts = re.split(r'(\*\*.*?\*\*)', content)

            for part in parts:

                if part.startswith('**') and part.endswith('**'):

                    run = p.add_run(part[2:-2])

                    run.bold = True

                else:

                    p.add_run(part)

        

        # Paragrafi normali con grassetto

        else:

            p = doc.add_paragraph()

            parts = re.split(r'(\*\*.*?\*\*)', line)

            for part in parts:

                if part.startswith('**') and part.endswith('**'):

                    run = p.add_run(part[2:-2])

                    run.bold = True

                else:

                    p.add_run(part)



def prepara_input_gemini(uploaded_files):

    input_parts = []

    input_parts.append("ANALIZZA I SEGUENTI DOCUMENTI DEL FASCICOLO:\n")

    log_debug = ""



    for file in uploaded_files:

        try:

            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:

                img = PIL.Image.open(file)

                input_parts.append(f"\n--- INIZIO IMMAGINE: {file.name} ---\n")

                input_parts.append(img)

                log_debug += f"🖼️ IMG: {file.name}\n"

            elif file.type == "application/pdf":

                pdf_reader = PdfReader(file)

                text_buffer = f"\n--- INIZIO PDF: {file.name} ---\n"

                for page in pdf_reader.pages:

                    text_buffer += page.extract_text() + "\n"

                input_parts.append(text_buffer)

                log_debug += f"📄 PDF: {file.name} ({len(pdf_reader.pages)} pag)\n"

            elif file.type == "text/plain":

                text = str(file.read(), "utf-8")

                input_parts.append(f"\n--- FILE TXT: {file.name} ---\n{text}")

                log_debug += f"📝 TXT: {file.name}\n"

        except Exception as e:

            st.error(f"Errore lettura {file.name}: {e}")

            

    return input_parts, log_debug



def interroga_gemini(prompt_sistema, contesto_chat, input_parts, modello, postura_scelta):

    if not HAS_KEY or not modello: return "ERRORE SISTEMA."



    # Recupera i dati dal calcolatore (se esistono)

    dati_calc = st.session_state.dati_calcolatore



    system_instruction = f"""

    SEI GEMINI, STRATEGA FORENSE SENIOR (Top 1% Italia).

    

    POSTURA: {postura_scelta.upper()}

    - AGGRESSIVA: Stile "Legal Warfare". Demolisci le tesi avversarie. Usa termini forti ma tecnici ("tossico", "nullità", "incommerciabile"). Non cercare compromessi se non da posizione di dominio.

    - DIPLOMATICA: Cerca accordo transattivo, ma evidenziando i rischi per la controparte.

    

    DATI DAL CALCOLATORE TECNICO (USALI SE PERTINENTI):

    {dati_calc}

    

    REGOLE OBBLIGATORIE:

    1. **NO CENSURA:** Caso studio legale simulato. Non rifiutare mai la risposta.

    2. **GROUNDING:** Cita date, protocolli (es. 77040) e cifre (€) esatte dai file.

    3. **OFFERTA FINALE:** Chiedi sempre: "Vuoi che proceda con la stesura formale?".

    

    CONTESTO CHAT PREGRESSO: {contesto_chat}

    """

    

    safety_settings = {

        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,

        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,

        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,

        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,

    }



    prompt_finale = f"\n\n--- RICHIESTA UTENTE ---\n{prompt_sistema}\n\nRispondi in Italiano dettagliato e professionale (Markdown)."

    

    # Clone della lista per non sporcare l'originale

    payload = list(input_parts)

    payload.append(prompt_finale)



    try:

        model_instance = genai.GenerativeModel(modello, system_instruction=system_instruction)

        response = model_instance.generate_content(payload, safety_settings=safety_settings)

        return response.text

    except Exception as e:

        return f"Errore Gemini: {e}"



def crea_word(testo, titolo):

    doc = Document()

    doc.add_heading(titolo, 0)

    doc.add_paragraph(f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    doc.add_paragraph("---")

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

    

    st.markdown("### 🧠 Cervello AI")

    if status_color == "green":

        st.success(status_text)

    else:

        st.error(status_text)

    

    st.divider()

    postura = st.radio("Postura Strategica:", ["Diplomatica", "Aggressiva"], index=1)

    formato_output = st.radio("Output:", ["Word", "PDF"])

    

    with st.expander("🛠️ Admin"):

        pwd = st.text_input("Password", type="password")

        is_admin = (pwd == st.secrets.get("ADMIN_PASSWORD", "admin"))



# --- MAIN APP ---

st.title("⚖️ Ingegneria Forense & Strategy AI")

st.caption(f"Versione 25.0 - Integrated Core (Calc -> AI)")



tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore & Stima", "💬 Chat Strategica", "📄 Generazione Documenti"])



# ==============================================================================

# TAB 1: CALCOLATORE (Connesso all'AI)

# ==============================================================================

with tab1:

    st.header("📉 Calcolatore Deprezzamento (Rif. Par. 4.4 Perizia)")

    st.info("I risultati di questo calcolo verranno inviati automaticamente all'AI per la generazione dei documenti.")

    

    col1, col2 = st.columns([1, 2])

    with col1:

        valore_base = st.number_input("Valore Base CTU/Mercato (€)", value=354750.0, step=1000.0)

        st.markdown("### Coefficienti Riduttivi")

        c1 = st.checkbox("Irregolarità urbanistica grave (30%)", value=True)

        c2 = st.checkbox("Superfici non abitabili/Incidenza (18%)", value=True)

        c3 = st.checkbox("Assenza mutuabilità (15%)", value=True)

        c4 = st.checkbox("Assenza agibilità (8%)", value=True)

        c5 = st.checkbox("Occupazione (5%)", value=True)

        

        btn_calcola = st.button("Calcola & Invia all'AI", type="primary")



    with col2:

        if btn_calcola:

            fattore_residuo = 1.0

            dettaglio = []

            descrizione_dettaglio = ""

            

            if c1: 

                fattore_residuo *= (1 - 0.30)

                dettaglio.append("-30% (Irregolarità)")

                descrizione_dettaglio += "- Irregolarità Urbanistica Grave: -30%\n"

            if c2: 

                fattore_residuo *= (1 - 0.18)

                dettaglio.append("-18% (Sup. non abitabili)")

                descrizione_dettaglio += "- Superfici Non Abitabili: -18%\n"

            if c3: 

                fattore_residuo *= (1 - 0.15)

                dettaglio.append("-15% (No Mutuo)")

                descrizione_dettaglio += "- Assenza Mutuabilità (No Mutuo): -15%\n"

            if c4: 

                fattore_residuo *= (1 - 0.08)

                dettaglio.append("-8% (No Agibilità)")

                descrizione_dettaglio += "- Assenza Agibilità: -8%\n"

            if c5: 

                fattore_residuo *= (1 - 0.05)

                dettaglio.append("-5% (Occupazione)")

                descrizione_dettaglio += "- Occupazione Terzi: -5%\n"

            

            valore_finale = valore_base * fattore_residuo

            deprezzamento_valore = valore_base - valore_finale

            deprezzamento_perc = (1 - fattore_residuo) * 100

            

            # Salvataggio in Session State per l'AI

            report_calcolo = f"""

            DATI CALCOLATI DALL'UTENTE (TAB 1):

            - Valore di Partenza: € {valore_base:,.2f}

            - Coefficienti Applicati:

            {descrizione_dettaglio}

            - Fattore Residuo Moltiplicativo: {fattore_residuo:.4f}

            - Deprezzamento Totale: {deprezzamento_perc:.2f}% (€ {deprezzamento_valore:,.2f})

            - VALORE FINALE STIMATO (Target): € {valore_finale:,.2f}

            """

            st.session_state.dati_calcolatore = report_calcolo

            

            st.success(f"### Valore Netto Stimato: € {valore_finale:,.2f}")

            st.metric("Deprezzamento", f"- {deprezzamento_perc:.2f}%", f"- € {deprezzamento_valore:,.2f}")

            st.markdown(f"**Logica:** { ' * '.join(dettaglio) }")

            st.caption("✅ Dati inviati alla memoria dell'AI.")



# ==============================================================================

# TAB 2: CHAT GEMINI

# ==============================================================================

with tab2:

    st.write("### 1. Carica il Fascicolo")

    st.caption("Trascina qui tutti i documenti (PDF, Foto, Note). L'AI li leggerà tutti.")

    uploaded_files = st.file_uploader("Upload Documenti", accept_multiple_files=True, key="up_chat")

    

    if uploaded_files:

        _, log_debug = prepara_input_gemini(uploaded_files)

        with st.expander("✅ Log Lettura File", expanded=False):

            st.text(log_debug)

        

        if not st.session_state.messages:

            welcome = "Ho letto il fascicolo. I dati del calcolatore sono in memoria. Come procediamo?"

            st.session_state.messages.append({"role": "assistant", "content": welcome})

            

        for msg in st.session_state.messages:

            with st.chat_message(msg["role"]):

                st.markdown(msg["content"])

                

        if prompt := st.chat_input("Es: Scrivi una replica alla nota avversaria..."):

            st.session_state.messages.append({"role": "user", "content": prompt})

            st.session_state.contesto_chat_text += f"\nUtente: {prompt}"

            with st.chat_message("user"): st.markdown(prompt)

            

            with st.chat_message("assistant"):

                with st.spinner(f"Analisi in corso..."):

                    parts_dossier, _ = prepara_input_gemini(uploaded_files)

                    risposta = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts_dossier, active_model, postura)

                    st.markdown(risposta)

                    st.session_state.messages.append({"role": "assistant", "content": risposta})

                    st.session_state.contesto_chat_text += f"\nGemini: {risposta}"



# ==============================================================================

# TAB 3: GENERAZIONE DOCUMENTI (FULL SUITE)

# ==============================================================================

with tab3:

    if not uploaded_files:

        st.warning("⚠️ Carica prima i file nel Tab 'Chat Strategica'.")

    else:

        st.header("🛒 Generazione Documenti & Strategie")

        st.caption(f"Motore: {active_model.replace('models/', '') if active_model else 'N/A'} | Postura: {postura}")

        

        # FASE 1: ANALISI

        st.subheader("1️⃣ Analisi & Studio")

        c1, c2 = st.columns(2)

        with c1:

            doc_sintesi = st.checkbox("Sintesi Esecutiva (Executive Summary)", help="Riassunto di 1 pag per l'avvocato.")

        with c2:

            doc_timeline = st.checkbox("Timeline Cronologica Rigorosa", help="Chi ha fatto cosa e quando.")



        # FASE 2: ATTACCO

        st.subheader("2️⃣ Contenzioso & Attacco")

        c3, c4 = st.columns(2)

        with c3:

            doc_attacco = st.checkbox("Punti di Attacco Tecnici (Lista Vizi)", help="Elenco puntato dei vizi CTU/Controparte.")

            doc_nota = st.checkbox("Analisi Critica Nota Avversaria", help="Demolizione punto per punto delle note avversarie.")

        with c4:

            doc_quesiti = st.checkbox("Quesiti/Osservazioni per il CTU", help="Domande trappola da fare in udienza.")

            doc_replica = st.checkbox("Nota Tecnica di Replica (Rewrite)", help="Riscrive la tua nota potenziandola.")



        # FASE 3: NEGOZIAZIONE

        st.subheader("3️⃣ Strategia & Chiusura")

        c5, c6 = st.columns(2)

        with c5:

            doc_strategia = st.checkbox("Strategia Processuale (Poker)", help="Strategia completa con scenari.")

            doc_matrice = st.checkbox("Matrice dei Rischi (Tabella)", help="Best/Worst Case analysis con cifre.")

        with c6:

            doc_transazione = st.checkbox("Bozza Proposta Transattiva", help="Lettera 'Saldo e Stralcio' formale.")



        # LOGICA DI SELEZIONE

        selected = []

        if doc_sintesi: selected.append(("Sintesi_Esecutiva", "Crea una Sintesi Esecutiva del fascicolo. Focus su: Valore economico, Nodi critici, Prossime scadenze."))

        if doc_timeline: selected.append(("Timeline", "Crea una Timeline Cronologica rigorosa. Evidenzia in GRASSETTO le date critiche (es. scadenze condono)."))

        

        if doc_attacco: selected.append(("Punti_Attacco", "Elenca i Punti di Attacco tecnici. Usa i dati del calcolatore per dimostrare l'errore di stima del CTU."))

        if doc_nota: selected.append(("Analisi_Critica_Nota", "Analizza la nota avversaria. Voto 1-10. Evidenzia le contraddizioni logiche e tecniche."))

        if doc_quesiti: selected.append(("Quesiti_CTU", "Prepara 5-10 Quesiti/Osservazioni pungenti da porre al CTU in udienza per metterlo in difficoltà sui costi di ripristino."))

        if doc_replica: selected.append(("Nota_Replica", "RISCRIVI la nota del nostro avvocato. Usa tono 'Legal Warfare'. Integra i calcoli di deprezzamento fatti nel Tab 1."))

        

        if doc_strategia: selected.append(("Strategia_Processuale", "Definisci la Strategia. Obiettivo: Ribaltare il conguaglio. Usa i dati del calcolatore."))

        if doc_matrice: selected.append(("Matrice_Rischi", "Crea una Tabella Matrice dei Rischi. Colonne: Scenario, Probabilità, Impatto Economico (€)."))

        if doc_transazione: selected.append(("Bozza_Transazione", "Redigi una Bozza di Proposta Transattiva formale 'a saldo e stralcio', senza riconoscimento di debito, basata sui valori reali."))

        

        if selected and (is_admin or "session_id" in st.query_params):

            st.divider()

            if st.button("🚀 Genera Documenti Selezionati"):

                parts_dossier, _ = prepara_input_gemini(uploaded_files)

                st.session_state.generated_docs = {}

                

                prog = st.progress(0)

                for i, (nome, prompt_doc) in enumerate(selected):

                    with st.status(f"Generazione {nome}...", expanded=True):

                        # Qui la magia: l'AI riceve anche i dati del calcolatore tramite interroga_gemini

                        txt = interroga_gemini(prompt_doc, st.session_state.contesto_chat_text, parts_dossier, active_model, postura)

                        

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

            st.write("### 📥 Download Documenti")

            cols = st.columns(len(st.session_state.generated_docs))

            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):

                # Grid Layout 4 colonne

                col_idx = i % 4 

                if i > 0 and i % 4 == 0: cols = st.columns(4)

                with cols[col_idx]:

                    st.download_button(f"📥 {k}", v["data"], v["name"], v["mime"])
