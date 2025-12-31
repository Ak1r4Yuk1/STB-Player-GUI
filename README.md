🎨 Stalker Turbo Player GUI

Un client IPTV premium con interfaccia grafica moderna e reattiva per portali Stalker.

Stalker Turbo Player è un'applicazione desktop basata su PyQt6 che trasforma l'esperienza dei portali Stalker in un'app fluida, elegante e facile da usare. Dimentica le vecchie interfacce lente: questo player è ottimizzato per la velocità e la bellezza visiva.
✨ Caratteristiche Esclusive (GUI)

    🌓 Design Borderless: Interfaccia moderna senza bordi, con trasparenze e angoli arrotondati.

    🚀 Turbo Engine Asincrono: Caricamento dei dati e delle immagini in background per evitare blocchi dell'interfaccia.

    🖼️ Galleria Poster & Loghi: Download e caching automatico delle locandine dei film e dei loghi dei canali TV.

    🍿 Dettagli Cinematici: Visualizzazione di trame, cast, registi, anno di uscita e rating IMDB.

    📁 Gestione Avanzata Serie: Selettori dedicati per stagioni ed episodi con caricamento dinamico.

    🔍 Ricerca Intelligente: Filtro dei contenuti in tempo reale con debounce per una ricerca fluida.

    📽️ Mini-Player Integrato: Supporto alla riproduzione tramite MPV con gestione automatica del processo.

🛠 Requisiti

    Python 3.9+

    MPV Player: Necessario per la riproduzione video.

        Windows: Assicurati che mpv.exe sia nel tuo PATH di sistema.

        Linux/macOS: Installa tramite il tuo package manager (apt, brew).

🚀 Guida all'Avvio

   Installazione Dipendenze:
    
    pip install PyQt6 requests

Esecuzione:

    python stalker_gui.py
    

  Accesso: All'avvio apparirà un box di login elegante. Inserisci l'URL del tuo portale e il tuo indirizzo MAC.

🖱 Esperienza Utente

    Navigazione: Usa i pulsanti superiori per switchare tra LIVE TV, FILM e SERIE.

    Categorie: Ogni sezione carica automaticamente le proprie sottocategorie (escludendo automaticamente la categoria "All" per una vista più pulita).

    Play: Clicca su un contenuto per vederne i dettagli e premi il tasto blu RIPRODUCI ORA per avviare la visione a schermo intero.

    Logout: Puoi cambiare account in qualsiasi momento usando il tasto Logout in alto a destra.

🛠 Dettagli Tecnici

    Multithreading: Utilizza QThread e ThreadPoolExecutor per gestire il traffico di rete senza rallentare i 60fps dell'interfaccia.

    Smart Paging: Per le categorie con migliaia di film, l'app carica i risultati a blocchi (pagine) in modo ricorsivo, permettendoti di scorrere la lista mentre il resto viene scaricato.

    Custom Styling: Interamente personalizzato tramite QSS (Qt Style Sheets) per un look dark professionale.

📄 Note sulla Privacy e Sicurezza

L'applicazione gestisce i token di sessione e i cookie in modo sicuro all'interno della sessione corrente. Nessun dato sensibile viene salvato in modo permanente su file, garantendo la massima pulizia ad ogni chiusura.
