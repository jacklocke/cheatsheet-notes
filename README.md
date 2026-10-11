# Cheatsheet Viewer

Mostra in una finestra (di solito sul monitor secondario) la guida dell'applicazione che ha il focus. Le guide arrivano da note di un vault Obsidian oppure da file markdown locali.

## Requisiti

- Windows 10 o 11
- Python 3.10 o successivo, nel PATH
- Microsoft Edge WebView2 Runtime (già presente sulla maggior parte dei PC Windows 10/11; pywebview lo usa per la finestra)

Versioni con cui è stato provato: pywebview 6.2.1, markdown 3.10.3, psutil 7.2.2, pyyaml 6.0.3.

## Prima installazione

Esegui `install.ps1` una volta sola. Controlla che Python sia nel PATH, crea `.venv`, installa le dipendenze, crea `config.json` dall'esempio se manca e verifica il vault e le guide, poi segnala gli eventuali problemi. Non avvia il programma.

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

Al termine lo script resta aperto finché non premi Invio; con `-NoPause` si chiude subito (utile per script o test). Se compaiono avvisi "vault non trovato" o "guida mancante", correggi `config.json` e riesegui lo script.

## Avvio rapido

Doppio clic su `avvia.bat` (lascia aperta una finestra di terminale) oppure su `avvia.ps1` (non lascia nessuna console aperta; gli errori compaiono in una finestra di messaggio). Alla prima esecuzione entrambi creano `config.json` (se manca), l'ambiente virtuale `.venv` e installano le dipendenze; le volte successive avviano direttamente il programma.

Se Windows blocca `avvia.ps1`, lancialo così: `powershell -ExecutionPolicy Bypass -File avvia.ps1`.

Il programma non si apre due volte: se è già in esecuzione, il secondo avvio termina subito.

## Installazione manuale

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python cheatsheet.py
```

L'ambiente `.venv` è isolato: le dipendenze non finiscono nell'installazione Python globale. Per reinstallarlo da zero, cancella la cartella `.venv` e riesegui `avvia.bat`.

## Configurazione (`config.json`)

`config.json` contiene i tuoi percorsi e **non** va condiviso: il repository include solo `config.example.json`, che `install.ps1`, `avvia.bat` e `avvia.ps1` copiano se il file manca.

```json
{
  "poll_ms": 500,
  "monitor": 2,
  "vault": "C:\\Users\\<utente>\\Documents\\ObsidianVault",
  "apps": {
    "Code.exe": "guides/vscode.md",
    "chrome.exe": "guides/chrome.md",
    "Obsidian.exe": "guides/obsidian.md",
    "WindowsTerminal.exe": "guides/windows-terminal.md",
    "notepad++.exe": "guides/notepad++.md"
  }
}
```

- `vault`: percorso assoluto della cartella del vault Obsidian. Nei JSON i backslash vanno raddoppiati. Il valore dell'esempio (`<utente>`) va sostituito con il tuo.
- `apps`: nome del processo (case-insensitive) → file markdown, usato come fallback. Percorsi relativi alla cartella di `config.json`.
- `monitor`: numero del monitor (1 = primario). Se omesso, usa il secondario.
- `poll_ms`: intervallo di controllo in millisecondi (minimo 100).

Le modifiche a `config.json` e alle note vengono rilevate automaticamente, senza riavviare. Il vault viene riscansionato circa ogni 10 secondi.

## Come si collega una guida

Ci sono due modi.

**1. Nota nel vault Obsidian (consigliato).** Aggiungi al frontmatter della nota il metadato `linked-process` con il nome del processo:

```yaml
---
linked-process: Code
---
```

Il nome può essere con o senza `.exe` e non fa differenza tra maiuscole e minuscole. Più processi si indicano come lista. Se più note sono collegate allo stesso processo, vengono mostrate tutte in sequenza con un avviso in cima.

Il vault viene letto **solo in lettura**: il programma non scrive né modifica mai le note. Frontmatter e cartelle nascoste (`.obsidian`, `.trash`) non vengono mostrati. La sintassi Obsidian (`[[link]]`, `![[embed]]`, callout, `%%commenti%%`) viene resa in markdown standard.

Le immagini embedded di Obsidian (`![[immagine.jpg]]`, anche con larghezza `![[immagine.jpg|300]]`) vengono cercate in tutto il vault e incorporate nella guida; se il file non si trova o supera 5 MB resta il nome. Le immagini remote (`![](https://…)`) vengono mostrate con la sintassi markdown standard.

Ogni nota mostrata ha, sotto il contenuto, il pulsante **Apri in Obsidian**, che apre quella nota nel vault indicato in `config.json` (il nome del vault è il nome della sua cartella: per `C:\…\Notes.md` è `Notes.md`). Il pulsante funziona solo per le note del vault.

Nell'angolo in alto a destra ci sono due pulsanti:

- **Lucchetto**: blocca la guida corrente, che resta visibile anche se cambi finestra, finché non lo riclicchi per sbloccarla. Spento è semitrasparente, acceso è grigio.
- **Schermo ("mantieni in primo piano")**: acceso di default, tiene la finestra sopra le altre. Spento, la finestra si comporta come una finestra normale.

Esempi pronti da copiare in un vault si trovano in `examples/vault-demo/`.

**2. File markdown esterno.** Voce nella mappa `apps` di `config.json`. È usata solo se nel vault non c'è nessuna nota per quel processo.

Se l'app in focus non ha né note nel vault né voci in `apps`, la finestra mostra "Nessuna guida per <processo>".

## Sicurezza

Le note del vault sono HTML e markdown di terze parti: il programma le mostra con una Content-Security-Policy che consente script solo al proprio codice. Uno `<script>` dentro una nota non viene eseguito.

## Log

Gli errori dell'applicazione vengono scritti in `cheatsheet.log`, nella stessa cartella del programma. Il file è escluso da git.

## Limiti noti

- Solo Windows (usa API di Windows per il focus e per aprire Obsidian).
- Le scorciatoie nelle guide di esempio (`guides/`) sono quelle predefinite delle app: non sono state verificate una per una. Se il tuo PC usa keymap personalizzati, modifica il markdown.
- Il pulsante "Apri in Obsidian" richiede Obsidian installato con il protocollo `obsidian://` registrato (lo è di default).
- La scansione del vault legge tutte le note a ogni variazione: su vault molto grandi o su dischi di rete il primo avvio può richiedere qualche secondo.

## Licenza

Distribuito con licenza MIT: vedi il file `LICENSE`.
