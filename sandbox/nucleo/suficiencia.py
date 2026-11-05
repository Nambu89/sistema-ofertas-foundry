"""Suficiencia de la solicitud (CONTRATOS.md §3.3 y §4.5).

El modelo rellena entrada/requisitos.json; aquí se recalcula el estado de cada campo y cada cita
se comprueba por subcadena normalizada contra el texto extraído de las fuentes registradas.
ASUMIDO solo lo fija el comercial con `asumir` (un ASUMIDO escrito por el modelo se rechaza).
"""
from __future__ import annotations

import copy
import importlib
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field

from nucleo import esquema, estado as est_mod
from nucleo.errores import EntradaInvalida, ReglaIncumplida

BLOQUEANTES: tuple[str, ...] = ("objetivo", "nubes", "alcance_funcional", "ubicacion_usuarios", "marco_normativo")
ASUMIBLES: tuple[str, ...] = ("canales_integraciones", "volumetria", "identidad_acl_origen", "red_privada",
                              "tipo_suscripcion", "plazo", "presupuesto_orientativo", "idioma_oferta")
OPCIONALES: tuple[str, ...] = ("fuera_de_alcance", "ya_contratado_por_cliente")
# REV17-3 (I1.8, decisión del PM): lo que el cliente ya tiene o paga (licencias, un servicio existente) solo vale con
# cita literal de la fuente: ni se asume (no es ASUMIBLE) ni el modelo lo escribe como ASUMIDO. De aquí sale la única
# cita que admite el motivo «a_cargo_del_cliente» del experto (experto.citas_cliente).
SOLO_CITADOS: tuple[str, ...] = ("ya_contratado_por_cliente",)
# I1.9 (PR18-1, decisión del PM): una entrada por recurso, con id «EX-nn», su servicio del catálogo (o null), el
# fragmento literal que lo nombra y la cita ENTERA de la fuente (errores_existentes; el brief lleva la cita, no un
# resumen). En Hostelia el resumen «API REST de RR. HH. que ya tienen en Azure» perdió el App Service y el API
# Management de la cita, y el experto valoró un API Management nuevo de 173,45 € al mes.
CAMPO_EXISTENTES = "ya_contratado_por_cliente"
CAMPOS: tuple[str, ...] = BLOQUEANTES + ASUMIBLES + OPCIONALES
CITA_MIN_CARACTERES = 15
CITA_MIN_PALABRAS = 3
NUBES_I1 = ("azure", "microsoft azure")
# REV-1 (LES-G-098.3): `nubes` falla cerrado con una LISTA BLANCA, no con una lista negra de proveedores (con la
# lista negra pasaban «Azure y nuestro centro de datos», DigitalOcean o «nube privada»). El valor, normalizado y
# sin puntuación en los extremos, tiene que ser una de estas formas; cualquier otra cosa se rechaza, también las
# negaciones («Azure, no AWS»). Se rechaza, no se reescribe (LES-G-047): la cita conserva la frase literal del
# cliente, así que el valor puede ser corto («Azure») sin perder nada. Misma lista en verificar_paquete.
PLANTILLAS_NUBES = ("{}", "en {}", "solo {}", "solo en {}", "unicamente en {}", "debe vivir en {}",
                    "la solucion debe vivir en {}", "queremos que viva en {}", "queremos que esto viva en {}")
NUBES_ADMITIDAS = frozenset(p.format(n) for p in PLANTILLAS_NUBES for n in NUBES_I1)
# Multinube (esquemas/MULTINUBE.md): la misma lista blanca con los nombres de la nube del pilar de la solicitud.
NUBES_PILAR = {"azure": NUBES_I1, "gcp": ("google cloud", "google cloud platform", "gcp"),
               "aws": ("aws", "amazon web services")}
NUBES_ADMITIDAS_PILAR = {p: frozenset(t.format(n) for t in PLANTILLAS_NUBES for n in ns) for p, ns in NUBES_PILAR.items()}
_BORDES_NUBES = " .,;:!?¡¿«»\"'"
# VER-2: separadores de línea (no se colapsan: hacen fallar la lista blanca) y espacios horizontales (sí se colapsan).
_SALTOS = re.compile(r"[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
_ESPACIOS_H = re.compile(r"[^\S\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]+")
_NOTE = re.compile(r"\bNOTE\b")
_AZURE = re.compile(r"\bazure\b")
# EB-4: Microsoft 365 es un entorno (donde trabajan los usuarios), no una nube de despliegue de la solución.
_M365 = re.compile(r"\b(microsoft 365|m365|office 365|o365|microsoft365|office365)\b")


@dataclass(frozen=True)
class ResultadoSuficiencia:
    completo: bool
    faltan: list[str] = field(default_factory=list)
    citas_invalidas: list[str] = field(default_factory=list)
    preguntas: list[str] = field(default_factory=list)


def nfc(obj: object) -> object:
    """NFC recursivo sobre cadenas (todo lo que entra en `carga` pasa por aquí)."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {nfc(k): nfc(v) for k, v in obj.items()}
    return obj


def extraer_texto(ruta: pathlib.Path) -> str:
    """Texto de .txt/.vtt (UTF-8), .docx (python-docx) o .pdf (fitz), en NFC y con LF."""
    ruta = pathlib.Path(ruta)
    ext = ruta.suffix.lower()
    try:
        if ext in (".txt", ".vtt"):
            texto = ruta.read_bytes().decode("utf-8-sig")
        elif ext == ".docx":
            import docx
            d = docx.Document(str(ruta))
            partes = [p.text for p in d.paragraphs]
            for t in d.tables:
                partes += [" | ".join(c.text for c in fila.cells) for fila in t.rows]
            texto = "\n".join(partes)
        elif ext == ".pdf":
            import fitz
            with fitz.open(str(ruta)) as doc:
                texto = "\n".join(p.get_text() for p in doc)
        else:
            raise EntradaInvalida(f"Formato de fuente no admitido: {ruta.name}", ["admitidos: .txt, .vtt, .docx, .pdf"])
    except EntradaInvalida:
        raise
    except Exception as e:  # ilegible: se dice cuál y por qué
        raise EntradaInvalida(f"No se puede extraer el texto de {ruta.name}: {e}", [repr(e)]) from e
    texto = unicodedata.normalize("NFC", texto.replace("\r\n", "\n").replace("\r", "\n"))
    if not texto.strip():
        raise EntradaInvalida(f"La fuente {ruta.name} no tiene texto", [])
    return texto


_TS = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}\s*-->.*$")
_VOZ = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]{1,80})>")
_HABLANTE_LINEA = re.compile(
    r"^\s*\[?\(?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\)?\]?\s*[-–]?\s*"
    r"([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'.-]*(?:\s+[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'.-]*){0,4})\s*:\s")


def hablantes(texto: str) -> list[str]:
    """Nombres de hablante: `<v Nombre>` (VTT) o `Nombre:` tras una marca de tiempo. Sin repetir."""
    vistos: list[str] = []
    for linea in texto.splitlines():
        for m in list(_VOZ.finditer(linea)) + ([_HABLANTE_LINEA.match(linea)] if _HABLANTE_LINEA.match(linea) else []):
            nombre = " ".join(unicodedata.normalize("NFC", m.group(1)).split())
            if len(nombre) >= 3 and nombre not in vistos:
                vistos.append(nombre)
    return vistos


def _sin_tildes(t: str) -> str:
    return unicodedata.normalize("NFC", "".join(
        ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn"))


def _quitar_vtt(texto: str) -> str:
    """Quita cabecera WEBVTT, bloques NOTE, identificadores de cue, marcas de tiempo y <v …>/</v>."""
    lineas = texto.split("\n")
    es_vtt = bool(lineas) and lineas[0].lstrip("\ufeff").strip().upper().startswith("WEBVTT")
    salida: list[str] = []
    i = 0
    while i < len(lineas):
        ln = lineas[i]
        if es_vtt and i == 0:
            i += 1
            continue
        if es_vtt and (ln.strip() == "NOTE" or ln.startswith("NOTE ")):
            while i < len(lineas) and lineas[i].strip():
                i += 1
            continue
        if _TS.match(ln):
            # identificador de cue: línea no vacía, sola, justo antes de la marca de tiempo
            if (es_vtt and i >= 1 and lineas[i - 1].strip() and (i < 2 or not lineas[i - 2].strip())
                    and salida and salida[-1] == lineas[i - 1]):
                salida.pop()
            i += 1
            continue
        salida.append(ln)
        i += 1
    t = "\n".join(salida)
    return re.sub(r"</v\s*>", " ", _VOZ.sub(" ", t))


def normalizar_para_cita(texto: str) -> str:
    """§3.3: NFC -> minúsculas -> sin tildes -> sin marcas VTT -> espacios colapsados."""
    t = unicodedata.normalize("NFC", (texto or "").replace("\r\n", "\n").replace("\r", "\n"))
    t = _quitar_vtt(t)
    t = _sin_tildes(t.lower())
    return " ".join(t.split())


def cita_valida(cita: str, textos_fuente: dict[str, str]) -> bool:
    """Subcadena normalizada de alguna fuente, con al menos 15 caracteres y 3 palabras."""
    if not isinstance(cita, str):
        return False
    n = normalizar_para_cita(cita)
    if len(n) < CITA_MIN_CARACTERES or len(n.split()) < CITA_MIN_PALABRAS:
        return False
    return any(n in normalizar_para_cita(t) for t in textos_fuente.values())


_PREGUNTAS = {
    "objetivo": ("¿Qué problema concreto debe resolver la solución?", "Asistente que responde con citas sobre documentación interna",
                 "Automatizar un proceso con agentes", "Analítica o informes con IA"),
    "nubes": ("¿En qué nube debe vivir la solución?", "Azure",
              "Azure, usado desde Microsoft 365 o Teams (el canal va en canales_integraciones)",
              "Otra nube, despliegue local o nube privada (fuera de I1)"),
    "alcance_funcional": ("¿Qué capacidades debe tener el primer día?", "Búsqueda y respuesta con cita",
                          "Resumen y comparación de documentos", "Acciones sobre sistemas del cliente"),
    "ubicacion_usuarios": ("¿Dónde están los usuarios finales (no la sede del cliente)?", "España",
                           "Unión Europea", "Fuera de la UE (indicar país)"),
    "marco_normativo": ("¿Qué marco normativo aplica a los datos y a los usuarios?", "RGPD con datos en la UE",
                        "RGPD más normativa sectorial", "Normativa de fuera de la UE (p. ej., HIPAA)"),
    "canales_integraciones": ("¿Desde qué canal lo usarán los usuarios y con qué sistemas debe integrarse?",
                              "Microsoft Teams", "Portal web propio con Entra ID", "Ninguna integración más allá del origen documental"),
    "volumetria": ("¿Qué volumen hay que dimensionar (usuarios, documentos, consultas)?",
                   "Menos de 50 usuarios y menos de 5.000 documentos", "Entre 50 y 500 usuarios y hasta 50.000 documentos",
                   "Más de 500 usuarios o más de 50.000 documentos"),
    "identidad_acl_origen": ("¿Dónde están los documentos y qué identidad gobierna sus permisos?",
                             "SharePoint Online con permisos por grupos de Entra ID",
                             "Repositorio propio sin permisos por documento", "Varios orígenes con permisos distintos"),
    "red_privada": ("¿Hace falta red privada?", "Sí, entrada y salida privadas", "Solo entrada privada",
                    "No, acceso público con autenticación"),
    "tipo_suscripcion": ("¿Qué tipo de suscripción de Azure tiene el cliente?", "Enterprise Agreement o MCA-E directo",
                         "CSP a través de un revendedor", "Pago por uso"),
    "plazo": ("¿Qué plazo se espera?", "Piloto en unos tres meses", "Piloto en seis semanas", "Sin fecha cerrada"),
    "presupuesto_orientativo": ("¿Hay un presupuesto orientativo?", "Menos de 25.000 euros", "Entre 25.000 y 60.000 euros",
                                "Más de 60.000 euros"),
    "idioma_oferta": ("¿En qué idioma va la oferta?", "Castellano", "Inglés", "Catalán"),
    "fuera_de_alcance": ("¿Hay algo que quede explícitamente fuera?", "Integraciones con sistemas de gestión",
                         "Soporte posterior a la aceptación", "Nada fuera de alcance"),
    "ya_contratado_por_cliente": ("¿Qué servicios o licencias ya tiene o paga el cliente por su cuenta?",
                                  "Licencias de Microsoft 365 con Teams y SharePoint",
                                  "Un servicio de Azure que ya usa (por ejemplo, Log Analytics)", "Nada: se valora todo"),
}


def preguntas_para(campo: str) -> str:
    """Pregunta fija a/b/c/d del campo (tabla de este módulo)."""
    if campo not in _PREGUNTAS:
        raise EntradaInvalida(f"Campo desconocido: {campo!r}", [f"admitidos: {list(CAMPOS)}"])
    q, a, b, c = _PREGUNTAS[campo]
    como = (f"ASUMIR: {campo} = valor" if campo in ASUMIBLES else "aclaración del comercial citada en suficiencia")
    return "\n".join([f"{campo}: {q}", f"  a) {a}", f"  b) {b}", f"  c) {c}", f"  d) otra: indicarla ({como})"])


def forma_nubes(valor: object) -> str:
    """Forma comparable de un valor de `nubes`: NFC, minúsculas, sin tildes, espacios horizontales colapsados y sin
    puntuación en los extremos. Misma función en verificar_paquete.forma_nubes.

    VER-2 (I1.2): NO usa normalizar_para_cita, que borra líneas de tiempo, bloques NOTE y etiquetas <v …>; con ella
    «Azure» + una línea «00:00:01.000 --> 00:00:02.000 y AWS» quedaba en «azure» y entraba en la lista blanca. Aquí
    no se borra nada: un salto de línea, una marca de tiempo, una etiqueta o un NOTE siguen en la forma y no casan.
    """
    t = _sin_tildes(unicodedata.normalize("NFC", valor if isinstance(valor, str) else "").lower())
    return _ESPACIOS_H.sub(" ", t).strip(_BORDES_NUBES)


def sintaxis_en_nubes(valor: object) -> bool:
    """El valor lleva un salto de línea o sintaxis de subtítulos (marca de tiempo «-->», «<v …>», «NOTE»)."""
    t = valor if isinstance(valor, str) else ""
    return bool(_SALTOS.search(t)) or "-->" in t or "<" in t or ">" in t or _NOTE.search(t) is not None


def nubes_fuera_de_i1(valores: list[str], pilar: str = "azure") -> list[str]:
    """Motivo por cada valor de `nubes` que I1 no cubre ([] si todos valen). Misma regla en verificar_paquete.

    Lista blanca (falla cerrado): solo vale una forma de NUBES_ADMITIDAS («Azure», «Microsoft Azure», «La solución
    debe vivir en Azure.»…). El valor nunca se reescribe (LES-G-047) y la cita conserva el literal.
    """
    motivos = []
    for v in valores:
        texto = v if isinstance(v, str) else repr(v)
        n = forma_nubes(v)
        if n in NUBES_ADMITIDAS_PILAR[pilar]:
            continue
        if sintaxis_en_nubes(v):
            motivos.append(f"{texto[:120]!r} lleva saltos de línea o sintaxis de subtítulos (marca de tiempo, <v …> "
                           "o NOTE) y no es una forma admitida de `nubes` (fuera de I1): el valor es solo «Azure», en "
                           "una línea, y la frase del cliente va en la cita")
        elif _M365.search(n):  # EB-4: se rechaza igual (LES-G-047); solo se precisa el motivo
            motivos.append(f"«{texto[:120]}» es un entorno del cliente, no una nube de despliegue: Microsoft 365 "
                           "(Teams, SharePoint, Outlook) va en canales_integraciones, o en identidad_acl_origen si es "
                           "donde están los documentos; en `nubes` va solo la nube donde se despliega, «Azure», si "
                           "el cliente lo dice, y si no, el campo queda en FALTA")
        elif not _AZURE.search(n):
            motivos.append(f"«{texto[:120]}» no es Azure (fuera de I1): en `nubes` va solo la nube, con el valor "
                           "«Azure»; un canal como Teams va en canales_integraciones y no se borra")
        else:
            motivos.append(f"«{texto[:120]}» no es una forma admitida de `nubes` (fuera de I1): el valor es «Azure» y la "
                           "cita conserva la frase literal; lo demás que diga la frase (un canal, otra nube, un "
                           "despliegue local o una nube privada) va en su campo o queda fuera de I1")
    return motivos


def _estado_campo(entradas: list[dict]) -> str:
    if not entradas:
        return "FALTA"
    return "ASUMIDO" if all(e["origen"] == "ASUMIDO" for e in entradas) else "CITADO"


def _faltan(campos: dict) -> list[str]:
    return [c for c in BLOQUEANTES + ASUMIBLES if (campos.get(c) or {}).get("estado", "FALTA") == "FALTA"]


def _resultado(campos: dict) -> ResultadoSuficiencia:
    faltan = _faltan(campos)
    return ResultadoSuficiencia(completo=not faltan, faltan=faltan, citas_invalidas=[],
                                preguntas=[preguntas_para(c) for c in faltan])


def _guardar_requisitos(estado: dict, nuevos: dict) -> None:
    if estado["carga"].get("requisitos") != nuevos:
        est_mod.invalidar_desde(estado, "requisitos")
    estado["carga"]["requisitos"] = nuevos


def errores_existentes(entradas: list, catalogo: dict | None) -> list[str]:
    """I1.9 (PR18-1, decisión del PM): motivos por los que `ya_contratado_por_cliente.entradas` no deja una entrada por
    recurso con su cita entera; [] si cumple (el detalle de reglas_existentes, con el id de la entrada delante)."""
    return [f"{ex}: {detalle}" for ex, _regla, detalle in _existentes(entradas, catalogo)]


def reglas_existentes(entradas: list, catalogo: dict | None) -> list[tuple]:
    """[(id de la entrada, regla)] de errores_existentes, en orden: lo que compara la réplica de la puerta."""
    return [(ex, regla) for ex, regla, _detalle in _existentes(entradas, catalogo)]


def _existentes(entradas: list, catalogo: dict | None) -> list[tuple]:
    """[(id, regla, detalle)] en orden de las entradas (misma regla en la réplica de la puerta):
    - «existente_id_repetido»: el id «EX-nn» se repite;
    - «existente_valor_no_literal»: el valor no es un fragmento literal de su cita (normalizar_para_cita);
    - «existente_servicio_desconocido»: servicio_catalogo no está en el catálogo;
    - «existente_valor_otro_servicio»: con servicio_catalogo, el valor no nombra ESE servicio y ningún otro
      (experto.servicios_nombrados, la coincidencia más larga); con null, el valor nombra un servicio del catálogo;
    - «existente_recurso_sin_entrada»: la cita nombra un servicio del catálogo que no tiene su propia entrada (la cita
      «…en un App Service propio, publicada con API Management» exige una de App Service y otra de API Management);
    - «existente_sin_catalogo»: sin catálogo no se puede comprobar (falla cerrado)."""
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("componentes"), list):
        return [("—", "existente_sin_catalogo", "no se puede comprobar sin el catálogo montado (una entrada por recurso "
                 "con su servicio del catálogo): falla cerrado")]
    from nucleo import experto  # diferido: experto importa módulos de B
    filas = {e.get("id"): e for e in catalogo["componentes"] if isinstance(e, dict)}
    nombre = {i: (e.get("nombre_oficial") or i) for i, e in filas.items()}
    servicios = {e.get("servicio_catalogo") for e in entradas if isinstance(e, dict)}
    vistos, avisados, salida = set(), set(), []
    for e in entradas:
        if not isinstance(e, dict):
            continue
        ex, sc, valor, cita = e.get("id"), e.get("servicio_catalogo"), e.get("valor"), e.get("cita")
        if ex in vistos:
            salida.append((ex, "existente_id_repetido", "id repetido; cada recurso lleva su propio id EX-nn"))
        vistos.add(ex)
        if not isinstance(valor, str) or not isinstance(cita, str) or                 normalizar_para_cita(valor) not in normalizar_para_cita(cita):
            salida.append((ex, "existente_valor_no_literal", f"el valor «{str(valor)[:120]}» no es un fragmento literal de "
                           "su cita: copia de la cita las palabras que nombran el recurso, sin resumir"))
        hits = experto.servicios_nombrados(valor, catalogo)
        if sc is not None and sc not in filas:
            salida.append((ex, "existente_servicio_desconocido", f"servicio_catalogo «{sc}» no está en el catálogo montado"))
        elif sc is not None and (not hits or any(sc not in h for h in hits)):
            otros = sorted({i for h in hits for i in h} - {sc})
            salida.append((ex, "existente_valor_otro_servicio", f"el valor «{str(valor)[:120]}» no nombra solo "
                           f"{nombre[sc]} ({sc})" + (f": nombra también {', '.join(nombre.get(i, i) for i in otros)}"
                                                     if otros else "")
                           + "; una entrada por recurso, con el fragmento que nombra ese servicio"))
        elif sc is None and hits:
            otros = sorted({i for h in hits for i in h})
            salida.append((ex, "existente_valor_otro_servicio", f"el valor nombra {', '.join(nombre.get(i, i) for i in otros)} "
                           "y servicio_catalogo es null: pon el id del catálogo de ese servicio"))
        for h in experto.servicios_nombrados(cita, catalogo):
            if h & servicios or h in avisados:
                continue
            avisados.add(h)
            salida.append((ex, "existente_recurso_sin_entrada", f"la cita nombra "
                           f"{' o '.join(nombre.get(i, i) for i in sorted(h))} y no hay una entrada con servicio_catalogo "
                           f"{' o '.join(sorted(h))}: una entrada por recurso, cada una con la cita entera (si la frase "
                           "nombra un servicio que el cliente NO tiene, recorta la cita a lo que sí tiene)"))
    return salida


def aplicar(estado: dict, requisitos: dict, textos_fuente: dict[str, str],
            catalogo: dict | None = None) -> ResultadoSuficiencia:
    """Valida requisitos.json, comprueba cada cita y recalcula el estado de cada campo.

    ReglaIncumplida si no valida (esquema, ASUMIDO no fijado por el comercial, fuente inexistente,
    nubes fuera de I1 y, desde I1.9, lo que el cliente ya tiene sin una entrada por recurso: errores_existentes).
    Con citas inválidas devuelve el resultado SIN guardar nada. Si no, guarda `carga.requisitos` (con la cascada de
    §5.3 si cambian) y devuelve completo o lo que falta. `catalogo` es el montado: sin él, unos requisitos que dicen
    lo que el cliente ya tiene no se pueden comprobar y se rechazan (falla cerrado).
    """
    errores = list(esquema.validar(requisitos, esquema.cargar("requisitos")))
    if errores:
        raise ReglaIncumplida("requisitos.json no valida contra su esquema", errores)
    req = nfc(copy.deepcopy(requisitos))
    previos = ((estado["carga"].get("requisitos") or {}).get("campos") or {})
    tipos = {f["id"]: f["tipo"] for f in estado["carga"]["fuentes"]}
    citas_invalidas: list[str] = []
    for campo, datos in req["campos"].items():
        asumidos_previos = [e["valor"] for e in (previos.get(campo) or {}).get("entradas", []) if e["origen"] == "ASUMIDO"]
        for i, e in enumerate(datos["entradas"]):
            donde = f"{campo}.entradas[{i}]"
            if e["origen"] == "ASUMIDO":
                if campo in SOLO_CITADOS:
                    errores.append(f"{donde}: {campo} solo se acepta con cita literal de la fuente (CITADO o "
                                   "ACLARACION): lo que el cliente ya tiene o paga no se asume (REV17-3)")
                    continue
                if e["cita"] is not None or e["fuente"] is not None:
                    errores.append(f"{donde}: un ASUMIDO va con cita y fuente null")
                if e["valor"] not in asumidos_previos:
                    errores.append(f"{donde}: ASUMIDO solo lo fija el comercial con «asumir» (valor no asumido antes)")
                continue
            esperado = "TRANSCRIPCION" if e["origen"] == "CITADO" else "ACLARACION"
            if e["origen"] == "CITADO" and tipos.get(e["fuente"]) == "NOTAS_COMERCIAL":
                esperado = "NOTAS_COMERCIAL"   # notas del comercial: también se cita de ellas (NOTAS_COMERCIAL.md)
            if e["fuente"] not in tipos or e["fuente"] not in textos_fuente:
                errores.append(f"{donde}: fuente {e['fuente']!r} no registrada")
            elif tipos[e["fuente"]] != esperado:
                errores.append(f"{donde}: origen {e['origen']} exige una fuente {esperado} y {e['fuente']} es {tipos[e['fuente']]}")
            elif e["cita"] is None:
                errores.append(f"{donde}: {e['origen']} sin cita literal")
            elif not cita_valida(e["cita"], {e["fuente"]: textos_fuente[e["fuente"]]}):
                citas_invalidas.append(f"{donde}: la cita «{e['cita'][:120]}» no está literal en {e['fuente']} "
                                       f"(o tiene menos de {CITA_MIN_CARACTERES} caracteres o {CITA_MIN_PALABRAS} palabras)")
        datos["estado"] = _estado_campo(datos["entradas"])
    errores += [f"nubes: {m}" for m in nubes_fuera_de_i1([e["valor"] for e in req["campos"]["nubes"]["entradas"]],
                                                          est_mod.pilar(estado))]
    existentes = (req["campos"].get(CAMPO_EXISTENTES) or {}).get("entradas") or []
    if existentes:  # I1.9 (PR18-1): una entrada por recurso, con la cita entera
        errores += [f"{CAMPO_EXISTENTES}: {m}" for m in errores_existentes(existentes, catalogo)]
    if errores:
        raise ReglaIncumplida("requisitos.json no es aceptable", errores)
    if citas_invalidas:
        return ResultadoSuficiencia(completo=False, faltan=_faltan(req["campos"]), citas_invalidas=citas_invalidas,
                                    preguntas=[])
    _guardar_requisitos(estado, req)
    return _resultado(req["campos"])


def asumir(estado: dict, campo: str, valor: str) -> ResultadoSuficiencia:
    """ASUMIR: campo = valor (solo ASUMIBLES). Queda como supuesto [BAJA] con cita null."""
    if campo not in ASUMIBLES:
        tipo = "BLOQUEANTE" if campo in BLOQUEANTES else ("OPCIONAL" if campo in OPCIONALES else "desconocido")
        raise EntradaInvalida(f"«{campo}» no se puede asumir: es {tipo}", [f"solo se asumen: {list(ASUMIBLES)}"])
    valor = unicodedata.normalize("NFC", (valor or "").strip())
    if not 2 <= len(valor) <= 600:
        raise EntradaInvalida("El valor asumido debe tener entre 2 y 600 caracteres", [repr(valor[:80])])
    hallados = importlib.import_module("nucleo.textos_cliente").marcadores(valor)  # barrido único de §0 (C)
    if hallados:
        raise EntradaInvalida("El valor asumido contiene marcadores (LES-G-006): va a los supuestos del cliente",
                              [repr(h) for h in hallados])
    req = estado["carga"].get("requisitos")
    if not req:
        raise EntradaInvalida("No hay requisitos registrados: primero suficiencia --requisitos …", [])
    req = copy.deepcopy(req)
    req["campos"][campo] = {"estado": "ASUMIDO",
                            "entradas": [{"valor": valor, "cita": None, "fuente": None, "origen": "ASUMIDO"}]}
    _guardar_requisitos(estado, req)
    return _resultado(req["campos"])


def forma_minima() -> str:
    """VERIF-1 (H1): forma JSON mínima de requisitos.json, generada desde el esquema (prueba de sincronía).

    La primera entrada muestra un CITADO completo; el resto, FALTA. Una línea por campo, en el orden del esquema.
    """
    esq = esquema.cargar("requisitos")
    campos = list(esq["properties"]["campos"]["properties"])
    entrada = esq["$defs"]["entrada"]["required"]
    ejemplo = dict(zip(entrada, ["dato en una frase", "fragmento literal de la transcripción", "F1", "CITADO"]))
    lineas = ['{"schema": "%s", "campos": {' % esq["properties"]["schema"]["const"]]
    for i, campo in enumerate(campos):
        valor = ({"estado": "CITADO", "entradas": [ejemplo]} if i == 0 else {"estado": "FALTA", "entradas": []})
        coma = "," if i < len(campos) - 1 else ""
        lineas.append(f'  "{campo}": {json.dumps(valor, ensure_ascii=False)}{coma}')
    lineas.append("}}")
    return "\n".join(lineas)


# VERIF-2: frases de la transcripción con forma de requisito que ningún campo cita entero (para la nota y para
# El comercial en T1). No bloquea: avisa (LES-G-062: lo que falta no da error, hay que enseñarlo).
_MARCAS_REQUISITO = re.compile(
    r"\b(?:tiene que|tienen que|tenemos que|queremos|quiero|querriamos|debe|deben|deberia|deberian|necesitamos|"
    r"necesito|necesitan|nos gustaria|me gustaria|hace falta|imprescindible|obligatorio|es necesario|pedimos|"
    r"exigimos|requiere|requerimos|hay que|habria que|tendria que|tendrian que|tendriamos que|esperamos|"
    r"buscamos|pretendemos|quisieramos|seria necesario|es importante|es clave|es fundamental)\b")
# Límite declarado: es una lista de marcas, no comprensión del texto. Lo que no la usa no se detecta; la nota
# lo dice y no afirma que esté todo citado.
DETECTOR_HEURISTICO = ("Detector heurístico por marcas («tiene que», «queremos», «debe», «hay que», «necesitamos»…): "
                       "una frase sin esas marcas no se detecta, así que no sustituye la lectura de la transcripción.")
_VACIAS = frozenset((
    "el la los las un una unos unas de del al en que se su sus con por para sin como lo le les nos es son esta "
    "este esto estos estas ese esa eso muy mas pero tambien hay cada todo toda todos todas nuestro nuestra "
    "nuestros nuestras dos tres primer primera dia cosas cosa hacer tiene tienen tenemos queremos quiero debe "
    "deben necesitamos gustaria hace falta desde cuando donde porque bien").split())
PERSONAS_DEVOTEAM = ("responsable comercial",)


def _contenido(palabra: str) -> bool:
    p = re.sub(r"\W", "", palabra)
    return len(p) >= 3 and p not in _VACIAS


def _intervenciones(texto: str) -> list[tuple[str | None, str]]:
    """[(hablante normalizado o None, texto)] uniendo las líneas y cues seguidos del mismo hablante (una frase
    partida entre dos cues sigue siendo una frase). Sin cabecera WEBVTT, bloques NOTE, ids de cue ni tiempos."""
    lineas = unicodedata.normalize("NFC", (texto or "").replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    es_vtt = bool(lineas) and lineas[0].lstrip("\ufeff").strip().upper().startswith("WEBVTT")
    salida: list[list] = []
    i = 0
    while i < len(lineas):
        ln = lineas[i]
        i += 1
        if es_vtt and i == 1:
            continue
        if es_vtt and (ln.strip() == "NOTE" or ln.startswith("NOTE ")):
            while i < len(lineas) and lineas[i].strip():
                i += 1
            continue
        if not ln.strip() or _TS.match(ln) or (es_vtt and i < len(lineas) and _TS.match(lineas[i])):
            continue  # vacía, marca de tiempo o identificador de cue
        voz = _VOZ.search(ln) or _HABLANTE_LINEA.match(ln)
        quien = normalizar_para_cita(voz.group(1)) if voz else None
        limpio = _quitar_vtt(ln)
        m = _HABLANTE_LINEA.match(limpio)
        limpio = (limpio[m.end():] if m else limpio).strip()
        # VTT: solo se unen cues del MISMO hablante identificado (un cue sin hablante va aparte y cuenta como del
        # cliente). Texto plano: una línea sin hablante continúa el párrafo de quien hablaba.
        previo = salida[-1][0] if salida else None
        if es_vtt:
            sigue = bool(salida) and quien is not None and quien == previo
        else:
            sigue = bool(salida) and (quien is None or quien == previo)
        if sigue:
            salida[-1][1] += " " + limpio
        else:
            salida.append([quien, limpio])
    return [(q, t) for q, t in salida]


def frases_requisito_sin_cita(texto: str, citas: list) -> list[tuple[str, str]]:
    """[(frase, parte sin citar)] de las intervenciones del cliente con forma de requisito no citadas enteras."""
    citas_n = [c for c in (normalizar_para_cita(x) for x in citas if isinstance(x, str)) if c]
    salida: list[tuple[str, str]] = []
    for quien, linea in _intervenciones(texto):
        if quien and quien.startswith(PERSONAS_DEVOTEAM):
            continue
        palabras = linea.split()
        norm = [normalizar_para_cita(p) for p in palabras]
        unido, pos, ini = " ".join(norm), [], 0
        for w in norm:  # posición del núcleo alfanumérico: «documento,» queda citada por «…al documento»
            nucleo = re.search(r"\w(?:.*\w)?", w)
            pos.append((ini + nucleo.start(), ini + nucleo.end()) if nucleo else (ini, ini + len(w)))
            ini += len(w) + 1
        cubierta = [False] * len(palabras)
        for c in citas_n:
            k = unido.find(c)
            while k >= 0:
                for i, (a, b) in enumerate(pos):  # solo palabras enteras dentro de la cita (Revisión 5)
                    cubierta[i] = cubierta[i] or (a >= k and b <= k + len(c))
                k = unido.find(c, k + 1)
        frase: list[int] = []
        for i, w in enumerate(palabras):
            frase.append(i)
            if not (re.search(r"[.!?]$", w) or i == len(palabras) - 1):
                continue
            sueltas = [j for j in frase if not cubierta[j]]
            if (_MARCAS_REQUISITO.search(" ".join(norm[j] for j in frase))
                    and sum(_contenido(norm[j]) for j in sueltas) >= 2):
                tramos, previo = [], None
                for j in sueltas:
                    tramos.append(("" if previo is None else (" " if j == previo + 1 else " … ")) + palabras[j])
                    previo = j
                salida.append((" ".join(palabras[j] for j in frase), "".join(tramos)))
            frase = []
    return salida
