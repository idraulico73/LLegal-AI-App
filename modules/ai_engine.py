import re
import json
import streamlit as st
from google import genai
from google.genai import types
from . import config

# --- 1. CONFIGURAZIONE AI ---
def init_ai():
    """Check presenza API Key"""
    if "GOOGLE_API_KEY" not in st.secrets:
        st.warning("⚠️ Google API Key mancante nei secrets.")

def get_client():
    """Inizializza il nuovo Client Google GenAI"""
    try:
        return genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
    except Exception as e:
        print(f"Errore Init Client: {e}")
        return None

def get_best_model():
    """
    Restituisce il nome del modello migliore da usare.
    Con la nuova libreria, usiamo i nomi senza prefisso 'models/'.
    """
    # La nuova libreria preferisce 'gemini-1.5-flash' a 'models/gemini-1.5-flash'
    return "gemini-1.5-flash"

def get_active_models_list():
    """Recupera lista modelli disponibili (per debug/UI)"""
    client = get_client()
    if not client: return []
    try:
        # La nuova sintassi per listare i modelli è diversa
        # Per ora ritorniamo una lista statica dei supportati per evitare errori di chiamata
        return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
    except:
        return ["gemini-1.5-flash"]

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
    if not text: return None
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()
    
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1:
        candidate = text[start:end+1]
    else:
        return None
    
    try:
        return json.loads(candidate, strict=False)
    except:
        try:
            fixed_text = candidate.replace('\n', '\\n')
            return json.loads(fixed_text, strict=False)
        except:
            return None

# --- 4. CALCOLO COSTI (Utility) ---
def stima_costo_token(context_text, num_docs, pricing_row):
    if not pricing_row: return 150.00
    try:
        p_fisso = float(pricing_row.get('prezzo_fisso', 0) or 0)
        p_in_1k = float(pricing_row.get('prezzo_per_1k_input_token', 0.02) or 0.02)
        p_out_1k = float(pricing_row.get('prezzo_per_1k_output_token', 0.05) or 0.05)
        molt = float(pricing_row.get('moltiplicatore_complessita', 1.0) or 1.0)
    except:
        return 150.00

    token_input_est = len(context_text) / 4
    token_output_est = (num_docs * 2000) / 4 
    totale = ((token_input_est / 1000) * p_in_1k + (token_output_est / 1000) * p_out_1k + p_fisso) * molt
    return max(5.0, round(totale, 2))

# --- 5. CHAT STRATEGICA (TAB 2) ---
def interroga_gemini(model_name, prompt, context, file_parts, calc_data, sanitizer, pricing_info, aggression_level):
    client = get_client()
    if not client: return {"fase": "errore", "titolo": "Errore Client", "contenuto": "API Key non valida."}

    # Pulizia nome modello (la nuova lib non vuole 'models/')
    active_model = model_name.replace("models/", "") if model_name else "gemini-1.5-flash"
    
    # Configurazione (Nuova Sintassi: types.GenerateContentConfig)
    conf = types.GenerateContentConfig(
        temperature=0.7 + (aggression_level * 0.03),
        response_mime_type="application/json",
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE")
        ]
    )

    # Costruzione Prompt
    # La nuova lib gestisce i file diversamente, per ora passiamo tutto come testo nel prompt per semplicità
    # Se file_parts contiene oggetti complessi, andrebbero gestiti, ma qui assumiamo siano stringhe estratte o gestite
    
    full_prompt = f"""
    RUOLO: Senior Legal Strategist.
    CONTESTO: {context}
    DATI: {calc_data}
    BUDGET: {pricing_info}
    AGGRESSIVITÀ: {aggression_level}/10.
    ISTRUZIONI UTENTE: "{prompt}"
    
    OUTPUT JSON: {{ "fase": "strategia", "titolo": "...", "contenuto": "..." }}
    """
    
    try:
        # Nuova chiamata API: client.models.generate_content
        response = client.models.generate_content(
            model=active_model,
            contents=full_prompt,
            config=conf
        )
        
        parsed = clean_json_text(response.text)
        
        if parsed is None:
             fallback_content = response.text[:2000]
             return {"fase": "strategia", "titolo": "Risposta (Raw)", "contenuto": fallback_content}

        if "contenuto" in parsed: parsed["contenuto"] = sanitizer.restore(parsed["contenuto"])
        if "titolo" in parsed: parsed["titolo"] = sanitizer.restore(parsed["titolo"])
            
        return parsed

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore GenAI", "contenuto": str(e)}

# --- 6. GENERATORE BATCH (TAB 3) ---
def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, selected_model_name):
    client = get_client()
    if not client: return {}

    # Pulizia nome modello
    active_model = selected_model_name.replace("models/", "") if selected_model_name else "gemini-1.5-flash"
    
    results = {}
    system_instruction = 'SEI UN GENERATORE DI API JSON. OUTPUT FORMAT: { "titolo": "...", "contenuto": "..." }'

    for task in tasks:
        if len(task) == 3:
            doc_name, task_prompt, doc_temp = task
        else:
            doc_name, task_prompt = task
            doc_temp = 0.7

        conf = types.GenerateContentConfig(
            temperature=float(doc_temp),
            response_mime_type="application/json"
        )
        
        full_prompt = f"""
        {system_instruction}
        CONTESTO: {context_chat}
        DATI: {calc_data}
        OBIETTIVO: {doc_name}
        ISTRUZIONI: {task_prompt}
        """
        
        try:
            response = client.models.generate_content(
                model=active_model,
                contents=full_prompt,
                config=conf
            )
            
            # Recupero Token (Nuova sintassi usage_metadata)
            t_in, t_out = 0, 0
            if response.usage_metadata:
                t_in = response.usage_metadata.prompt_token_count
                t_out = response.usage_metadata.candidates_token_count

            cleaned_obj = clean_json_text(response.text)
            
            if isinstance(cleaned_obj, dict):
                cleaned_obj["_metrics"] = {"tokens_input": t_in, "tokens_output": t_out}
                results[doc_name] = cleaned_obj
            else:
                results[doc_name] = {
                    "titolo": f"Errore {doc_name}", 
                    "contenuto": response.text,
                    "_metrics": {"tokens_input": t_in, "tokens_output": t_out}
                }
                
        except Exception as e:
            results[doc_name] = {
                "titolo": "Errore Tecnico", 
                "contenuto": str(e),
                "_metrics": {"tokens_input": 0, "tokens_output": 0}
            }
            
    return results
