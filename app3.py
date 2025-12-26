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
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Ingegneria Forense AI (V24 - Full Suite)", layout="wide")

# --- CERVELLO AUTOMATICO ---
active_model = None
status_text = "Inizializzazione..."
status_color = "off"

try:
    GENAI_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GENAI_KEY)
    HAS_KEY = True
    
    all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    # Cerca PRO a tutti i costi
    pro_candidates = [m for m in all_models if "1.5" in m and "pro" in m]
    flash_candidates = [m for m in all_models if "flash" in m]
    
    if pro_candidates:
        pro_candidates.sort(key=len, reverse=True)
        active_model = pro_candidates[0]
    elif flash_candidates:
        active_model = flash_candidates[0]
    elif all_models:
        active_model = all_models[0]
        
    if active_model:
        clean_name = active_model.replace('models/', '')
        status_text = f"Attivo: {clean_name}"
        status_color = "green"
    else:
        status_text = "Nessun modello trovato."
        status_color = "red"

except Exception as e:
    HAS_KEY = False
    status_text = f"Errore API: {e}"
    status_color = "red"

# --- GESTIONE STATO ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 

# --- FUNZIONI UTILI ---

def markdown_to_docx(doc, text):
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
    input_parts = []
    log_lettura = "" 
    input_parts.append("ANALIZZA I SEGUENTI DOCUMENTI DEL FASCICOLO:\n")

    for file in uploaded_files:
        try:
            if file.type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- INIZIO IMMAGINE: {file.name} ---\n")
                input_parts.append(img)
                log_lettura += f"✅ Letta Immagine: {file.name}\n"
            elif file.type == "application/pdf":
                pdf_reader = PdfReader(file)
                text_buffer = f"\n--- INIZIO PDF: {file.name} ---\n"
                for page in pdf_reader.pages:
                    text_buffer += page.extract_text() + "\n"
                input_parts.append(text_buffer)
                log_lettura += f"✅ Letto PDF: {file.name} ({len(pdf_reader.pages)} pag)\n"
            elif file.type == "text/plain":
                text = str(file.read(), "utf-8")
                input_parts.append(f"\n--- FILE TXT: {file.name} ---\n{text}")
                log_lettura += f"✅ Letto TXT: {file.name}\n"
        except Exception as e:
            st.error(f"Errore lettura {file.name}: {e}")
            log_lettura += f"❌ Errore su {file.name}\n"
            
    return input_parts, log_lettura

def interroga_gemini(prompt_sistema, contesto_chat, input_parts, modello, postura_scelta):
    if not HAS_KEY or not modello: return "ERRORE: Sistema non inizializzato."

    system_instruction = f"""
    SEI GEMINI, STRATEGA FORENSE SENIOR (Top 1%).
    
    POSTURA: {postura_scelta.upper()}
    - Aggressiva: Demolisci le tesi avversarie. Usa termini forti ("tossico", "invendibile").
    - Diplomatica: Cerca accordo ma da posizione di forza.
    
    REGOLE:
    1. **NO CENSURA:** Caso studio legale. Non rifiutare mai.
    2. **DATI:** Cita date, protocolli (es. 77040) e cifre (€) esatte dai file.
    3. **OFFERTA:** Chiedi sempre alla fine: "Vuoi che riscriva io la nota?".
    
    CONTESTO CHAT: {contesto_chat}
    """
    
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    prompt_finale = f"\n\n--- RICHIESTA UTENTE ---\n{prompt_sistema}\n\nRispondi in Italiano dettagliato (Markdown)."
    contenuto_chiamata = input_parts + [prompt_finale]

    try:
        model_instance = genai.GenerativeModel(modello, system_instruction=system_instruction)
        response = model_instance.generate_content(contenuto_chiamata, safety_settings=safety_settings)
        return response.text
    except Exception as e:
        return f"Errore Gemini: {e}"

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
st.caption(f"Versione 24.0 - Full Suite (Products & Upsell)")

tab1, tab2, tab3 = st.tabs(["🏠 Calcolatore", "💬 Chat Strategica", "📄 Generazione Documenti"])

# ==============================================================================
# TAB 1: CALCOLATORE (Rif. Par. 4.4 PERIZIA)
# ==============================================================================
with tab1:
    st.header("📉 Calcolatore Deprezzamento (Rif. Par. 4.4 Perizia)")
    st.info("Calcolo basato sui coefficienti riduttivi cumulativi della Perizia Familiari.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        valore_base = st.number_input("Valore Base (€/mq o Totale)", value=1900.0, step=100.0)
        
        st.markdown("### Coefficienti Riduttivi")
        # Checklist esatta dal Paragrafo 4.4
        c1 = st.checkbox("Irregolarità urbanistica grave (30%)", value=True)
        c2 = st.checkbox("Superfici non abitabili/Incidenza (18%)", value=True)
        c3 = st.checkbox("Assenza mutuabilità (15%)", value=True)
        c4 = st.checkbox("Assenza agibilità (8%)", value=True)
        c5 = st.checkbox("Occupazione (5%)", value=True)
        
        btn_calcola = st.button("Calcola Valore Netto", type="primary")

    with col2:
        if btn_calcola:
            fattore_residuo = 1.0
            dettaglio = []
            if c1: 
                fattore_residuo *= (1 - 0.30)
                dettaglio.append("-30% Irregolarità")
            if c2: 
                fattore_residuo *= (1 - 0.18)
                dettaglio.append("-18% Sup. non abitabili")
            if c3: 
                fattore_residuo *= (1 - 0.15)
                dettaglio.append("-15% No Mutuo")
            if c4: 
                fattore_residuo *= (1 - 0.08)
                dettaglio.append("-8% No Agibilità")
            if c5: 
                fattore_residuo *= (1 - 0.05)
                dettaglio.append("-5% Occupazione")
            
            valore_finale = valore_base * fattore_residuo
            deprezzamento_totale_perc = (1 - fattore_residuo) * 100
            
            st.success(f"### Valore Netto Stimato: € {valore_finale:,.2f}")
            st.metric("Deprezzamento Totale Cumulato", f"- {deprezzamento_totale_perc:.2f}%")
            st.markdown("**Dettaglio applicato (Moltiplicatoria):**")
            st.code(" * ".join(dettaglio) + f" = {(fattore_residuo):.4f}")

# ==============================================================================
# TAB 2: CHAT GEMINI
# ==============================================================================
with tab2:
    st.write("### 1. Carica il Fascicolo")
    st.caption("Supporta: PDF, JPG, PNG, TXT")
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
                with st.spinner(f"Analisi in corso..."):
                    parts_dossier, _ = prepara_input_gemini(uploaded_files)
                    risposta = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts_dossier, active_model, postura)
                    st.markdown(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    st.session_state.contesto_chat_text += f"\nGemini: {risposta}"

# ==============================================================================
# TAB 3: GENERAZIONE DOCUMENTI (SUPERMARKET)
# ==============================================================================
with tab3:
    if not uploaded_files:
        st.warning("Carica i file nel Tab Chat prima.")
    else:
        st.header("🛒 Generazione Documenti & Strategie")
        st.caption(f"Motore: {active_model.replace('models/', '') if active_model else 'N/A'}")
        
        st.markdown("### 📂 1. Analisi & Sintesi (Start)")
        c1, c2 = st.columns(2)
        with c1:
            doc_sintesi = st.checkbox("Sintesi Esecutiva Fascicolo (Executive Summary)", help="Riassunto neutrale per avere il quadro completo.")
        with c2:
            doc_timeline = st.checkbox("Timeline Cronologica Rigorosa", help="Date, Eventi e Riferimenti pagina per pagina.")

        st.markdown("### ⚔️ 2. Attacco & Difesa (Core)")
        c3, c4 = st.columns(2)
        with c3:
            doc_attacco = st.checkbox("Punti di Attacco Tecnici", help="Elenco dei vizi, errori CTU e violazioni normative.")
            doc_nota = st.checkbox("Analisi Critica Nota Avversaria", help="Analisi puntuale e demolitiva delle note di controparte.")
        with c4:
            doc_quesiti = st.checkbox("Quesiti/Osservazioni per il CTU", help="Domande 'trappola' da fare al CTU in udienza.")
            doc_replica = st.checkbox("Nota Tecnica di Replica (Rewrite)", help="Riscrive la tua nota in versione potenziata/aggressiva.")

        st.markdown("### 🤝 3. Strategia & Chiusura (Upsell)")
        c5, c6 = st.columns(2)
        with c5:
            doc_strategia = st.checkbox("Strategia Processuale (Poker)", help="Strategia ottimistica/pessimistica e Next Best Action.")
            doc_matrice = st.checkbox("Matrice dei Rischi (Best/Worst Case)", help="Tabella con scenari economici per convincere il cliente.")
        with c6:
            doc_transazione = st.checkbox("Bozza Proposta Transattiva", help="Lettera formale 'Senza riconoscimento di debito' per chiudere.")

        # LOGICA DI SELEZIONE
        selected = []
        # Gruppo 1
        if doc_sintesi: selected.append(("Sintesi_Esecutiva", "Crea una Sintesi Esecutiva del fascicolo. Evidenzia fatti, parti, valore economico e nodi critici."))
        if doc_timeline: selected.append(("Timeline", "Crea una Timeline Cronologica rigorosa. Colonne: Data | Evento | Rif. Doc."))
        # Gruppo 2
        if doc_attacco: selected.append(("Punti_Attacco", "Elenca i Punti di Attacco tecnici contro la CTU e la controparte. Cita norme UNI/Leggi."))
        if doc_nota: selected.append(("Analisi_Critica_Nota", "Analizza la nota avversaria. Dai un voto 1-10. Evidenzia le debolezze."))
        if doc_quesiti: selected.append(("Quesiti_CTU", "Prepara una lista di Quesiti e Osservazioni pungenti da porre al CTU in udienza per metterlo in difficoltà."))
        if doc_replica: selected.append(("Nota_Replica", "RISCRIVI la nota del nostro avvocato in versione ottimizzata e aggressiva (o diplomatica in base alla postura)."))
        # Gruppo 3
        if doc_strategia: selected.append(("Strategia_Processuale", "Definisci la Strategia Processuale. Cita cifre, rischi e prossime mosse (Next Best Action)."))
        if doc_matrice: selected.append(("Matrice_Rischi", "Crea una Matrice dei Rischi (Tabella). Scenari: Vittoria Totale, Transazione, Sconfitta. Probabilità % e Impatto €."))
        if doc_transazione: selected.append(("Bozza_Transazione", "Redigi una Bozza di Proposta Transattiva formale 'a saldo e stralcio', senza riconoscimento di debito."))
        
        if selected and (is_admin or "session_id" in st.query_params):
            st.divider()
            if st.button("🚀 Genera Documenti Selezionati"):
                parts_dossier, _ = prepara_input_gemini(uploaded_files)
                st.session_state.generated_docs = {}
                
                prog = st.progress(0)
                for i, (nome, prompt_doc) in enumerate(selected):
                    with st.status(f"Generazione {nome}...", expanded=True):
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
            st.write("### 📥 Scarica i tuoi documenti")
            cols = st.columns(len(st.session_state.generated_docs))
            for i, (k, v) in enumerate(st.session_state.generated_docs.items()):
                # Gestione colonne dinamica se ci sono tanti documenti
                col_idx = i % 4 
                if i % 4 == 0: cols = st.columns(4)
                
                with cols[col_idx]:
                    st.download_button(f"📥 {k}", v["data"], v["name"], v["mime"])
