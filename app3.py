import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io
import re

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="GemKick Legal Strategist", page_icon="⚖️")

# --- STILI CSS ---
st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    .download-desc { font-size: 0.85em; color: #666; margin-bottom: 15px; margin-top: -10px; }
    h1 { color: #2c3e50; }
    h3 { color: #34495e; }
    .chat-message { padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex }
    .chat-message.user { background-color: #f0f2f6 }
    .chat-message.bot { background-color: #ffffff; border: 1px solid #e0e0e0 }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; border-left: 5px solid; }
</style>
""", unsafe_allow_html=True)

# --- INIZIALIZZAZIONE SESSION STATE ---
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "sufficiency_check" not in st.session_state: st.session_state.sufficiency_check = False
if "ready_to_generate" not in st.session_state: st.session_state.ready_to_generate = False
if "current_target_doc" not in st.session_state: st.session_state.current_target_doc = None
if "question_count" not in st.session_state: st.session_state.question_count = 0

# --- PROMPT LIBRARY (Il Cervello Strategico) ---
# Qui definiamo le istruzioni specifiche per ogni tipo di documento
DOC_PROMPTS = {
    "Sintesi Esecutiva & Timeline": """
        TASK: Crea DUE sezioni distinte.
        1. TIMELINE NARRATIVA (Visual Legal Design): Non un elenco di date, ma una narrazione Causa->Effetto. Evidenzia i ritardi della PA (Comune) e le omissioni del CTU.
        2. SINTESI ESECUTIVA: Usa box per i 'Numeri Chiave' (Valore CTP vs CTU). Includi una sezione 'Decisioni da prendere oggi'.
        TONO: Chiaro, direttivo, essenziale.
    """,
    "Matrice dei Rischi & Strategia": """
        TASK: Crea DUE sezioni distinte.
        1. MATRICE DEI RISCHI (Quantitativa): Tabella con colonne [Scenario di Rischio | Probabilità % | Impatto Economico € | Valore Ponderato (Prob*Imp) | Mitigazione].
        2. STRATEGIA PROCESSUALE (Game Theory): Usa la teoria dei giochi. Crea un 'Albero Decisionale': "Se controparte fa A -> Noi facciamo B (Aggressiva) o C (Transattiva)". Analizza Best Case e Worst Case.
    """,
    "Quesiti CTU & Replica": """
        TASK: Crea DUE sezioni distinte.
        1. QUESITI PER IL CTU (Attacco Preventivo): Formula domande 'Binarie' (Sì/No) o a trappola logica. Costringi il CTU a smentire documenti ufficiali (es. Nota Comune) o a contraddirsi.
        2. NOTA DI REPLICA: Smonta le tesi avversarie (es. 'sollecitare il comune dopo 30 anni') usando la tecnica della 'Reductio ad Absurdum'.
    """,
    "Bozza Transazione (Saldo e Stralcio)": """
        TASK: Scrivi una BOZZA DI ACCORDO TRANSATTIVO (Golden Bridge).
        LOGICA DEL CONGUAGLIO: 
        - Dimostra che il valore reale dei beni assegnati al cliente (al netto dei costi di ripristino/demolizione Albano) è inferiore alla sua quota di legittima.
        - Pertanto, il conguaglio deve essere A FAVORE del cliente o drasticamente ridotto.
        - Fai sembrare l'accordo una 'via di fuga' per la controparte dai rischi dell'immobile abusivo.
        STRUTTURA: Premesse (aggressive) -> Assegnazioni -> Conguaglio (giustificato matematicamente) -> Rinunce.
    """
}

# --- SIDEBAR CONFIGURAZIONE ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Gavel_01.jpg/1200px-Gavel_01.jpg", width=200)
    st.title("⚙️ Configurazione Tattica")
    
    api_key = st.text_input("Inserisci Google API Key", type="password")
    
    st.subheader("Postura Legale")
    tone_intensity = st.slider("Aggressività Strategica", 1, 10, 7, help="1: Diplomatico - 10: Guerra Totale")
    
    if tone_intensity <= 3: tone_desc = "Approccio 'Soft': Toni pacati, focus sulla conciliazione."
    elif tone_intensity <= 7: tone_desc = "Approccio 'Hard': Fermezza professionale, nessun cedimento."
    else: tone_desc = "Approccio 'Nuclear': Terminologia demolitoria ('Aliud pro alio', 'Valore zero', 'Tossico')."
    st.info(tone_desc)

    st.subheader("Obiettivo Primario")
    strategy_goal = st.selectbox("Seleziona Obiettivo", [
        "Minimizzare il Conguaglio (Cavalaglio paga il meno possibile)",
        "Ribaltare il Conguaglio (Castillo deve pagare)",
        "Massimizzare valore quote (Per vendita a terzi)"
    ])

    model_choice = st.selectbox("Modello AI", ["gemini-1.5-pro-latest", "gemini-1.5-flash"])

# --- FUNZIONI CORE ---

def clean_ai_response(text):
    """Rimuove tassativamente i convenevoli dell'AI."""
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
    """Converte testo Markdown in Docx con tabelle reali."""
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
                if i == 0:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.bold = True

def check_sufficiency_and_ask(context, doc_type, conversation_history):
    """
    IL SUPERVISORE AI: Analizza se mancano dati critici.
    """
    if not api_key: return "ERROR", "Manca API Key"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash") # Veloce per il check
    
    history_txt = "\n".join([f"{role}: {msg}" for role, msg in conversation_history])
    
    prompt = f"""
    SEI UN SUPERVISORE LEGALE SENIOR.
    Il tuo compito NON è generare il documento, ma decidere se abbiamo abbastanza informazioni per generarlo.
    
    Documento Richiesto: {doc_type}
    Contesto Documentale Fornito:
    {context}
    
    Storico Conversazione:
    {history_txt}
    
    ISTRUZIONI:
    1. Analizza se nel contesto ci sono i dati essenziali per {doc_type}.
    2. Se mancano dati CRITICI (es. valori beni, date chiave, controparti), formula UNA sola domanda specifica.
    3. Se le info sono sufficienti, rispondi SOLO "READY".
    4. Sii pragmatico. Non fare domande di rito. Massimo 1 domanda alla volta.
    
    Rispondi SOLO con la domanda O con "READY".
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "READY" in text.upper(): return "READY", ""
        else: return "ASK", text
    except Exception as e:
        return "READY", "" # Fallback in caso di errore API, proviamo a generare comunque

def generate_final_document(doc_type, context, posture, goal, conversation_history):
    """Generazione finale con prompt engineering avanzato."""
    if not api_key: return "Manca API Key"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_choice)
    
    chat_context = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in conversation_history if msg['role'] == 'user'])
    full_context = context + "\n\nINFORMAZIONI INTEGRATIVE UTENTE:\n" + chat_context
    
    # Recupera l'istruzione specifica dal dizionario
    specific_instruction = DOC_PROMPTS.get(doc_type, "Genera un documento professionale.")
    
    system_prompt = f"""
    SEI GEMINI, STRATEGA FORENSE SENIOR (Top 1% Italia).
    
    POSTURA: Livello Aggressività {posture}/10. 
    OBIETTIVO: {goal}.
    
    REGOLE DI SCRITTURA (NO CHAT):
    1. NON INSERIRE SALUTI, PREMESSE O CONCLUSIONI.
    2. INIZIA DIRETTAMENTE CON IL TITOLO DEL DOCUMENTO.
    3. USA MARKDOWN per formattare (**grassetto**, # titoli).
    4. USA TABELLE MARKDOWN (| A | B |) per i dati numerici.
    
    REGOLE LOGICHE:
    - Se l'obiettivo è ribaltare il conguaglio, usa i valori 'deprezzati' per dimostrare che il cliente riceve meno del dovuto.
    - Se aggressività > 7, usa linguaggio perentorio ("Inaccettabile", "Viziato", "Nullo").
    
    ISTRUZIONI SPECIFICHE PER QUESTO DOCUMENTO:
    {specific_instruction}
    
    TASK: Genera il documento completo basandoti sul contesto.
    """
    
    try:
        response = model.generate_content(system_prompt + "\n\n" + full_context)
        return clean_ai_response(response.text)
    except Exception as e:
        return f"Errore durante la generazione: {str(e)}"

# --- INTERFACCIA PRINCIPALE ---
st.title("⚖️ GemKick: Legal Strategy Suite (Rev. 29)")
st.markdown("### Generatore Legale con Intervista Dinamica & Strategia Mirata")

# 1. INPUT CONTESTO
uploaded_context = st.text_area("1. Incolla qui il contenuto dei documenti:", height=150, placeholder="Es: Testo estratto da PDF, note avvocati, perizie...")

# 2. SELEZIONE DOCUMENTO
doc_options = ["Seleziona..."] + list(DOC_PROMPTS.keys())
target_doc = st.selectbox("2. Che documento vuoi generare?", doc_options)

# LOGICA DI CONTROLLO STATO
if uploaded_context and target_doc != "Seleziona...":
    # Reset se cambio documento
    if st.session_state.current_target_doc != target_doc:
        st.session_state.current_target_doc = target_doc
        st.session_state.chat_history = []
        st.session_state.ready_to_generate = False
        st.session_state.sufficiency_check = False
        st.session_state.question_count = 0

    # Bottone di avvio analisi
    if not st.session_state.sufficiency_check:
        if st.button("🚀 Avvia Analisi Preliminare"):
            status, msg = check_sufficiency_and_ask(uploaded_context, target_doc, [])
            if status == "READY":
                st.session_state.ready_to_generate = True
                st.success("✅ Informazioni sufficienti! Pronto a generare.")
            else:
                st.session_state.chat_history.append({"role": "assistant", "content": msg})
                st.session_state.question_count += 1
            st.session_state.sufficiency_check = True
            st.rerun()

    # INTERFACCIA CHAT (INTERVISTA DINAMICA)
    if st.session_state.sufficiency_check and not st.session_state.ready_to_generate:
        st.markdown(f"""
        <div class="status-box" style="background-color: #e8f4f8; border-color: #00a8cc;">
            <b>🤖 Assistente Strategico:</b> Sto analizzando il caso per preparare: <i>{target_doc}</i>.<br>
            Domanda {st.session_state.question_count}/10 per affinare la strategia.
        </div>
        """, unsafe_allow_html=True)
        
        # Mostra storico
        for msg in st.session_state.chat_history:
            role_class = "user" if msg["role"] == "user" else "bot"
            icon = "👤" if msg["role"] == "user" else "🤖"
            st.markdown(f"<div class='chat-message {role_class}'><b>{icon}:</b>&nbsp;{msg['content']}</div>", unsafe_allow_html=True)
        
        # Input utente
        user_input = st.chat_input("Rispondi qui (o scrivi 'Basta' per generare)...")
        
        if user_input:
            if user_input.lower() in ["basta", "stop", "salta", "fine"]:
                st.session_state.ready_to_generate = True
                st.rerun()
            
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            
            # Controllo soglia domande (Max 10)
            if st.session_state.question_count >= 10:
                st.session_state.ready_to_generate = True
                st.warning("⚠️ Raggiunto limite massimo domande. Procedo con le info disponibili.")
                st.rerun()
            
            # Nuova verifica sufficienza
            status, next_msg = check_sufficiency_and_ask(uploaded_context, target_doc, [(m['role'], m['content']) for m in st.session_state.chat_history])
            
            if status == "READY":
                st.session_state.ready_to_generate = True
                st.success("✅ Ottimo! Ora ho tutto il necessario.")
                st.rerun()
            else:
                st.session_state.chat_history.append({"role": "assistant", "content": next_msg})
                st.session_state.question_count += 1
                st.rerun()
        
        # Bottone di fuga (Force Generate)
        if st.button("⏩ Salta domande e Genera Subito"):
            st.session_state.ready_to_generate = True
            st.rerun()

    # 3. GENERAZIONE FINALE
    if st.session_state.ready_to_generate:
        st.markdown("---")
        st.subheader(f"📄 Generazione: {target_doc}")
        
        if st.button("⚡ Genera Documento Finale"):
            with st.spinner("Elaborazione Strategica in corso (Game Theory & Visual Design)..."):
                final_content = generate_final_document(target_doc, uploaded_context, tone_intensity, strategy_goal, st.session_state.chat_history)
                
                # Creazione file Word
                docx_file = markdown_to_docx(final_content, target_doc)
                
                st.session_state['final_docx'] = docx_file
                st.success("Documento Generato!")

        if 'final_docx' in st.session_state:
            st.download_button(
                label="📥 SCARICA DOCUMENTO WORD (.docx)",
                data=st.session_state['final_docx'],
                file_name=f"{target_doc.replace(' ', '_')}_Final.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            st.caption("Il file include tabelle formattate, calcoli corretti e strategia legale ottimizzata.")

else:
    if not uploaded_context:
        st.info("👋 Inizia incollando il testo dei documenti nel box sopra.")
