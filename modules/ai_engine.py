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

# --- JSON CLEANER ---
def clean_json_text(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    # Rimuove char di controllo ma preserva newline validi
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == '\n' or ch == '\t')
    start = text.find('{'); end = text.rfind('}')
    if start != -1 and end != -1: text = text[start:end+1]
    return text.strip()

# --- GEMINI INIT ---
def init_ai():
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        return True
    return False

# --- LOGICA CORE 50.5: INTERVISTA ADATTIVA ---
def interroga_gemini(model_name, prompt, history, files_content, calc_data, sanitizer, price_info, livello_aggressivita):
    """
    Restituisce un DIZIONARIO JSON: {'fase', 'titolo', 'contenuto'}
    """
    safe_p = sanitizer.sanitize(prompt)
    safe_h = sanitizer.sanitize(history)
    
    # Mapping Aggressività 1-10
    mood_map = {
        1: "Diplomatico, Conciliante, Orientato alla Pace",
        2: "Molto Cauto e Formale",
        3: "Cauto",
        4: "Neutrale/Equilibrato",
        5: "Pragmatico e Fermo (Standard)",
        6: "Deciso",
        7: "Molto Deciso",
        8: "Aggressivo",
        9: "Molto Aggressivo (Legal Warfare)",
        10: "DISTRUTTIVO / 'Scorched Earth'"
    }
    # Fallback sicuro se livello_aggressivita è None
    livello = livello_aggressivita if livello_aggressivita else 5
    mood_desc = mood_map.get(livello, "Pragmatico")

    sys_prompt = f"""
    SEI LEXVANTAGE. RUOLO: Senior Legal Strategist.
    MOOD IMPOSTATO DALL'UTENTE: {livello}/10 ({mood_desc}).
    
    OBIETTIVO FINALE: Vendere il 'Fascicolo Documentale Completo' ({price_info}).
    
    DATI TECNICI (Calcolatore): {calc_data}
    STORICO CHAT: {safe_h}
    
    ISTRUZIONI LOGICHE (INTERVISTA ADATTIVA):
    1. Analizza l'input dell'utente e i documenti caricati.
    2. VALUTA LA TUA CONOSCENZA DEL CASO:
       - Hai i 4 PILASTRI? (FATTI, NUMERI, CONTROPARTE, OBIETTIVO DELL'UTENTE).
    
    3. GENERA UNA RISPOSTA JSON RIGOROSA:
       {{
         "fase": "...",  <-- "intervista" (se mancano dati) OPPURE "strategia" (se hai tutto)
         "titolo": "...", 
         "contenuto": "..." <-- Usa Markdown qui.
       }}
    
    --- SCENARIO A: MANCANO DATI ("fase": "intervista") ---
    Se mancano dettagli CRITICI, NON inventare strategie.
    Nel 'contenuto': Rispondi con una lista di domande numerate necessarie a capire il caso.
    Sii diretto. Se l'utente scrive solo "ho un problema", chiedi "Quale problema? Con chi? Quando?".
    
    --- SCENARIO B: QUADRO CHIARO ("fase": "strategia") ---
    Se hai abbastanza elementi, elabora la strategia usando il MOOD {mood_desc}.
    Nel 'contenuto':
    - Spiega la strategia legale/tecnica.
    - AL TERMINE, aggiungi una Call To Action esplicita:
      "La strategia è definita. Sono pronto a generare il Fascicolo Esecutivo ora. Procediamo?"
    """

    payload = list(files_content)
    payload.append(f"UTENTE: {safe_p}")
    
    try:
        model = genai.GenerativeModel(model_name, system_instruction=sys_prompt, generation_config={"response_mime_type": "application/json"})
        raw_response = model.generate_content(payload).text
        clean_response = clean_json_text(raw_response)
        
        # Parsing JSON
        try:
            parsed = json.loads(clean_response)
        except:
            # Fallback se l'AI sbaglia il formato JSON
            parsed = {
                "fase": "strategia",
                "titolo": "Analisi",
                "contenuto": raw_response
            }
        
        # Restore Privacy
        if "contenuto" in parsed: parsed["contenuto"] = sanitizer.restore(parsed["contenuto"])
        if "titolo" in parsed: parsed["titolo"] = sanitizer.restore(parsed["titolo"])
            
        return parsed

    except Exception as e:
        return {"fase": "errore", "titolo": "Errore Tecnico", "contenuto": str(e)}

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
        FORMATO: JSON {{ "titolo": "...", "contenuto": "..." }}. Contenuto in Markdown.
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
