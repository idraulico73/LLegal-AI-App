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
    """
    preferred_models = [
        'models/gemini-1.5-flash',
        'models/gemini-1.5-pro', 
        'models/gemini-pro'
    ]
    
    try:
        all_models = list(genai.list_models())
        # 1. Cerca tra i preferiti
        for pref in preferred_models:
            for m in all_models:
                if m.name == pref:
                    return pref

        # 2. Cerca qualsiasi modello generativo
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                if 'gemini' in m.name:
                    return m.name
        
        return 'models/gemini-1.5-flash'
        
    except Exception:
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

# --- 3. JSON PARSER ROBUSTO ---
def clean_json_text(text):
    """
    Pulisce il testo da markdown e tenta il parsing JSON in modo permissivo.
    """
    if not text: return None
    
    # 1. Pulizia Markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()
    
    # 2. Estrazione blocco JSON
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1:
        candidate = text[start:end+1]
    else:
        # Se non trova graffe, restituisci None per attivare il fallback
        return None
    
    # 3. Tentativi di Parsing
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass

    # 4. Tentativo Fix newline (comune con Gemini Flash)
    try:
        fixed_text = candidate.replace('\n', '\\n')
        return json.loads(fixed_text, strict=False)
    except:
        return None

# --- 4. CALCOLO COSTI (Legacy/Utility) ---
def stima_costo_token(context_text, num_docs, pricing_row):
    """Calcola costo preventivo dinamico (usato per stime rapide)"""
    if not pricing_row: return 150.00 # Fallback
    
    try:
        p_fisso = float(pricing_row.get('prezzo_fisso', 0) or 0)
        p_in_1k = float(pricing_row.get('prezzo_per_1k_input_token', 0.02) or 0.02)
        p_out_1k = float(pricing_row.get('prezzo_per_1k_output_token', 0.05) or 0.05)
        molt = float(pricing_row.get('moltiplicatore_complessita', 1.0) or 1.0)
    except:
        return 150.00

    # Stima Token (1 token ~= 4 chars)
    token_input_est = len(context_text) / 4
    token_output_est = (num_docs * 2000) / 4 

    costo_input = (token_input_est / 1000) * p_in_1k
    costo_output = (token_output_est / 1000) * p_out_1k
    
    totale = (costo_input + costo_output + p_fisso) * molt
    return max(5.0, round(totale, 2))

# --- 5. CHAT STRATEGICA (TAB 2) ---
def interroga_gemini(model_name, prompt, context, file_parts, calc_data, sanitizer, pricing_info, aggression_level):
    """
    Gestisce la chat interattiva.
    """
    # Se il modello non è specificato, lo cerca
    if not model_name: 
        active_model = get_best_model()
    else:
        active_model = model_name
    
    # Configurazione generazione dinamica
    generation_config = {
        "temperature": 0.7 + (aggression_level * 0.03),
        "response_mime_type": "application/json"
    }
    
    # SAFETY SETTINGS: BLOCK_NONE (Critico per strategie legali aggressive)
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    try:
        model = genai.GenerativeModel(active_model, safety_settings=safety_settings, generation_config=generation_config)
    except Exception as e:
        # Fallback su modello base se quello richiesto fallisce (es. nome errato)
        try:
            model = genai.GenerativeModel("models/gemini-1.5-flash", safety_settings=safety_settings, generation_config=generation_config)
        except:
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
        
        # Parsing sicuro con fallback
        parsed = clean_json_text(response.text)
        
        if parsed is None:
             # === FALLBACK INTELLIGENTE ===
             fallback_text = response.text
             # Tentativo regex per recuperare il contenuto se il JSON è rotto
             match = re.search(r'"contenuto":\s*"(.*)"', fallback_text, re.DOTALL)
             if match:
                 fallback_content = match.group(1).replace('\\n', '\n').replace('\\"', '"')
             else:
                 fallback_content = fallback_text[:2000] # Tronchiamo per sicurezza visuale

             return {
                 "fase": "strategia", 
                 "titolo": "Risposta (Formato non standard)", 
                 "contenuto": fallback_content
             }

        # Privacy Restore
        if "contenuto" in parsed: parsed["contenuto"] = sanitizer.restore(parsed["contenuto"])
        if "titolo" in parsed: parsed["titolo"] = sanitizer.restore(parsed["titolo"])
            
        return parsed

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore Tecnico", "contenuto": str(e)}

# --- 6. GENERATORE BATCH (TAB 3) ---
def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, selected_model_name):
    """
    Genera documenti in batch.
    Supporta tasks nel formato [(nome, prompt)] oppure [(nome, prompt, temp)].
    Restituisce un dict con contenuto e metriche token.
    """
    if not selected_model_name: selected_model_name = "models/gemini-1.5-flash"

    results = {}
    system_instruction = """
    SEI UN GENERATORE DI API JSON.
    OUTPUT FORMAT: { "titolo": "...", "contenuto": "..." }
    """

    for task in tasks:
        # Gestione compatibilità tuple a 2 o 3 elementi
        if len(task) == 3:
            doc_name, task_prompt, doc_temp = task
        else:
            doc_name, task_prompt = task
            doc_temp = 0.7 # Default

        # Configurazione specifica per questo documento
        current_config = {
            "response_mime_type": "application/json",
            "temperature": float(doc_temp)
        }
        
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
            # Re-inizializza modello per applicare la nuova temperatura
            model = genai.GenerativeModel(selected_model_name, generation_config=current_config)
            
            response = model.generate_content(full_payload)
            
            # Estrazione Token (Metrics)
            try:
                t_in = response.usage_metadata.prompt_token_count
                t_out = response.usage_metadata.candidates_token_count
            except:
                t_in, t_out = 0, 0
            
            # Parsing risposta
            raw_response = response.text
            cleaned_obj = clean_json_text(raw_response)
            
            if isinstance(cleaned_obj, dict):
                cleaned_obj["_metrics"] = {"tokens_input": t_in, "tokens_output": t_out}
                results[doc_name] = cleaned_obj
            else:
                # Fallback testo grezzo
                results[doc_name] = {
                    "titolo": f"Errore {doc_name}", 
                    "contenuto": raw_response,
                    "_metrics": {"tokens_input": t_in, "tokens_output": t_out}
                }
                
        except Exception as e:
            results[doc_name] = {
                "titolo": "Errore Tecnico", 
                "contenuto": str(e),
                "_metrics": {"tokens_input": 0, "tokens_output": 0}
            }
            
    return results
