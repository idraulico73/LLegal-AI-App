import re
import json
import streamlit as st
import google.generativeai as genai
import logging

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

# 1. FUNZIONE CLEAN JSON PIÙ ROBUSTA
def clean_json_text(text):
    """
    Pulisce il testo da markdown e tenta di estrarre UN SOLO oggetto JSON valido.
    Gestisce il caso 'Extra data' troncando il testo dopo la chiusura corretta.
    """
    # Rimuovi markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text)
    
    # Trova la prima graffa aperta
    start = text.find('{')
    if start == -1: return ""
    text = text[start:]
    
    # TENTATIVO 1: Parsing diretto (se è pulito)
    try:
        return json.loads(text) # Ritorna direttamente l'oggetto se funziona
    except json.JSONDecodeError:
        pass # Continua con la pulizia aggressiva

    # TENTATIVO 2: Trova l'ultima graffa chiusa
    end = text.rfind('}')
    if end == -1: return ""
    
    candidate = text[:end+1]
    
    # Se fallisce ancora con "Extra data", significa che ci sono più oggetti {..} {..}
    # Cerchiamo di parsare iterativamente trovando la chiusura logica
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        if "Extra data" in str(e):
            # Errore classico: c'è roba dopo il JSON valido. 
            # Dobbiamo trovare dove finisce davvero il primo oggetto.
            # Metodo euristico: contiamo le graffe.
            balance = 0
            for i, char in enumerate(text):
                if char == '{': balance += 1
                elif char == '}': balance -= 1
                if balance == 0:
                    # Trovata la fine del primo oggetto
                    return json.loads(text[:i+1])
        return None # Parsing fallito

# 2. CALCOLO PREZZI DINAMICO (Nuova Funzione)
def stima_costo_token(context_text, num_docs, pricing_row):
    """
    Calcola il prezzo preventivo basato sui token.
    1 Token ~= 4 caratteri (approssimazione standard per stime)
    """
    if not pricing_row:
        # Fallback se il DB è offline o vuoto
        return 150.00 
    
    # Prezzi dal DB (default a 0 se null)
    p_fisso = float(pricing_row.get('prezzo_fisso', 0) or 0)
    p_in_1k = float(pricing_row.get('prezzo_per_1k_input_token', 0.02) or 0.02) # Esempio default OpenAI/Gemini
    p_out_1k = float(pricing_row.get('prezzo_per_1k_output_token', 0.05) or 0.05)
    moltiplicatore = float(pricing_row.get('moltiplicatore_complessita', 1.0) or 1.0)

    # Conteggio Input
    len_input = len(context_text)
    token_input_est = len_input / 4

    # Stima Output (Media 2000 caratteri per documento legale denso)
    len_output_est = num_docs * 2000 
    token_output_est = len_output_est / 4

    # Calcolo
    costo_input = (token_input_est / 1000) * p_in_1k
    costo_output = (token_output_est / 1000) * p_out_1k
    
    totale = (costo_input + costo_output + p_fisso) * moltiplicatore
    
    # Arrotondamento (minimo 5 euro per evitare micro-transazioni ridicole)
    return max(5.0, round(totale, 2))

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

# 3. AGGIORNAMENTO GENERATORE BATCH (System Prompt Indurito)
def genera_docs_json_batch(tasks, context_chat, file_parts, calc_data, model_name_ignored):
    active_model = get_best_model() # Usa la tua funzione esistente
    if not active_model: return {"Errore": {"titolo": "Errore", "contenuto": "Modello non trovato"}}

    results = {}
    model = genai.GenerativeModel(active_model, generation_config={"response_mime_type": "application/json"})
    
    # Prompt di Sistema Rinforzato per JSON PURO
    system_instruction = """
    SEI UN GENERATORE DI API JSON. 
    IL TUO UNICO OUTPUT DEVE ESSERE UN OGGETTO JSON VALIDO.
    NON SCRIVERE NULLA PRIMA DI '{'. 
    NON SCRIVERE NULLA DOPO '}'.
    NON USARE MARKDOWN.
    NON SPIEGARE IL CODICE.
    OUTPUT FORMAT: { "titolo": "...", "contenuto": "..." }
    """

    for doc_name, task_prompt in tasks:
        full_payload = list(file_parts)
        
        prompt_specifico = f"""
        {system_instruction}
        
        CONTESTO FASCICOLO: {context_chat}
        DATI TECNICI: {calc_data}
        
        OBIETTIVO DOCUMENTO: {doc_name}
        ISTRUZIONI DETTAGLIATE: {task_prompt}
        """
        
        full_payload.append(prompt_specifico)
        
        try:
            # Chiamata all'AI
            raw_response = model.generate_content(full_payload).text
            
            # Pulizia Avanzata
            cleaned_obj = clean_json_text(raw_response)
            
            if isinstance(cleaned_obj, dict):
                results[doc_name] = cleaned_obj
            else:
                # Fallback se il parsing fallisce ancora
                results[doc_name] = {
                    "titolo": f"Errore Formato {doc_name}", 
                    "contenuto": f"L'AI ha generato un JSON non valido. Raw output: {raw_response[:200]}..."
                }

        except Exception as e:
            results[doc_name] = {"titolo": "Errore Tecnico", "contenuto": str(e)}
            
    return results

# --- FINE MODIFICHE ---
