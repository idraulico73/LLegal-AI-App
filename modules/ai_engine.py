# FILE: modules/ai_engine.py
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
    Trova il modello migliore disponibile.
    Cerca gemini-1.5-flash o pro, fallback su gemini-pro standard.
    """
    try:
        models = [m.name for m in genai.list_models()]
        # Priorità
        if 'models/gemini-1.5-flash' in models: return 'models/gemini-1.5-flash'
        if 'models/gemini-1.5-pro' in models: return 'models/gemini-1.5-pro'
        if 'models/gemini-pro' in models: return 'models/gemini-pro'
        return models[0] if models else None
    except:
        return None

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

# --- 3. JSON PARSER ROBUSTO (Versione che ritorna DICT) ---
def clean_json_text(text):
    """
    Pulisce il testo da markdown e tenta di estrarre UN SOLO oggetto JSON valido.
    Restituisce un DIZIONARIO (dict) se ha successo, o None se fallisce.
    """
    # Rimuovi markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    
    # Trova la prima graffa aperta
    start = text.find('{')
    if start == -1: return None
    text = text[start:]
    
    # TENTATIVO 1: Parsing diretto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass 

    # TENTATIVO 2: Trova l'ultima graffa chiusa (per ignorare testo finale)
    end = text.rfind('}')
    if end == -1: return None
    candidate = text[:end+1]
    
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # TENTATIVO 3: Gestione "Extra data" (es. doppi JSON o testo sporco)
        # Conta le parentesi per trovare la chiusura logica del primo oggetto
        balance = 0
        for i, char in enumerate(text):
            if char == '{': balance += 1
            elif char == '}': balance -= 1
            if balance == 0:
                try:
                    return json.loads(text[:i+1])
                except: break
        return None

# --- 4. FUNZIONI DI CALCOLO COSTI ---
def stima_costo_token(context_text, num_docs, pricing_row):
    """Calcola costo preventivo dinamico"""
    if not pricing_row: return 150.00 # Fallback
    
    p_fisso = float(pricing_row.get('prezzo_fisso', 0) or 0)
    p_in_1k = float(pricing_row.get('prezzo_per_1k_input_token', 0.02) or 0.02)
    p_out_1k = float(pricing_row.get('prezzo_per_1k_output_token', 0.05) or 0.05)
    molt = float(pricing_row.get('moltiplicatore_complessita', 1.0) or 1.0)

    # 1 Token ~= 4 caratteri
    token_input_est = len(context_text) / 4
    token_output_est = (num_docs * 2000) / 4 # 2k caratteri medi per doc

    costo_input = (token_input_est / 1000) * p_in_1k
    costo_output = (token_output_est / 1000) * p_out_1k
    
    totale = (costo_input + costo_output + p_fisso) * moltiplicatore
    return max(5.0, round(totale, 2))

# --- 5. CHAT STRATEGICA (TAB 2) - FIX DICT/STR ---
def interroga_gemini(model_name, prompt, context, file_parts, calc_data, sanitizer, pricing_info, aggression_level):
    
    active_model = get_best_model()
    if not active_model: 
        return {"fase": "errore", "titolo": "Errore", "contenuto": "Nessun modello AI configurato."}

    # SAFETY SETTINGS: BLOCK_NONE per strategie legali aggressive
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    
    generation_config = {
        "temperature": 0.7 + (aggression_level * 0.03),
        "response_mime_type": "application/json"
    }

    model = genai.GenerativeModel(active_model, safety_settings=safety_settings, generation_config=generation_config)

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
        
        if not response.parts:
            return {"fase": "errore", "titolo": "Blocco Sicurezza", "contenuto": str(response.prompt_feedback)}

        # FIX: clean_json_text ritorna già un DICT, non usare json.loads qui!
        parsed = clean_json_text(response.text)
        
        if parsed is None:
             return {"fase": "errore", "titolo": "Errore Formato", "contenuto": f"Output AI non valido:\n{response.text[:300]}..."}

        # Privacy Restore
        if "contenuto" in parsed: parsed["contenuto"] = sanitizer.restore(parsed["contenuto"])
        if "titolo" in parsed: parsed["titolo"] = sanitizer.restore(parsed["titolo"])
            
        return parsed

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore Tecnico", "contenuto": str(e)}

# --- 6. GENERATORE BATCH (TAB 3) ---
def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, model_name_ignored):
    active_model = get_best_model()
    if not active_model: return {"Errore": {"titolo": "Errore", "contenuto": "Modello non trovato"}}

    results = {}
    model = genai.GenerativeModel(active_model, generation_config={"response_mime_type": "application/json"})
    
    system_instruction = """
    SEI UN GENERATORE DI API JSON. OUTPUT FORMAT: { "titolo": "...", "contenuto": "..." }
    NON SCRIVERE TESTO FUORI DAL JSON.
    """

    for doc_name, task_prompt in tasks:
        full_payload = list(file_parts)
        
        prompt_specifico = f"""
        {system_instruction}
        CONTESTO FASCICOLO: {context_chat}
        DATI TECNICI: {calc_data}
        OBIETTIVO DOCUMENTO: {doc_name}
        ISTRUZIONI: {task_prompt}
        """
        full_payload.append(prompt_specifico)
        
        try:
            raw_response = model.generate_content(full_payload).text
            # clean_json_text ritorna dict
            cleaned_obj = clean_json_text(raw_response)
            
            if isinstance(cleaned_obj, dict):
                results[doc_name] = cleaned_obj
            else:
                results[doc_name] = {
                    "titolo": f"Errore {doc_name}", 
                    "contenuto": f"Formato non valido. Raw: {raw_response[:200]}..."
                }
        except Exception as e:
            results[doc_name] = {"titolo": "Errore Tecnico", "contenuto": str(e)}
            
    return results
