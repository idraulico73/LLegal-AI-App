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
def clean_json_text(text):
    """
    Pulisce il testo da markdown e tenta di estrarre UN SOLO oggetto JSON valido.
    Restituisce un DIZIONARIO (dict).
    Se fallisce, restituisce None (NON crasha).
    """
    if not text: return None # Protezione input vuoto
    
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

    # TENTATIVO 2: Trova l'ultima graffa chiusa
    end = text.rfind('}')
    if end == -1: return None
    candidate = text[:end+1]
    
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # TENTATIVO 3: Bilanciamento parentesi (per Extra Data)
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

        # Parsing sicuro
        # NOTA: Qui NON usiamo json.loads() perché clean_json_text ritorna già un DICT!
        parsed = clean_json_text(response.text)
        
        if parsed is None:
             # Se il parsing fallisce, mostriamo il testo grezzo per debug
             return {
                 "fase": "errore", 
                 "titolo": "Errore Formato AI", 
                 "contenuto": f"L'AI ha risposto ma non in JSON valido.\n\nRaw output:\n{response.text[:500]}..."
             }

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
            
            # Parsing sicuro
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
