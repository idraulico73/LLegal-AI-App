# modules/config.py

APP_NAME = "LexVantage"
APP_VER = "Rev 50.4 (Modular)"

# Fallback Pricing (se DB offline)
PRICING_CONFIG_FALLBACK = {
    "pacchetto_base": 150.00,
    "descrizione": "Include: Sintesi Strategica, Matrice Rischi, Nota Difensiva, Quesiti Tecnici, Bozza Transazione."
}

# Fallback Tipi Causa (se DB offline)
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

# Metadati Documenti (Descrizioni per l'AI)
DOCS_METADATA = {
    "Sintesi": "Sintesi Esecutiva e Strategica (per il Cliente)",
    "Matrice_Rischi": "Matrice dei Rischi Economici (Tabella)",
    "Nota_Difensiva": "Nota Difensiva Aggressiva (per il Giudice)",
    "Quesiti_CTU": "Quesiti Tecnici Demolitori per il CTU",
    "Bozza_Transazione": "Bozza Accordo Transattivo",
    "Analisi_Danno_Biologico": "Valutazione Danno Biologico e Morale",
    "Relazione_Nesso_Causale": "Analisi Medico-Legale Nesso Causale",
    "Richiesta_Risarcitoria": "Lettera di Richiesta Danni",
    "Analisi_Cronoprogramma": "Analisi Ritardi e Cronoprogramma",
    "Registro_Riserve": "Esplicazione Riserve Contabili",
    "Contestazione_Vizi": "Lettera Contestazione Vizi Opere",
    "Diffida_Adempiere": "Diffida ad Adempiere ex art. 1454 cc",
    "Trascrizione_Chat": "Cronologia Completa Analisi AI"
}
