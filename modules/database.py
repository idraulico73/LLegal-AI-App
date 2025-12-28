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
