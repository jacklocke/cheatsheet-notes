"""Cheatsheet viewer: mostra la guida dell'app che ha il focus.

Le guide arrivano da due fonti:
1. il vault Obsidian (sola lettura): note con il metadato 'linked-process: <processo>';
2. la mappa 'apps' di config.json (file markdown fuori dal vault), usata come fallback.
"""

import base64
import ctypes
import html
import json
import logging
import os
import re
import secrets
import sys
import time
from ctypes import wintypes
from urllib.parse import quote

import markdown
import psutil
import webview
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "cheatsheet.log")

LINKED_KEY = "linked-process"  # nome del metadato Obsidian
VAULT_SCAN_INTERVAL = 10  # secondi tra due scansioni del vault

MUTEX_NAME = "CheatsheetViewerSingleInstance"
ERROR_ALREADY_EXISTS = 183

WINDOW_TITLE = "Cheatsheet"
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE_NOSIZE_NOACTIVATE = 0x0001 | 0x0002 | 0x0010

# Su Windows a 64 bit gli handle vanno dichiarati come HWND: senza, HWND_TOPMOST/-2 viene
# passato come intero a 32 bit e la chiamata non ha effetto.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL

# Nonce per lo script della pagina: le note non possono eseguire JavaScript,
# perché il loro HTML non porta questo valore (vedi Content-Security-Policy).
NONCE = secrets.token_urlsafe(16)

PAGE_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https:; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'">
<style>
  body {{ margin: 0; padding: 16px; font-family: "Segoe UI", sans-serif;
         background: #1e1e1e; color: #e6e6e6; font-size: 14px; }}
  h1, h2, h3 {{ color: #ffffff; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ border: 1px solid #444; padding: 6px 10px; text-align: left; }}
  th {{ background: #2d2d2d; }}
  code {{ background: #2d2d2d; padding: 2px 6px; border-radius: 4px;
         font-family: Consolas, monospace; }}
  pre code {{ display: block; padding: 8px; overflow-x: auto; }}
  hr {{ border: 0; border-top: 1px solid #444; margin: 24px 0; }}
  .muted {{ color: #999; }}
  .error {{ color: #ff8080; }}
  .warn {{ color: #ffcc66; border: 1px solid #665c33; padding: 6px 10px;
          border-radius: 4px; }}
  .sec-head {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .obs {{ background: #2d2d2d; color: #e6e6e6; border: 1px solid #555;
         border-radius: 4px; padding: 4px 10px; cursor: pointer; font: inherit; }}
  .obs:hover {{ background: #3a3a3a; }}
  .corner {{ position: fixed; top: 8px; right: 8px; display: flex; gap: 6px; }}
  .toggle {{ background: #2d2d2d; color: #e6e6e6; border: 1px solid #555; border-radius: 4px;
            padding: 4px 6px; cursor: pointer; line-height: 0; opacity: 0.4; }}
  .toggle.on {{ opacity: 1; color: #bbbbbb; border-color: #888; background: #3a3a3a; }}
  .toggle .ic-closed {{ display: none; }}
  .toggle.on .ic-closed {{ display: inline; }}
  .toggle.on .ic-open {{ display: none; }}
</style>
</head>
<body>{body}
<script nonce="{nonce}">
  document.addEventListener("click", function (e) {{
    var b = e.target.closest("button.obs");
    if (b && window.pywebview) {{ pywebview.api.open_note(b.dataset.path); }}
    var l = e.target.closest("#lock");
    if (l) {{
      l.classList.toggle("on");
      l.title = l.classList.contains("on") ? "Sblocca nota" : "Blocca nota";
      if (window.pywebview) {{ pywebview.api.toggle_lock(); }}
    }}
    var t = e.target.closest("#topmost");
    if (t) {{
      t.classList.toggle("on");
      if (window.pywebview) {{ pywebview.api.toggle_topmost(); }}
    }}
  }});
</script>
</body>
</html>"""


def page(body):
    """Pagina completa con il contenuto indicato e il nonce dello script."""
    return PAGE_TEMPLATE.format(body=body, nonce=NONCE)


# Sintassi Obsidian che python-markdown non conosce: viene convertita in markdown standard.
OBSIDIAN_RULES = [
    (re.compile(r"%%.*?%%", re.S), ""),  # commenti
    (re.compile(r"^[\w-]+::.*$", re.M), ""),  # campi inline (key:: value)
    (re.compile(r"\s\^[\w-]+$", re.M), ""),  # id di blocco
    (re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]"), r"\2"),  # link con alias
    (re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?\]\]"), r"\1"),  # wikilink
    (re.compile(r"^(>\s*)\[!(\w+)\][+-]?(.*)$", re.M), r"\1**\2**\3"),  # callout
]

# Embed Obsidian: ![[file]] o ![[file|larghezza]]. Vengono risolti prima dei wikilink.
EMBED_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # oltre questa soglia l'immagine non viene incorporata

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*\r?\n?", re.S)


def get_foreground_process_name():
    """Restituisce (pid, nome processo) della finestra in primo piano, oppure (None, None)."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return pid.value, psutil.Process(pid.value).name()
    except (psutil.Error, OSError):
        return pid.value, None


def set_window_topmost(topmost):
    """Imposta 'sempre in primo piano' con Win32.

    Non si usa il setter window.on_top di pywebview: su Windows si blocca se chiamato
    da un thread diverso da quello della UI mentre la pagina viene aggiornata.
    """
    hwnd = _user32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        _user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)


def load_config():
    """Carica config.json; in caso di errore restituisce un messaggio di errore."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data, None
    except (OSError, json.JSONDecodeError) as exc:
        return {"apps": {}}, f"config.json non valido: {exc}"


def split_frontmatter(text):
    """Separa il frontmatter YAML dal corpo. Restituisce (metadati, corpo)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1) or "") or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end():]


def normalize_process(value):
    """'Code' -> 'code.exe', 'Obsidian.exe' -> 'obsidian.exe' (confronto case-insensitive)."""
    name = str(value).strip().lower()
    return name if name.endswith(".exe") else name + ".exe"


def read_linked_processes(path):
    """Legge il metadato linked-process di una nota. Restituisce la lista dei processi."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return []
    if not text.startswith("---"):
        return []
    meta, _ = split_frontmatter(text)
    value = meta.get(LINKED_KEY)
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    return [normalize_process(v) for v in values if str(v).strip()]


def obsidian_uri(vault, note_path):
    """Link obsidian://open per una nota: il vault è identificato dal nome della sua cartella."""
    vault_name = os.path.basename(os.path.normpath(vault))
    rel = os.path.relpath(note_path, vault).replace("\\", "/")
    return f"obsidian://open?vault={quote(vault_name)}&file={quote(rel)}"


class Api:
    """Esposta alla pagina come pywebview.api: apre una nota del vault in Obsidian."""

    # Gli attributi con '_' non vengono esplorati da pywebview: senza, la scansione
    # attraverserebbe l'intero oggetto finestra a ogni caricamento di pagina.
    def __init__(self):
        self._index = None  # impostato da main()
        self._viewer = None  # impostato da main()

    def toggle_lock(self):
        if self._viewer:
            self._viewer.toggle_lock()

    def toggle_topmost(self):
        if self._viewer:
            self._viewer.toggle_topmost()

    def open_note(self, note_path):
        vault = self._index.vault if self._index else None
        if not vault:
            return
        full = os.path.normcase(os.path.abspath(note_path))
        root = os.path.normcase(os.path.abspath(vault))
        # Accetta solo file .md che stanno dentro il vault.
        if not full.startswith(root + os.sep) or not full.endswith(".md") or not os.path.isfile(full):
            return
        try:
            os.startfile(obsidian_uri(vault, note_path))
        except OSError:
            logging.exception("impossibile aprire la nota in Obsidian: %s", note_path)


def embed_image(match, attachments):
    """Sostituisce un embed Obsidian con l'immagine incorporata, se e' un'immagine del vault."""
    target = match.group(1).strip()
    name = os.path.basename(target)
    ext = os.path.splitext(name)[1].lower()
    path = attachments.get(name.lower())
    if path is None or ext not in IMAGE_TYPES or os.path.getsize(path) > MAX_IMAGE_BYTES:
        return f"*{target}*"  # non e' un'immagine trovabile: resta il nome
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    size = (match.group(2) or "").strip()
    width = f' width="{int(size)}"' if size.isdigit() else ""
    return f'<img src="data:{IMAGE_TYPES[ext]};base64,{data}" alt="{html.escape(name)}"{width}>'


def clean_obsidian_markdown(text, attachments=None):
    """Rimuove il frontmatter e converte la sintassi Obsidian in markdown standard."""
    attachments = attachments or {}
    _, body = split_frontmatter(text)
    body = EMBED_RE.sub(lambda m: embed_image(m, attachments), body)
    for pattern, replacement in OBSIDIAN_RULES:
        body = pattern.sub(replacement, body)
    return body


class VaultIndex:
    """Indice in sola lettura: processo -> note del vault collegate."""

    def __init__(self):
        self.vault = None
        self.files = {}  # percorso -> (mtime, [processi])
        self.by_process = {}  # processo -> [percorsi]
        self.attachments = {}  # nome file immagine (minuscolo) -> percorso
        self.last_scan = None

    def set_vault(self, vault):
        if vault != self.vault:
            self.vault = vault
            self.files = {}
            self.by_process = {}
            self.attachments = {}
            self.last_scan = None

    def scan(self):
        """Riscansiona il vault, rileggendo solo le note modificate."""
        if not self.vault:
            return
        now = time.monotonic()
        if self.last_scan is not None and now - self.last_scan < VAULT_SCAN_INTERVAL:
            return
        self.last_scan = now

        seen = set()
        attachments = {}
        for root, dirs, files in os.walk(self.vault):
            dirs[:] = [d for d in dirs if not d.startswith(".")]  # salta .obsidian, .trash
            for name in files:
                path = os.path.join(root, name)
                if os.path.splitext(name)[1].lower() in IMAGE_TYPES:
                    attachments.setdefault(name.lower(), path)
                    continue
                if not name.lower().endswith(".md"):
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                seen.add(path)
                old = self.files.get(path)
                if old is None or old[0] != mtime:
                    self.files[path] = (mtime, read_linked_processes(path))

        for path in list(self.files):
            if path not in seen:
                del self.files[path]

        self.attachments = attachments
        self.by_process = {}
        for path, (_, processes) in self.files.items():
            for process in processes:
                self.by_process.setdefault(process, []).append(path)
        for paths in self.by_process.values():
            paths.sort()


def render_vault_notes(paths, process_name, attachments=None):
    """Pagina HTML con il contenuto di tutte le note collegate, in sequenza."""
    parts = [f'<p class="muted">{html.escape(process_name)}</p>']
    if len(paths) > 1:
        parts.append(
            f'<p class="warn">Attenzione: {len(paths)} note collegate a '
            f"{html.escape(process_name)}. Mostrate in sequenza.</p>"
        )

    sections = []
    for path in paths:
        title = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8-sig") as f:
                body = clean_obsidian_markdown(f.read(), attachments)
            content = markdown.markdown(body, extensions=["tables", "fenced_code"])
        except OSError as exc:
            content = f'<p class="error">Impossibile leggere la nota: {html.escape(str(exc))}</p>'
        button = f'<p><button class="obs" data-path="{html.escape(path, quote=True)}">Apri in Obsidian</button></p>'
        sections.append(f"<section><h2>{html.escape(title)}</h2>{content}{button}</section>")

    parts.append("<hr>".join(sections))
    return page("".join(parts))


def render_guide(md_path, process_name):
    """Converte un markdown fuori dal vault in HTML."""
    try:
        with open(md_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        body = f'<p class="error">Impossibile leggere il file della guida: {html.escape(str(exc))}</p>'
        return page(body)

    content = markdown.markdown(text, extensions=["tables", "fenced_code"])
    header = f'<p class="muted">{html.escape(process_name)}</p>'
    return page(header + content)


LOCK_ICONS = (
    '<svg class="ic-open" viewBox="0 0 24 24" width="16" height="16">'
    '<path d="M8 10V7a4 4 0 0 1 8 0" fill="none" stroke="currentColor" stroke-width="2"/>'
    '<rect x="5" y="10" width="14" height="11" rx="2" fill="currentColor"/></svg>'
    '<svg class="ic-closed" viewBox="0 0 24 24" width="16" height="16">'
    '<path d="M8 10V7a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" stroke-width="2"/>'
    '<rect x="5" y="10" width="14" height="11" rx="2" fill="currentColor"/></svg>'
)


SCREEN_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16">'
    '<rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/>'
    '<path d="M8 20h8M12 16v4" fill="none" stroke="currentColor" stroke-width="2"/></svg>'
)


def with_toolbar(page, locked, topmost):
    """Inserisce i pulsanti nell'angolo della pagina (primo piano e lucchetto), nello stato indicato."""
    lock_cls = " on" if locked else ""
    lock_title = "Sblocca nota" if locked else "Blocca nota"
    top_cls = " on" if topmost else ""
    toolbar = (
        '<div class="corner">'
        f'<button id="topmost" class="toggle topmost{top_cls}" title="mantieni in primo piano">{SCREEN_ICON}</button>'
        f'<button id="lock" class="toggle lock{lock_cls}" title="{lock_title}">{LOCK_ICONS}</button>'
        "</div>"
    )
    return page.replace("<body>", "<body>" + toolbar, 1)


def message_page(text, css_class="muted"):
    return page(f'<p class="{css_class}">{html.escape(text)}</p>')


def pick_screen(config):
    """Sceglie il monitor: quello indicato in config o il secondario se presente."""
    try:
        screens = webview.screens
    except Exception:
        return None
    if not screens:
        return None
    wanted = config.get("monitor")
    if isinstance(wanted, int) and 1 <= wanted <= len(screens):
        return screens[wanted - 1]
    if len(screens) > 1:
        return screens[1]
    return screens[0]


class Viewer:
    def __init__(self, window):
        self.window = window
        self.index = VaultIndex()
        self.config = {}
        self.config_error = None
        self.vault_error = None
        self.config_mtime = None
        self.config_dir = BASE_DIR
        self.last_key = None
        self.last_name = None
        self.locked_name = None  # processo bloccato dal lucchetto
        self.topmost = True  # finestra sempre in primo piano (acceso di default)

    def toggle_lock(self):
        if self.locked_name:
            self.locked_name = None
        elif self.last_name:
            self.locked_name = self.last_name
        self.last_key = None  # ridisegna la pagina con il nuovo stato

    def toggle_topmost(self):
        self.topmost = not self.topmost
        set_window_topmost(self.topmost)

    def refresh_config(self):
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            mtime = None
        if mtime != self.config_mtime:
            self.config_mtime = mtime
            self.config, self.config_error = load_config()
            self.config_dir = os.path.dirname(CONFIG_PATH)

            vault = self.config.get("vault")
            self.index.set_vault(vault)
            if vault and not os.path.isdir(vault):
                self.vault_error = f"Vault non trovato: {vault}"
            else:
                self.vault_error = None
            self.last_key = None  # forza il ridisegno

    def fallback_guides(self):
        return {k.lower(): v for k, v in self.config.get("apps", {}).items()}

    def describe(self, name):
        """Restituisce (chiave, funzione che produce la pagina) per il processo indicato."""
        lname = name.lower()

        paths = self.index.by_process.get(lname)
        if paths:
            key = ("vault", lname, tuple((p, self.index.files[p][0]) for p in paths), len(self.index.attachments))
            return key, lambda: render_vault_notes(paths, name, self.index.attachments)

        rel = self.fallback_guides().get(lname)
        if rel:
            md_path = os.path.normpath(os.path.join(self.config_dir, rel))
            try:
                md_mtime = os.path.getmtime(md_path)
            except OSError:
                md_mtime = None
            key = ("file", lname, md_path, md_mtime)
            if md_mtime is None:
                return key, lambda: message_page(f"File guida non trovato: {md_path}", "error")
            return key, lambda: render_guide(md_path, name)

        return ("none", lname), lambda: message_page(f"Nessuna guida per {name}")

    def tick(self):
        self.refresh_config()
        pid, name = get_foreground_process_name()

        # Se il focus è sul viewer stesso, mantieni l'ultimo stato.
        if pid == os.getpid():
            return
        if name is None:
            name = self.last_name
        if self.locked_name:
            name = self.locked_name  # con il lucchetto la guida non segue il focus
        self.last_name = name

        if self.config_error:
            key, make_page = ("config-error", self.config_error), lambda: message_page(self.config_error, "error")
        elif self.vault_error:
            key, make_page = ("vault-error", self.vault_error), lambda: message_page(self.vault_error, "error")
        elif not name:
            return
        else:
            self.index.scan()
            key, make_page = self.describe(name)

        if key != self.last_key:
            self.last_key = key
            self.window.load_html(with_toolbar(make_page(), self.locked_name is not None, self.topmost))

    def run(self, window):
        while True:
            try:
                self.tick()
            except Exception as exc:  # il loop non deve morire
                logging.exception("errore nel ciclo di controllo")
                window.load_html(message_page(f"Errore: {exc}", "error"))
            time.sleep(max(100, int(self.config.get("poll_ms", 500))) / 1000)


_mutex_handle = None  # tenuto vivo per tutta la durata del programma


def acquire_single_instance():
    """Restituisce False se un'altra istanza è già in esecuzione."""
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def main():
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    if not acquire_single_instance():
        logging.info("un'altra istanza e' gia' in esecuzione: esco")
        sys.exit(0)

    try:
        initial = page('<p class="muted">Avvio...</p>')
        config, _ = load_config()
        screen = pick_screen(config)

        kwargs = {"width": 520, "height": 720, "on_top": True}
        if screen is not None:
            kwargs.update(x=screen.x + 40, y=screen.y + 40)

        api = Api()
        window = webview.create_window(WINDOW_TITLE, html=initial, js_api=api, **kwargs)
        viewer = Viewer(window)
        api._index = viewer.index
        api._viewer = viewer
        webview.start(viewer.run, window)
    except Exception:
        logging.exception("errore all'avvio")
        raise


if __name__ == "__main__":
    main()
