# modules/config.py

APP_NAME = "LexVantage"
APP_VER = "Rev 50.5 (Case Management & Adaptive AI)" # <--- AGGIORNATO

# Fallback Pricing (se DB offline)
PRICING_CONFIG_FALLBACK = {
    "pacchetto_base": 150.00,
    "descrizione": "Include: Sintesi Strategica, Matrice Rischi, Nota Difensiva, Quesiti Tecnici, Bozza Transazione."
}

# Fallback Tipi Causa
CASE_TYPES_FALLBACK = {
    "immobiliare": {
        "label": "🏗️ Immobiliare & Vizi", 
        "docs": ["Sintesi", "Matrice_Rischi", "Nota_Difensiva", "Quesiti_CTU", "Bozza_Transazione"]
    },
    "medico": {
        "label": "⚕️ Resp. Medica", 
        "docs": ["Sintesi", "Analisi_Danno_Biologico", "Relazione_Nesso_Causale", "Nota_Difensiva", "Richiesta_Risarcitoria"]
    },
    "appalti": {
        "label": "🧱 Appalti & Riserve", 
        "docs": ["Sintesi", "Analisi_Cronoprogramma", "Registro_Riserve", "Contestazione_Vizi", "Diffida_Adempiere"]
    }
}

DOCS_METADATA = {
    "Sintesi": "Sintesi Esecutiva e Strategica",
    "Matrice_Rischi": "Matrice dei Rischi Economici",
    "Nota_Difensiva": "Nota Difensiva Aggressiva",
    "Quesiti_CTU": "Quesiti Tecnici Demolitori",
    "Bozza_Transazione": "Bozza Accordo Transattivo",
    "Analisi_Danno_Biologico": "Valutazione Danno Biologico",
    "Relazione_Nesso_Causale": "Analisi Nesso Causale",
    "Richiesta_Risarcitoria": "Lettera Richiesta Danni",
    "Analisi_Cronoprogramma": "Analisi Ritardi",
    "Registro_Riserve": "Esplicazione Riserve",
    "Contestazione_Vizi": "Contestazione Vizi",
    "Diffida_Adempiere": "Diffida ad Adempiere",
    "Trascrizione_Chat": "Cronologia Completa"
}
