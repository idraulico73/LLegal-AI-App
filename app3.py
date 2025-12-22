import streamlit as st
import openai
from PyPDF2 import PdfReader
import os
from io import BytesIO

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(
    page_title="Ingegneria Processuale | Analisi Preliminare",
    page_icon="⚖️",
    layout="centered"
)

# --- CSS PER STILE PROFESSIONALE ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .stSelectbox label { font-size: 18px; font-weight: bold; color: #1e3a8a; }
    .stTextArea label { font-size: 18px; font-weight: bold; color: #1e3a8a; }
    div[data-testid="stMetricValue"] { color: #15803d; font-weight: bold; }
    .package-box { background-color: #f0fdf4; padding: 20px; border-radius: 10px; border-left: 5px solid #15803d; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- CHIAVI E SETUP ---
DEFAULT_KEY = st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else ""
DEFAULT_KEY = DEFAULT_KEY or os.getenv("OPENAI_API_KEY", "")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    # In produzione nascondi questo campo o usa st.secrets
    api_key = st.text_input("OpenAI API Key", value=DEFAULT_KEY, type="password") 
    
    st.divider()
    st.markdown("### 📞 I tuoi Dati")
    st.info("Compila per ricevere l'analisi.")
    nome = st.text_input("Nome e Cognome")
    email = st.text_input("Email")
    telefono = st.text_input("Telefono")

# --- INTERFACCIA PRINCIPALE ---
st.title("⚖️ Analisi Tecnica Preliminare")
st.markdown("""
**Hai un dubbio tecnico-legale?** Carica i documenti (CTU, Atti, Contratti). 
La nostra AI analizzerà la fattibilità e ti fornirà una prima diagnosi strategica per l'intervento dell'Ing. Familiari.
""")

st.divider()

# 1. MENU AMBITO
ambito = st.selectbox(
    "Seleziona l'Area di Intervento:",
    [
        "🏗️ Immobiliare & Urbanistica (Abusi, Aste, Condoni)",
        "🏦 Bancario & Finanziario (Usura, Mutui, Contratti)",
        "🏥 Responsabilità Medica (Malasanità)",
        "🚗 Infortunistica & Assicurazioni",
        "🏭 Sicurezza sul Lavoro & Industriale"
    ]
)

# 2. FILTRO BUDGET (IL TUO SCUDO)
budget = st.selectbox(
    "Qual è il budget indicativo per risolvere questo problema?",
    [
        "Non lo so / Da valutare",
        "€ 500 - € 2.000",
        "Oltre € 2.000",
        "Sotto € 500 (Solo consulenza base)"
    ]
)

# 3. QUESITO E FILE
obiettivo = st.text_area(
    "Qual è il tuo obiettivo specifico?",
    placeholder="Es: Voglio sapere se la perizia del CTU è contestabile; Devo vendere ma c'è un abuso...",
    height=100
)

uploaded_file = st.file_uploader("Carica Documento (PDF, max 10MB)", type="pdf")

# --- LOGICA PROMPT DI VENDITA ---
def get_system_prompt(ambito_scelto):
    return f"""
    Sei il Responsabile Commerciale Tecnico dello Studio di Ingegneria Forense Familiari.
    Il tuo obiettivo è:
    1. Dimostrare al cliente che hai capito il problema (citando dati reali dal documento).
    2. Convincerlo che serve un'analisi umana approfondita.
    3. Trasmettere CERTEZZA che lo studio può gestire la pratica.

    FORMATO RISPOSTA OBBLIGATORIO:
    [DIAGNOSI]: 3 frasi dirette. Cita Date, Luoghi e Problemi Tecnici specifici trovati nel testo.
    [GANCIO]: Una frase che spiega perché serve l'intervento umano (es. "Serve ricalcolare le superfici / verificare il nesso causale").
    [COMPLESSITÀ]: BASSA o MEDIA o ALTA
    """

# --- FUNZIONI BACKEND ---
@st.cache_data(show_spinner=False)
def extract_text_from_pdf(pdf_bytes, max_pages=15):
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages[:max_pages]:
            text += page.extract_text() or ""
        return text if text else None
    except: return None

def analyze_with_gpt4(text, user_goal, key, prompt_sys):
    client = openai.OpenAI(api_key=key)
    prompt_user = f"OBIETTIVO CLIENTE:\n{user_goal}\n\nDOCUMENTO:\n{text[:12000]}"
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt_sys},{"role": "user", "content": prompt_user}],
            temperature=0.2 
        )
        return response.choices[0].message.content
    except Exception as e: return str(e)

def get_package_details(complexity, ambito):
    base_price = 0
    if "Medica" in ambito: base_price = 1000
    elif "Bancario" in ambito: base_price = 500
    else: base_price = 800

    if "ALTA" in complexity:
        min_p, max_p = base_price + 1000, base_price + 2000
    elif "MEDIA" in complexity:
        min_p, max_p = base_price + 400, base_price + 800
    else: 
        min_p, max_p = base_price, base_price + 300
    return min_p, max_p

def safe_parse(ai_text):
    try:
        diagnosi = ai_text.split("[DIAGNOSI]:")[1].split("[GANCIO]:")[0].strip()
        gancio = ai_text.split("[GANCIO]:")[1].split("[COMPLESSITÀ]:")[0].strip()
        livello = ai_text.split("[COMPLESSITÀ]:")[1].strip()
        return diagnosi, gancio, livello
    except: return None, None, None

# --- ESECUZIONE ---
if st.button("🚀 Analizza Fattibilità"):
    if not api_key or not uploaded_file:
        st.warning("Inserisci API Key e carica un file.")
    elif not email:
        st.warning("Inserisci la tua email per ricevere il report.")
    else:
        with st.spinner("L'IA sta studiando il caso..."):
            text = extract_text_from_pdf(uploaded_file.getvalue())
            if text:
                sys_prompt = get_system_prompt(ambito)
                res = analyze_with_gpt4(text, obiettivo, api_key, sys_prompt)
                diagnosi, gancio, livello = safe_parse(res)
                
                if diagnosi:
                    st.balloons()
                    st.success("✅ Analisi Completata. Caso idoneo.")
                    
                    st.markdown(f"### 🧐 Diagnosi dell'Esperto AI")
                    st.info(f"**{diagnosi}**")
                    
                    st.markdown(f"### 💡 Perché serve il nostro intervento")
                    st.warning(f"_{gancio}_")
                    
                    min_p, max_p = get_package_details(livello, ambito)
                    
                    # BOX PREVENTIVO
                    st.markdown(f"""
                    <div class="package-box">
                        <h3>Stima Preventivo per Intervento Completo</h3>
                        <h2 style="color:green">€ {min_p} - € {max_p}</h2>
                        <p><i>Il prezzo varia in base alla strategia difensiva che adotteremo.</i></p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.divider()
                    st.markdown("### 👉 Prossimo Step: Attivazione")
                    
                    if "Sotto € 500" in budget:
                        st.error("⚠️ Il budget indicato potrebbe non coprire le spese tecniche minime per una perizia complessa.")
                        st.markdown("**Consiglio:** Scarica la nostra guida gratuita o richiedi una consulenza standard.")
                    else:
                        st.markdown("""
                        **Il caso presenta i requisiti per essere gestito con successo.**
                        Per confermare la strategia e bloccare il preventivo, offriamo una sessione telefonica preliminare.
                        """)
                        
                        # ESEMPIO LINK MAILTO PER PRENOTARE
                        mail_subject = f"Richiesta Call Strategica - {nome}"
                        mail_body = f"Buongiorno Ing. Familiari,%0A%0AHo ricevuto l'analisi AI per il caso {ambito}.%0APreventivo stimato: {min_p}-{max_p}.%0A%0AVorrei fissare la call di 15 minuti.%0A%0AMiei contatti:%0A{email}%0A{telefono}"
                        
                        st.markdown(f"""
                        <a href="mailto:info@periziedilizie.it?subject={mail_subject}&body={mail_body}" target="_blank">
                            <button style="
                                background-color:#15803d; 
                                color:white; 
                                padding:15px 32px; 
                                text-align:center; 
                                text-decoration:none; 
                                display:inline-block; 
                                font-size:18px; 
                                border:none; 
                                border-radius:8px; 
                                cursor:pointer; 
                                width:100%;">
                                📞 RICHIEDI CALL STRATEGICA (GRATUITA)
                            </button>
                        </a>
                        """, unsafe_allow_html=True)
                        st.caption("Cliccando si aprirà il tuo client di posta precompilato.")
                else:
                    st.error("Errore lettura AI. Riprova.")
            else:
                st.error("File illeggibile.")