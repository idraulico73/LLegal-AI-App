import streamlit as st
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Ingegneria Forense & Strategy", layout="wide")

# --- FUNZIONI DI UTILITÀ (MOCKUP) ---
def stima_pagine_pdf(file):
    # Qui andrebbe l'integrazione con PyPDF2 per contare le pagine reali
    # Per ora stimiamo 1 pagina per MB o fisso per demo
    return max(1, int(file.size / 100000))

def genera_anteprima_ai(testo_input, tipo_output):
    time.sleep(1) # Simula elaborazione
    anteprime = {
        "timeline": "12/05/2020: Deposito CILA...\n15/06/2021: Notifica Atto di Citazione...\n[CONTENUTO BLOCCATO - ACQUISTA PER VEDERE TUTTO]",
        "sintesi": "Il contenzioso verte sulla difformità urbanistica dell'immobile sito in...\nLe parti sostengono rispettivamente che...\n[CONTENUTO BLOCCATO]",
        "punti_attacco": "1. Mancanza di Agibilità (Cass. Civ. 2011)...\n2. Errore calcolo superfici CTU...\n3. [OSCURATO]...\n4. [OSCURATO]...",
        "strategia": "Si consiglia di procedere con Istanza di Sospensione basata su...\nIl valore recuperabile è stimato in...\n[CONTENUTO COMPLETO DISPONIBILE NELLA VERSIONE FULL]"
    }
    return anteprime.get(tipo_output, "Anteprima non disponibile")

# --- SIDEBAR: CONTATTI SEMPRE VISIBILI ---
with st.sidebar:
    st.image("https://via.placeholder.com/150x50?text=LOGO+STUDIO", use_column_width=True) # Placeholder Logo
    st.markdown("### 📞 Contatti Diretti")
    
    st.markdown("""
    <div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px;'>
        <p>📱 <a href='https://wa.me/393758269561' target='_blank'><strong>WhatsApp</strong></a></p>
        <p>📅 <a href='https://calendar.app.google/y4QwPGmH9V7yGpny5' target='_blank'><strong>Prenota Consulenza</strong></a></p>
        <p>✉️ <a href='mailto:info@periziedilizie.it'><strong>info@periziedilizie.it</strong></a></p>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("ℹ️ I documenti completi vengono sbloccati dopo il pagamento.")

# --- TITOLO PRINCIPALE ---
st.title("⚖️ Ingegneria Forense & Strategy AI")
st.markdown("Strumenti avanzati per Avvocati e Studi Legali. Analisi tecnica, strategia e calcolo del valore.")

# --- TABS PRINCIPALI ---
tab1, tab2 = st.tabs(["🏠 Calcolatore & Checklist CTU", "📄 Macina Documenti (AI)"])

# ==============================================================================
# TAB 1: CHECKLIST & CALCOLATORE (Unified)
# ==============================================================================
with tab1:
    st.header("Analisi Rapida Valore & Criticità")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Dati Immobile")
        valore_mercato = st.number_input("Valore di Mercato Teorico (€)", min_value=0, value=350000, step=10000)
        mq_comm = st.number_input("Superficie Commerciale (mq)", min_value=0, value=120)
        
        st.subheader("Checklist Criticità")
        c1 = st.checkbox("Assenza Certificato Agibilità/Abitabilità")
        c2 = st.checkbox("Condono in corso (non perfezionato)")
        c3 = st.checkbox("Difformità Catastali (es. tramezzi spostati)")
        c4 = st.checkbox("Difformità Volumetriche (es. ampliamenti, chiusure)")
        c5 = st.checkbox("Impianti non a norma (no DICO)")
        
        btn_calcola = st.button("📉 Calcola Valore Reale e Genera Report", type="primary")

    with col2:
        if btn_calcola:
            # Logica di calcolo (Semplificata per demo)
            deprezzamento = 0
            rischi = []
            
            if c1: 
                deprezzamento += 0.15 
                rischi.append("Aliud pro alio (Cass. 24343/2011)")
            if c2: 
                deprezzamento += 0.20
                rischi.append("Rischio incommerciabilità e costi oblazione")
            if c3: deprezzamento += 0.02
            if c4: deprezzamento += 0.10
            if c5: deprezzamento += 0.05
            
            valore_reale = valore_mercato * (1 - deprezzamento)
            perdita = valore_mercato - valore_reale
            
            # OUTPUT GRATUITO
            st.success(f"### Valore Giudiziale Stimato: € {valore_reale:,.2f}")
            st.metric("Deprezzamento Totale", f"- {deprezzamento*100:.0f}%", f"- € {perdita:,.2f}")
            
            # OUTPUT A PAGAMENTO (ANTEPRIMA)
            st.divider()
            st.warning("🔒 **ANTEPRIMA RELAZIONE TECNICA DI PARTE (Bozza)**")
            
            report_preview = f"""
            OGGETTO: Analisi critica CTU e Valutazione
            
            Dall'analisi preliminare emergono i seguenti punti di attacco alla CTU avversaria:
            1. {rischi[0] if rischi else 'Nessuna criticità maggiore rilevata'}...
            2. Il valore non considera i costi di ripristino stimati in...
            
            [IL RESTO DEL DOCUMENTO È BLOCCATO]
            """
            st.text_area("Anteprima Documento", report_preview, height=150, disabled=True)
            
            col_buy, col_code = st.columns(2)
            with col_buy:
                st.write("**Prezzo Relazione Completa: € 390,00**")
                if st.button("🛒 Acquista Relazione CTU"):
                    st.toast("📧 Ordine inviato! Controlla la tua mail per il link di pagamento Stripe.")
                    # Qui invieresti la mail reale a te stesso con i dettagli dell'ordine
            
            with col_code:
                codice_sblocco = st.text_input("Hai già pagato? Inserisci Codice Sblocco", key="code_ctu")
                if st.button("Sblocca Download", key="btn_unlock_ctu"):
                    if codice_sblocco == "DEMO123": # Codice demo
                        st.download_button("📥 Scarica Relazione.docx", data="Contenuto Documento...", file_name="Relazione_CTU.docx")
                    else:
                        st.error("Codice non valido.")

# ==============================================================================
# TAB 2: MACINA DOCUMENTI (Con Backdoor Admin)
# ==============================================================================
with tab2:
    st.header("🤖 Analisi Documentale AI")
    st.info("Carica fascicoli completi (PDF, Scansioni JPG/PNG). L'AI estrarrà dati e strategia.")
    
    uploaded_files = st.file_uploader("Trascina qui i tuoi file", accept_multiple_files=True, type=['pdf', 'jpg', 'png', 'jpeg'])
    
    # --- Inizializzazione variabili ---
    prodotti = {
        "timeline": {"nome": "Timeline Cronologica", "prezzo": 90},
        "sintesi": {"nome": "Sintesi Vicende", "prezzo": 90},
        "punti": {"nome": "Punti di Attacco (CTU/Controparte)", "prezzo": 190},
        "strategia": {"nome": "Strategia Processuale (Bozza)", "prezzo": 390}
    }
    selected_prods = []
    totale_ordine = 0.0

    if uploaded_files:
        # Calcolo Costi
        totale_pagine = sum([stima_pagine_pdf(f) for f in uploaded_files])
        costo_entry = totale_pagine * 1.0 # 1€ a pagina
        
        st.write(f"📊 **Analisi Volumetrica:** {len(uploaded_files)} file caricati, circa {totale_pagine} pagine totali.")
        st.write(f"💰 **Costo elaborazione (Entry Fee):** € {costo_entry:.2f}")
        
        st.divider()
        st.subheader("Seleziona Prodotti da Generare")
        
        # Selezione Prodotti
        col_p1, col_p2, col_p3, col_p4 = st.columns(4)
        with col_p1:
            if st.checkbox("Timeline (€ 90)"): selected_prods.append("timeline")
        with col_p2:
            if st.checkbox("Sintesi (€ 90)"): selected_prods.append("sintesi")
        with col_p3:
            if st.checkbox("Punti Attacco (€ 190)"): selected_prods.append("punti")
        with col_p4:
            if st.checkbox("Strategia (€ 390)"): selected_prods.append("strategia")
            
        totale_ordine = costo_entry + sum([prodotti[k]["prezzo"] for k in selected_prods])
        
        if selected_prods:
            st.divider()
            st.subheader(f"🛒 Totale Ordine: € {totale_ordine:.2f}")

           # --- 🛠️ SEZIONE ADMIN (BACKDOOR) ---
            is_admin = False
            with st.expander("🛠️ Area Riservata (Admin / Debug)"):
                # Nota: assicurati che questa riga e le successive siano allineate
                admin_pwd = st.text_input("Password Admin", type="password", help="Inserisci la password per scaricare senza pagare")
                
                # Verifica sicura tramite st.secrets (o fallback per test locale)
                segreto_reale = st.secrets.get("ADMIN_PASSWORD", "admin") 
                
                if admin_pwd == segreto_reale:
                    is_admin = True
                    st.success("🔓 Modalità Admin Attiva! Bypass pagamento abilitato.")

            # --- LOGICA DI VISUALIZZAZIONE BOTTONI ---
            
            # CONDIZIONE DI SBLOCCO: O sei Admin, O hai pagato (session_id nell'URL)
            if is_admin or "session_id" in st.query_params:
                
                if "session_id" in st.query_params and not is_admin:
                    st.balloons()
                    st.success("✅ Pagamento confermato! Ecco i tuoi documenti.")
                
                st.write("### 📥 Download Documenti")
                
                # Qui generi i file veri. Per ora usiamo dati simulati.
                for k in selected_prods:
                    # SIMULAZIONE CONTENUTO FILE
                    file_content = f"DOCUMENTO: {prodotti[k]['nome']}\nCAUSA: Cavalaglio\nDATA: {datetime.now()}\n\n[Analisi generata dall'AI...]"
                    
                    st.download_button(
                        label=f"Scarica {prodotti[k]['nome']}",
                        data=file_content,
                        file_name=f"{k}_Analisi_Cavalaglio.txt",
                        mime="text/plain",
                        key=f"btn_down_{k}"
                    )
                
                # Tasto per resettare l'URL dopo il pagamento
                if "session_id" in st.query_params:
                    if st.button("Chiudi e Torna alla Home"):
                        st.query_params.clear()
                        st.rerun()

            # CONDIZIONE NORMALE: Mostra pulsante Pagamento
            else:
                if st.button("💳 Paga e Scarica Subito", type="primary"):
                    # Qui andrà la chiamata a crea_sessione_stripe()
                    # Per ora mettiamo un link finto o disabilitato
                    st.info("⚠️ Configura Stripe nei Secrets per attivare il pagamento reale.")
                    # st.link_button("Procedi al pagamento", url_pagamento)


