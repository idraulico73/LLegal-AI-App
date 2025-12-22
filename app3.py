import streamlit as st
import openai
from PyPDF2 import PdfReader
import fitz  # Questo è PyMuPDF
import base64
import os
from io import BytesIO

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(
    page_title="Ingegneria Processuale | Analisi Vision AI",
    page_icon="⚖️",
    layout="centered"
)

# --- CSS PRO ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .stSelectbox label { font-size: 18px; font-weight: bold; color: #1e3a8a; }
    div[data-testid="stMetricValue"] { color: #15803d; font-weight: bold; }
    .package-box { background-color: #f0fdf4; padding: 20px; border-radius: 10px; border-left: 5px solid #15803d; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- SETUP API KEY ---
DEFAULT_KEY = st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else ""
DEFAULT_KEY = DEFAULT_KEY or os.getenv("OPENAI_API_KEY", "")

# --- SIDEBAR ---
with st.sidebar:
    if DEFAULT_KEY:
        api_key = DEFAULT_KEY
    else:
        st.header("⚙️ Configurazione")
        api_key = st.text_input("OpenAI API Key", type="password")
    
    st.divider()
    st.info("Compila per ricevere l'analisi.")
    nome = st.text_input("Nome e Cognome")
    email = st.text_input("Email")
    telefono = st.text_input("Telefono")

# --- INTERFACCIA ---
st.title("⚖️ Analisi Scansioni & Documenti")
st.markdown("""
**Il sistema legge tutto.** Carica PDF nativi, scansioni vecchie o foto di atti. 
L'AI riconoscerà il testo anche dalle immagini.
""")

st.divider()

ambito = st.selectbox(
    "Seleziona l'Area di Intervento:",
    [
        "🏗️ Immobiliare & Urbanistica",
        "🏦 Bancario & Finanziario",
        "🏥 Responsabilità Medica",
        "🚗 Infortunistica & Assicurazioni",
        "🏭 Sicurezza sul Lavoro"
    ]
)

budget = st.selectbox(
    "Budget indicativo:",
    ["Non lo so / Da valutare", "€ 500 - € 2.000", "Oltre € 2.000", "Sotto € 500"]
)

obiettivo = st.text_area(
    "Obiettivo specifico:",
    placeholder="Es: Analisi scansione vecchia del 1985...",
    height=100
)

uploaded_file = st.file_uploader("Carica Documento (PDF anche scansione)", type="pdf")

# --- FUNZIONI VISION & TEXT ---

def pdf_page_to_base64(pdf_bytes, page_num):
    """Converte una pagina PDF in immagine Base64 per GPT-4o Vision"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(page_num)
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Zoom 2x per leggere meglio
    img_data = pix.tobytes("png")
    return base64.b64encode(img_data).decode('utf-8')

def analyze_hybrid(file_bytes, user_goal, key, prompt_sys):
    client = openai.OpenAI(api_key=key)
    
    # 1. TENTATIVO TESTO (Veloce ed Economico)
    reader = PdfReader(BytesIO(file_bytes))
    text_content = ""
    max_pages = 10 # Limite pagine
    for i, page in enumerate(reader.pages[:max_pages]):
        text_content += page.extract_text() or ""
    
    # 2. DECISIONE STRATEGICA
    # Se ha trovato meno di 50 caratteri in totale, è probabilmente una scansione
    is_scan = len(text_content) < 50
    
    messages = [{"role": "system", "content": prompt_sys}]
    
    if is_scan:
        # --- MODALITÀ VISION (Costosa ma Potente) ---
        st.toast("⚠️ Scansione rilevata! Attivo la lettura ottica AI (Vision)...")
        
        # Prendiamo le prime 4 pagine come immagini (per risparmiare costi API)
        content_payload = [{"type": "text", "text": f"OBIETTIVO CLIENTE: {user_goal}. Analizza queste immagini del documento:"}]
        
        doc_len = len(reader.pages)
        pages_to_scan = min(4, doc_len)
        
        for i in range(pages_to_scan):
            base64_image = pdf_page_to_base64(file_bytes, i)
            content_payload.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"}
            })
            
        messages.append({"role": "user", "content": content_payload})
        
    else:
        # --- MODALITÀ TESTO (Standard) ---
        prompt_user = f"OBIETTIVO CLIENTE:\n{user_goal}\n\nTESTO ESTRATTO DAL PDF:\n{text_content[:15000]}"
        messages.append({"role": "user", "content": prompt_user})

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.2,
            max_tokens=1000
        )
        return response.choices[0].message.content, is_scan
    except Exception as e:
        return f"Errore: {str(e)}", False

def get_system_prompt(ambito_scelto):
    return f"""
    Sei il Responsabile Commerciale Tecnico dello Studio Familiari.
    
    FORMATO RISPOSTA OBBLIGATORIO:
    [DIAGNOSI]: 3 frasi dirette. Cita Date, Luoghi e Problemi Tecnici specifici.
    [GANCIO]: Una frase che spiega perché serve l'intervento umano.
    [COMPLESSITÀ]: BASSA o MEDIA o ALTA
    """

def safe_parse(ai_text):
    try:
        diagnosi = ai_text.split("[DIAGNOSI]:")[1].split("[GANCIO]:")[0].strip()
        gancio = ai_text.split("[GANCIO]:")[1].split("[COMPLESSITÀ]:")[0].strip()
        livello = ai_text.split("[COMPLESSITÀ]:")[1].strip()
        return diagnosi, gancio, livello
    except: return None, None, None

def get_price(complexity):
    if "ALTA" in complexity: return "2000", "3000"
    if "MEDIA" in complexity: return "1000", "1800"
    return "500", "800"

# --- ESECUZIONE ---
if st.button("🚀 Analizza Documento"):
    if not api_key or not uploaded_file:
        st.warning("Inserisci API Key e file.")
    else:
        with st.spinner("L'IA sta leggendo (se è una scansione ci vorrà qualche secondo in più)..."):
            sys_prompt = get_system_prompt(ambito)
            res, scan_mode = analyze_hybrid(uploaded_file.getvalue(), obiettivo, api_key, sys_prompt)
            
            diagnosi, gancio, livello = safe_parse(res)
            
            if diagnosi:
                st.balloons()
                if scan_mode:
                    st.info("👁️ **Modalità OCR attivata:** Il documento era una scansione, ma l'ho letto perfettamente.")
                
                st.success("✅ Analisi Completata.")
                st.markdown(f"### 🧐 Diagnosi: {diagnosi}")
                st.warning(f"💡 {gancio}")
                
                min_p, max_p = get_price(livello)
                st.markdown(f"""<div class="package-box"><h3>Preventivo: € {min_p} - € {max_p}</h3></div>""", unsafe_allow_html=True)
                
                # Call to action finale
                st.divider()
                st.markdown(f"**Interessato?** [Richiedi Call Strategica Gratuita](mailto:{email or 'info@periziedilizie.it'}?subject=Richiesta%20Call&body=Interessato%20al%20preventivo%20{min_p}-{max_p})")
            else:
                st.error("Errore lettura AI.")
