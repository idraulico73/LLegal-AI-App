# modules/database.py
import streamlit as st
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

def get_config_tipi_causa(supabase):
    """Recupera configurazione dinamica tipi causa"""
    if not supabase: return None
    try:
        # Legge dalla tabella config_tipi_causa che vedo nel tuo JSON
        res = supabase.table("config_tipi_causa").select("*").execute()
        return res.data
    except: return None

def get_pricing(supabase):
    """Recupera prezzi dal DB"""
    if not supabase: return None
    try:
        res = supabase.table("listino_prezzi").select("*").eq("tipo_documento", "pacchetto_base").execute()
        if res.data: return res.data[0]
    except: pass
    return None

def save_fascicolo(supabase, user_id, nome, tipo, dati_tec, chat_hist):
    """Salva stato lavoro"""
    if not supabase: return
    return supabase.table("fascicoli").upsert({
        "user_id": user_id,
        "nome_riferimento": nome,
        "tipo_causa": tipo,
        "dati_tecnici": dati_tec,
        "cronologia_chat": chat_hist,
        "stato": "in_lavorazione"
    }).execute()
