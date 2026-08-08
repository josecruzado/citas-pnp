#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  MONITOR DE CITAS PNP  ·  Aplicacion de escritorio
================================================================================

  Una ventana, dos casillas: documento y clave. Se pulsa "Empezar a vigilar" y
  se deja abierta. Cuando aparece un cupo suena una alarma y la ventana salta
  al frente.

  Pensada para alguien que no quiere instalar nada ni abrir una terminal, asi
  que todo lo demas (sede, ritmo, avisos al celular) tiene valores por defecto
  que funcionan sin tocarlos.

  Se compila a un unico .exe con PyInstaller; ver .github/workflows/exe.yml.
================================================================================
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import requests

import pnp

APP = "Monitor de Citas PNP"

# Ritmo de las revisiones. Se puede cambiar desde la ventana, incluso mientras
# vigila. El minimo no es capricho: cada revision es una peticion al servidor
# de la PNP y bajar de ahi solo aumenta el riesgo de que bloqueen la conexion,
# sin encontrar los cupos antes.
INTERVALO_POR_DEFECTO = 120
INTERVALO_MINIMO = 30
INTERVALO_MAXIMO = 3600
RITMO_EXIGENTE = 60          # por debajo de esto, avisar al usuario

REINTENTO_SEG = 30           # tras un fallo de red, esperar menos
FALLOS_PARA_AVISAR = 3

UNIDADES = {"segundos": 1, "minutos": 60}

COLOR_FONDO = "#f4f5f7"
COLOR_TEXTO = "#1c1e21"
COLOR_SUAVE = "#6b7280"
COLOR_OK = "#0f7b3f"
COLOR_ALERTA = "#c62828"
COLOR_ESPERA = "#1f4e8c"


def carpeta_datos() -> Path:
    """Sitio donde guardar la configuracion, distinto en cada sistema."""
    if sys.platform == "win32":
        raiz = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        raiz = Path.home() / "Library" / "Application Support"
    else:
        raiz = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    destino = raiz / "MonitorCitasPNP"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


ARCHIVO = carpeta_datos() / "config.json"


def leer_config() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def guardar_config(datos: dict) -> None:
    try:
        ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except OSError:
        pass


def _partir_intervalo(segundos: int) -> tuple[int, str]:
    """Segundos -> (cantidad, unidad) en la forma mas legible para mostrar."""
    if segundos >= 60 and segundos % 60 == 0:
        return segundos // 60, "minutos"
    return segundos, "segundos"


def _describir_ritmo(segundos: int) -> str:
    veces = round(3600 / segundos)
    return f"{veces} revisión por hora" if veces == 1 else f"{veces} revisiones por hora"


def guardar_evidencia(html: str, cupos: list[dict], etiqueta: str) -> Path | None:
    """Deja constancia de por que se aviso de un cupo.

    Si alguna vez avisa de algo que no existe, aqui queda el HTML exacto que
    devolvio la PNP en ese instante, que es la unica forma de comprobarlo
    despues (los cupos desaparecen en minutos y ya no se pueden reproducir).
    """
    try:
        carpeta = carpeta_datos() / "evidencia"
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        resumen = [f"Detectado: {datetime.now():%d/%m/%Y %H:%M:%S}",
                   f"Cartel del sitio (lblcupos): {etiqueta!r}", ""]
        for c in cupos:
            resumen.append(f"fecha={c['fecha']!r}  cupos={c['cupos']!r}  "
                           f"horas={c['horas']}")
        (carpeta / f"cupo-{marca}.txt").write_text("\n".join(resumen),
                                                   encoding="utf-8")
        destino = carpeta / f"cupo-{marca}.html"
        destino.write_text(html, encoding="utf-8")
        return destino
    except OSError:
        return None


def sonar_alarma(detener: threading.Event) -> None:
    """Pitidos hasta que se silencie o pase medio minuto."""
    fin = time.time() + 30
    try:
        import winsound
        while not detener.is_set() and time.time() < fin:
            winsound.Beep(880, 400)
            winsound.Beep(1320, 400)
            time.sleep(0.2)
    except Exception:  # noqa: BLE001  - sin winsound (Mac/Linux) o sin audio
        while not detener.is_set() and time.time() < fin:
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(1)


def avisar_al_celular(topic: str, cupos: list[dict]) -> None:
    lineas = []
    for c in cupos:
        horas = ", ".join(c["horas"][:8]) if c["horas"] else "(ver en el sitio)"
        lineas.append(f"* {c['fecha']}\n  Horas: {horas}\n  Cupos: {c['cupos']}")
    cuerpo = ("HAY CUPO DE CITA DISPONIBLE\n\n" + "\n\n".join(lineas) +
              "\n\nEntra YA y reserva. El formulario te pedira un captcha.")
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=cuerpo.encode("utf-8"),
                      headers={"Title": "CUPO DE CITA DISPONIBLE".encode("utf-8"),
                               "Priority": "urgent", "Tags": "rotating_light",
                               "Click": pnp.URL_LOGIN},
                      timeout=15)
    except requests.RequestException:
        pass


# --------------------------------------------------------------------------- #

class Vigilante(threading.Thread):
    """Revisa en segundo plano y manda novedades a la ventana por una cola."""

    def __init__(self, cfg: dict, buzon: queue.Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.buzon = buzon
        self.parar = threading.Event()
        self.intervalo = int(cfg.get("intervalo", INTERVALO_POR_DEFECTO))
        # Permite acortar la espera en curso cuando cambia el intervalo, en vez
        # de obligar a esperar el ciclo entero para que surta efecto.
        self.despertar = threading.Event()

    def avisar(self, tipo: str, **extra) -> None:
        self.buzon.put({"tipo": tipo, **extra})

    def _esperar(self, segundos: float, seguir_intervalo: bool = True) -> None:
        """Espera, despertando antes si cambia el intervalo o se pide parar."""
        inicio = time.monotonic()
        while not self.parar.is_set():
            self.despertar.clear()
            objetivo = self.intervalo if seguir_intervalo else segundos
            restante = objetivo - (time.monotonic() - inicio)
            if restante <= 0:
                return
            self.despertar.wait(restante)

    def run(self) -> None:
        fallos = 0
        anterior = None
        sesion = None
        while not self.parar.is_set():
            espera, seguir = self.intervalo, True
            try:
                if sesion is None:
                    sesion = pnp.SesionPNP(self.cfg["dni"], self.cfg["clave"],
                                           self.cfg.get("tipo_doc", "1"),
                                           self.cfg.get("sede", "1"))
                cupos = sesion.consultar()
                if fallos >= FALLOS_PARA_AVISAR:
                    self.avisar("recuperado")
                fallos = 0

                huella = [(c["fecha"], c["cupos"], tuple(c["horas"])) for c in cupos]
                if cupos and huella != anterior:
                    prueba = guardar_evidencia(sesion.evidencia, cupos,
                                               sesion.etiqueta_cupos)
                    self.avisar("cupo", cupos=cupos, espera=espera,
                                cartel=sesion.etiqueta_cupos, prueba=prueba)
                elif cupos:
                    self.avisar("sigue", cupos=cupos, espera=espera)
                else:
                    self.avisar("vacio", espera=espera)
                anterior = huella

            except pnp.CredencialesInvalidas as e:
                self.avisar("credenciales", detalle=str(e))
                return
            except pnp.ErrorPNP as e:
                sesion = None          # empezar limpio en el proximo intento
                fallos += 1
                if fallos < FALLOS_PARA_AVISAR:
                    espera, seguir = REINTENTO_SEG, False
                self.avisar("fallo", detalle=str(e), seguidos=fallos, espera=espera)

            self._esperar(espera, seguir)


# --------------------------------------------------------------------------- #

class Ventana(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("560x600")
        self.minsize(520, 560)
        self.configure(bg=COLOR_FONDO)

        self.cfg = leer_config()
        self.buzon: queue.Queue = queue.Queue()
        self.vigilante: Vigilante | None = None
        self.silenciar = threading.Event()
        self.revisiones = 0
        self._listo = False        # evita reaccionar a los widgets al crearlos
        self.estado_base = "Escribe tus datos y pulsa el botón."
        self.proxima: float | None = None
        self.en_alarma = False

        self._construir()
        self._listo = True
        self._aplicar_intervalo()
        self._revisar_buzon()
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

    # -- interfaz ----------------------------------------------------------- #

    def _construir(self) -> None:
        tk.Label(self, text="Monitor de Citas PNP", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 19, "bold")).pack(pady=(22, 2))
        tk.Label(self, text="Lunas oscurecidas · te avisa apenas aparece un cupo",
                 bg=COLOR_FONDO, fg=COLOR_SUAVE,
                 font=("Segoe UI", 10)).pack(pady=(0, 18))

        # --- datos de acceso ---
        self.caja = tk.Frame(self, bg="white", highlightbackground="#dfe3e8",
                             highlightthickness=1)
        self.caja.pack(fill="x", padx=26)

        tk.Label(self.caja, text="Tu documento (DNI)", bg="white", fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        self.e_dni = tk.Entry(self.caja, font=("Segoe UI", 13), relief="solid", bd=1)
        self.e_dni.pack(fill="x", padx=18, ipady=6)
        self.e_dni.insert(0, self.cfg.get("dni", ""))

        tk.Label(self.caja, text="Tu clave del sistema PNP", bg="white",
                 fg=COLOR_TEXTO, font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w", padx=18, pady=(14, 4))
        self.e_clave = tk.Entry(self.caja, font=("Segoe UI", 13), show="●",
                                relief="solid", bd=1)
        self.e_clave.pack(fill="x", padx=18, ipady=6)
        self.e_clave.insert(0, self.cfg.get("clave", ""))

        # --- ritmo de revision ---
        fila = tk.Frame(self.caja, bg="white")
        fila.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(fila, text="Revisar cada", bg="white", fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        cantidad, unidad = _partir_intervalo(
            int(self.cfg.get("intervalo", INTERVALO_POR_DEFECTO)))
        self.v_cantidad = tk.StringVar(value=str(cantidad))
        self.v_unidad = tk.StringVar(value=unidad)

        self.sp_cantidad = ttk.Spinbox(fila, from_=1, to=60, width=5, justify="center",
                                       textvariable=self.v_cantidad,
                                       command=self._aplicar_intervalo)
        self.sp_cantidad.pack(side="left", padx=(8, 6))
        self.cb_unidad = ttk.Combobox(fila, values=list(UNIDADES), state="readonly",
                                      width=10, textvariable=self.v_unidad)
        self.cb_unidad.pack(side="left")
        self.cb_unidad.bind("<<ComboboxSelected>>",
                            lambda _e: self._aplicar_intervalo())
        self.v_cantidad.trace_add("write", lambda *_: self._aplicar_intervalo())

        self.l_ritmo = tk.Label(self.caja, text="", bg="white", fg=COLOR_SUAVE,
                                font=("Segoe UI", 9), wraplength=440, justify="left")
        self.l_ritmo.pack(anchor="w", padx=18, pady=(4, 0))

        self.v_sonido = tk.BooleanVar(value=self.cfg.get("sonido", True))
        tk.Checkbutton(self.caja, text="Sonar alarma cuando haya cupo",
                       variable=self.v_sonido, bg="white", fg=COLOR_TEXTO,
                       activebackground="white", font=("Segoe UI", 10),
                       command=self._alternar_sonido
                       ).pack(anchor="w", padx=14, pady=(12, 0))

        self.v_celular = tk.BooleanVar(value=bool(self.cfg.get("topic")))
        tk.Checkbutton(self.caja, text="Avisarme también al celular",
                       variable=self.v_celular, bg="white", fg=COLOR_TEXTO,
                       activebackground="white", font=("Segoe UI", 10),
                       command=self._alternar_celular
                       ).pack(anchor="w", padx=14, pady=(14, 0))

        self.f_topic = tk.Frame(self.caja, bg="white")
        self.l_topic = tk.Label(self.f_topic, text="", bg="#eef2f7", fg=COLOR_TEXTO,
                                font=("Consolas", 11), padx=8, pady=5)
        self.l_topic.pack(side="left", fill="x", expand=True)
        tk.Button(self.f_topic, text="Copiar", command=self._copiar_topic,
                  font=("Segoe UI", 9), relief="solid", bd=1).pack(side="left", padx=(6, 0))
        tk.Label(self.caja, text="", bg="white").pack(pady=(0, 6))

        self.b_empezar = tk.Button(self, text="Empezar a vigilar",
                                   command=self._empezar, bg="#1f4e8c", fg="white",
                                   activebackground="#17406f", activeforeground="white",
                                   font=("Segoe UI", 13, "bold"), relief="flat",
                                   cursor="hand2")
        self.b_empezar.pack(fill="x", padx=26, pady=(18, 6), ipady=11)

        # --- estado ---
        self.l_estado = tk.Label(self, text="Escribe tus datos y pulsa el botón.",
                                 bg=COLOR_FONDO, fg=COLOR_SUAVE,
                                 font=("Segoe UI", 11), wraplength=500)
        self.l_estado.pack(pady=(6, 4))

        self.b_abrir = tk.Button(self, text="ABRIR LA PÁGINA DE LA PNP",
                                 command=self._abrir_pnp, bg=COLOR_OK, fg="white",
                                 activebackground="#0b5f30", activeforeground="white",
                                 font=("Segoe UI", 13, "bold"), relief="flat",
                                 cursor="hand2")
        self.b_silenciar = tk.Button(self, text="Silenciar alarma",
                                     command=lambda: self.silenciar.set(),
                                     font=("Segoe UI", 10), relief="solid", bd=1,
                                     cursor="hand2")

        tk.Label(self, text="Historial", bg=COLOR_FONDO, fg=COLOR_SUAVE,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=28, pady=(10, 2))
        marco = tk.Frame(self, bg=COLOR_FONDO)
        marco.pack(fill="both", expand=True, padx=26, pady=(0, 20))
        self.historial = tk.Text(marco, height=7, font=("Consolas", 9), relief="solid",
                                 bd=1, bg="white", fg=COLOR_SUAVE, state="disabled",
                                 wrap="word")
        barra = ttk.Scrollbar(marco, command=self.historial.yview)
        self.historial.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.historial.pack(side="left", fill="both", expand=True)

        self._alternar_celular(inicial=True)

    def _alternar_sonido(self) -> None:
        """Activa o silencia la alarma sonora, tambien la que este sonando."""
        activo = self.v_sonido.get()
        self.cfg["sonido"] = activo
        guardar_config(self.cfg)
        if not activo:
            self.silenciar.set()          # corta la alarma en curso al instante
            self._apuntar("Sonido silenciado. El aviso seguirá siendo visible.")
        else:
            self._apuntar("Sonido activado.")

    def _alternar_celular(self, inicial: bool = False) -> None:
        if self.v_celular.get():
            if not self.cfg.get("topic"):
                self.cfg["topic"] = "citas-" + os.urandom(8).hex()
            self.l_topic.configure(text=self.cfg["topic"])
            self.f_topic.pack(fill="x", padx=18, pady=(8, 0))
            if not inicial:
                self._nota("Instala la app ntfy en el celular y suscríbete a ese "
                           "nombre para recibir los avisos fuera de casa.")
        else:
            self.f_topic.pack_forget()

    def _aplicar_intervalo(self) -> int | None:
        """Valida el ritmo elegido, lo guarda y lo aplica aunque este vigilando."""
        if not self._listo:
            return None
        try:
            cantidad = int(self.v_cantidad.get())
        except ValueError:
            self.l_ritmo.configure(text="Escribe un número.", fg=COLOR_ALERTA)
            return None
        if cantidad < 1:
            self.l_ritmo.configure(text="Escribe un número mayor que cero.",
                                   fg=COLOR_ALERTA)
            return None

        segundos = cantidad * UNIDADES.get(self.v_unidad.get(), 60)
        ajustado = max(INTERVALO_MINIMO, min(INTERVALO_MAXIMO, segundos))

        if ajustado != segundos:
            limite = "mínimo" if segundos < INTERVALO_MINIMO else "máximo"
            texto, color = (f"El {limite} son {_partir_intervalo(ajustado)[0]} "
                            f"{_partir_intervalo(ajustado)[1]}. Se usará ese.",
                            COLOR_ALERTA)
        elif ajustado < RITMO_EXIGENTE:
            texto, color = (f"{_describir_ritmo(ajustado)}. Muy seguido: aumenta "
                            "el riesgo de que la PNP bloquee tu conexión.",
                            COLOR_ALERTA)
        else:
            texto, color = _describir_ritmo(ajustado) + ".", COLOR_SUAVE

        self.l_ritmo.configure(text=texto, fg=color)
        self.cfg["intervalo"] = ajustado
        guardar_config(self.cfg)

        # Si ya esta vigilando, el cambio surte efecto sin reiniciar nada.
        if self.vigilante and self.vigilante.is_alive():
            anterior = self.vigilante.intervalo
            self.vigilante.intervalo = ajustado
            self.vigilante.despertar.set()
            if anterior != ajustado:
                self._apuntar(f"Ritmo cambiado a {_describir_ritmo(ajustado)}.")
        return ajustado

    def _copiar_topic(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.cfg.get("topic", ""))
        self._nota("Nombre copiado. Pégalo en la app ntfy del celular.")

    # -- acciones ----------------------------------------------------------- #

    def _nota(self, texto: str, color: str = COLOR_SUAVE) -> None:
        self.estado_base = texto
        self.l_estado.configure(text=texto, fg=color)

    def _pintar_cuenta_atras(self) -> None:
        """Anade al estado los segundos que faltan para la proxima revision."""
        if self.en_alarma or not self.proxima or not self.vigilante:
            return
        restante = max(0, int(round(self.proxima - time.monotonic())))
        sufijo = "ahora" if restante == 0 else f"en {restante} s"
        self.l_estado.configure(text=f"{self.estado_base}  ·  próxima {sufijo}")

    def _apuntar(self, texto: str) -> None:
        self.historial.configure(state="normal")
        self.historial.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        self.historial.see("end")
        self.historial.configure(state="disabled")

    def _empezar(self) -> None:
        if self.vigilante and self.vigilante.is_alive():
            return self._detener()

        dni, clave = self.e_dni.get().strip(), self.e_clave.get().strip()
        if not dni or not clave:
            return self._nota("Falta tu documento o tu clave.", COLOR_ALERTA)
        if self._aplicar_intervalo() is None:
            return self._nota("Corrige el ritmo de revisión antes de empezar.",
                              COLOR_ALERTA)

        self.cfg.update({"dni": dni, "clave": clave})
        if not self.v_celular.get():
            self.cfg.pop("topic", None)
        guardar_config(self.cfg)

        self.e_dni.configure(state="disabled")
        self.e_clave.configure(state="disabled")
        self.b_empezar.configure(text="Detener", bg="#6b7280",
                                 activebackground="#565c66")
        self.revisiones = 0
        self.en_alarma = False
        self.proxima = None
        self._nota("Conectando con el sistema de la PNP…", COLOR_ESPERA)
        self._apuntar("Vigilancia iniciada.")

        self.vigilante = Vigilante(self.cfg, self.buzon)
        self.vigilante.start()

    def _detener(self) -> None:
        if self.vigilante:
            self.vigilante.parar.set()
            self.vigilante = None
        self.silenciar.set()
        self.e_dni.configure(state="normal")
        self.e_clave.configure(state="normal")
        self.b_empezar.configure(text="Empezar a vigilar", bg="#1f4e8c",
                                 activebackground="#17406f")
        self.b_abrir.pack_forget()
        self.b_silenciar.pack_forget()
        self.en_alarma = False
        self.proxima = None
        self._nota("Detenido. Pulsa el botón para volver a vigilar.")
        self._apuntar("Vigilancia detenida.")

    def _abrir_pnp(self) -> None:
        self.silenciar.set()
        webbrowser.open(pnp.URL_LOGIN)

    def _alarma(self, cupos: list[dict], cartel: str = "", prueba=None) -> None:
        self.en_alarma = True
        self.silenciar.clear()
        # El aviso visual y el del celular llegan igual aunque este en silencio.
        if self.v_sonido.get():
            threading.Thread(target=sonar_alarma, args=(self.silenciar,),
                             daemon=True).start()
        detalle = " · ".join(
            f"{c['fecha']} ({', '.join(c['horas'][:4]) or 'ver horarios'})"
            for c in cupos)
        self._nota(f"¡HAY CUPO!  {detalle}", COLOR_ALERTA)
        self.b_abrir.pack(fill="x", padx=26, pady=(4, 2), ipady=10)
        if self.v_sonido.get():
            self.b_silenciar.pack(pady=(0, 4))
        self._apuntar(f"*** CUPO DISPONIBLE: {detalle} ***")
        # El cartel del propio sitio permite juzgar de un vistazo si el aviso
        # cuadra con lo que la PNP dice, sin salir de la ventana.
        if cartel:
            self._apuntar(f"    la PNP dice: {cartel!r}")
        if prueba:
            self._apuntar(f"    prueba guardada en {prueba}")

        # Traer la ventana al frente aunque este minimizada.
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(3000, lambda: self.attributes("-topmost", False))

        if self.cfg.get("topic"):
            threading.Thread(target=avisar_al_celular,
                             args=(self.cfg["topic"], cupos), daemon=True).start()

    def _revisar_buzon(self) -> None:
        try:
            while True:
                m = self.buzon.get_nowait()
                t = m["tipo"]
                if "espera" in m:
                    self.proxima = time.monotonic() + m["espera"]
                if t in ("vacio", "sigue", "cupo"):
                    self.revisiones += 1
                if t == "vacio":
                    self.en_alarma = False
                    self._nota(f"Vigilando. Sin cupos por ahora "
                               f"({self.revisiones} revisiones).", COLOR_ESPERA)
                    self._apuntar("Sin cupos.")
                elif t == "cupo":
                    self._alarma(m["cupos"], m.get("cartel", ""), m.get("prueba"))
                elif t == "sigue":
                    self._apuntar("El mismo cupo de antes (no repito la alarma).")
                elif t == "credenciales":
                    self._nota(f"{m['detalle']}  Corrige tus datos y vuelve a "
                               "empezar.", COLOR_ALERTA)
                    self._apuntar(f"Acceso rechazado: {m['detalle']}")
                    self._detener()
                elif t == "fallo":
                    self._apuntar(f"Fallo {m['seguidos']}: {m['detalle'][:90]}")
                    if m["seguidos"] >= FALLOS_PARA_AVISAR:
                        self._nota("No consigo conectar con la PNP. Sigo "
                                   "intentando…", COLOR_ALERTA)
                elif t == "recuperado":
                    self._apuntar("Conexión recuperada.")
        except queue.Empty:
            pass
        self._pintar_cuenta_atras()
        self.after(400, self._revisar_buzon)

    def _cerrar(self) -> None:
        if self.vigilante and self.vigilante.is_alive():
            self.vigilante.parar.set()
        self.silenciar.set()
        self.destroy()


if __name__ == "__main__":
    Ventana().mainloop()
