import streamlit as st
from datetime import datetime
from io import BytesIO
import time
import re
import PIL.Image

# --- LIBRERIE ESTERNE ---
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, RGBColor
from fpdf import FPDF

# --- CONFIGURAZIONE APP & CSS ---
APP_NAME = "LexVantage"
APP_VER = "Rev 37 (Brainstorming Implemented & Doc Sanitizer)"

st.set_page_config(page_title=f"{APP_NAME} AI", layout="wide", page_icon="⚖️")

# CSS per layout sicuro e tabelle
st.markdown("""
<style>
    .stMarkdown { overflow-x: auto; }
    div[data-testid="stChatMessage"] { overflow-x: hidden; }
    h1, h2, h3 { color: #2c3e50; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
</style>
""", unsafe_allow_html=True)

# --- MEMORIA DI SESSIONE ---
if "messages" not in st.session_state: st.session_state.messages = []
if "contesto_chat_text" not in st.session_state: st.session_state.contesto_chat_text = ""
if "generated_docs" not in st.session_state: st.session_state.generated_docs = {} 
if "dati_calcolatore" not in st.session_state: st.session_state.dati_calcolatore = "Nessun calcolo tecnico effettuato."
if "livello_aggressivita" not in st.session_state: st.session_state.livello_aggressivita = 5
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
        except: all_models = []

        priority_list = ["models/gemini-1.5-pro-latest", "models/gemini-1.5-pro", "models/gemini-1.5-flash"]
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

# --- FUNZIONI DI UTILITÀ & SANITIZZAZIONE ---

def rimuovi_tabelle_forzato(text):
    """Chat Mode: Distrugge le tabelle per evitare bug grafici."""
    if not text: return ""
    return text.replace("|", " - ")

def sterilizza_documento_ai(text):
    """
    Doc Mode: RIMUOVE PREAMBOLI E DOMANDE FINALI.
    Elimina 'Perfetto', 'Ecco', 'Certo' e domande tipo 'Vuoi procedere?'.
    """
    if not text: return ""
    
    # 1. Rimuove preamboli comuni (Case Insensitive)
    patterns_start = [
        r"^Perfetto.*?\n", r"^Certo.*?\n", r"^Assolutamente.*?\n", 
        r"^Ecco.*?\n", r"^Ok, .*?\n", r"^Capito.*?\n", 
        r"^Sure.*?\n", r"^Here.*?\n"
    ]
    for p in patterns_start:
        text = re.sub(p, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # 2. Rimuove domande finali o saluti di servizio
    patterns_end = [
        r"Vuoi che proceda.*?$", r"Fammi sapere.*?$", r"Spero che.*?$", 
        r"Resto a disposizione.*?$", r"Dimmi se.*?$"
    ]
    for p in patterns_end:
        text = re.sub(p, "", text, flags=re.IGNORECASE | re.MULTILINE)
        
    return text.strip()

def advanced_markdown_to_docx(doc, text):
    """Parser DOCX con supporto Tabelle Reali."""
    lines = text.split('\n')
    iterator = iter(lines)
    in_table = False
    table_data = []

    for line in iterator:
        stripped = line.strip()
        # Rileva tabella
        if "|" in stripped and len(stripped) > 2 and stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_data = []
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            # Salta righe di separazione markdown (es. ---|---)
            if all(set(c).issubset({'-', ':'}) for c in cells if c): continue
            table_data.append(cells)
            continue
        
        # Fine tabella -> Renderizza
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
        
        # Titoli e Liste
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
            if file.type == "application/pdf":
                pdf = PdfReader(file)
                text = ""
                for page in pdf.pages: text += page.extract_text().replace("|", " ") + "\n"
                input_parts.append(f"\n--- PDF: {safe_name} ---\n{text}")
                log_debug += f"📄 {safe_name}\n"
            elif "word" in file.type:
                 doc = Document(file)
                 text = "\n".join([p.text for p in doc.paragraphs])
                 input_parts.append(f"\n--- DOCX: {safe_name} ---\n{text}")
                 log_debug += f"📘 {safe_name}\n"
            elif "image" in file.type:
                img = PIL.Image.open(file)
                input_parts.append(f"\n--- IMG: {safe_name} ---\n")
                input_parts.append(img)
                log_debug += f"🖼️ {safe_name}\n"
        except Exception as e:
            st.error(f"Errore {file.name}: {e}")
    return input_parts, log_debug

def interroga_gemini(prompt, contesto, input_parts, modello, aggressivita, is_chat=True, force_interview=False):
    if not HAS_KEY or not modello: return "ERRORE: AI Offline."
    dati_calc = st.session_state.dati_calcolatore
    
    mood_map = {1: "Diplomatico", 5: "Fermo/Tecnico", 10: "Guerra Legale (Aggressivo)"}
    mood = mood_map.get(aggressivita, "Fermo")
    if aggressivita < 4: mood = "Diplomatico"
    elif aggressivita > 7: mood = "Aggressivo (Warfare)"

    # Regole rigide per evitare output colloquiali
    doc_rules = """
    REGOLA RIGIDA DOCUMENTI:
    1. NON INIZIARE MAI con "Ecco...", "Certo...", "Perfetto...". Inizia SUBITO col Titolo.
    2. NON FARE DOMANDE alla fine. Il documento deve essere finito e pronto per la firma/invio.
    3. USA TABELLE per i dati numerici.
    4. Cita i documenti con acronimi (es. [Doc. Perizia]).
    """
    
    chat_rules = "USA ELENCHI PUNTATI. NIENTE TABELLE."

    if force_interview:
        prompt_final = f"L'utente ha chiesto: '{prompt}'. IGNORA. Fai invece 3 domande strategiche cruciali per capire budget e obiettivi. Rispondi SOLO con le domande."
    else:
        prompt_final = prompt

    sys_instr = f"""
    SEI {APP_NAME}, STRATEGA FORENSE. MOOD: {mood}.
    DATI CALCOLATORE: {dati_calc}
    CONTESTO: {contesto}
    {chat_rules if is_chat else doc_rules}
    """
    
    payload = list(input_parts)
    payload.append(prompt_final)

    try:
        model = genai.GenerativeModel(modello, system_instruction=sys_instr)
        return model.generate_content(payload).text
    except Exception as e: return f"Errore API: {e}"

def crea_word(testo, titolo):
    testo = sterilizza_documento_ai(testo) # Nuova funzione killer
    doc = Document()
    doc.add_heading(titolo, 0)
    advanced_markdown_to_docx(doc, testo)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crea_pdf_safe(testo, titolo):
    testo = sterilizza_documento_ai(testo)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=titolo.encode('latin-1','replace').decode('latin-1'), ln=1, align='C')
    replacements = {"€": "EUR", "’": "'", "“": '"', "”": '"'}
    for k,v in replacements.items(): testo = testo.replace(k,v)
    pdf.multi_cell(0, 10, txt=testo.encode('latin-1','replace').decode('latin-1'))
    buffer = BytesIO()
    buffer.write(pdf.output(dest='S').encode('latin-1'))
    buffer.seek(0)
    return buffer

# --- SIDEBAR & MAIN ---
with st.sidebar:
    st.title(APP_NAME)
    st.caption(APP_VER)
    if status_color == "green": st.success(status_text)
    else: st.error(status_text)
    st.divider()
    st.session_state.livello_aggressivita = st.slider("Aggressività", 1, 10, 5)
    if st.button("Reset"):
        st.session_state.clear()
        st.rerun()

tab1, tab2, tab3 = st.tabs(["🧮 Calcolatore", "💬 Chat", "📄 Documenti (Brainstorming Applied)"])

# TAB 1
with tab1:
    st.header("Calcolatore")
    base = st.number_input("Base CTU (€)", value=354750.0)
    c1, c2, c3 = st.columns(3)
    with c1: chk_abuso = st.checkbox("Abuso Grave (-30%)", True)
    with c2: chk_sup = st.checkbox("Non Abitabile (-18%)", True)
    with c3: chk_mutuo = st.checkbox("No Mutuo (-15%)", True)
    if st.button("Calcola"):
        f = 1.0 * (0.7 if chk_abuso else 1) * (0.82 if chk_sup else 1) * (0.85 if chk_mutuo else 1)
        res = base * f
        st.session_state.dati_calcolatore = f"VALORE BASE: {base} -> FINALE: {res:.2f} (Fattore {f:.3f})"
        st.success("Salvato.")
    if st.session_state.dati_calcolatore: st.code(st.session_state.dati_calcolatore)

# TAB 2
with tab2:
    files = st.file_uploader("Fascicolo", accept_multiple_files=True, key="up_chat")
    if not st.session_state.messages:
        msg = "Carica i documenti." if not files else "Documenti letti. Analizzo..."
        st.session_state.messages.append({"role": "assistant", "content": msg})

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(rimuovi_tabelle_forzato(m["content"]) if m["role"]=="assistant" else m["content"])

    if prompt := st.chat_input("..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.contesto_chat_text += f"\nUser: {prompt}"
        with st.chat_message("user"): st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("..."):
                parts, _ = prepara_input_gemini(files) if files else ([], "")
                
                force_int = False
                if len(st.session_state.messages) < 5 and not st.session_state.intervista_fatta and files:
                    force_int = True
                    st.session_state.intervista_fatta = True

                resp = interroga_gemini(prompt, st.session_state.contesto_chat_text, parts, active_model, st.session_state.livello_aggressivita, True, force_int)
                
                clean_resp = rimuovi_tabelle_forzato(resp)
                st.markdown(clean_resp)
                st.session_state.messages.append({"role": "assistant", "content": clean_resp})
                st.session_state.contesto_chat_text += f"\nAI: {clean_resp}"
                if force_int: st.rerun()

# TAB 3 (FULL BRAINSTORMING IMPLEMENTATION)
with tab3:
    st.header("Generazione Documenti Ottimizzati")
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        d1 = st.checkbox("Sintesi Esecutiva", help="Con Semafori e Valore Target")
        d2 = st.checkbox("Timeline", help="Con Calcolo Giorni e Decadenze")
        d3 = st.checkbox("Matrice Rischi", help="Con Riga Totale")
    with col_b:
        d4 = st.checkbox("Punti di Attacco", help="Con Citazioni Pagina")
        d5 = st.checkbox("Analisi Nota", help="Warfare Mode")
        d6 = st.checkbox("Quesiti CTU", help="Trappole Logiche")
    with col_c:
        d7 = st.checkbox("Nota Replica", help="Math Injection")
        d8 = st.checkbox("Strategia A/B", help="Scenari Comparati")
        d9 = st.checkbox("Transazione", help="Ancoraggio Valore Tecnico")
    
    fmt = st.radio("Formato", ["Word", "PDF"])

    if st.button("Genera Atti"):
        payload, _ = prepara_input_gemini(files) if files else ([], "")
        tasks = []
        
        # QUI IMPLEMENTO IL BRAINSTORMING ESATTO
        if d1: tasks.append(("Sintesi_Esecutiva", "Crea Sintesi Esecutiva. REQUISITI: Usa bullet points 'SEMAFORICI' (🟢/🟡/🔴) per indicare il livello di rischio. Inserisci subito in alto un box con il 'Valore Target' del calcolatore."))
        if d2: tasks.append(("Timeline", "Crea Timeline. REQUISITI: Evidenzia in GRASSETTO le date di decadenza. Calcola e scrivi esplicitamente i giorni/anni trascorsi tra gli eventi chiave (es. 'Trascorsi 25 anni')."))
        if d3: tasks.append(("Matrice_Rischi", "Crea Matrice Rischi. REQUISITI: Colonne: Evento, Probabilità, Impatto (€). DEVI inserire una riga finale con la SOMMA TOTALE dell'esposizione finanziaria massima."))
        if d4: tasks.append(("Punti_Attacco", "Crea Punti di Attacco. REQUISITI: Citation Mode attiva. Cita la pagina esatta dei documenti (es. 'Pag. 12 Perizia Familiari'). Usa i numeri del calcolatore per mostrare il delta economico esatto."))
        if d5: tasks.append(("Analisi_Critica_Nota", "Analizza Nota Avversaria. REQUISITI: Warfare Mode. Se aggressività > 7, usa termini come 'inammissibile', 'infondato in fatto', 'strumentale'. Smonta ogni punto."))
        if d6: tasks.append(("Quesiti_CTU", "Crea Quesiti CTU. REQUISITI: Trappole Logiche. Usa domande retoriche (es. 'Dica il CTU se ha verificato fisicamente...'). NON fare domande all'utente alla fine."))
        if d7: tasks.append(("Nota_Replica", "Crea Nota Replica. REQUISITI: Math-Injection. Integra la tabella del calcolatore nel testo. Non dire 'valore basso', scrivi 'Il valore è € X a causa del coefficiente Y'."))
        if d8: tasks.append(("Strategia_Processuale", "Crea Strategia. REQUISITI: Scenari A/B. Confronta 'Scenario A (Transazione Subito)' vs 'Scenario B (Guerra Totale)' con tabella costi/benefici stimati."))
        if d9: tasks.append(("Bozza_Transazione", "Crea Bozza Transazione. REQUISITI: Ancoraggio. Ancora l'offerta al 'Valore Tecnico di Perizia' (quello del calcolatore) presentandolo come una concessione generosa."))

        st.session_state.generated_docs = {}
        bar = st.progress(0)
        
        for i, (name, prompt) in enumerate(tasks):
            # Passiamo False a is_chat per permettere tabelle (ma la sanitizzazione rimuoverà i "Perfetto")
            txt = interroga_gemini(prompt, st.session_state.contesto_chat_text, payload, active_model, st.session_state.livello_aggressivita, False)
            
            if fmt == "Word":
                data = crea_word(txt, name)
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ext = "docx"
            else:
                data = crea_pdf_safe(txt, name)
                mime = "application/pdf"
                ext = "pdf"
            st.session_state.generated_docs[name] = {"data":data, "mime":mime, "ext":ext}
            bar.progress((i+1)/len(tasks))
            
    if st.session_state.generated_docs:
        cols = st.columns(4)
        for i, (k,v) in enumerate(st.session_state.generated_docs.items()):
            cols[i%4].download_button(f"📥 {k}", v["data"], f"{k}.{v['ext']}", v["mime"])
