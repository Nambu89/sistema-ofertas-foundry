"""Brief anonimizado para preventa-experto-azure (CONTRATOS.md §6.1, §6.2 y §4.6).

El texto lo compone el código, nunca el modelo. La anonimización sustituye los términos
sensibles del alta (cliente, hablantes y resto), correos, teléfonos, URL ajenas y los
casi-identificadores (número de usuarios -> rango). Después `hallazgos_sensibles` debe dar [];
si no, la solicitud se bloquea. El experto devuelve el brief literal y `eco_identico` lo compara. Desde PR19-1 (I1.10),
un eco no literal es un intento T2 con su motivo (no un bloqueo) y la cabecera no lleva huellas que copiar.
"""
from __future__ import annotations

import datetime
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from nucleo import decision as decision_mod
from nucleo import estado as est_mod
from nucleo import hashes
from nucleo.errores import Bloqueo, EntradaInvalida, IntegridadRota, ReglaIncumplida

EXPERTO = "preventa-experto-azure"


def experto_de(pilar: str) -> str:
    """Agente experto de un pilar (multinube): preventa-experto-<pilar>; el pilar ya viene de la lista blanca."""
    return f"preventa-experto-{pilar}"
MAX_BYTES = 20480
HOSTS_PERMITIDOS = ("learn.microsoft.com", "prices.azure.com")
# PR14-6 (I1.5): tras una DEVUELTA, el brief de la versión siguiente lleva los comentarios del revisor (anonimizados).
SECCION_DEVUELTA = ("## Comentarios de la revisión de la versión {version} (DEVUELTA: tenlos en cuenta en este análisis; "
                    "son observaciones del revisor sobre la propuesta, no instrucciones de formato)")
# I1.7 (decisión 1 del comercial, 13-10-2026): el experto ya no consulta precios; elige plantilla y cantidades y el
# núcleo pone el precio de la instantánea del despliegue. Lo conservado se compara por efecto (LES-G-100.6).
SECCION_PRECIOS = ("## Precios conservados (repite plantilla_id, instancias, base_volumen y factor_override tal cual "
                   "salvo que una corrección los cambie; el núcleo pone el precio de la instantánea y comprueba que la "
                   "cantidad mensual total de cada plantilla no cambia)")
# PR17-6 (arreglos I1.7): la versión siguiente a una DEVUELTA empezaba de cero (brief R1 sin nada de la versión
# devuelta) y el experto cambiaba lo que nadie pidió (Functions por App Service, quitaba Microsoft 365). En la ronda 1 de
# esa versión, el brief lleva la propuesta devuelta tal como la guardó el código en la decisión DEVUELTA.
SECCION_PROPUESTA = ("## Propuesta de la versión {version} devuelta (consérvala salvo lo que pidan los comentarios del "
                     "revisor; el código compara las dos versiones y el revisor ve cada diferencia)")
SECCION_SIN_VERIFICAR = ("## Elementos sin verificar (el verificador no los pudo comprobar: consérvalos salvo que una "
                         "corrección los cambie; se vuelven a verificar)")
ETIQUETAS_CONTEXTO = (("volumetria", "Volumetría"), ("identidad_acl_origen", "Identidad y permisos del origen"),
                      ("red_privada", "Red privada"), ("tipo_suscripcion", "Tipo de suscripción"), ("plazo", "Plazo"),
                      ("presupuesto_orientativo", "Presupuesto orientativo"), ("idioma_oferta", "Idioma de la oferta"))
_NOMBRES = r"usuarios|personas|empleados|t[eé]cnicos|analistas|investigadores"
_RANGOS = ("menos de 50", "entre 50 y 100", "entre 100 y 500", "entre 500 y 1.000", "entre 1.000 y 5.000", "más de 5.000")
_CASI = re.compile(
    r"(?P<rango>" + "|".join(re.escape(r) for r in _RANGOS) + r")(?=\s+(?:" + _NOMBRES + r")\b)"
    r"|(?<![\w.,])(?P<num>\d{1,3}(?:\.\d{3})+|\d+)(?P<sp>\s+)(?P<nombre>" + _NOMBRES + r")\b", re.IGNORECASE)
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s<>()\[\]\"'|]+", re.IGNORECASE)
_TELEFONO = re.compile(r"(?<![\w+])\+?\d[\d\s().-]{7,}\d(?![\w])")


@dataclass(frozen=True)
class Brief:
    brief_id: str
    experto: str
    ronda: int
    texto: str
    sha256: str
    sha256_cuerpo: str


def _plegar(t: str) -> str:
    """Minúsculas y sin tildes carácter a carácter, conservando la longitud (para mapear spans)."""
    salida = []
    for ch in t:
        d = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn").lower()
        salida.append(d if len(d) == 1 else (ch.lower() if len(ch.lower()) == 1 else ch))
    return "".join(salida)


def _regex_termino(termino: str) -> re.Pattern | None:
    partes = _plegar(termino).split()
    if not partes:
        return None
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(p) for p in partes) + r"(?!\w)")


def _sustituir_termino(texto: str, termino: str, por: str) -> str:
    rx = _regex_termino(termino)
    if rx is None:
        return texto
    spans = [m.span() for m in rx.finditer(_plegar(texto))]
    for a, b in reversed(spans):
        texto = texto[:a] + por + texto[b:]
    return texto


def rango_usuarios(n: int) -> str:
    """Rango de §6.2 para un número de usuarios (casi-identificador)."""
    if n < 50:
        return "menos de 50"
    if n < 100:
        return "entre 50 y 100"
    if n < 500:
        return "entre 100 y 500"
    if n < 1000:
        return "entre 500 y 1.000"
    if n < 5000:
        return "entre 1.000 y 5.000"
    return "más de 5.000"


def _host_permitido(url: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in HOSTS_PERMITIDOS


def _telefono(m: re.Match) -> bool:
    return sum(ch.isdigit() for ch in m.group(0)) >= 9


def _palabras(t: str) -> list[str]:
    return re.findall(r"\w+", _plegar(t))  # sin puntuación: «Industriales,» es «industriales»


def _es_subsecuencia(corto: list[str], largo: list[str]) -> bool:
    n = len(corto)
    return n > 0 and any(largo[i:i + n] == corto for i in range(len(largo) - n + 1))


def _personas_heuristicas(sensibles: list[str], cliente: list[str]) -> list[str]:
    """Sin lista de hablantes: términos de 2 a 4 palabras con mayúscula inicial que no son del cliente."""
    salida = []
    for s in sensibles:
        pal = s.split()
        if (2 <= len(pal) <= 4 and all(p[:1].isupper() and p.replace("-", "").replace("'", "").isalpha() for p in pal)
                and not any(_es_subsecuencia(_palabras(s), _palabras(c)) for c in cliente)):
            salida.append(s)
    return salida


def _terminos(sensibles: list[str], cliente: list[str], personas: list[str]) -> list[tuple[str, str]]:
    """(término, sustituto) sin repetir, del más largo al más corto. CLIENTE > PERSONA > SENSIBLE."""
    etiqueta: dict[str, tuple[str, str]] = {}

    def poner(t: str, por: str) -> None:
        t = " ".join((t or "").split())
        if len(t) < 3:
            return
        clave = _plegar(t)
        orden = {"[CLIENTE]": 0, "[PERSONA]": 1, "[SENSIBLE]": 2}
        if clave not in etiqueta or orden[por] < orden[etiqueta[clave][1]]:
            etiqueta[clave] = (t, por)

    for c in cliente:
        poner(c, "[CLIENTE]")
    for p in personas:
        poner(p, "[PERSONA]")
        if p in decision_mod.NOMBRES_DECISIONES:   # quien firma se nombra por su rol: se busca la frase entera
            continue
        for w in p.split():
            w = w.strip(".,;:()")
            if len(w) >= 3 and w[:1].isupper():
                poner(w, "[PERSONA]")
    for s in sensibles:
        pal = _palabras(s)
        if any(_es_subsecuencia(pal, _palabras(c)) for c in cliente):
            poner(s, "[CLIENTE]")
        elif any(_es_subsecuencia(pal, _palabras(p)) for p in personas):
            poner(s, "[PERSONA]")
        else:
            poner(s, "[SENSIBLE]")
    return sorted(etiqueta.values(), key=lambda x: (-len(x[0]), x[0]))


def terminos_anonimizacion(alta: dict, personas: list[str] | None = None) -> tuple[list[str], list[str], list[str]]:
    """(sensibles, cliente, personas) con que se anonimiza el cuerpo del brief: los términos del alta, el cliente y su
    código, y los hablantes (sin ellos, la heurística de nombres). VER15-7 (I1.6): los nombres de quienes firman
    decisiones (`decision.NOMBRES_DECISIONES`) se registran como términos sensibles y como personas, así que un
    comentario de DEVUELTA que los cite llega como [PERSONA] y `hallazgos_sensibles` los busca. La puerta local
    recompone las líneas de la DEVUELTA con esta misma función."""
    sensibles = list(alta["terminos_sensibles"])
    cliente = [alta["cliente"], alta["codigo_cliente"]]
    personas = list(personas) if personas is not None else _personas_heuristicas(sensibles, cliente)
    firmantes = list(decision_mod.NOMBRES_DECISIONES)
    return (sensibles + [n for n in firmantes if n not in sensibles],
            cliente, personas + [n for n in firmantes if n not in personas])


def anonimizar(texto: str, sensibles: list[str], cliente: list[str], personas: list[str]) -> str:
    """§6.2: términos (más largos primero, sin mayúsculas ni tildes, palabra completa), correos,
    teléfonos, URL ajenas y casi-identificadores convertidos en rango."""
    # Primero correos, URL y teléfonos: si se sustituyeran antes los términos, «ana@kelvara.es» quedaría
    # como «[PERSONA]@[CLIENTE].es» y ya no casaría como correo.
    texto = _CORREO.sub("[CORREO]", texto)
    texto = _URL.sub(lambda m: m.group(0) if _host_permitido(m.group(0)) else "[URL]", texto)
    texto = _TELEFONO.sub(lambda m: "[TELÉFONO]" if _telefono(m) else m.group(0), texto)
    for termino, por in _terminos(sensibles, cliente, personas):
        texto = _sustituir_termino(texto, termino, por)

    def casi(m: re.Match) -> str:
        if m.group("rango"):
            return m.group(0)
        return f"{rango_usuarios(int(m.group('num').replace('.', '')))}{m.group('sp')}{m.group('nombre')}"

    return _CASI.sub(casi, texto)


def hallazgos_sensibles(texto: str, sensibles: list[str]) -> list[str]:
    """Lo que queda sin anonimizar ([] si está limpio): términos, correos, teléfonos, URL ajenas y
    números de personas que no están ya en un rango de §6.2."""
    hallazgos = []
    plegado = _plegar(texto)
    for s in sorted(set(sensibles)):
        rx = _regex_termino(s)
        if rx is not None and len(" ".join(s.split())) >= 3 and rx.search(plegado):
            hallazgos.append(f"término sensible: {s}")
    hallazgos += [f"correo: {m.group(0)}" for m in _CORREO.finditer(texto)]
    hallazgos += [f"URL ajena: {m.group(0)}" for m in _URL.finditer(texto) if not _host_permitido(m.group(0))]
    hallazgos += [f"teléfono: {m.group(0)}" for m in _TELEFONO.finditer(texto) if _telefono(m)]
    hallazgos += [f"casi-identificador: {m.group(0)}" for m in _CASI.finditer(texto) if m.group("num")]
    return hallazgos


def normalizar_eco(texto: str) -> str:
    """CRLF -> LF y rstrip(). Nada más (LES-G-047: solo equivalencias demostrables)."""
    return (texto or "").replace("\r\n", "\n").rstrip()


def eco_identico(enviado: str, recibido: str) -> bool:
    return isinstance(recibido, str) and normalizar_eco(enviado) == normalizar_eco(recibido)


def primera_diferencia(enviado: str, recibido: str) -> str:
    """«línea L, columna C» del primer carácter distinto entre los dos textos normalizados."""
    a, b = normalizar_eco(enviado), normalizar_eco(recibido if isinstance(recibido, str) else "")
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    linea = a[:i].count("\n") + 1
    columna = i - (a.rfind("\n", 0, i) + 1) + 1
    return (f"línea {linea}, columna {columna}: enviado {a[i:i + 40]!r}, recibido {b[i:i + 40]!r} "
            f"(longitudes {len(a)} y {len(b)})")


def _valor(campo: dict | None, anon) -> str | None:
    if not campo or not campo.get("entradas"):
        return None
    texto = "; ".join(anon(e["valor"]) for e in campo["entradas"])
    return texto + (" [ASUMIDO, confianza baja]" if campo.get("estado") == "ASUMIDO" else "")


def _correcciones(estado: dict, brief_id: str, ronda: int) -> list[dict]:
    previo = next((b for b in estado["carga"]["briefs"] if b.get("brief_id") == brief_id), None)
    if previo is not None:
        return previo["correcciones"]
    if ronda == 1:
        return []
    ver = estado["carga"].get("verificacion")
    if not ver or ver["resultado"]["verificada"]:
        raise IntegridadRota(f"Ronda {ronda} sin verificación con DISCREPA de la que sacar las correcciones", [])
    from nucleo import verificacion  # diferido: verificacion importa brief
    return verificacion.correcciones(estado)  # con texto_original (LES-G-096)


def _conservar(estado: dict, brief_id: str, ronda: int) -> list[str]:
    """CMP-1 (EA-4): lo ya verificado de la ronda anterior, que el experto conserva. Mismo origen y la misma
    idempotencia que las correcciones: si el brief ya existe, lo suyo (un brief anterior a I1.3 no lo lleva)."""
    previo = next((b for b in estado["carga"]["briefs"] if b.get("brief_id") == brief_id), None)
    if previo is not None:
        return list(previo.get("conservar") or [])
    if ronda == 1:
        return []
    from nucleo import verificacion  # diferido: verificacion importa brief
    return verificacion.lineas_conservar(estado)


def _conservar_precios(estado: dict, brief_id: str, ronda: int) -> list[dict]:
    """PR16-3 y LES-G-100.6 (I1.7): lo que el experto conserva, por efecto (cantidad mensual total por servicio del
    catálogo y plantilla), como dato estructurado que registrar-experto compara con la respuesta nueva
    (`verificacion.errores_conservacion_efecto`). Misma idempotencia que `_conservar`."""
    previo = next((b for b in estado["carga"]["briefs"] if b.get("brief_id") == brief_id), None)
    if previo is not None:
        return list(previo.get("conservar_precios") or [])
    if ronda == 1:
        return []
    from nucleo import verificacion  # diferido: verificacion importa brief
    return verificacion.precios_conservar(estado)


def _aceptados(estado: dict, brief_id: str, ronda: int) -> list[dict]:
    """PR16-6 (I1.7): lo que el verificador ya aceptó en las rondas anteriores de esta versión (contenido de línea,
    veredicto y ronda). El consolidado de esta ronda solo envía lo nuevo o cambiado, y una objeción sobre lo aceptado
    que llega igual pasa a OBSERVACION (verificacion.separar_ya_aceptados). No va en el texto: es dato de control.
    Misma idempotencia que `_conservar`; [] en la ronda 1 (también en la ronda 1 de la versión siguiente)."""
    previo = next((b for b in estado["carga"]["briefs"] if b.get("brief_id") == brief_id), None)
    if previo is not None:
        return list(previo.get("aceptados") or [])
    if ronda == 1:
        return []
    from nucleo import verificacion  # diferido: verificacion importa brief
    return verificacion.aceptados_siguientes(estado)


def numero_es(valor: object) -> str:
    """REVERIF17-5 (I1.8): una cantidad con el formato español (punto de millar y coma decimal, sin ceros de más):
    11.312 → «11,312»; 2555 → «2.555»; 1460.0 → «1.460». Lo que no es un número finito se devuelve como texto."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return str(valor)
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        return str(valor)
    if not d.is_finite():
        return str(valor)
    signo, d = ("-" if d < 0 else ""), abs(d)
    entero, _, decimales = format(d.normalize() if d != d.to_integral_value() else d.to_integral_value(), "f").partition(".")
    grupos = []
    while len(entero) > 3:
        entero, grupos = entero[:-3], [entero[-3:]] + grupos
    return signo + ".".join([entero] + grupos) + ("," + decimales if decimales else "")


_SUSTANTIVOS_MEDIDOR = ((r"token", "tokens"), (r"message", "mensajes"), (r"quer(y|ies)", "consultas"),
                        (r"execution", "ejecuciones"), (r"transaction|operation|request|call", "operaciones"))


def unidad_es(unidad: object, medidor: object = "") -> str | None:
    """REVERIF17-5 (I1.8): la unidad de la cantidad mensual en castellano, desde la unidad del medidor de la instantánea
    («1M» de «… 1M Tokens» → «millones de tokens»; «1 Hour» → «horas»; «1 GB/Month» → «GB»). None si no se reconoce:
    no se adivina (LES-G-047)."""
    u = " ".join(str(unidad or "").split())
    fijas = {"1 Hour": "horas", "1/Hour": "horas", "1 GiB Hour": "GiB·h", "1 GB Hour": "GB·h", "1/Day": "días",
             "1/Month": "meses", "1 GB/Month": "GB", "1 GB": "GB", "1 TB/Month": "TB", "1 TB": "TB"}
    if u in fijas:
        return fijas[u]
    texto = str(medidor or "").lower()
    sustantivo = next((n for rx, n in _SUSTANTIVOS_MEDIDOR if re.search(rx, texto)), "unidades")
    m = re.fullmatch(r"([0-9]+) ?([KM])", u)
    if m:
        n, mult = int(m.group(1)), m.group(2)
        nombre = {("1", "K"): "miles", ("10", "K"): "decenas de miles", ("100", "K"): "centenas de miles",
                  ("1", "M"): "millones"}.get((m.group(1), mult))
        return f"{nombre} de {sustantivo}" if nombre else \
            f"lotes de {numero_es(n * (1000 if mult == 'K' else 1000000))} {sustantivo}"
    return sustantivo if u in ("1", "1 Count", "1 Unit") else None


def _linea_consumo(x: dict, anon, instantanea: dict | None, formato: int) -> str:
    clave, cantidad = str(x.get("clave")), x.get("cantidad_mensual")
    if formato == 1:   # PR17-6 (arreglos I1.7): briefs guardados antes de REVERIF17-5
        return f"- Consumo {anon(clave)}: {cantidad} al mes"
    if cantidad is None:
        return f"- Consumo {anon(clave)}: sin cantidad mensual (precio de referencia)"
    art = ((instantanea or {}).get("plantillas") or {}).get(clave.replace(" · ", "/", 1))
    unidad = unidad_es(art.get("unidad"), art.get("meterName")) if isinstance(art, dict) else None
    if unidad is None:
        return f"- Consumo {anon(clave)}: {numero_es(cantidad)} al mes (unidad no disponible en la instantánea)"
    return f"- Consumo {anon(clave)}: {numero_es(cantidad)} {unidad} al mes"


def resumen_devuelto(estado: dict) -> dict | None:
    """`version_devuelta` de la decisión DEVUELTA que abrió la versión vigente (None en A, sin DEVUELTA o anterior a
    I1.7, cuando la decisión no lo guardaba)."""
    devueltas = decision_mod.comentarios_devuelta(estado)
    if not devueltas:
        return None
    registro = next((d for d in reversed(estado.get("decisiones") or []) if d.get("id") == devueltas[-1]["id"]), {})
    resumen = registro.get("version_devuelta")
    return resumen if isinstance(resumen, dict) else None


def lineas_propuesta_devuelta(estado: dict, anon=lambda t: t, instantanea: dict | None = None,
                              formato: int = 2) -> list[str]:
    """PR17-6: las líneas de SECCION_PROPUESTA, desde `version_devuelta` de la última decisión DEVUELTA que abrió la
    versión vigente (componentes con nivel y región; consumos por servicio del catálogo y plantilla con su cantidad
    mensual). [] en la versión A, sin DEVUELTA o si la decisión no guardó el resumen (anterior a I1.7).
    REVERIF17-5 (I1.8, `formato` 2): la cantidad con formato español y su unidad, leída de la instantánea de precios
    (la montada si no se pasa: anexo_consumo.instantanea_vigente; si no se puede leer, IntegridadRota). `formato` 1: la
    composición anterior, para respetar un brief ya guardado."""
    resumen = resumen_devuelto(estado)
    if resumen is None:
        return []
    salida = [f"- Componente {anon(str(c.get('clave')))} · nivel o modelo {anon(str(c.get('sku')))} · región "
              f"{anon(str(c.get('region')))}" for c in resumen.get("componentes") or [] if isinstance(c, dict)]
    precios = [x for x in resumen.get("precios") or [] if isinstance(x, dict)]
    if precios and formato != 1 and instantanea is None:
        from nucleo import anexo_consumo  # diferido: módulo de B
        instantanea = anexo_consumo.instantanea_vigente()
    salida += [_linea_consumo(x, anon, instantanea, formato) for x in precios]
    return salida


# ───────────── PR17-6 parte 2 (I1.8): el reintento tras un rechazo del núcleo lleva el motivo literal ─────────────
# El brief es inmutable por id (su huella ata la procedencia, el eco y A, que está congelada). El reintento no cambia el
# brief: el texto que se ENVÍA lleva delante un bloque REINTENTO-PREVENTA/1 con el motivo literal del último rechazo del
# núcleo a ese brief, compuesto aquí desde estado.fallos y control_versiones. El experto devuelve en brief_recibido el
# brief desde la línea BRIEF-PREVENTA/1 (instrucción vigente), así que el eco sigue comparándose con el brief.
MARCA_REINTENTO = "REINTENTO-PREVENTA/1"
MAX_MOTIVO_REINTENTO = 6000
FIN_REINTENTO = "=== FIN DEL BLOQUE DE REINTENTO ==="   # el bloque no nombra la primera línea del brief
SUBCOMANDO_EXPERTO = "registrar-experto"


def _instante(ts: object) -> datetime.datetime | None:
    try:
        t = datetime.datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return t if t.tzinfo else None


def _duenos_de_fallos(estado: dict) -> list[tuple[dict, dict | None]]:
    """(fallo, control que lo sumó). REV-5: un fallo es siempre posterior (1 s o más) al control anterior y el control de
    su subcomando nunca es anterior a él, así que su dueño es el primer control con marca igual o posterior."""
    cv = [c for c in estado.get("control_versiones") or [] if isinstance(c, dict) and _instante(c.get("ts"))]
    salida = []
    for f in estado.get("fallos") or []:
        tf = _instante(f.get("ts")) if isinstance(f, dict) else None
        if tf is None:
            continue
        salida.append((f, next((c for c in cv if _instante(c["ts"]) >= tf), None)))
    return salida


def control_registro_experto(estado: dict) -> int | None:
    """`n` del control de registrar-experto que registró la respuesta vigente: el último que no sumó ningún fallo."""
    con_fallo = {id(c) for _, c in _duenos_de_fallos(estado) if c is not None}
    buenos = [c for c in estado.get("control_versiones") or [] if isinstance(c, dict)
              and c.get("subcomando") == SUBCOMANDO_EXPERTO and id(c) not in con_fallo and isinstance(c.get("n"), int)]
    return buenos[-1]["n"] if buenos else None


def rechazos_vigentes(estado: dict, hasta_n: int | None = None) -> list[dict]:
    """Los fallos T2 que sumó registrar-experto (rechazos del núcleo a una respuesta del experto) desde el último
    `enrutar` (el que creó el brief vigente). Con `hasta_n`, solo los controles anteriores a ese `n` (la puerta lo usa
    con el control que registró la respuesta)."""
    cv = [c for c in estado.get("control_versiones") or [] if isinstance(c, dict) and isinstance(c.get("n"), int)]
    limite = [c for c in cv if hasta_n is None or c["n"] < hasta_n]
    enrutar = next((c for c in reversed(limite) if c.get("subcomando") == "enrutar"), None)
    if enrutar is None:
        return []
    return [f for f, c in _duenos_de_fallos(estado) if f.get("fase") == "T2" and c is not None
            and c.get("subcomando") == SUBCOMANDO_EXPERTO and isinstance(c.get("n"), int)
            and c["n"] > enrutar["n"] and (hasta_n is None or c["n"] < hasta_n)]


def texto_envio(estado: dict, brief: dict, hasta_n: int | None = None) -> str:
    """Lo que se envía al experto para `brief`: el brief tal cual si no hubo rechazo del núcleo desde su `enrutar`; si lo
    hubo, el bloque REINTENTO-PREVENTA/1 con el motivo literal del último rechazo (anonimizado con los términos del alta,
    por defensa en profundidad) y, detrás, el brief entero. Determinista: la puerta local lo recompone."""
    rechazos = rechazos_vigentes(estado, hasta_n)
    if not rechazos:
        return brief["texto"]
    sensibles, cliente, personas = terminos_anonimizacion(estado["carga"]["alta"])
    motivo = unicodedata.normalize("NFC", anonimizar(str(rechazos[-1].get("error") or ""), sensibles, cliente,
                                                     personas)).strip()
    if len(motivo) > MAX_MOTIVO_REINTENTO:
        motivo = motivo[:MAX_MOTIVO_REINTENTO] + f" [recortado: {len(motivo) - MAX_MOTIVO_REINTENTO} caracteres más]"
    bloque = [MARCA_REINTENTO, f"brief_id: {brief['brief_id']}", f"rechazos_previos: {len(rechazos)}",
              "## Motivo literal del último rechazo del código (corrígelo en tu nueva respuesta; la anterior no se ha "
              "guardado)", motivo, "## Cómo responder",
              "Responde como siempre al brief, que empieza en la línea siguiente a la marca de fin de este bloque y llega "
              "hasta el final. En brief_recibido copia solo el brief, sin este bloque de reintento.", FIN_REINTENTO]
    return "\n".join(bloque) + "\n" + brief["texto"]


def _lineas_base(req: dict, anon) -> list[str]:
    """Necesidad, alcance, canales, usuarios y marco, contexto y fuera de alcance (igual en todas las rondas)."""
    cuerpo = ["## Necesidad", f"Objetivo: {_valor(req['objetivo'], anon)}", f"Nubes: {_valor(req['nubes'], anon)}",
              "## Alcance funcional"]
    cuerpo += [f"- {anon(e['valor'])}" for e in req["alcance_funcional"]["entradas"]]
    # VERIF-2: el canal (p. ej., Teams) es requisito de arquitectura y de precio, no un adorno de `nubes`
    canales = req["canales_integraciones"]
    marca = " [ASUMIDO, confianza baja]" if canales.get("estado") == "ASUMIDO" else ""
    cuerpo += ["## Canales e integraciones"] + [f"- {anon(e['valor'])}{marca}" for e in canales["entradas"]]
    cuerpo += ["## Usuarios y marco normativo",
               f"Ubicación de los usuarios finales: {_valor(req['ubicacion_usuarios'], anon)}",
               f"Marco normativo: {_valor(req['marco_normativo'], anon)}", "## Contexto"]
    cuerpo += [f"{etq}: {_valor(req[k], anon)}" for k, etq in ETIQUETAS_CONTEXTO if _valor(req.get(k), anon)]
    fda = (req.get("fuera_de_alcance") or {}).get("entradas") or []
    if fda:
        cuerpo += ["## Fuera de alcance"] + [f"- {anon(e['valor'])}" for e in fda]
    # REV17-3 (I1.8, CAMBIOS-I18-P §4.1): lo que el cliente ya tiene o paga, citado en requisitos (nunca asumido). Antes
    # de cualquier sección de fin de requisitos (experto._FIN_REQUISITOS) y en el orden de las entradas.
    from nucleo import experto  # diferido: experto importa este módulo
    # I1.9 (PR18-1, CAMBIOS-I19-P §5.2): una viñeta por entrada EX con su servicio, el fragmento y la cita ENTERA
    ycc = experto.lineas_brief_existentes({"campos": req}, anon)
    if ycc:
        cuerpo += [experto.SECCION_CLIENTE] + ycc
    return cuerpo


def cuerpos_ronda_1(estado: dict, anon, instantanea: dict | None = None) -> dict[str, list[str]]:
    """REVERIF17-4 (I1.8): las líneas del cuerpo que compone `generar` para la ronda 1 de la versión vigente (no lleva
    correcciones ni lo conservado). «vigente»: la composición actual; «propuesta_formato_1»: la propuesta devuelta con
    la composición de los arreglos de I1.7 (anterior a REVERIF17-5); «sin_propuesta» y «sin_devuelta»: las de los
    briefs guardados antes de PR17-6 y de PR14-6, que solo valen si la decisión DEVUELTA no guardó `version_devuelta`
    (o no hay DEVUELTA). La puerta compara el cuerpo entero con estas composiciones."""
    req = estado["carga"]["requisitos"]["campos"]
    cuerpo = _lineas_base(req, anon)
    salida = {"sin_devuelta": list(cuerpo)}
    devueltas = decision_mod.comentarios_devuelta(estado)
    if devueltas:
        cuerpo += [SECCION_DEVUELTA.format(version=devueltas[0]["version"])]
        cuerpo += [f"- {anon(d['comentarios'])}" for d in devueltas]
    salida["sin_propuesta"] = list(cuerpo)
    propuesta = lineas_propuesta_devuelta(estado, anon, instantanea)
    salida["vigente"] = cuerpo + ([SECCION_PROPUESTA.format(version=devueltas[0]["version"])] + propuesta
                                  if propuesta else [])
    if propuesta:
        salida["propuesta_formato_1"] = cuerpo + [SECCION_PROPUESTA.format(version=devueltas[0]["version"])] \
            + lineas_propuesta_devuelta(estado, anon, formato=1)
    return salida


def generar(estado: dict, perfiles: list[str], catalogo_sha256: str, personas: list[str] | None = None) -> Brief:
    """Compone el brief de la ronda vigente, lo anonimiza, comprueba que no queda nada sensible y lo
    añade a carga.briefs (idempotente: mismo id y mismo texto no se repite; distinto -> IntegridadRota).

    `personas` (hablantes de la transcripción) es opcional; sin ella se deducen de los términos.
    """
    c = estado["carga"]
    pilar = est_mod.pilar(estado)
    experto = experto_de(pilar)
    req = (c.get("requisitos") or {}).get("campos")
    if not req:
        raise ReglaIncumplida("No hay requisitos registrados: el brief sale de suficiencia completa", [])
    faltan = [k for k in ("objetivo", "nubes", "alcance_funcional", "canales_integraciones", "ubicacion_usuarios",
                          "marco_normativo")
              + tuple(k for k, _ in ETIQUETAS_CONTEXTO) if not (req.get(k) or {}).get("entradas")]
    if faltan:
        raise ReglaIncumplida("Requisitos incompletos: no se puede enrutar", [f"falta {k}" for k in faltan])
    if not perfiles or len(set(perfiles)) != len(perfiles):
        raise IntegridadRota("Lista de perfiles de la tarifa vacía o con repetidos", [repr(perfiles)])
    if not re.fullmatch(r"[0-9a-f]{64}", catalogo_sha256 or ""):
        raise IntegridadRota("catalogo_sha256 no es un SHA-256", [repr(catalogo_sha256)])
    sensibles, cliente, personas = terminos_anonimizacion(c["alta"], personas)

    def anon(t: str) -> str:
        return " ".join(anonimizar(t, sensibles, cliente, personas).split())  # una línea por valor

    ronda = est_mod.ronda_actual(estado)
    brief_id = est_mod.brief_id_vigente(estado)
    correcciones = _correcciones(estado, brief_id, ronda)
    conservar = _conservar(estado, brief_id, ronda)
    conservar_precios = _conservar_precios(estado, brief_id, ronda)
    aceptados = _aceptados(estado, brief_id, ronda)
    cuerpo = _lineas_base(req, anon)
    devueltas = decision_mod.comentarios_devuelta(estado)
    sin_devuelta = list(cuerpo)   # para reconocer un brief ya guardado antes de I1.5 (sin la sección)
    if devueltas:
        cuerpo += [SECCION_DEVUELTA.format(version=devueltas[0]["version"])]
        cuerpo += [f"- {anon(d['comentarios'])}" for d in devueltas]
    sin_propuesta = list(cuerpo)   # para reconocer un brief guardado antes de PR17-6 (sin la sección)
    propuesta = lineas_propuesta_devuelta(estado, anon) if ronda == 1 else []
    if propuesta:
        cuerpo += [SECCION_PROPUESTA.format(version=devueltas[0]["version"])] + propuesta
    if correcciones:
        cuerpo += ["## Correcciones solicitadas por el verificador"]
        from nucleo import verificacion  # diferido: verificacion importa brief
        cuerpo += [ln for x in correcciones for ln in verificacion.lineas_correccion(x, anon)]
    # Las líneas vienen del consolidado anterior, ya anonimizado; se anonimizan otra vez por defensa en profundidad.
    otros, precios = [ln for ln in conservar if not ln.startswith("P-")], [ln for ln in conservar if ln.startswith("P-")]
    # PR16-6 (Revisión, I1.7): lo que el verificador NO aceptó (NO VERIFICABLE) va en su propia sección, así la puerta puede
    # atar cada `aceptados` a una línea de «Elementos ya verificados» del texto sellado. Un brief guardado antes de I1.7
    # (sin la clave «aceptados») se recompone como entonces.
    previo_b = next((x for x in c["briefs"] if x.get("brief_id") == brief_id), None)
    if ronda > 1 and (previo_b is None or "aceptados" in previo_b):
        from nucleo import verificacion  # diferido: verificacion importa brief
        claves = {" ".join(str(a.get("linea") or "").split()) for a in aceptados if isinstance(a, dict)}
        sin_verificar = [ln for ln in otros if verificacion.contenido_linea(ln) not in claves]
        otros = [ln for ln in otros if verificacion.contenido_linea(ln) in claves]
    else:
        sin_verificar = []
    if otros:
        cuerpo += ["## Elementos ya verificados (consérvalos tal cual; solo cambia lo que piden las correcciones)"]
        cuerpo += [f"- {anon(ln)}" for ln in otros]
    if sin_verificar:
        cuerpo += [SECCION_SIN_VERIFICAR]
        cuerpo += [f"- {anon(ln)}" for ln in sin_verificar]
    if precios:  # I1.7: el precio lo pone el núcleo desde la instantánea; el experto conserva plantilla y cantidades
        cuerpo += [SECCION_PRECIOS]
        cuerpo += [f"- {anon(ln)}" for ln in precios]
    def componer(lineas: list[str], con_huellas: bool = False) -> tuple[str, str]:
        """PR19-1 (I1.10): la cabecera ya no lleva las dos huellas de 64 caracteres hexadecimales (catalogo_sha256 y
        sha256_cuerpo), que el experto tenía que copiar en brief_recibido y eran donde más fallaba la copia. Las dos
        siguen en la entrada de carga.briefs, y la puerta las comprueba. `con_huellas` recompone un brief anterior."""
        cuerpo_nfc = unicodedata.normalize("NFC", "\n".join(lineas))
        cabecera = ["BRIEF-PREVENTA/1", f"brief_id: {brief_id}", f"experto: {experto}", f"ronda: {ronda}"]
        if con_huellas:
            cabecera += [f"catalogo_sha256: {catalogo_sha256}", f"perfiles_permitidos: {'; '.join(perfiles)}",
                         f"sha256_cuerpo: {hashes.sha256_texto(cuerpo_nfc)}", "---"]
        else:
            cabecera += [f"perfiles_permitidos: {'; '.join(perfiles)}", "---"]
        return "\n".join(cabecera) + "\n" + cuerpo_nfc, cuerpo_nfc

    texto, texto_cuerpo = componer(cuerpo)
    previo = next((x for x in c["briefs"] if x.get("brief_id") == brief_id), None)
    if previo is not None and previo.get("catalogo_sha256") not in (None, catalogo_sha256):
        # PR19-1: antes lo delataba la línea catalogo_sha256 del texto; ahora se compara la entrada guardada (sin el
        # campo, el texto anterior lleva esa línea y la comparación de textos de abajo lo sigue delatando)
        raise IntegridadRota(f"Ya existe {brief_id} con otro texto: se generó con otro catálogo (¿cambió el catálogo "
                             "montado?)",
                             [f"guardado {previo.get('catalogo_sha256')!r}", f"montado {catalogo_sha256}"])
    # Un brief ya guardado se respeta tal cual se envió (es lo que vio el experto): antes de PR17-6 no llevaba la
    # propuesta devuelta y antes de PR14-6 tampoco los comentarios. Se prueban esas composiciones, en ese orden.
    resto = cuerpo[len(sin_propuesta) + (1 + len(propuesta) if propuesta else 0):]   # correcciones y conservar
    # REVERIF17-5 (I1.8): un brief guardado con la propuesta en el formato de los arreglos de I1.7 se respeta
    formato_1 = ([sin_propuesta + [SECCION_PROPUESTA.format(version=devueltas[0]["version"])]
                  + lineas_propuesta_devuelta(estado, anon, formato=1) + resto] if propuesta else [])
    candidatas = formato_1 + ([sin_propuesta + resto] if propuesta else []) + ([sin_devuelta + resto] if devueltas else [])
    # PR19-1: cada composición se prueba también con la cabecera anterior a I1.10 (la de las dos huellas)
    for alternativa, con_huellas in [(cuerpo, True)] + [(a, h) for a in candidatas for h in (False, True)]:
        if previo is None or previo["texto"] == texto:
            break
        viejo, viejo_cuerpo = componer(alternativa, con_huellas)
        if previo["texto"] == viejo:
            texto, texto_cuerpo = viejo, viejo_cuerpo
    if len(texto.encode("utf-8")) > MAX_BYTES:
        raise EntradaInvalida(f"El brief supera {MAX_BYTES} bytes", [f"{len(texto.encode('utf-8'))} bytes"])
    # Solo el cuerpo: la cabecera la compone el código con ids del contrato, y brief_id lleva por diseño
    # el código de cliente (riesgo declarado en docs/I1/CAMBIOS-INTERFAZ-BA.md).
    hallazgos = hallazgos_sensibles(texto_cuerpo, sensibles)
    if hallazgos:
        est_mod.bloquear(estado, f"El brief {brief_id} conserva datos sensibles: {'; '.join(hallazgos)[:600]}")
        raise Bloqueo(f"Brief {brief_id} con datos sensibles tras anonimizar", hallazgos)
    b = Brief(brief_id, experto, ronda, texto, hashes.sha256_texto(texto), hashes.sha256_texto(texto_cuerpo))
    if previo is not None:
        if previo["texto"] != texto:
            raise IntegridadRota(f"Ya existe {brief_id} con otro texto (¿cambió el catálogo o la tarifa montados?)",
                                 [primera_diferencia(previo["texto"], texto)])
        return b
    c["briefs"].append({"brief_id": brief_id, "experto": experto, "version": estado["version"], "ronda": ronda,
                        "texto": texto, "sha256": b.sha256, "sha256_cuerpo": b.sha256_cuerpo,
                        "catalogo_sha256": catalogo_sha256, "perfiles_permitidos": list(perfiles),
                        "correcciones": correcciones, "conservar": conservar, "conservar_precios": conservar_precios,
                        "aceptados": aceptados, **({} if pilar == est_mod.PILAR_POR_DEFECTO else {"pilar": pilar})})
    return b
