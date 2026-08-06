#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  ALERTA DE CITAS  -  Lunas Oscurecidas (PNP)
================================================================================

  Aplicacion de escritorio que vigila el sistema de citas de la PNP y te manda
  una notificacion push al movil (iPhone y Android) en cuanto aparece un cupo.

  Solo tienes que escribir tu DNI y tu clave y pulsar INICIAR.

  --------------------------------------------------------------------------
  INSTALACION  (una sola vez)
  --------------------------------------------------------------------------
      pip install playwright requests
      playwright install chromium

  --------------------------------------------------------------------------
  RECIBIR LAS ALERTAS EN EL MOVIL  (gratis, sin crear cuenta)
  --------------------------------------------------------------------------
      1. Instala la app "ntfy" desde App Store o Google Play
      2. Pulsa "+" y suscribete al tema que aparece en esta app
      3. Listo. No hay registro ni contraseña.

  --------------------------------------------------------------------------
  USO
  --------------------------------------------------------------------------
      python alerta_citas_app.py                 # abre la interfaz
      python alerta_citas_app.py --consola       # sin interfaz (servidor/VPS)

  --------------------------------------------------------------------------
  IMPORTANTE
  --------------------------------------------------------------------------
  Esta app CONSULTA y AVISA. La reserva la haces tu desde el movil o el PC:
  cuando hay cupo, el sitio muestra un captcha que debe resolver una persona.
================================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import random
import re
import secrets
import smtplib
import stat
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Dependencias
# --------------------------------------------------------------------------- #

_FALTAN: list[str] = []
try:
    import requests
except ImportError:
    _FALTAN.append("requests")
try:
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
except ImportError:
    _FALTAN.append("playwright")

if _FALTAN:
    print("\n  Faltan dependencias: " + ", ".join(_FALTAN))
    print("\n  Instalalas con estos dos comandos:\n")
    print("      pip install playwright requests")
    print("      playwright install chromium\n")
    sys.exit(1)


# --------------------------------------------------------------------------- #
#  Constantes
# --------------------------------------------------------------------------- #

APP_NOMBRE = "Alerta de Citas PNP"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_citas.json"
ESTADO_FILE = BASE_DIR / "estado_citas.json"
LOG_FILE = BASE_DIR / "alerta_citas.log"

URL_LOGIN = "https://sistemas.policia.gob.pe/lunasoscurecidas/Solicitud_Menu.aspx"
NTFY_SERVER = "https://ntfy.sh"

# Selectores del sitio. Si rediseñan la web, se ajustan aqui y nada mas.
SEL_TIPO_DOC  = "#DdlDocumento"
SEL_DOC       = "#TxtCIP"
SEL_CLAVE     = "#TxtClave"
SEL_LOGIN_BTN = "#BtnContinuar"
SEL_LOGIN_MSG = "#LblMensaje"
SEL_BTN_VER   = "#MainContent_gvProgramacion_btnAccion_0"
SEL_BTN_CITA  = "#MainContent_btnCita"
SEL_SEDE      = "#MainContent_idUcitas_cbosede"
SEL_FECHA     = "#MainContent_idUcitas_cboFecha"
SEL_HORA      = "#MainContent_idUcitas_cboHora"
SEL_CUPOS     = "#MainContent_idUcitas_lblcupos"

RE_VACIO = re.compile(r"sin\s*cupos|seleccione|no\s*hay|^-+$", re.IGNORECASE)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

TIMEOUT = 30_000

DEFAULTS = {
    "tipo_doc": "1",
    "sede": "1",
    "intervalo_min": 5.0,
    "reaviso_min": 30.0,
    "fecha_objetivo": "",
    "hora_inicio": 6,
    "hora_fin": 23,
    "ntfy_topic": "",
    "ntfy_on": True,
    "discord_webhook": "",
    "discord_on": False,
    "email_to": "",
    "email_from": "",
    "email_pass": "",
    "email_smtp": "smtp.gmail.com",
    "email_puerto": 465,
    "email_on": False,
}


# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #

def _init_log() -> logging.Logger:
    log = logging.getLogger("citas")
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%d/%m %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    return log


LOG = _init_log()


class ColaHandler(logging.Handler):
    """Envia los mensajes del log al recuadro de la interfaz."""

    def __init__(self, cola: queue.Queue):
        super().__init__()
        self.cola = cola
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.cola.put((record.levelno, self.format(record)))
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
#  Utilidades
# --------------------------------------------------------------------------- #

def sin_tildes(s: str) -> str:
    return s.translate(str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN"))


def parse_fecha(txt: str) -> date | None:
    """Reconoce '15/08/2026', '2026-08-15', 'JUEVES 15 DE AGOSTO DE 2026'."""
    if not txt:
        return None
    t = txt.strip()
    for patron, orden in ((r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", (0, 1, 2)),
                          (r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", (2, 1, 0))):
        m = re.search(patron, t)
        if m:
            g = m.groups()
            try:
                return date(int(g[orden[0]]), int(g[orden[1]]), int(g[orden[2]]))
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]{4,})\s*(?:de\s+)?(\d{4})",
                  t, re.IGNORECASE)
    if m:
        mes = MESES.get(sin_tildes(m.group(2)).lower())
        if mes:
            try:
                return date(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass
    return None


def leer_json(path: Path, defecto: dict) -> dict:
    datos = dict(defecto)
    if path.exists():
        try:
            datos.update(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            LOG.warning("No pude leer %s; uso valores por defecto.", path.name)
    return datos


def escribir_json(path: Path, datos: dict) -> None:
    try:
        path.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name != "nt":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)   # 600
    except OSError as e:
        LOG.error("No pude guardar %s: %s", path.name, e)


def cargar_config() -> dict:
    cfg = leer_json(CONFIG_FILE, DEFAULTS)
    if not cfg.get("ntfy_topic"):
        cfg["ntfy_topic"] = "citas-pnp-" + secrets.token_hex(5)
        escribir_json(CONFIG_FILE, cfg)
    return cfg


# --------------------------------------------------------------------------- #
#  Canales de notificacion
# --------------------------------------------------------------------------- #

def notif_ntfy(cfg: dict, titulo: str, cuerpo: str, urgente: bool) -> bool:
    if not cfg.get("ntfy_on") or not cfg.get("ntfy_topic"):
        return False
    try:
        r = requests.post(
            f"{NTFY_SERVER}/{cfg['ntfy_topic']}",
            data=cuerpo.encode("utf-8"),
            headers={
                "Title": titulo.encode("utf-8"),
                "Priority": "urgent" if urgente else "default",
                "Tags": "rotating_light" if urgente else "white_check_mark",
                "Click": URL_LOGIN,
                "Actions": f"view, Abrir sistema, {URL_LOGIN}",
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        LOG.error("ntfy fallo: %s", e)
        return False


def notif_discord(cfg: dict, titulo: str, cuerpo: str, urgente: bool) -> bool:
    url = cfg.get("discord_webhook", "").strip()
    if not cfg.get("discord_on") or not url:
        return False
    try:
        r = requests.post(url, json={
            "username": APP_NOMBRE,
            "embeds": [{
                "title": titulo,
                "description": cuerpo[:3800],
                "url": URL_LOGIN,
                "color": 0xE53935 if urgente else 0x2E7D32,
                "footer": {"text": "Entra y reserva cuanto antes"},
            }],
        }, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        LOG.error("Discord fallo: %s", e)
        return False


def notif_email(cfg: dict, titulo: str, cuerpo: str) -> bool:
    if not cfg.get("email_on") or not cfg.get("email_to") or not cfg.get("email_from"):
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = titulo
        msg["From"] = cfg["email_from"]
        msg["To"] = cfg["email_to"]
        msg.set_content(f"{cuerpo}\n\nEntra aqui:\n{URL_LOGIN}\n")
        with smtplib.SMTP_SSL(cfg.get("email_smtp", "smtp.gmail.com"),
                              int(cfg.get("email_puerto", 465)), timeout=25) as s:
            s.login(cfg["email_from"], cfg.get("email_pass", ""))
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        LOG.error("Email fallo: %s", e)
        return False


def beep(n: int = 6) -> None:
    for _ in range(n):
        sys.stdout.write("\a")
        sys.stdout.flush()
        time.sleep(0.3)


def enviar_alerta(cfg: dict, titulo: str, cuerpo: str, urgente: bool = True) -> list[str]:
    """Dispara todos los canales activos. Devuelve los que funcionaron."""
    ok = []
    if notif_ntfy(cfg, titulo, cuerpo, urgente):
        ok.append("ntfy")
    if notif_discord(cfg, titulo, cuerpo, urgente):
        ok.append("Discord")
    if notif_email(cfg, titulo, cuerpo):
        ok.append("correo")
    if urgente:
        beep()
    return ok


# --------------------------------------------------------------------------- #
#  Navegacion del sitio
# --------------------------------------------------------------------------- #

def _postback(page, selector: str, timeout: int = TIMEOUT) -> None:
    """Click que dispara un __doPostBack de ASP.NET."""
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout):
            page.click(selector)
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=timeout)


def login(page, dni: str, clave: str, tipo_doc: str) -> None:
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=TIMEOUT)
    page.wait_for_selector(SEL_DOC, timeout=TIMEOUT)
    page.select_option(SEL_TIPO_DOC, tipo_doc)
    page.fill(SEL_DOC, dni)
    page.fill(SEL_CLAVE, clave)
    _postback(page, SEL_LOGIN_BTN)

    if page.locator(SEL_LOGIN_MSG).count():
        msg = (page.locator(SEL_LOGIN_MSG).first.inner_text() or "").strip()
        if msg:
            raise RuntimeError(f"El sitio rechazo el acceso: {msg}")
    if page.locator(SEL_CLAVE).count() and page.locator(SEL_LOGIN_BTN).count():
        raise RuntimeError("Sigue en la pantalla de login (revisa DNI y clave).")


def abrir_formulario(page):
    """Boton del ojito -> 'Reservar Cita' -> pagina con el combo de fechas."""
    page.wait_for_selector(SEL_BTN_VER, timeout=TIMEOUT)
    _postback(page, SEL_BTN_VER)

    page.wait_for_selector(SEL_BTN_CITA, timeout=TIMEOUT)
    destino = page
    try:
        with page.context.expect_page(timeout=8_000) as info:
            page.click(SEL_BTN_CITA)
        destino = info.value
        destino.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
    except PWTimeout:
        destino.wait_for_load_state("networkidle", timeout=TIMEOUT)

    destino.wait_for_selector(SEL_SEDE, timeout=TIMEOUT)
    return destino


def _opciones(page, selector: str) -> list[dict]:
    if not page.locator(selector).count():
        return []
    return page.eval_on_selector_all(
        f"{selector} option",
        "els => els.map(e => ({value: e.value, text: (e.textContent||'').trim()}))",
    )


def _solo_reales(ops: list[dict]) -> list[dict]:
    out = []
    for o in ops:
        v, t = (o.get("value") or "").strip(), (o.get("text") or "").strip()
        if v in ("", "0", "00", "-1") or not t or RE_VACIO.search(t):
            continue
        out.append({"value": v, "text": t})
    return out


def buscar_cupos(page, sede: str) -> list[dict]:
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=TIMEOUT):
            page.select_option(SEL_SEDE, sede)
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.wait_for_timeout(1200)     # el onchange usa setTimeout(...,0)

    fechas = _solo_reales(_opciones(page, SEL_FECHA))
    etiqueta = ""
    if page.locator(SEL_CUPOS).count():
        etiqueta = (page.locator(SEL_CUPOS).first.inner_text() or "").strip()

    LOG.info("Revision hecha. Fechas con cupo: %d  |  %s", len(fechas), etiqueta or "-")

    resultado = []
    for f in fechas:
        item = {"texto": f["text"], "fecha": parse_fecha(f["text"]),
                "horas": [], "cupos": etiqueta}
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
                page.select_option(SEL_FECHA, f["value"])
            page.wait_for_timeout(900)
            item["horas"] = [h["text"] for h in _solo_reales(_opciones(page, SEL_HORA))]
            if page.locator(SEL_CUPOS).count():
                item["cupos"] = (page.locator(SEL_CUPOS).first.inner_text() or "").strip()
        except Exception as e:  # noqa: BLE001
            LOG.debug("Sin detalle de horas para %s: %s", f["text"], e)
        resultado.append(item)
    return resultado


# --------------------------------------------------------------------------- #
#  Motor de monitoreo
# --------------------------------------------------------------------------- #

class Monitor(threading.Thread):
    """Hilo que revisa el sitio en bucle y dispara las alertas."""

    def __init__(self, cfg: dict, dni: str, clave: str,
                 al_actualizar=None, debug: bool = False):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.dni = dni
        self.clave = clave
        self.debug = debug
        self.al_actualizar = al_actualizar or (lambda *_: None)
        self._parar = threading.Event()
        self.ultima_revision: datetime | None = None
        self.revisiones = 0
        self.cupos_actuales: list[dict] = []

    # -- control ----------------------------------------------------------- #

    def detener(self) -> None:
        self._parar.set()

    def _dormir(self, segundos: float) -> bool:
        """Espera troceada para poder cancelar al instante. False si hay que salir."""
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            if self._parar.is_set():
                return False
            time.sleep(0.5)
        return not self._parar.is_set()

    def _en_horario(self) -> bool:
        h = datetime.now().hour
        ini, fin = int(self.cfg.get("hora_inicio", 0)), int(self.cfg.get("hora_fin", 23))
        return ini <= h <= fin if ini <= fin else (h >= ini or h <= fin)

    # -- ciclo ------------------------------------------------------------- #

    def _una_revision(self, pw) -> list[dict]:
        navegador = pw.chromium.launch(
            headless=not self.debug,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = navegador.new_context(user_agent=USER_AGENT, locale="es-PE",
                                    viewport={"width": 1366, "height": 900})
        ctx.set_default_timeout(TIMEOUT)
        page = ctx.new_page()
        try:
            login(page, self.dni, self.clave, self.cfg["tipo_doc"])
            return buscar_cupos(abrir_formulario(page), self.cfg["sede"])
        finally:
            ctx.close()
            navegador.close()

    def _filtrar(self, cupos: list[dict]) -> list[dict]:
        objetivo = parse_fecha(self.cfg.get("fecha_objetivo", ""))
        if not objetivo:
            return cupos
        utiles = [c for c in cupos if c["fecha"] is None or c["fecha"] < objetivo]
        if len(utiles) < len(cupos):
            LOG.info("Ignoro %d cupo(s) que no mejoran tu cita del %s.",
                     len(cupos) - len(utiles), objetivo)
        return utiles

    def _avisar(self, cupos: list[dict]) -> None:
        estado = leer_json(ESTADO_FILE, {"fechas": [], "ultimo": None})
        utiles = self._filtrar(cupos)
        self.cupos_actuales = utiles

        if not utiles:
            if estado.get("fechas"):
                LOG.info("Los cupos que habia ya se agotaron.")
            escribir_json(ESTADO_FILE, {"fechas": [], "ultimo": None})
            return

        actuales = sorted(c["texto"] for c in utiles)
        hay_nuevos = actuales != sorted(estado.get("fechas", []))

        repetir = True
        if estado.get("ultimo"):
            try:
                repetir = (datetime.now() - datetime.fromisoformat(estado["ultimo"])) > \
                          timedelta(minutes=float(self.cfg.get("reaviso_min", 30)))
            except (ValueError, TypeError):
                repetir = True

        if not (hay_nuevos or repetir):
            LOG.info("Mismos cupos ya avisados; no repito todavia.")
            return

        lineas = []
        for c in utiles:
            horas = ", ".join(c["horas"][:8]) if c["horas"] else "(ver en el sitio)"
            lineas.append(f"* {c['texto']}\n  Horas: {horas}\n  Cupos: {c['cupos']}")
        cuerpo = ("HAY CUPO DE CITA DISPONIBLE\n\n" + "\n\n".join(lineas) +
                  "\n\nEntra YA y reserva. El formulario te pedira un captcha.")

        LOG.warning("*** CUPO DISPONIBLE ***  %s", " | ".join(actuales))
        canales = enviar_alerta(self.cfg, "CUPO DE CITA DISPONIBLE", cuerpo, urgente=True)
        if canales:
            LOG.info("Alerta enviada por: %s", ", ".join(canales))
        else:
            LOG.error("NINGUN canal de alerta funciono. Revisa la configuracion.")

        escribir_json(ESTADO_FILE,
                      {"fechas": actuales, "ultimo": datetime.now().isoformat()})

    def run(self) -> None:
        objetivo = self.cfg.get("fecha_objetivo") or "cualquier cupo"
        LOG.info("Monitor iniciado. Reviso cada %s min. Busco: %s",
                 self.cfg["intervalo_min"], objetivo)
        self.al_actualizar("vigilando")

        fallos = 0
        try:
            with sync_playwright() as pw:
                while not self._parar.is_set():
                    if not self._en_horario():
                        LOG.info("Fuera del horario de vigilancia; espero 15 min.")
                        if not self._dormir(900):
                            break
                        continue
                    try:
                        cupos = self._una_revision(pw)
                        self.ultima_revision = datetime.now()
                        self.revisiones += 1
                        self._avisar(cupos)
                        fallos = 0
                        self.al_actualizar("vigilando")
                    except Exception as e:  # noqa: BLE001
                        fallos += 1
                        LOG.error("Revision fallida (%d seguidas): %s", fallos, e)
                        self.al_actualizar("error")
                        if fallos == 4:
                            enviar_alerta(self.cfg, "Monitor con problemas",
                                          f"Cuatro fallos seguidos.\nUltimo error: {e}",
                                          urgente=False)
                        if fallos >= 3:
                            espera = min(120 * 2 ** (fallos - 3), 1800)
                            LOG.info("Espero %d s antes de reintentar.", espera)
                            if not self._dormir(espera):
                                break
                            continue

                    pausa = float(self.cfg["intervalo_min"]) * 60 + random.randint(0, 45)
                    LOG.info("Siguiente revision en %.1f min.", pausa / 60)
                    if not self._dormir(pausa):
                        break
        except Exception as e:  # noqa: BLE001
            LOG.error("El monitor se detuvo por un error grave: %s", e)
        finally:
            LOG.info("Monitor detenido.")
            self.al_actualizar("detenido")


# --------------------------------------------------------------------------- #
#  Interfaz grafica
# --------------------------------------------------------------------------- #

def lanzar_gui(cfg: dict) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("\n  Tkinter no esta instalado.")
        print("  Ubuntu/Debian:  sudo apt install python3-tk")
        print("  O usa el modo consola:  python alerta_citas_app.py --consola\n")
        sys.exit(1)

    COL_BG, COL_CARD = "#0f172a", "#1e293b"
    COL_TXT, COL_SUAVE = "#e2e8f0", "#94a3b8"
    COL_OK, COL_ERR, COL_ACC = "#22c55e", "#ef4444", "#38bdf8"

    root = tk.Tk()
    root.title(APP_NOMBRE)
    root.geometry("760x820")
    root.minsize(700, 720)
    root.configure(bg=COL_BG)

    cola_log: queue.Queue = queue.Queue()
    LOG.addHandler(ColaHandler(cola_log))
    estado = {"monitor": None}

    st = ttk.Style()
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("TFrame", background=COL_BG)
    st.configure("Card.TFrame", background=COL_CARD)
    st.configure("TLabel", background=COL_CARD, foreground=COL_TXT, font=("Segoe UI", 10))
    st.configure("Bg.TLabel", background=COL_BG, foreground=COL_TXT)
    st.configure("Sub.TLabel", background=COL_CARD, foreground=COL_SUAVE,
                 font=("Segoe UI", 9))
    st.configure("Titulo.TLabel", background=COL_BG, foreground=COL_TXT,
                 font=("Segoe UI", 17, "bold"))
    st.configure("TEntry", fieldbackground="#0b1220", foreground=COL_TXT,
                 insertcolor=COL_TXT, borderwidth=0)
    st.configure("TCombobox", fieldbackground="#0b1220", foreground=COL_TXT)
    st.configure("TCheckbutton", background=COL_CARD, foreground=COL_TXT)
    st.configure("TNotebook", background=COL_BG, borderwidth=0)
    st.configure("TNotebook.Tab", background=COL_BG, foreground=COL_SUAVE, padding=(16, 8))
    st.map("TNotebook.Tab", background=[("selected", COL_CARD)],
           foreground=[("selected", COL_TXT)])

    def tarjeta(padre) -> ttk.Frame:
        f = ttk.Frame(padre, style="Card.TFrame", padding=16)
        f.pack(fill="x", pady=(0, 12))
        return f

    # ---- cabecera ----
    cab = ttk.Frame(root, style="TFrame", padding=(20, 16, 20, 8))
    cab.pack(fill="x")
    ttk.Label(cab, text="Alerta de Citas  ·  Lunas Oscurecidas",
              style="Titulo.TLabel").pack(anchor="w")
    ttk.Label(cab, text="Vigila el sistema de la PNP y te avisa al movil cuando "
                        "aparece un cupo.", style="Bg.TLabel",
              foreground=COL_SUAVE).pack(anchor="w", pady=(2, 0))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=20, pady=(8, 0))

    tab_main = ttk.Frame(nb, style="TFrame", padding=14)
    tab_cfg = ttk.Frame(nb, style="TFrame", padding=14)
    nb.add(tab_main, text="  Monitor  ")
    nb.add(tab_cfg, text="  Alertas y ajustes  ")

    # ---------------- pestaña principal ---------------- #

    c1 = tarjeta(tab_main)
    ttk.Label(c1, text="Tus datos de acceso",
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 2))
    ttk.Label(c1, text="No se guardan en ningun archivo. Solo viven mientras la "
                       "app esta abierta.", style="Sub.TLabel").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(c1, text="Tipo de documento").grid(row=2, column=0, sticky="w", pady=5)
    v_tipo = tk.StringVar(value="DNI" if cfg.get("tipo_doc") == "1"
                          else "Carnet de extranjeria")
    cb_tipo = ttk.Combobox(c1, textvariable=v_tipo, state="readonly", width=28,
                           values=["DNI", "Carnet de extranjeria"])
    cb_tipo.grid(row=2, column=1, sticky="ew", pady=5)

    ttk.Label(c1, text="Nro. de documento").grid(row=3, column=0, sticky="w", pady=5)
    v_dni = tk.StringVar()
    e_dni = ttk.Entry(c1, textvariable=v_dni, width=30)
    e_dni.grid(row=3, column=1, sticky="ew", pady=5)

    ttk.Label(c1, text="Clave").grid(row=4, column=0, sticky="w", pady=5)
    v_clave = tk.StringVar()
    e_clave = ttk.Entry(c1, textvariable=v_clave, show="\u2022", width=30)
    e_clave.grid(row=4, column=1, sticky="ew", pady=5)
    c1.columnconfigure(1, weight=1)

    # estado
    c2 = tarjeta(tab_main)
    lbl_estado = tk.Label(c2, text="Detenido", bg=COL_CARD, fg=COL_SUAVE,
                          font=("Segoe UI", 15, "bold"))
    lbl_estado.pack(anchor="w")
    lbl_detalle = tk.Label(c2, text="Escribe tu documento y tu clave, y pulsa INICIAR.",
                           bg=COL_CARD, fg=COL_SUAVE, font=("Segoe UI", 10),
                           justify="left", wraplength=650)
    lbl_detalle.pack(anchor="w", pady=(4, 0))

    botones = ttk.Frame(tab_main, style="TFrame")
    botones.pack(fill="x", pady=(0, 12))
    btn_ini = tk.Button(botones, text="INICIAR VIGILANCIA", bg=COL_OK, fg="#04210f",
                        font=("Segoe UI", 11, "bold"), relief="flat",
                        padx=22, pady=11, cursor="hand2")
    btn_ini.pack(side="left")
    btn_stop = tk.Button(botones, text="DETENER", bg="#334155", fg=COL_TXT,
                         font=("Segoe UI", 11, "bold"), relief="flat",
                         padx=22, pady=11, cursor="hand2", state="disabled")
    btn_stop.pack(side="left", padx=8)
    btn_test = tk.Button(botones, text="Probar alerta", bg="#334155", fg=COL_TXT,
                         font=("Segoe UI", 10), relief="flat",
                         padx=16, pady=11, cursor="hand2")
    btn_test.pack(side="left")

    ttk.Label(tab_main, text="Actividad", style="Bg.TLabel",
              font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
    caja = tk.Text(tab_main, height=11, bg="#0b1220", fg=COL_TXT, relief="flat",
                   font=("Consolas", 9), wrap="word", state="disabled",
                   insertbackground=COL_TXT)
    caja.pack(fill="both", expand=True)
    caja.tag_config("warn", foreground="#fbbf24")
    caja.tag_config("err", foreground=COL_ERR)
    caja.tag_config("hit", foreground=COL_OK, font=("Consolas", 9, "bold"))

    # ---------------- pestaña de ajustes ---------------- #

    c3 = tarjeta(tab_cfg)
    ttk.Label(c3, text="Notificacion al movil  ·  ntfy",
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3,
                                                  sticky="w")
    ttk.Label(c3, text="Gratis y sin crear cuenta. Instala la app \"ntfy\" en tu "
                       "iPhone o Android,\npulsa \"+\" y suscribete a este tema:",
              style="Sub.TLabel").grid(row=1, column=0, columnspan=3, sticky="w",
                                       pady=(2, 8))
    v_topic = tk.StringVar(value=cfg.get("ntfy_topic", ""))
    e_topic = ttk.Entry(c3, textvariable=v_topic, width=34, font=("Consolas", 11))
    e_topic.grid(row=2, column=0, sticky="ew", pady=4)

    def copiar_topic():
        root.clipboard_clear()
        root.clipboard_append(v_topic.get())
        lbl_copiado.config(text="Copiado")
        root.after(2000, lambda: lbl_copiado.config(text=""))

    tk.Button(c3, text="Copiar", bg="#334155", fg=COL_TXT, relief="flat",
              padx=12, pady=4, cursor="hand2", command=copiar_topic
              ).grid(row=2, column=1, padx=6)
    tk.Button(c3, text="Abrir en web", bg="#334155", fg=COL_TXT, relief="flat",
              padx=12, pady=4, cursor="hand2",
              command=lambda: webbrowser.open(f"{NTFY_SERVER}/{v_topic.get()}")
              ).grid(row=2, column=2)
    lbl_copiado = ttk.Label(c3, text="", style="Sub.TLabel", foreground=COL_OK)
    lbl_copiado.grid(row=3, column=0, sticky="w")
    v_ntfy_on = tk.BooleanVar(value=cfg.get("ntfy_on", True))
    ttk.Checkbutton(c3, text="Enviar alertas por ntfy", variable=v_ntfy_on
                    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Label(c3, text="El tema es publico para quien conozca el nombre: por eso es "
                       "aleatorio.\nSolo viaja la fecha del cupo, nunca tus credenciales.",
              style="Sub.TLabel").grid(row=5, column=0, columnspan=3, sticky="w",
                                       pady=(6, 0))
    c3.columnconfigure(0, weight=1)

    c4 = tarjeta(tab_cfg)
    ttk.Label(c4, text="Canales de respaldo (opcionales)",
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 8))
    v_disc_on = tk.BooleanVar(value=cfg.get("discord_on", False))
    ttk.Checkbutton(c4, text="Discord", variable=v_disc_on).grid(row=1, column=0,
                                                                 sticky="w")
    v_disc = tk.StringVar(value=cfg.get("discord_webhook", ""))
    ttk.Entry(c4, textvariable=v_disc, width=46).grid(row=1, column=1, sticky="ew", pady=4)
    ttk.Label(c4, text="URL del webhook (Ajustes del canal > Integraciones)",
              style="Sub.TLabel").grid(row=2, column=1, sticky="w")

    v_mail_on = tk.BooleanVar(value=cfg.get("email_on", False))
    ttk.Checkbutton(c4, text="Correo", variable=v_mail_on).grid(row=3, column=0,
                                                               sticky="w", pady=(10, 0))
    v_mail_to = tk.StringVar(value=cfg.get("email_to", ""))
    ttk.Entry(c4, textvariable=v_mail_to, width=46).grid(row=3, column=1, sticky="ew",
                                                         pady=(10, 4))
    ttk.Label(c4, text="Destinatario", style="Sub.TLabel").grid(row=4, column=1,
                                                                sticky="w")
    v_mail_from = tk.StringVar(value=cfg.get("email_from", ""))
    ttk.Entry(c4, textvariable=v_mail_from, width=46).grid(row=5, column=1,
                                                           sticky="ew", pady=4)
    ttk.Label(c4, text="Cuenta Gmail que envia", style="Sub.TLabel").grid(row=6, column=1,
                                                                          sticky="w")
    v_mail_pass = tk.StringVar(value=cfg.get("email_pass", ""))
    ttk.Entry(c4, textvariable=v_mail_pass, width=46, show="\u2022").grid(
        row=7, column=1, sticky="ew", pady=4)
    ttk.Label(c4, text="Clave de aplicacion de Gmail (no tu clave normal)",
              style="Sub.TLabel").grid(row=8, column=1, sticky="w")
    c4.columnconfigure(1, weight=1)

    c5 = tarjeta(tab_cfg)
    ttk.Label(c5, text="Que buscar", font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    ttk.Label(c5, text="Codigo de sede").grid(row=1, column=0, sticky="w", pady=4)
    v_sede = tk.StringVar(value=str(cfg.get("sede", "1")))
    ttk.Entry(c5, textvariable=v_sede, width=14).grid(row=1, column=1, sticky="w", pady=4)
    ttk.Label(c5, text="1 = LIMA-LA VICTORIA", style="Sub.TLabel").grid(row=2, column=1,
                                                                        sticky="w")

    ttk.Label(c5, text="Tu cita actual").grid(row=3, column=0, sticky="w", pady=(10, 4))
    v_obj = tk.StringVar(value=cfg.get("fecha_objetivo", ""))
    ttk.Entry(c5, textvariable=v_obj, width=18).grid(row=3, column=1, sticky="w",
                                                     pady=(10, 4))
    ttk.Label(c5, text="AAAA-MM-DD. Solo te avisara de cupos anteriores a esta fecha.\n"
                       "Dejalo vacio para que te avise de cualquier cupo.",
              style="Sub.TLabel").grid(row=4, column=1, sticky="w")

    ttk.Label(c5, text="Revisar cada").grid(row=5, column=0, sticky="w", pady=(10, 4))
    v_int = tk.StringVar(value=str(cfg.get("intervalo_min", 5)))
    ttk.Entry(c5, textvariable=v_int, width=8).grid(row=5, column=1, sticky="w",
                                                    pady=(10, 4))
    ttk.Label(c5, text="minutos. Minimo 3: mas seguido te arriesgas a un bloqueo por IP.",
              style="Sub.TLabel").grid(row=6, column=1, sticky="w")

    ttk.Label(c5, text="Vigilar entre").grid(row=7, column=0, sticky="w", pady=(10, 4))
    marco_h = ttk.Frame(c5, style="Card.TFrame")
    marco_h.grid(row=7, column=1, sticky="w", pady=(10, 4))
    v_h1 = tk.StringVar(value=str(cfg.get("hora_inicio", 6)))
    v_h2 = tk.StringVar(value=str(cfg.get("hora_fin", 23)))
    ttk.Entry(marco_h, textvariable=v_h1, width=5).pack(side="left")
    ttk.Label(marco_h, text="  y  ").pack(side="left")
    ttk.Entry(marco_h, textvariable=v_h2, width=5).pack(side="left")
    ttk.Label(marco_h, text="  horas").pack(side="left")
    c5.columnconfigure(1, weight=1)

    # ---------------- logica ---------------- #

    def recoger_cfg() -> dict | None:
        try:
            intervalo = float(v_int.get().replace(",", "."))
        except ValueError:
            messagebox.showerror(APP_NOMBRE, "El intervalo debe ser un numero.")
            return None
        if intervalo < 3:
            messagebox.showerror(APP_NOMBRE,
                                 "El intervalo minimo es 3 minutos.\n\nRevisar mas "
                                 "seguido te expone a un bloqueo por IP, y te quedarias "
                                 "sin monitor justo el dia que salga el cupo.")
            return None
        if v_obj.get().strip() and not parse_fecha(v_obj.get()):
            messagebox.showerror(APP_NOMBRE, "No entiendo la fecha de tu cita actual.\n"
                                             "Usa el formato 2026-11-20.")
            return None
        try:
            h1, h2 = int(v_h1.get()), int(v_h2.get())
            if not (0 <= h1 <= 23 and 0 <= h2 <= 23):
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NOMBRE, "Las horas deben ir de 0 a 23.")
            return None

        cfg.update({
            "tipo_doc": "1" if v_tipo.get() == "DNI" else "2",
            "sede": v_sede.get().strip() or "1",
            "intervalo_min": intervalo,
            "fecha_objetivo": v_obj.get().strip(),
            "hora_inicio": h1,
            "hora_fin": h2,
            "ntfy_topic": v_topic.get().strip(),
            "ntfy_on": bool(v_ntfy_on.get()),
            "discord_webhook": v_disc.get().strip(),
            "discord_on": bool(v_disc_on.get()),
            "email_to": v_mail_to.get().strip(),
            "email_from": v_mail_from.get().strip(),
            "email_pass": v_mail_pass.get(),
            "email_on": bool(v_mail_on.get()),
        })
        escribir_json(CONFIG_FILE, cfg)
        return cfg

    def pintar_estado(clave: str) -> None:
        mon = estado["monitor"]
        if clave == "vigilando":
            lbl_estado.config(text="Vigilando", fg=COL_OK)
            ult = mon.ultima_revision.strftime("%H:%M:%S") if mon and mon.ultima_revision else "-"
            n = mon.revisiones if mon else 0
            hay = len(mon.cupos_actuales) if mon else 0
            txt = (f"Te avisare en cuanto haya un cupo. Puedes minimizar esta ventana.\n"
                   f"Ultima revision: {ult}   ·   revisiones: {n}")
            if hay:
                txt += f"\nAHORA MISMO HAY {hay} FECHA(S) CON CUPO. Entra y reserva."
            lbl_detalle.config(text=txt)
        elif clave == "error":
            lbl_estado.config(text="Reintentando", fg="#fbbf24")
            lbl_detalle.config(text="Una revision fallo. Lo intento de nuevo solo; "
                                    "mira la actividad para el detalle.")
        else:
            lbl_estado.config(text="Detenido", fg=COL_SUAVE)
            lbl_detalle.config(text="Escribe tu documento y tu clave, y pulsa INICIAR.")
            btn_ini.config(state="normal")
            btn_stop.config(state="disabled")
            for w in (e_dni, e_clave, cb_tipo):
                w.config(state="normal" if w is not cb_tipo else "readonly")

    def desde_hilo(clave: str) -> None:
        root.after(0, lambda: pintar_estado(clave))

    def iniciar() -> None:
        dni, clave = v_dni.get().strip(), v_clave.get()
        if not dni or not clave:
            messagebox.showwarning(APP_NOMBRE, "Escribe tu documento y tu clave.")
            return
        c = recoger_cfg()
        if c is None:
            return
        if not (c["ntfy_on"] or c["discord_on"] or c["email_on"]):
            if not messagebox.askyesno(
                    APP_NOMBRE,
                    "No tienes ningun canal de alerta activo.\n\n"
                    "Solo veras los avisos en esta ventana, no en el movil.\n"
                    "¿Continuar de todas formas?"):
                return

        mon = Monitor(c, dni, clave, al_actualizar=desde_hilo)
        estado["monitor"] = mon
        mon.start()
        btn_ini.config(state="disabled")
        btn_stop.config(state="normal")
        for w in (e_dni, e_clave, cb_tipo):
            w.config(state="disabled")
        pintar_estado("vigilando")

    def detener() -> None:
        mon = estado["monitor"]
        if mon:
            LOG.info("Deteniendo... (termino la revision en curso)")
            mon.detener()
        btn_stop.config(state="disabled")

    def probar() -> None:
        c = recoger_cfg()
        if c is None:
            return
        canales = enviar_alerta(
            c, "Prueba · Alerta de Citas",
            "Si lees esto en tu movil, las alertas funcionan.\n"
            "Cuando aparezca un cupo real te llegara un aviso como este.",
            urgente=False)
        if canales:
            messagebox.showinfo(APP_NOMBRE,
                                "Enviado por: " + ", ".join(canales) +
                                "\n\nRevisa tu movil.")
        else:
            messagebox.showerror(APP_NOMBRE,
                                 "No se pudo enviar por ningun canal.\n\n"
                                 "Revisa que el tema de ntfy este escrito y activo.")

    btn_ini.config(command=iniciar)
    btn_stop.config(command=detener)
    btn_test.config(command=probar)

    def drenar_log() -> None:
        try:
            while True:
                nivel, texto = cola_log.get_nowait()
                tag = ""
                if nivel >= logging.ERROR:
                    tag = "err"
                elif nivel >= logging.WARNING:
                    tag = "hit" if "CUPO" in texto else "warn"
                caja.config(state="normal")
                caja.insert("end", texto + "\n", tag)
                caja.see("end")
                if float(caja.index("end-1c").split(".")[0]) > 500:
                    caja.delete("1.0", "200.0")
                caja.config(state="disabled")
        except queue.Empty:
            pass
        root.after(250, drenar_log)

    def al_cerrar() -> None:
        mon = estado["monitor"]
        if mon and mon.is_alive():
            if not messagebox.askokcancel(APP_NOMBRE,
                                          "El monitor esta vigilando.\n\n"
                                          "Si cierras dejaras de recibir alertas. "
                                          "¿Cerrar igual?"):
                return
            mon.detener()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", al_cerrar)
    root.after(250, drenar_log)
    e_dni.focus_set()
    LOG.info("Listo. Suscribete en la app ntfy al tema: %s", cfg.get("ntfy_topic"))
    root.mainloop()


# --------------------------------------------------------------------------- #
#  Modo consola (para dejarlo corriendo en un servidor)
# --------------------------------------------------------------------------- #

def modo_consola(cfg: dict, debug: bool = False) -> None:
    import getpass

    print("\n" + "=" * 68)
    print(f"  {APP_NOMBRE}  ·  modo consola")
    print("=" * 68)
    print(f"  Suscribete en la app ntfy al tema:  {cfg.get('ntfy_topic')}")
    print("  Tus credenciales no se guardan en ningun archivo.\n")

    dni = os.environ.get("PNP_DNI", "").strip()
    clave = os.environ.get("PNP_CLAVE", "").strip()
    while not dni:
        dni = input("  Nro. de documento : ").strip()
    while not clave:
        clave = getpass.getpass("  Clave             : ").strip()
    print()

    mon = Monitor(cfg, dni, clave, debug=debug)
    mon.start()
    try:
        while mon.is_alive():
            mon.join(timeout=1)
    except KeyboardInterrupt:
        print("\n  Deteniendo...")
        mon.detener()
        mon.join(timeout=60)


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=f"{APP_NOMBRE}")
    ap.add_argument("--consola", action="store_true",
                    help="ejecutar sin interfaz grafica (servidor/VPS)")
    ap.add_argument("--debug", action="store_true",
                    help="mostrar el navegador durante la revision")
    args = ap.parse_args()

    cfg = cargar_config()
    if args.consola:
        modo_consola(cfg, debug=args.debug)
    else:
        lanzar_gui(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nHasta luego.\n")
