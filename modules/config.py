# modules/config.py

APP_NAME = "LexVantage"
APP_VER = "Rev 50.5 (Case Management & Adaptive AI)" # <--- AGGIORNATO

# Fallback Pricing (se DB offline)
PRICING_CONFIG_FALLBACK = {
    "pacchetto_base": 150.00,
    "descrizione": "Include: Sintesi Strategica, Matrice Rischi, Nota Difensiva, Quesiti Tecnici, Bozza Transazione."
}

# Fallback Tipi Causa
# --- IN modules/config.py ---

CASE_TYPES_FALLBACK = {
    "immobiliare": {
        "label": "🏗️ Immobiliare & Condoni", 
        "docs": [
            "Sintesi", 
            "Timeline", 
            "Analisi_Critica", 
            "Matrice_Rischi", 
            "Quesiti_Tecnici", 
            "Strategia", 
            "Nota_Difensiva", 
            "Punti_Attacco", 
            "Bozza_Accordo"
        ]
    },
    "medico": {
        "label": "⚕️ Resp. Medica (Malpractice)", 
        "docs": [
            "Sintesi", 
            "Timeline", 
            "Analisi_Critica", # Fondamentale per cartelle cliniche
            "Quesiti_Tecnici", # Fondamentale per CTU medico-legale
            "Strategia", 
            "Nota_Difensiva", 
            "Bozza_Accordo"
        ]
    },
    "appalti": {
        "label": "🧱 Appalti & Costruzioni", 
        "docs": [
            "Sintesi", 
            "Timeline", # Fondamentale per ritardi cantiere
            "Matrice_Rischi", 
            "Punti_Attacco", # Utile per contestare riserve
            "Quesiti_Tecnici", 
            "Nota_Difensiva", 
            "Bozza_Accordo"
        ]
    },
    "lavoro": {
        "label": "💼 Diritto del Lavoro", 
        "docs": [
            "Sintesi", 
            "Timeline", # Fondamentale per procedimenti disciplinari
            "Strategia", 
            "Punti_Attacco", 
            "Nota_Difensiva", 
            "Bozza_Accordo" # Conciliazioni sindacali
        ]
    },
    "famiglia": {
        "label": "👨‍👩‍👧 Diritto di Famiglia", 
        "docs": [
            "Sintesi", 
            "Timeline", # Utile per storia coniugale
            "Strategia", 
            "Nota_Difensiva", 
            "Bozza_Accordo" # Separazioni consensuali
        ]
    }
}

# Aggiorna anche i metadati per i prompt AI corretti
DOCS_METADATA = {
    "Sintesi": "Sintesi Esecutiva chiara e strutturata dei fatti.",
    "Timeline": "Elenco cronologico rigoroso degli eventi con date in grassetto.",
    "Matrice_Rischi": "Tabella di analisi rischi/opportunità e probabilità.",
    "Strategia": "Analisi strategica basata su Game Theory e punti di forza.",
    "Nota_Difensiva": "Bozza di atto difensivo formale e persuasivo.",
    "Punti_Attacco": "Elenco aggressivo delle debolezze della controparte.",
    "Bozza_Accordo": "Bozza di accordo transattivo o conciliazione.",
    "Analisi_Critica": "Analisi critica dei documenti avversari e contraddizioni.",
    "Quesiti_Tecnici": "Quesiti tecnici precisi per il Consulente (CTU/CTP)."
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
