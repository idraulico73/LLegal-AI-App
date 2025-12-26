import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io
import re

# --- 1. CONFIGURAZIONE PAGINA E CSS ---
st.set_page_config(layout="wide", page_title="GemKick Legal Strategist", page_icon="⚖️")

st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    .download-desc { font-size: 0.85em; color: #666; margin-bottom: 15px; margin-top: -10px; }
    h1 { color: #2c3e50; }
    h3 { color: #34495e; }
    .chat-message { padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex; align-items: flex-start; gap: 10px; }
    .chat-message.user { background-color: #f0f2f6; }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0; }
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid; }
</style>
""", unsafe_allow_html=True)

# --- 2. INIZIALIZZAZIONE SESSION STATE ---
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "sufficiency_check" not in st.session_state: st.session_state.sufficiency_check = False
if "ready_to_generate" not in st.session_state: st.session_state.ready_to_generate = False
if "current_target_doc" not in st.session_state: st.session_state.current_target_doc = None
if "question_count" not in st.session_state: st.session_state.question_count = 0

# --- 3. PROMPT LIBRARY (IL CERVELLO STRATEGICO) ---
# Istruzioni agnostiche applicabili a qualsiasi branca del diritto
DOC_PROMPTS = {
    "Sintesi Esecutiva & Timeline": """
        TASK: Crea DUE sezioni distinte.
        1. TIMELINE NARRATIVA (Visual Legal Design): Non un elenco di date, ma una narrazione Causa -> Effetto -> Danno. Evidenzia ritardi, inadempimenti o inerzie della controparte o della PA.
        2. SINTESI ESECUTIVA: Usa box per i 'Numeri Chiave' (Valore Richiesto vs Valore Reale). Includi una sezione 'Decisioni Urgenti'.
        TONO: Chiaro, direttivo, essenziale.
    """,
    "Matrice dei Rischi & Strategia": """
        TASK: Crea DUE sezioni distinte.
        1. MATRICE DEI RISCHI (Quantitativa): Tabella con colonne [Scenario di Rischio | Probabilità % | Impatto Economico € | Valore Ponderato (Prob*Imp) | Strategia di Mitigazione].
        2. STRATEGIA PROCESSUALE (Game Theory): Usa la teoria dei giochi. Crea un 'Albero Decisionale': "Se controparte fa A -> Noi facciamo B (Aggressiva) o C (Transattiva)". Analizza Best Case e Worst Case.
    """,
    "Quesiti CTU & Replica": """
        TASK: Crea DUE sezioni distinte.
        1. QUESITI PER IL CTU (Attacco Preventivo): Formula domande 'Binarie' (Sì/No) o a trappola logica. Costringi il tecnico a smentire documenti ufficiali o a contraddirsi.
        2. NOTA DI REPLICA: Identifica le fallacie logiche nella tesi avversaria e smontale usando la tecnica della 'Reductio ad Absurdum'.
    """,
    "Bozza Transazione (Saldo e Stralcio)": """
        TASK: Scrivi una BOZZA DI ACCORDO TRANSATTIVO.
        
        LOGICA GENERALE DEL CONGUAGLIO (UNIVERSALE):
        1. Identifica la 'Quota di Diritto' teorica del cliente (es. % ereditaria, % societaria, quota di comunione legale).
        2. Calcola il 'Valore Nominale' dei beni/asset assegnati al cliente.
        3. Identifica nel testo i 'Fattori di Deprezzamento' occulti (es. vizi, abusi edilizi, debiti latenti, costi di ripristino, rischi legali pendenti, illiquidità).
        4. Sottrai questi fattori dal Valore Nominale per ottenere il 'Valore Netto Reale'.
        
        OBIETTIVO STRATEGICO:
        - Dimostra che il 'Valore Netto Reale' è inferiore alla 'Quota di Diritto'.
        - Di conseguenza, il conguaglio deve essere A FAVORE del cliente (o drasticamente ridotto se a debito).
        - Presenta l'accordo come un 'Golden Bridge': la controparte evita di accollarsi i rischi occulti accettando le nostre condizioni.
        
        STRUTTURA: Premesse (aggressive sui rischi) -> Assegnazioni -> Calcolo del Conguaglio (basato sul valore reale) -> Rinunce.
    """
}

# --- 4. SIDEBAR CONFIGURAZIONE ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Gavel_01.jpg/1200px-Gavel_01.jpg", width=200)
    st.title("⚙️ Configurazione Tattica")
    
    api_key = st.text_input("Inserisci Google API Key", type="password")
    
    st.subheader("Postura Legale")
    tone_intensity = st.slider("Aggressività Strategica", 1, 10, 7, help="1: Diplomatico - 10: Guerra Totale")
    
    if tone_intensity <= 3: tone_desc = "Approccio 'Soft': Toni pacati, focus sulla conciliazione."
    elif tone_intensity <= 7: tone_desc = "Approccio 'Hard': Fermezza professionale, nessun cedimento."
    else: tone_desc = "Approccio 'Nuclear': Terminologia demolitoria ('Tossico', 'Nullità', 'Malafede')."
    st.info(tone_desc)

    st.subheader("Obiettivo Primario")
    strategy_goal = st.selectbox("Seleziona Obiettivo", [
        "Minimizzare il debito/conguaglio",
        "Ribaltare la situazione (Ottenere denaro)",
        "Massimizzare valore quote (Per vendita)",
        "Chiudere la lite nel minor tempo possibile"
    ])

    model_choice = st.selectbox("Modello AI", ["gemini-1.5-flash", "gemini-1.5-pro-latest"])

# --- 5. FUNZIONI UTILITY & CLEANING ---

def clean_ai_response(text):
    """Rimuove tassativamente i convenevoli dell'AI (Ciao, ecco il file, ecc)."""
    patterns_start = [r"^Assolutamente.*", r"^Certo.*", r"^Ecco.*", r"^Analizzo.*", r"^In base ai.*", r"^Generato il.*", r"^Sulla base.*", r"^Per procedere.*"]
    patterns_end = [r"Spero che.*", r"Dimmi se posso.*", r"Fammi sapere.*", r"Vuoi che proceda.*", r"Resto a disposizione.*", r"Posso fare altro.*"]
    
    lines = text.split('\n')
    cleaned_lines = []
    
    skip = True
    for line in lines:
        if skip:
            if any(re.match(p, line, re.IGNORECASE) for p in patterns_start) or line.strip() == "---" or not line.strip():
                continue
            skip = False
        cleaned_lines.append(line)
    
    final_lines = []
    skip = True
    for line in reversed(cleaned_lines):
        if skip:
            if any(re.match(p, line, re.IGNORECASE) for p in patterns_end) or line.strip() == "---" or not line.strip():
                continue
            skip = False
        final_lines.insert(0, line)
        
    return "\n".join(final_lines).strip()

def markdown_to_docx(content, title):
    """Converte testo Markdown in Docx con tabelle native Word."""
    doc = Document()
    
    heading = doc.add_heading(title, 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    lines = content.split('\n')
    table_lines = []
    in_table = False
    
    for line in lines:
        # Rilevamento tabelle
        if line.strip().startswith('|') and line.strip().endswith('|'):
            table_lines.append(line)
            in_table = True
        else:
            if in_table:
                create_word_table(doc, table_lines)
                table_lines = []
                in_table = False
            
            # Gestione Intestazioni Markdown
            if line.startswith('### '): doc.add_heading(line.replace('### ', ''), level=3)
            elif line.startswith('## '): doc.add_heading(line.replace('## ', ''), level=2)
            elif line.startswith('# '): doc.add_heading(line.replace('# ', ''), level=1)
            elif line.strip() == "": continue
            else:
                p = doc.add_paragraph()
                parts = re.split(r'(\*\*.*?\*\*)', line)
                for part in parts:
                    if part.startswith('**') and part.endswith('**'):
                        run = p.add_run(part.replace('**', ''))
                        run.bold = True
                    else:
                        p.add_run(part)

    if in_table:
        create_word_table(doc, table_lines)
        
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def create_word_table(doc, table_lines):
    """Crea una tabella Word nativa parsando il Markdown."""
    data_rows = [row for row in table_lines if not re.search(r'\|\s*:?-+:?\s*\|', row)]
    if not data_rows: return

    rows = len(data_rows)
    cols = len(data_rows[0].strip().strip('|').split('|'))
    
    table = doc.add_table(rows=rows, cols=cols)
    table.style = 'Table Grid'
    
    for i, row_text in enumerate(data_rows):
        cells = row_text.strip().strip('|').split('|')
        for j, cell_text in enumerate(cells):
            if j < cols:
                cell = table.cell(i, j)
                cell.text = cell_text.strip()
                if i == 0: # Intestazione Bold
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.bold = True

# --- 6. AGENTI AI (SUPERVISORE & GENERATORE) ---

def check_sufficiency_and_ask(context, doc_type, conversation_history):
    """
    AGENTE SUPERVISORE:
    Valuta se i dati sono sufficienti.
    Output: "READY" oppure "ASK: <domanda>"
    """
    if not api_key: return "ERROR", "Manca API Key"
    
    genai.configure(api_key=api_key)
    # Usiamo Flash per velocità nell'interazione
    model = genai.GenerativeModel("gemini-1.5-flash") 
    
    history_txt = "\n".join([f"{role}: {msg}" for role, msg in conversation_history])
    
    prompt = f"""
    SEI UN SUPERVISORE LEGALE SENIOR.
    Non devi generare il documento, ma decidere se abbiamo abbastanza informazioni per scriverlo.
    
    Documento Richiesto: {doc_type}
    Contesto Attuale:
    {context}
    
    Storico Conversazione:
    {history_txt}
    
    ISTRUZIONI:
    1. Analizza se ci sono i dati essenziali (nomi, date, valori, controparti) per {doc_type}.
    2. Se mancano dati CRITICI per la strategia, formula UNA sola domanda specifica.
    3. Se le info sono sufficienti (o se siamo bloccati), rispondi SOLO "READY".
    4. Sii pragmatico: massimo 1 domanda alla volta.
    
    Rispondi SOLO con la domanda O con "READY".
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "READY" in text.upper(): return "READY", ""
        else: return "ASK", text
    except Exception as e:
        return "READY", "" # Fallback in caso di errore

def generate_final_document(doc_type, context, posture, goal, conversation_history):
    """
    AGENTE REDATTORE:
    Genera il documento finale formattato e strategico.
    """
    if not api_key: return "Manca API Key"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_choice)
    
    # Integra chat history nel contesto
    chat_context = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in conversation_history if msg['role'] == 'user'])
    full_context = context + "\n\nDATI INTEGRATIVI DALL'UTENTE:\n" + chat_context
    
    specific_instruction = DOC_PROMPTS.get(doc_type, "Genera un documento legale professionale.")
    
    system_prompt = f"""
    SEI GEMINI, STRATEGA FORENSE SENIOR (Top 1% Italia).
    
    POSTURA: Livello Aggressività {posture}/10. 
    OBIETTIVO: {goal}.
    
    REGOLE DI FORMATTAZIONE (TASSATIVE):
    1. NON INSERIRE SALUTI, PREMESSE O CONCLUSIONI.
    2. INIZIA DIRETTAMENTE CON IL TITOLO DEL DOCUMENTO.
    3. USA MARKDOWN per formattare (**grassetto**, # titoli).
    4. USA TABELLE MARKDOWN (| A | B |) per tutti i dati numerici e matrici.
    
    REGOLE DI STILE:
    - Se Aggressività > 7: Usa termini come "Inaccettabile", "Viziato", "Pretestuoso", "Grave nocumento".
    - Se Aggressività < 4: Usa termini come "Criticità", "Da rivedere", "Auspicabile accordo".
    - Quando citi valori, distingui sempre tra "Valore Nominale" (teorico) e "Valore Reale" (di realizzo).
    
    ISTRUZIONI SPECIFICHE PER IL DOCUMENTO '{doc_type}':
    {specific_instruction}
    
    TASK: Genera il documento completo, pronto per l'uso professionale.
    """
    
    try:
        response = model.generate_content(system_prompt + "\n\n" + full_context)
        return clean_ai_response(response.text)
    except Exception as e:
        return f"Errore durante la generazione: {str(e)}"

# --- 7. INTERFACCIA UTENTE PRINCIPALE ---
st.title("⚖️ GemKick: Legal Strategy Suite")
st.markdown("### Generatore Legale Agnostico con Intervista Dinamica")

# 1. INPUT CONTESTO
uploaded_context = st.text_area("1. Incolla qui il contenuto dei documenti (Testo estratto):", height=150, placeholder="Es: Testo di perizie, atti giudiziari, contratti, bilanci...")

# 2. SELEZIONE DOCUMENTO
doc_options = ["Seleziona..."] + list(DOC_PROMPTS.keys())
target_doc = st.selectbox("2. Che documento vuoi generare?", doc_options)

# LOGICA DEL FLUSSO
if uploaded_context and target_doc != "Seleziona...":
    
    # Reset stato se cambia il documento target
    if st.session_state.current_target_doc != target_doc:
        st.session_state.current_target_doc = target_doc
        st.session_state.chat_history = []
        st.session_state.ready_to_generate = False
        st.session_state.sufficiency_check = False
        st.session_state.question_count = 0

    # A. BOTTONE DI ANALISI INIZIALE
    if not st.session_state.sufficiency_check:
        if st.button("🚀 Avvia Analisi Preliminare"):
            with st.spinner("Analisi del contesto in corso..."):
                status, msg = check_sufficiency_and_ask(uploaded_context, target_doc, [])
                if status == "READY":
                    st.session_state.ready_to_generate = True
                    st.success("✅ Informazioni sufficienti! Pronto a generare.")
                else:
                    st.session_state.chat_history.append({"role": "assistant", "content": msg})
                    st.session_state.question_count += 1
                st.session_state.sufficiency_check = True
                st.rerun()

    # B. INTERFACCIA CHAT (LOOP DI SUPERVISIONE)
    if st.session_state.sufficiency_check and not st.session_state.ready_to_generate:
        
        # Display stato
        color = "#e8f4f8"
        st.markdown(f"""
        <div class='status-box' style='background-color: {color}; border-color: #00a8cc;'>
            <b>🤖 Assistente Strategico:</b> Sto analizzando i dati per: <i>{target_doc}</i>.<br>
            Domanda {st.session_state.question_count}/10 per perfezionare la strategia.
        </div>
        """, unsafe_allow_html=True)
        
        # Display cronologia
        for msg in st.session_state.chat_history:
            role_cls = "user" if msg["role"] == "user" else "bot"
            icon = "👤" if msg["role"] == "user" else "🤖"
            st.markdown(f"<div class='chat-message {role_cls}'><b>{icon}:</b> {msg['content']}</div>", unsafe_allow_html=True)
        
        # Input
        user_input = st.chat_input("Rispondi qui (o scrivi 'Salta' per forzare la generazione)...")
        
        if user_input:
            # Gestione comandi di uscita
            if user_input.lower() in ["salta", "basta", "stop", "fine", "genera"]:
                st.session_state.ready_to_generate = True
                st.rerun()
            
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            
            # Limite massimo 10 domande
            if st.session_state.question_count >= 10:
                st.warning("⚠️ Raggiunto limite massimo interazioni. Procedo con la generazione.")
                st.session_state.ready_to_generate = True
                st.rerun()
            
            # Nuova verifica col Supervisore
            status, next_msg = check_sufficiency_and_ask(uploaded_context, target_doc, [(m['role'], m['content']) for m in st.session_state.chat_history])
            
            if status == "READY":
                st.session_state.ready_to_generate = True
                st.success("✅ Ottimo! Ho tutto il necessario.")
                st.rerun()
            else:
                st.session_state.chat_history.append({"role": "assistant", "content": next_msg})
                st.session_state.question_count += 1
                st.rerun()

        # Bottone di fuga manuale
        if st.button("⏩ Salta domande e Genera Subito"):
            st.session_state.ready_to_generate = True
            st.rerun()

    # C. GENERAZIONE FINALE
    if st.session_state.ready_to_generate:
        st.markdown("---")
        st.subheader(f"📄 Generazione Documento: {target_doc}")
        
        if st.button("⚡ Genera Documento Definitivo"):
            with st.spinner("Elaborazione Strategica in corso (Game Theory & Visual Design)..."):
                final_content = generate_final_document(target_doc, uploaded_context, tone_intensity, strategy_goal, st.session_state.chat_history)
                
                # Creazione DOCX
                docx_file = markdown_to_docx(final_content, target_doc)
                st.session_state['final_docx'] = docx_file
                st.success("Documento Generato con Successo!")

        if 'final_docx' in st.session_state:
            safe_filename = target_doc.replace(' ', '_').replace('&', 'e')
            st.download_button(
                label="📥 SCARICA DOCUMENTO WORD (.docx)",
                data=st.session_state['final_docx'],
                file_name=f"{safe_filename}_GemKick.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            st.caption("Il file include tabelle formattate, calcoli corretti e logica 'Net Value'.")

else:
    if not uploaded_context:
        st.info("👋 Benvenuto. Incolla il testo dei documenti nel box sopra per iniziare.")
