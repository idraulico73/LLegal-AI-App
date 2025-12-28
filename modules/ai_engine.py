# modules/ai_engine.py
import re
import json
import streamlit as st
import google.generativeai as genai

# --- PRIVACY SHIELD ---
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

# --- JSON CLEANING (Il fix per rev 50.4) ---
def clean_json_text(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == '\n' or ch == '\t')
    start = text.find('{'); end = text.rfind('}')
    if start != -1 and end != -1: text = text[start:end+1]
    return text.strip()

# --- GEMINI CORE ---
def init_ai():
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        return True
    return False

def interroga_gemini(model_name, prompt, history, files_parts, calc_data, is_commit_phase, sanitizer, price_info):
    safe_p = sanitizer.sanitize(prompt)
    safe_h = sanitizer.sanitize(history)
    
    sys_prompt = f"""
    SEI LEXVANTAGE. MOOD: AGGRESSIVO E PRAGMATICO.
    DATI TECNICI: {calc_data}
    STORICO: {safe_h}
    NOTA PREZZO: {price_info}
    """
    if is_commit_phase:
        sys_prompt += "\nTASK: Sintetizza strategia, mostra prezzo e chiedi conferma."

    payload = list(files_parts)
    payload.append(f"UTENTE: {safe_p}")
    
    try:
        model = genai.GenerativeModel(model_name, system_instruction=sys_prompt)
        return sanitizer.restore(model.generate_content(payload).text)
    except Exception as e: return f"Errore AI: {e}"

def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, model_name):
    results = {}
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    for doc_name, task_prompt in tasks:
        full_payload = list(file_parts)
        prompt_specifico = f"""
        CONTESTO COMPLETO: {context_chat}
        DATI CALCOLATORE: {calc_data}
        
        OBIETTIVO: Genera documento '{doc_name}'.
        ISTRUZIONI: {task_prompt}
        
        FORMATO: JSON {{ "titolo": "...", "contenuto": "..." }}.
        Il contenuto deve essere Markdown valido.
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
