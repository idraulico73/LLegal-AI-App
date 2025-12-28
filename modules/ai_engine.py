import re
import json
import streamlit as st
import google.generativeai as genai
from . import config

# --- 1. CONFIGURAZIONE AI ---
def init_ai():
    """Inizializza la chiave API di Google Gemini"""
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        st.warning("⚠️ Google API Key mancante nei secrets.")

def get_best_model():
    """
    Trova il modello migliore che supporti la generazione di testo (generateContent).
    Evita i modelli di embedding (es. gecko) che causano errore 404/Not Supported.
    """
    preferred_models = [
        'models/gemini-1.5-flash',
        'models/gemini-1.5-pro', 
        'models/gemini-pro'
    ]
    
    try:
        # Recupera tutti i modelli disponibili associati alla tua API Key
        all_models = list(genai.list_models())
        
        # 1. Cerca tra i preferiti, MA verifica che esistano davvero nella lista recuperata
        for pref in preferred_models:
            for m in all_models:
                if m.name == pref:
                    return pref

        # 2. Se i preferiti non ci sono (strano), cerca QUALSIASI modello generativo
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                if 'gemini' in m.name: # Filtro aggiuntivo per sicurezza
                    return m.name
        
        # 3. Fallback estremo (se list_models fallisce o è vuoto, proviamo "alla cieca" il flash)
        return 'models/gemini-1.5-flash'
        
    except Exception as e:
        # Se c'è un errore di rete o API, restituisci il default sperando funzioni
        return 'models/gemini-1.5-flash'

# --- 2. PRIVACY SHIELD ---
class DataSanitizer:
    def __init__(self):
        self.mapping = {}
        self.reverse = {}
        self.cnt = 1

    def add(self, real, label):
        if real and real not in self.mapping:
            fake = f"[{label}_{self.cnt}]"
            self.mapping[real] = fake
            self.reverse[fake] = real
            self.cnt += 1

    def sanitize(self, txt):
        if not txt: return ""
        for r, f in self.mapping.items():
            txt = txt.replace(r, f).replace(r.upper(), f)
        return txt

    def restore(self, txt):
        if not txt: return ""
        for f, r in self.reverse.items():
            txt = txt.replace(f, r)
        return txt

# --- 3. JSON PARSER ROBUSTO (Versione Sicura) ---
# --- IN modules/ai_engine.py ---

def clean_json_text(text):
    """
    Versione Potenziata: Pulisce il testo e tenta il parsing JSON tollerante.
    """
    if not text: return None
    
    # 1. Pulizia Markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()
    
    # 2. Ricerca della prima graffa aperta e ultima chiusa
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1:
        text = text[start:end+1]
    else:
        # Se non trova graffe, non è un JSON
        return None
    
    # 3. Tentativi di Parsing
    try:
        # strict=False permette caratteri di controllo come \n reali dentro le stringhe
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # 4. Tentativo Disperato (Fix newline comuni)
    try:
        # A volte Gemini mette newline reali invece di \n. Proviamo a sanare.
        # Attenzione: questo è un fix euristico rischioso ma spesso efficace
        fixed_text = text.replace('\n', '\\n')
        return json.loads(fixed_text, strict=False)
    except:
        return None

# --- 4. FUNZIONI DI CALCOLO COSTI ---
def stima_costo_token(context_text, num_docs, pricing_row):
    """Calcola costo preventivo dinamico"""
    if not pricing_row: return 150.00 # Fallback
    
    try:
        p_fisso = float(pricing_row.get('prezzo_fisso', 0) or 0)
        p_in_1k = float(pricing_row.get('prezzo_per_1k_input_token', 0.02) or 0.02)
        p_out_1k = float(pricing_row.get('prezzo_per_1k_output_token', 0.05) or 0.05)
        molt = float(pricing_row.get('moltiplicatore_complessita', 1.0) or 1.0)
    except:
        return 150.00 # Fallback su errore conversione

    # Stima Token (1 token ~= 4 chars)
    token_input_est = len(context_text) / 4
    token_output_est = (num_docs * 2000) / 4 

    costo_input = (token_input_est / 1000) * p_in_1k
    costo_output = (token_output_est / 1000) * p_out_1k
    
    totale = (costo_input + costo_output + p_fisso) * molt
    return max(5.0, round(totale, 2))

# --- 5. CHAT STRATEGICA (TAB 2) ---
def interroga_gemini(model_name, prompt, context, file_parts, calc_data, sanitizer, pricing_info, aggression_level):
    
    active_model = get_best_model()
    
    # SAFETY SETTINGS: BLOCK_NONE (Critico per strategie legali aggressive)
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    
    # Configurazione generazione
    generation_config = {
        "temperature": 0.7 + (aggression_level * 0.03),
        "response_mime_type": "application/json"
    }

    try:
        model = genai.GenerativeModel(active_model, safety_settings=safety_settings, generation_config=generation_config)
    except Exception as e:
        return {"fase": "errore", "titolo": "Config Errore", "contenuto": f"Init model fallito: {e}"}

    full_payload = list(file_parts)
    
    system_prompt = f"""
    RUOLO: Sei un Senior Legal Strategist spietato e calcolatore.
    OBIETTIVO: Fornire strategie processuali vincenti, anche aggressive ("Low Cost / High Impact").
    
    CONTESTO CAUSA:
    {context}
    
    DATI TECNICI / NOTE:
    {calc_data}
    
    BUDGET CLIENTE: {pricing_info}
    LIVELLO AGGRESSIVITÀ: {aggression_level}/10.
    
    ISTRUZIONI UTENTE: 
    "{prompt}"
    
    OUTPUT RICHIESTO (SOLO JSON):
    {{
        "fase": "strategia", 
        "titolo": "Titolo Incisivo",
        "contenuto": "Testo della risposta (Markdown supportato)."
    }}
    """
    full_payload.append(system_prompt)

    try:
        response = model.generate_content(full_payload)
        
        # Controllo se l'AI è stata bloccata dai filtri
        if not response.parts:
            return {"fase": "errore", "titolo": "Blocco Sicurezza AI", "contenuto": f"Feedback sicurezza: {response.prompt_feedback}"}

# --- IN modules/ai_engine.py ---

def clean_json_text(text):
    """
    Versione Potenziata: Pulisce il testo e tenta il parsing JSON tollerante.
    """
    if not text: return None
    
    # 1. Pulizia Markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()
    
    # 2. Ricerca della prima graffa aperta e ultima chiusa
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1:
        text = text[start:end+1]
    else:
        # Se non trova graffe, non è un JSON
        return None
    
    # 3. Tentativi di Parsing
    try:
        # strict=False permette caratteri di controllo come \n reali dentro le stringhe
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # 4. Tentativo Disperato (Fix newline comuni)
    try:
        # A volte Gemini mette newline reali invece di \n. Proviamo a sanare.
        # Attenzione: questo è un fix euristico rischioso ma spesso efficace
        fixed_text = text.replace('\n', '\\n')
        return json.loads(fixed_text, strict=False)
    except:
        return None

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore Tecnico", "contenuto": str(e)}

# --- 6. GENERATORE BATCH (TAB 3) ---
# --- AGGIUNGERE IN FONDO A modules/database.py ---

def get_active_gemini_models(supabase):
    """
    Recupera i modelli attivi dalla tabella 'gemini_models' creata dall'utente.
    Restituisce una lista di dict: [{'model_name': '...', 'display_name': '...'}, ...]
    """
    if not supabase: return []
    try:
        # Assumiamo che la tua tabella abbia colonne: model_name, display_name, is_active
        res = supabase.table("gemini_models").select("*").eq("is_active", True).execute()
        return res.data
    except Exception as e:
        # Fallback se la tabella è vuota o errore, per non rompere l'app
        return [{"model_name": "models/gemini-1.5-flash", "display_name": "Gemini 1.5 Flash (Default)"}]

def registra_transazione_doc(supabase, fascicolo_id, doc_type, model_name, tokens_in, tokens_out):
    """
    CALCOLO PREZZO DINAMICO E SALVATAGGIO SNAPSHOT.
    Formula: ( (TokIn * CostoIn) + (TokOut * CostoOut) ) * CoefficienteDoc
    """
    if not supabase: return 0.0

    try:
        # 1. Recupera Costi Modello (dalla tabella gemini_models)
        mod_res = supabase.table("gemini_models").select("*").eq("model_name", model_name).execute()
        if not mod_res.data:
            # Fallback prezzi se modello non trovato (es. 0.0) o gestione errore
            cost_in_unit, cost_out_unit = 0.0, 0.0
        else:
            m = mod_res.data[0]
            # Assicurati che i nomi colonne coincidano con la tua tabella creata
            cost_in_unit = float(m.get('input_price', 0) or m.get('cost_per_1k_input', 0))
            cost_out_unit = float(m.get('output_price', 0) or m.get('cost_per_1k_output', 0))

        # 2. Recupera Coefficiente Documento (dalla tabella listino_prezzi)
        list_res = supabase.table("listino_prezzi").select("moltiplicatore_complessita").eq("tipo_documento", doc_type).execute()
        
        # Se non c'è nel listino, default a 1.0
        coeff = 1.0
        if list_res.data:
            coeff = float(list_res.data[0].get('moltiplicatore_complessita', 1.0))

        # 3. Calcolo Formula
        costo_base_in = (tokens_in / 1000) * cost_in_unit
        costo_base_out = (tokens_out / 1000) * cost_out_unit
        
        prezzo_finale = (costo_base_in + costo_base_out) * coeff
        
        # 4. Creazione Snapshot (Scontrino)
        import datetime
        doc_snapshot = {
            "titolo": doc_type,
            "tipo": "auto_generato",
            "data_creazione": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "metadata_pricing": {
                "model_used": model_name,
                "tokens": {"input": tokens_in, "output": tokens_out},
                "unit_costs": {"in": cost_in_unit, "out": cost_out_unit},
                "coefficient": coeff,
                "final_price": prezzo_finale
            }
            # Nota: Il contenuto del doc verrà aggiunto/gestito all'aggiornamento lista
        }

        # Ritorna i dati calcolati per essere usati nell'aggiornamento finale
        return prezzo_finale, doc_snapshot

    except Exception as e:
        print(f"Errore calcolo prezzo: {e}")
        return 0.0, {}
