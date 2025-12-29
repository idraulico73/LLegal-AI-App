import streamlit as st
import json

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

@st.cache_resource
def init_supabase():
    if not SUPABASE_AVAILABLE: return None
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

# --- CONFIGURAZIONI ---
def get_config_tipi_causa(supabase):
    if not supabase: return None
    try:
        res = supabase.table("config_tipi_causa").select("*").execute()
        return res.data
    except: return None

def get_pricing(supabase):
    if not supabase: return None
    try:
        res = supabase.table("listino_prezzi").select("*").eq("tipo_documento", "pacchetto_base").execute()
        return res.data[0] if res.data else None
    except: return None

# --- GESTIONE FASCICOLI (CRUD COMPLETO) ---
def get_fascicoli_utente(supabase, user_id):
    """Recupera lista fascicoli per la dashboard"""
    if not supabase: return []
    res = supabase.table("fascicoli").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return res.data

def crea_fascicolo(supabase, user_id, nome, tipo, cliente, controparte):
    """Crea un nuovo fascicolo con metadati base"""
    if not supabase: return None
    meta = {"cliente_info": cliente, "controparte_info": controparte}
    data = {
        "user_id": user_id,
        "nome_riferimento": nome,
        "tipo_causa": tipo,
        "nome_cliente": cliente,
        "nome_controparte": controparte,
        "metadata": meta,
        "stato": "in_lavorazione",
        "livello_aggressivita": 5 # Default standard
    }
    res = supabase.table("fascicoli").insert(data).execute()
    return res.data[0] if res.data else None

def aggiorna_fascicolo(supabase, fascicolo_id, update_data):
    """Aggiorna campi specifici (es. chat history, documenti generati, aggressività)"""
    if not supabase: return
    supabase.table("fascicoli").update(update_data).eq("id", fascicolo_id).execute()

def elimina_fascicolo(supabase, fascicolo_id):
    if not supabase: return
    supabase.table("fascicoli").delete().eq("id", fascicolo_id).execute()
# --- AGGIUNGERE IN FONDO A modules/database.py ---

def get_listino_completo(supabase):
    """
    Recupera TUTTO il listino prezzi come dizionario per calcoli complessi.
    Return: { 'Sintesi': {row_data}, 'Diffida': {row_data}, ... }
    """
    if not supabase: return {}
    try:
        res = supabase.table("listino_prezzi").select("*").execute()
        pricing_dict = {}
        for row in res.data:
            pricing_dict[row['tipo_documento']] = row
        return pricing_dict
    except Exception as e:
        print(f"Err listino: {e}")
        return {}

def archivia_generazione(supabase, fascicolo_id, nuovi_docs_dict):
    """
    Legge lo storico esistente e aggiunge (append) i nuovi documenti.
    Gestisce sia il caso di storico vuoto che esistente.
    """
    if not supabase: return
    
    try:
        # 1. Recupera storico attuale
        res = supabase.table("fascicoli").select("documenti_generati").eq("id", fascicolo_id).execute()
        if not res.data: return
        
        storico_attuale = res.data[0].get("documenti_generati", [])
        
        # Se il campo è null o non è una lista, inizializzalo
        if not isinstance(storico_attuale, list):
            storico_attuale = []
            
        # 2. Aggiungi timestamp ai nuovi docs e converti in lista per il JSONB
        timestamp_str = str(datetime.now().strftime("%Y-%m-%d %H:%M"))
        
        for titolo, doc_data in nuovi_docs_dict.items():
            entry = {
                "titolo": titolo,
                "contenuto": doc_data.get("contenuto", ""),
                "data_creazione": timestamp_str,
                "tipo": "auto_generato" if "Chat" not in titolo else "trascrizione_chat"
            }
            storico_attuale.append(entry)
            
        # 3. Aggiorna DB
        supabase.table("fascicoli").update({"documenti_generati": storico_attuale}).eq("id", fascicolo_id).execute()
        
    except Exception as e:
        print(f"Errore archiviazione: {e}")
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

# --- IN modules/database.py ---

def registra_transazione_doc(supabase, fascicolo_id, doc_type, model_name, tokens_in, tokens_out):
    """
    CALCOLO PREZZO "VALUE BASED":
    Prezzo = Fisso + [ (CostoIn * TokIn) + (CostoOut * TokOut) ] * MoltiplicatoreModello
    """
    if not supabase: return 0.0, {}

    try:
        # 1. Recupera Moltiplicatore Modello (Es. Flash=1.0, Pro=10.0)
        mod_res = supabase.table("gemini_models").select("price_multiplier").eq("model_name", model_name).execute()
        model_multiplier = 1.0
        if mod_res.data:
            model_multiplier = float(mod_res.data[0].get('price_multiplier', 1.0))

        # 2. Recupera Listino Base del Documento
        list_res = supabase.table("listino_prezzi").select("*").eq("tipo_documento", doc_type).execute()
        
        prezzo_fisso = 0.0
        costo_base_in = 0.0
        costo_base_out = 0.0
        
        if list_res.data:
            row = list_res.data[0]
            prezzo_fisso = float(row.get('prezzo_fisso', 0.0))
            # Questi valori sono già calcolati come 0.5% e 5% dal SQL
            costo_base_in = float(row.get('prezzo_per_1k_input_token', 0.0))
            costo_base_out = float(row.get('prezzo_per_1k_output_token', 0.0))

        # 3. Calcolo Parte Variabile (Valore Intellettuale)
        valore_input = (tokens_in / 1000) * costo_base_in
        valore_output = (tokens_out / 1000) * costo_base_out
        
        # 4. Applicazione Moltiplicatore Modello solo alla parte variabile
        # (O a tutto, a seconda della tua strategia. Qui applico alla variabile come discusso)
        variabile_totale = (valore_input + valore_output) * model_multiplier
        
        prezzo_finale = prezzo_fisso + variabile_totale
        
        # 5. Creazione Snapshot
        import datetime
        doc_snapshot = {
            "titolo": doc_type,
            "tipo": "auto_generato",
            "data_creazione": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "metadata_pricing": {
                "model_used": model_name,
                "multiplier_used": model_multiplier,
                "tokens": {"input": tokens_in, "output": tokens_out},
                "components": {
                    "fixed": prezzo_fisso,
                    "variable_base": valore_input + valore_output,
                    "variable_final": variabile_totale
                },
                "final_price": prezzo_finale
            }
        }

        return prezzo_finale, doc_snapshot

    except Exception as e:
        print(f"Errore calcolo prezzo: {e}")
        return 0.0, {}
        print(f"Errore calcolo prezzo: {e}")
        return 0.0, {}
