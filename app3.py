import streamlit as st
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Ingegneria Forense & Strategy", layout="wide")

# --- FUNZIONI DI UTILITÀ (MOCKUP) ---
def stima_pagine_pdf(file):
    # Stima 1 pagina ogni 100KB
    return max(1, int(file.size / 100000))

def genera_anteprima_ai(testo_input, tipo_output):
    time.sleep(1) # Simula elaborazione
    anteprime = {
        "timeline": "12/05/2020: Deposito CILA...\n15/06/2021: Notifica Atto di Citazione...\n[CONTENUTO BLOCCATO]",
        "sintesi": "Il contenzioso verte sulla difformità urbanistica...\n[CONTENUTO BLOCCATO]",
        "punti": "1. Mancanza di Agibilità...\n2. Errore calcolo superfici CTU...\n[OSCURATO]",
        "strategia": "Si consiglia Istanza di Sospensione...\n[VERSIONE FULL RICHIESTA]"
    }
    return anteprime.get(tipo_output, "Anteprima non disponibile")

# --- SIDEBAR: CONTATTI ---
with st.sidebar:
    st.markdown("### 📞 Contatti Diretti")
    st.markdown("""
    <div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px;'>
        <p>📱 <a href='https://wa.me/393758269561' target='_blank'><strong>WhatsApp</strong></a></p>
        <p>📅 <a href='https://calendar.app.google/y4QwPGmH9V7yGpny5' target='_blank'><strong>Prenota Consulenza</strong></a></p>
        <p>✉️ <a href='mailto:info@periziedilizie.it'><strong>info@periziedilizie.it</strong></a></p>
    </div>
    """, unsafe_allow_html=True)
    st.info("ℹ️ I documenti completi vengono sbloccati dopo il pagamento.")

# --- TITOLO ---
st.title("⚖️ Ingegneria Forense & Strategy AI")
st.markdown("Strumenti avanzati per Avvocati e Studi Legali. Analisi tecnica, strategia e calcolo del valore.")

# --- TABS ---
tab1, tab2 = st.tabs(["🏠 Calcolatore & Checklist CTU", "📄 Macina Documenti (AI)"])

# ==============================================================================
# TAB 1: CHECKLIST & CALCOLATORE
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
        c3 = st.checkbox("Difformità Catastali")
        c4 = st.checkbox("Difformità Volumetriche")
        c5 = st.checkbox("Impianti non a norma")
        
        btn_calcola = st.button("📉 Calcola Valore Reale", type="primary")

    with col2:
        if btn_calcola:
            deprezzamento = 0
            rischi = []
            if c1: 
                deprezzamento += 0.15 
                rischi.append("Aliud pro alio (Cass. 24343/2011)")
            if c2: 
                deprezzamento += 0.20
                rischi.append("Rischio incommerciabilità")
            if c3: deprezzamento += 0.02
            if c4: deprezzamento += 0.10
            if c5: deprezzamento += 0.05
            
            valore_reale = valore_mercato * (1 - deprezzamento)
            perdita = valore_mercato - valore_reale
            
            st.success(f"### Valore Giudiziale Stimato: € {valore_reale:,.2f}")
            st.metric("Deprezzamento Totale", f"- {deprezzamento*100:.0f}%", f"- € {perdita:,.2f}")
            
            st.divider()
            st.warning("🔒 **ANTEPRIMA RELAZIONE TECNICA (Bozza)**")
            st.text_area("Anteprima", "OGGETTO: Analisi critica CTU...\n[RESTO BLOCCATO]", height=100, disabled=True)
            st.button("🛒 Acquista Relazione (€ 390)", key="btn_buy_rel")

# ==============================================================================
# TAB 2: MACINA DOCUMENTI (CORRETTO)
# ==============================================================================
with tab2:
    st.header("🤖 Analisi Documentale AI")
    st.info("Carica fascicoli completi (PDF, Scansioni JPG/PNG). L'AI estrarrà dati e strategia.")
    
    uploaded_files = st.file_uploader("Trascina qui i tuoi file", accept_multiple_files=True, type=['pdf', 'jpg', 'png', 'jpeg'])
    
    prodotti = {
        "timeline": {"nome": "Timeline Cronologica", "prezzo": 90},
        "sintesi": {"nome": "Sintesi Vicende", "prezzo": 90},
        "punti": {"nome": "Punti di Attacco", "prezzo": 190},
        "strategia": {"nome": "Strategia Processuale", "prezzo": 390}
    }
    selected_prods = []
    
    if uploaded_files:
        totale_pagine = sum([stima_pagine_pdf(f) for f in uploaded_files])
        costo_entry = totale_pagine * 1.0
        
        st.write(f"📊 **Analisi Volumetrica:** {len(uploaded_files)} file caricati, circa {totale_pagine} pagine.")
        st.write(f"💰 **Costo Entry:** € {costo_entry:.2f}")
        
        st.divider()
        st.subheader("Seleziona Prodotti")
        
        c_p1, c_p2, c_p3, c_p4 = st.columns(4)
        with c_p1:
            if st.checkbox("Timeline (€ 90)"): selected_prods.append("timeline")
        with c_p2:
            if st.checkbox("Sintesi (€ 90)"): selected_prods.append("sintesi")
        with c_p3:
            if st.checkbox("Punti Attacco (€ 190)"): selected_prods.append("punti")
        with c_p4:
            if st.checkbox("Strategia (€ 390)"): selected_prods.append("strategia")
            
        totale_ordine = costo_entry + sum([prodotti[k]["prezzo"] for k in selected_prods])
        
        if selected_prods:
            st.divider()
            st.subheader(f"🛒 Totale Ordine: € {totale_ordine:.2f}")

            # --- 🛠️ SEZIONE ADMIN (BACKDOOR) ---
            is_admin = False
            with st.expander("🛠️ Area Riservata (Admin / Debug)"):
                # ATTENZIONE ALL'ALLINEAMENTO QUI SOTTO
                admin_pwd = st.text_input("Password Admin", type="password", help="Inserisci la password per scaricare senza pagare")
                
                # Recupera la password dai secrets (o usa 'admin' se non settata)
                segreto_reale = st.secrets.get("ADMIN_PASSWORD", "admin")
                
                if admin_pwd == segreto_reale:
                    is_admin = True
                    st.success("🔓 Modalità Admin Attiva! Bypass pagamento abilitato.")

            # --- VISUALIZZAZIONE BOTTONI ---
            if is_admin or "session_id" in st.query_params:
                
                if not is_admin:
                    st.success("✅ Pagamento confermato!")
                
                st.write("### 📥 Download Documenti")
                
                for k in selected_prods:
                    # Simulazione contenuto
                    file_content = f"DOCUMENTO: {prodotti[k]['nome']}\nCAUSA: Cavalaglio\nGenerato il: {datetime.now()}"
                    
                    st.download_button(
                        label=f"Scarica {prodotti[k]['nome']}",
                        data=file_content,
                        file_name=f"{k}_Analisi.txt",
                        mime="text/plain",
                        key=f"btn_down_{k}"
                    )
                
                if "session_id" in st.query_params:
                    if st.button("Chiudi e Torna alla Home"):
                        st.query_params.clear()
                        st.rerun()

            else:
                st.button("💳 Paga e Scarica Subito", type="primary", disabled=True, help="Configura Stripe per attivare")
                st.info("⚠️ Pagamento disabilitato in questa demo (usa Admin Mode)")
