import re
import json
import streamlit as st
import google.generativeai as genai

# --- 1. PRIVACY SHIELD (INVARIATO) ---
class DataSanitizer:
    def __init__(self):
        self.mapping = {}; self.reverse = {}; self.cnt = 1
    def add(self, real, label):
        if real and real not in self.mapping:
            fake = f"[{label}_{self.cnt}]"
            self.mapping[real] = fake; self.reverse[fake] = real; self.cnt += 1
    def sanitize(self, txt):
        if not txt: return ""
        for r, f in self.mapping.items(): txt = txt.replace(r, f).replace(r.upper(), f)
        return txt
    def restore(self, txt):
        if not txt: return ""
        for f, r in self.reverse.items(): txt = txt.replace(f, r)
        return txt

# --- 2. JSON CLEANER (INVARIATO) ---
def clean_json_text(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == '\n' or ch == '\t')
    start = text.find('{'); end = text.rfind('}')
    if start != -1 and end != -1: text = text[start:end+1]
    return text.strip()

# --- 3. GEMINI INIT & AUTO-DISCOVERY (NUOVO - Ottimizzato) ---
def init_ai():
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        return True
    return False

def get_best_model():
    """
    Trova il miglior modello disponibile.
    Sostituisce la logica duplicata nelle funzioni successive.
    """
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if "models/gemini-1.5-flash" in models: return "models/gemini-1.5-flash"
        if "models/gemini-1.5-pro" in models: return "models/gemini-1.5-pro"
        if "models/gemini-pro" in models: return "models/gemini-pro"
        return models[0] if models else None
    except Exception as e:
        return None

# --- 4. LOGICA CORE: INTERVISTA (REFATTORED - Usa get_best_model) ---
def interroga_gemini(model_name_ignored, prompt, history, files_content, calc_data, sanitizer, price_info, livello_aggressivita):
    # QUI ABBIAMO RISPARMIATO RIGHE: Usiamo la funzione centralizzata invece di ripetere il try/except
    active_model = get_best_model()
    
    if not active_model:
        return {"fase": "errore", "titolo": "Errore AI", "contenuto": "Nessun modello Google Gemini disponibile o chiave errata."}

    safe_p = sanitizer.sanitize(prompt)
    safe_h = sanitizer.sanitize(history)
    
    mood_map = { 1: "Diplomatico", 5: "Pragmatico", 10: "DISTRUTTIVO" }
    livello = livello_aggressivita if livello_aggressivita else 5
    mood_desc = mood_map.get(livello, "Pragmatico")

    sys_prompt = f"""
    SEI LEXVANTAGE. RUOLO: Senior Legal Strategist.
    MOOD: {livello}/10 ({mood_desc}).
    OBIETTIVO: Vendere il 'Fascicolo Documentale' ({price_info}).
    DATI TECNICI: {calc_data}
    STORICO: {safe_h}
    
    ISTRUZIONI:
    1. Analizza input e documenti.
    2. RISPONDI IN JSON:
       {{
         "fase": "intervista" (se mancano dati) O "strategia" (se ok),
         "titolo": "...", 
         "contenuto": "..." (Markdown)
       }}
    """

    payload = list(files_content)
    payload.append(f"UTENTE: {safe_p}")
    
    try:
        model = genai.GenerativeModel(active_model, system_instruction=sys_prompt, generation_config={"response_mime_type": "application/json"})
        raw_response = model.generate_content(payload).text
        clean_response = clean_json_text(raw_response)
        parsed = json.loads(clean_response)
        
        if "contenuto" in parsed: parsed["contenuto"] = sanitizer.restore(parsed["contenuto"])
        if "titolo" in parsed: parsed["titolo"] = sanitizer.restore(parsed["titolo"])
            
        return parsed

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore Tecnico", "contenuto": f"Errore modello ({active_model}): {str(e)}"}

# --- 5. GENERATORE BATCH (REFATTORED - Usa get_best_model) ---
def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, model_name_ignored):
    # ANCHE QUI: Risparmio righe riutilizzando get_best_model
    active_model = get_best_model()
    if not active_model: return {"Errore": {"titolo": "Errore", "contenuto": "Modello non trovato"}}

    results = {}
    model = genai.GenerativeModel(active_model, generation_config={"response_mime_type": "application/json"})
    
    for doc_name, task_prompt in tasks:
        full_payload = list(file_parts)
        prompt_specifico = f"""
        CONTESTO: {context_chat}
        DATI: {calc_data}
        DOC: {doc_name}
        ISTRUZIONI: {task_prompt}
        OUTPUT: JSON {{ "titolo": "...", "contenuto": "..." }} (Markdown).
        """
        full_payload.append(prompt_specifico)
        try:
            raw = model.generate_content(full_payload).text
            clean = clean_json_text(raw)
            parsed = json.loads(clean)
            results[doc_name] = parsed
        except Exception as e:
            results[doc_name] = {"titolo": f"Errore {doc_name}", "contenuto": str(e)}
    return results
