"""Plantillas de filtro de precio por servicio del catálogo (I1.5, decisión 1 del comercial; LES-G-090.9).

Cada componente con serviceName lleva en catalogo_referencias_azure.json una lista `plantillas_precio`: filtros OData de
Azure Retail Prices comprobados contra la API pública en EUR que devuelven UN solo medidor (o sus tramos). El experto solo
consulta precios con ellas: un filtro amplio mete cientos de artículos en el contexto (429 por la ventana de tokens) y uno
mal formado da HTTP 400, que aborta su respuesta entera. Este módulo no usa la red: forma, región y bloque generado.
"""
from __future__ import annotations

import math
import re

# Orden canónico de las condiciones; solo «campo eq 'valor'» unidas con « and ».
CAMPOS = ("serviceName", "productName", "armRegionName", "priceType", "productId", "armSkuName", "skuName", "meterName")
_CONDICION = re.compile(r"([A-Za-z]+) eq '([^']+)'")
# I1.6 (decisión 4, LES-G-100): qué mueve la cantidad mensual de cada plantilla. «tiempo»: horas, días o meses que un
# recurso está desplegado (730 h al mes por instancia). «volumen»: tokens, páginas, mensajes, operaciones o GB, que
# salen de la volumetría citada con un factor explícito: cantidad_mensual = cantidad_base × factor / divisor.
IMPULSORES = ("tiempo", "volumen")
_MULTIPLO = {"K": 1000, "M": 1000000}
MOTIVOS_NO_VALORABLE = {
    "precio_redondeado_en_eur": "Retail Prices en EUR redondea a 4 decimales y el precio publicado sale a 0 o desviado",
    "sin_medidor_unico": "sin productName en el filtro no hay un medidor único para este concepto",
    "no_publicado_en_la_region": "Retail Prices no publica este medidor en la región UE del componente",
    "se_factura_en_otro_componente": "este consumo se factura con el medidor de otro componente del catálogo",
}


def condiciones(filtro: str) -> list[tuple[str, str]] | None:
    """[(campo, valor)] si el filtro es exactamente «campo eq 'valor'» unidas con « and »; None si no."""
    if not isinstance(filtro, str):
        return None
    trozos = filtro.split(" and ")
    pares = [(_CONDICION.fullmatch(t)) for t in trozos]
    return None if not all(pares) else [(m.group(1), m.group(2)) for m in pares]


def region_de(entrada: dict) -> str | None:
    """armRegionName con el que se comprobaron las plantillas: region_precio («Global») o region_ue."""
    return entrada.get("region_precio") or entrada.get("region_ue")


def problemas_plantilla(plantilla: dict, entrada: dict) -> list[str]:
    """Motivos por los que una plantilla no tiene la forma exigida para su componente; [] si la tiene."""
    pares = condiciones(plantilla.get("filtro"))
    if pares is None:
        return ["no es una serie de «campo eq 'valor'» unidas con « and »"]
    campos = [c for c, _ in pares]
    d = dict(pares)
    m = []
    if len(set(campos)) != len(campos) or any(c not in CAMPOS for c in campos):
        m.append(f"campos repetidos o no admitidos: {campos}")
    elif campos != sorted(campos, key=CAMPOS.index):
        m.append("las condiciones no van en el orden canónico")
    if d.get("serviceName") != entrada.get("service_name_precios"):
        m.append("serviceName distinto del de su fila")
    if d.get("productName") != entrada.get("producto_precios"):
        m.append("productName distinto del de su fila (ninguno si la fila no lo tiene)")
    if d.get("armRegionName") != region_de(entrada):
        m.append(f"armRegionName distinto de «{region_de(entrada)}»")
    if d.get("priceType") != "Consumption":
        m.append("falta priceType eq 'Consumption'")
    if "meterName" not in d:
        m.append("exige meterName (y skuName, armSkuName o productId solo si hacen falta para un medidor único)")
    elif not plantilla["filtro"].startswith(prefijo(entrada) + " and "):
        m.append("no empieza por el prefijo de su fila")
    return m + problemas_impulsor(plantilla)


def divisor_de_unidad(unidad: object) -> int | None:
    """Divisor de la unidad del medidor (unitOfMeasure): «1M» → 1.000.000, «1K» → 1.000, «10K» → 10.000; una unidad
    de 1 («1 Hour», «1/Day», «1 GB/Month», «1») → 1. None si no se reconoce: no se adivina (LES-G-047)."""
    if not isinstance(unidad, str):
        return None
    m = re.fullmatch(r"([0-9]+) ?([KM])", unidad.strip())
    if m:
        return int(m.group(1)) * _MULTIPLO[m.group(2)]
    return 1 if re.fullmatch(r"1(?:[ /].*)?", unidad.strip()) else None


def problemas_impulsor(plantilla: dict) -> list[str]:
    """Contrato común de la decisión 4: `impulsor` de la lista y `divisor` igual al de la unidad comprobada."""
    m = []
    if plantilla.get("impulsor") not in IMPULSORES:
        m.append(f"impulsor {plantilla.get('impulsor')!r} fuera de {IMPULSORES}")
    div, unidad = plantilla.get("divisor"), (plantilla.get("comprobacion") or {}).get("unidad")
    if not isinstance(div, int) or isinstance(div, bool) or div < 1:
        m.append(f"divisor {div!r}: entero de 1 o más")
    elif unidad is not None and divisor_de_unidad(unidad) != div:
        m.append(f"divisor {div} distinto del de la unidad comprobada «{unidad}» ({divisor_de_unidad(unidad)})")
    if plantilla.get("impulsor") == "tiempo" and div not in (None, 1):
        m.append("una plantilla de tiempo lleva divisor 1")
    if "por_defecto" in plantilla and plantilla.get("por_defecto") is not True:  # PR16-3: solo true, o sin la clave
        m.append(f"por_defecto {plantilla.get('por_defecto')!r}: solo true (o sin la clave)")
    return m


def problemas_niveles(entrada: dict) -> list[str]:
    """Niveles de un servicio (decisión 4): de menor a mayor, cada uno con sus plantillas de la fila, al menos un
    límite oficial literal y su fuente de Learn con fecha; nombres y plantillas sin repetir."""
    ids, m, vistos, usadas = {p["id"] for p in entrada.get("plantillas_precio") or []}, [], set(), set()
    for n in entrada.get("niveles") or []:
        nombre = n.get("nivel")
        if not isinstance(nombre, str) or not nombre.strip() or nombre in vistos:
            m.append(f"nivel {nombre!r} vacío o repetido")
        vistos.add(nombre)
        ps = n.get("plantillas") or []
        if not ps or set(ps) - ids or usadas & set(ps):
            m.append(f"nivel {nombre}: plantillas {ps} vacías, ajenas a la fila o repetidas en otro nivel")
        usadas |= set(ps)
        lim = n.get("limites") or []
        if not lim or not all(isinstance(x, str) and 10 <= len(x) <= 160 for x in lim) or len(set(lim)) != len(lim):
            m.append(f"nivel {nombre}: límites oficiales vacíos, repetidos o fuera de 10 a 160 caracteres")
        if not str(n.get("fuente_url") or "").startswith("https://learn.microsoft.com/") or not n.get("consultado"):
            m.append(f"nivel {nombre}: sin fuente de Learn o sin fecha de consulta")
    return m


def prefijo(entrada: dict) -> str:
    """Condiciones comunes a todas las plantillas de la fila: serviceName, productName (si la fila lo tiene),
    armRegionName y priceType. El filtro de una plantilla es este prefijo, un espacio y su resto («and …»)."""
    partes = [f"serviceName eq '{entrada.get('service_name_precios')}'"]
    if entrada.get("producto_precios"):
        partes.append(f"productName eq '{entrada['producto_precios']}'")
    return " and ".join(partes + [f"armRegionName eq '{region_de(entrada)}'", "priceType eq 'Consumption'"])


def resto(plantilla: dict, entrada: dict) -> str:
    """Lo que la plantilla añade al prefijo de su fila, empezando por «and »."""
    return plantilla["filtro"][len(prefijo(entrada)) + 1:]


def filtro_para_region(plantilla: dict, entrada: dict, region: str) -> str | None:
    """El filtro de la plantilla para un componente en `region`. Con region_precio («Global») no se cambia nunca; si no,
    solo cambia el valor de armRegionName. None si la región no es una armRegionName válida."""
    base = region_de(entrada)
    if entrada.get("region_precio"):
        return plantilla["filtro"]
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]+[a-z0-9]*", region) or region == "global":
        return None
    return plantilla["filtro"].replace(f" and armRegionName eq '{base}' and ", f" and armRegionName eq '{region}' and ", 1)


def plantilla_de(filtro: object, entrada: dict, region: str) -> dict | None:
    """La plantilla de `entrada` cuyo filtro, para la región del componente, es EXACTAMENTE `filtro`; None si ninguna.
    Es la comprobación que el núcleo y la puerta pueden aplicar a cada precio registrado (CAMBIOS-I15-E)."""
    return next((p for p in entrada.get("plantillas_precio") or []
                 if isinstance(filtro, str) and filtro_para_region(p, entrada, region) == filtro), None)


def concepto(plantilla: dict) -> str:
    """`concepto` del precio, derivado de lo que devolvió la API (equivalencia demostrable, LES-G-047): el meterName
    comprobado; con `concepto_con_sku`, el meterName y su skuName («vCore (2 vCore)»: el meterName solo no distingue
    el tamaño); si el meterName tiene menos de 3 caracteres («B1»), con su productName. Falla en alto si falta el dato
    que necesita: un « (None)» no es un concepto (PR15-3)."""
    k = plantilla.get("comprobacion") or {}
    medidor = k.get("medidor") or ""
    extra = k.get("sku") if plantilla.get("concepto_con_sku") else None if len(medidor) >= 3 else k.get("producto")
    if not medidor or (extra is None and (plantilla.get("concepto_con_sku") or len(medidor) < 3)):
        raise ValueError(f"plantilla {plantilla.get('id')}: sin medidor, o sin el sku o el producto que necesita")
    return f"{medidor} ({extra})" if extra else medidor


INICIO = ("### Plantillas de filtro de precio (generado por catalogo/derivar.py desde el catálogo; no editar a "
          "mano)")
FIN = "### Fin de las plantillas de filtro de precio"
ANCLA = "- Si la respuesta trae `NextPageLink`"


def _tope_kb(cat: dict) -> str:
    """Tope medido de bytes por consulta, redondeado hacia arriba a décimas de KB («2,4»): el texto no promete menos
    de lo que se midió (I1.6: Service Bus Standard trae 4 tramos y 2.340 bytes)."""
    maximo = max((b for c in cat["componentes"] for p in c.get("plantillas_precio") or []
                  for b in (p.get("comprobacion") or {}).get("bytes") or []), default=0)
    decimas = maximo // 100 + 1  # estrictamente por encima: «menos de»
    return f"{decimas // 10},{decimas % 10}" if decimas % 10 else str(decimas // 10)


def _fecha(cat: dict) -> str:
    fechas = sorted({(p.get("comprobacion") or {}).get("fecha") for c in cat["componentes"]
                     for p in c.get("plantillas_precio") or []} - {None})
    return " y ".join(fechas) or "sin fecha"


def bloque_markdown(cat: dict, auxiliares_con_plantillas: bool = False, completo: bool = False) -> str:
    """Bloque de las instrucciones del experto: las reglas y, por servicio, el prefijo y el resto de cada plantilla con
    su impulsor (I1.6), los niveles con sus límites oficiales y, si el catálogo del sandbox ya las admite
    (`auxiliares_con_plantillas`, lo decide derivar.py con el esquema), las plantillas de los precios auxiliares.
    Compacto a propósito: viaja en cada vuelta del modelo (cuota de tokens por minuto del despliegue)."""
    lineas = [
        INICIO,
        f"Comprobadas el {_fecha(cat)} contra Retail Prices en EUR: cada filtro devuelve un solo medidor (o los "
        f"tramos que se indican) y menos de {_tope_kb(cat)} KB. Una consulta amplia mete cientos de artículos en tu "
        "contexto y agota la cuota del modelo; un filtro mal escrito hace que Retail Prices responda 400 y Foundry aborta tu respuesta "
        "entera.",
        ("- El `$filter` de cada llamada a `precios_azure` es EXACTAMENTE el filtro de una de las plantillas de la fila "
         "del servicio, copiado ENTERO carácter a carácter, desde `serviceName` hasta la comilla simple final. "
         "`currencyCode` = `EUR`; sin `$skip` ni `api-version`. Ejemplo (`az-ai-search`, `s1`): " + _ejemplo(cat)
         if completo else
         "- El `$filter` de cada llamada a `precios_azure` es EXACTAMENTE el prefijo de la fila del servicio, un espacio "
         "y el resto de una de sus plantillas, copiados carácter a carácter. `currencyCode` = `EUR`; sin `$skip` ni "
         "`api-version`. Ejemplo (`az-ai-search`, `s1`): `" + _ejemplo(cat) + "`."),
        "- Lo único que puedes cambiar es el valor de `armRegionName`, y solo si la `region` del componente es otra "
        "región admitida para ese servicio. Donde el filtro lleva `armRegionName eq 'Global'` no cambia nunca.",
        "- Nunca un filtro escrito a mano ni uno sin `meterName`; nunca `or`, `not`, `ne`, `contains`, `startswith`, "
        "`tolower`, paréntesis ni comillas dobles.",
        "- En el precio, `filtro` = el que usaste y `concepto` = `null`. No escribas el concepto: lo fija el código "
        "desde la plantilla del filtro (si escribes otro, lo sustituye y lo anota para el revisor).",
        "- Tras el id de cada plantilla va lo que mueve su cantidad: `T` = tiempo (`cantidad_mensual` = horas, días o "
        "meses desplegado: 730 horas al mes por instancia, 30,42 días o 1 mes); `V/n` = volumen (`cantidad_mensual` = "
        "`cantidad_base` × `factor.valor` / n, con su `base_volumen`; ver §6).",
        "- Con varios tramos (`tierMinimumUnits` distinto), usa el que corresponde a la cantidad mensual y dilo en "
        "`supuesto_cantidad` (los 5 primeros GB de ingesta de Log Analytics son gratuitos).",
        "- El `$filter` termina SIEMPRE en la comilla simple que cierra el valor del último campo: antes de llamar, "
        "comprueba que la tiene. Sin ella Retail Prices responde 400 y Foundry aborta tu respuesta entera.",
        "- Las plantillas marcadas «por defecto» son las que usas salvo que una frase del brief o un comentario de la "
        "revisión pida otra (por ejemplo, un modelo más barato o más rápido); si usas otra, dilo en un supuesto con esa "
        "frase. El código lo anota para el revisor.",
        "- Si devuelve 0 artículos, no pruebes otro filtro; y si el concepto no tiene plantilla, no consultes. En los "
        "dos casos, sin ese precio y con un supuesto de confianza `BAJA` «Precio de … NO VERIFICADO en Azure Retail "
        "Prices: …». `sin_medidor_publico` vale solo para un servicio sin plantillas (o en una región distinta de la de "
        "su fila, si la fila no la fija): con plantillas en su región, el código rechaza ese motivo (REV16-1).",
        "",
    ]
    for c in cat["componentes"]:
        ps = c.get("plantillas_precio") or []
        if ps and completo:  # PR16-2 (arreglos I1.6): el filtro entero, sin comilla invertida pegada a la comilla final
            lineas.append(f"- {c['nombre_oficial']} (`{c['id']}`). Filtros:")
            lineas += [f"  - `{p['id']}` {_nota(p)}: {p['filtro']}" for p in ps]
        elif ps:
            cuerpo = "; ".join(f"`{p['id']}` {_nota(p)} → `{resto(p, c)}`" for p in ps)
            lineas.append(f"- {c['nombre_oficial']} (`{c['id']}`). Prefijo: `{prefijo(c)}`. Plantillas: {cuerpo}.")
    con_niveles = [c for c in cat["componentes"] if c.get("niveles")]
    if con_niveles:
        lineas += ["", "Niveles de servicio, de menor a mayor. Elige el MENOR nivel cuyo límite cumple lo citado en los "
                   "requisitos; en `justificacion_nivel` copia literal el nombre del nivel, uno de sus límites y la "
                   "fuente (el código lo compara con esta lista):"]
        lineas += [_linea_niveles(c) for c in con_niveles]
    nv = [(c, x) for c in cat["componentes"] for x in c.get("no_valorables") or []]
    if nv:
        lineas += ["", "Sin plantilla a propósito (no se valoran; el supuesto dice el motivo):"]
        lineas += [f"- {c['nombre_oficial']}: {x['concepto']}. Motivo: {MOTIVOS_NO_VALORABLE[x['motivo']]}."
                   for c, x in nv]
    if auxiliares_con_plantillas:
        lineas += _lineas_auxiliares(cat, completo)
    return "\n".join(lineas + [FIN])


def _corto(divisor: int) -> str:
    for n, s in ((1000000, "M"), (1000, "K")):
        if divisor >= n and divisor % n == 0:
            return f"{divisor // n}{s}"
    return str(divisor)


def _nota(p: dict) -> str:
    """Impulsor (`T` o `V/n`) y, si aplica, gratuito o el número de tramos distintos (I1.6: dos artículos con el mismo
    tramo, como el vCore de SQL Database, no son dos tramos)."""
    k = p.get("comprobacion") or {}
    marca = "T" if p.get("impulsor") == "tiempo" else f"V/{_corto(p['divisor'])}"
    n = len(set(k.get("tramos") or [0]))
    defecto = " (por defecto)" if p.get("por_defecto") is True else ""  # PR16-3 (arreglos I1.6)
    return marca + defecto + (" (gratuito)" if p.get("gratuito") else f" ({n} tramos)" if n > 1 else "")


def _extra_nivel(n: dict) -> str:
    """I1.8 (REVERIF17-2 y -3): medidores obligatorios del nivel y sus instancias (tope, mínimo y valores admitidos)."""
    partes = []
    if n.get("medidores_obligatorios"):
        partes.append("lleva " + " y ".join(f"`{x}`" for x in n["medidores_obligatorios"]))
    if n.get("instancias_min"):
        partes.append(f"desde {n['instancias_min']} instancias")
    if n.get("instancias_validas"):
        partes.append("instancias " + ", ".join(str(v) for v in n["instancias_validas"]))
    elif n.get("instancias_max"):
        partes.append(f"hasta {n['instancias_max']} instancias")
    return f" [{'; '.join(partes)}]" if partes else ""


def _lado_derecho(regla: dict) -> str:
    """«`a`, `b` y una de `c`, `d`» para una regla de medidores (I1.8)."""
    partes = []
    if regla.get("exige"):
        partes.append(", ".join(f"`{x}`" for x in regla["exige"]))
    if regla.get("exige_uno_de"):
        partes.append("una de " + ", ".join(f"`{x}`" for x in regla["exige_uno_de"]))
    return " y ".join(partes)


def _linea_niveles(c: dict) -> str:
    fuentes = {n["fuente_url"] for n in c["niveles"]}
    comun = len(fuentes) == 1
    partes = [f"`{n['nivel']}` ({', '.join(n['plantillas'])}){_extra_nivel(n)}: "
              + "; ".join(f"«{x}»" for x in n["limites"])
              + ("" if comun else f" (fuente {n['fuente_url']})") for n in c["niveles"]]
    return (f"- {c['nombre_oficial']} (`{c['id']}`)" + (f", fuente {next(iter(fuentes))}" if comun else "") + ": "
            + " · ".join(partes) + ".")


def plantillas_de_auxiliar(aux: dict, cat: dict) -> list[dict]:
    """Plantillas de un precio auxiliar (INT15-3): las de la fila `plantillas_de` con los ids `plantillas`, tal cual
    (Global: nunca cambian de región). Falla en alto si la referencia no resuelve, si el vínculo está a medias
    (Revisión I1.6: un auxiliar con `componentes` y sin `plantillas` perdía el vínculo en silencio) o si algún componente
    no es una fila facturable del catálogo."""
    claves = ("plantillas", "plantillas_de", "componentes", "componentes_fuente_url")
    presentes = [k for k in claves if k in aux]  # Revisión I1.6, 2.ª pasada: una clave vacía no es «sin vínculo»
    if not presentes:
        return []
    if len(presentes) != len(claves) or not all(aux[k] for k in claves):
        raise ValueError(f"precio auxiliar {aux.get('service_name')!r}: vínculo a medias, faltan "
                         f"{[k for k in claves if k not in presentes]}")
    fila = next((c for c in cat["componentes"] if c["id"] == aux.get("plantillas_de")), None)
    por_id = {p["id"]: p for p in (fila or {}).get("plantillas_precio") or []}
    if fila is None or not fila.get("region_precio") or set(aux["plantillas"]) - set(por_id):
        raise ValueError(f"precio auxiliar {aux.get('service_name')!r}: plantillas_de/plantillas no resuelven en una "
                         "fila con region_precio")
    facturables = {c["id"] for c in cat["componentes"] if c.get("plantillas_precio")} - {fila["id"]}
    if set(aux["componentes"]) - facturables:
        raise ValueError(f"precio auxiliar {aux.get('service_name')!r}: componentes que no son filas con plantillas: "
                         f"{sorted(set(aux['componentes']) - facturables)}")
    return [por_id[i] for i in aux["plantillas"]]


def _lineas_auxiliares(cat: dict, completo: bool = False) -> list[str]:
    salida = []
    for a in cat.get("precios_auxiliares") or []:
        ps = plantillas_de_auxiliar(a, cat)
        if ps and completo:  # PR16-2 (arreglos I1.6): el filtro al final de su línea, sin nada pegado
            salida += ["", f"Precio auxiliar `{a['service_name']}` (punto de conexión privado de un componente): su "
                       "`componente_id` es el del componente al que da acceso privado, cuyo `catalogo_id` tiene que "
                       "ser uno de " + ", ".join(f"`{i}`" for i in a["componentes"]) + ". No cubre al componente: "
                       "sigue necesitando su precio propio o su motivo. Filtros EXACTOS:"]
            salida += [f"  - `{p['id']}` {_nota(p)}: {p['filtro']}" for p in ps]
        elif ps:
            salida += ["", f"Precio auxiliar `{a['service_name']}` (punto de conexión privado de un componente): su "
                       "`componente_id` es el del componente al que da acceso privado, cuyo `catalogo_id` tiene que "
                       "ser uno de " + ", ".join(f"`{i}`" for i in a["componentes"]) + ". Filtro EXACTO: "
                       + "; ".join(f"`{p['id']}` {_nota(p)} → `{p['filtro']}`" for p in ps)
                       + ". No cubre al componente: sigue necesitando su precio propio o su motivo."]
    return salida


def _ejemplo(cat: dict) -> str:
    c = next(x for x in cat["componentes"] if x["id"] == "az-ai-search")
    return next(p["filtro"] for p in c["plantillas_precio"] if p["id"] == "s1")


def insertar_bloque(texto: str, bloque: str) -> str:
    """Sustituye el bloque entre INICIO y FIN; si no está, lo inserta antes de ANCLA. Falla en alto si faltan,
    sobran o están desordenadas las marcas."""
    ni, nf = texto.count(INICIO), texto.count(FIN)
    if ni == nf == 0:
        if texto.count(ANCLA) != 1:
            raise ValueError("no está (o está repetida) la línea ancla de las plantillas de precio")
        return texto.replace(ANCLA, bloque + "\n" + ANCLA, 1)
    i, f = texto.find(INICIO), texto.find(FIN)
    if ni != 1 or nf != 1 or f < i:
        raise ValueError("faltan, sobran o están desordenadas las líneas del bloque de plantillas de precio")
    return texto[:i] + bloque + texto[f + len(FIN):]


# ---------------------------------------------------------------------------------------------------------------------
# I1.7 (decisiones del comercial del 13-10-2026): precios por instantánea, modelo por defecto gpt-6-luna, factores estándar
# en el catálogo, ciclo de vida de los modelos, «incluye» y arquitecturas de referencia por id.
# ---------------------------------------------------------------------------------------------------------------------
import datetime as _dt  # noqa: E402

MESES_EXPLOTACION = 12  # regla del PM: retirada antes de fecha de la oferta + Gantt + 12 meses → no se propone


def factores(cat: dict) -> dict[str, dict]:
    """{«caso_uso.factor»: factor} de `casos_uso`."""
    return {f"{c['id']}.{f['id']}": f for c in cat.get("casos_uso") or [] for f in c.get("factores") or []}


def ciclos_vida(cat: dict) -> dict[str, dict]:
    """{modelo: ciclo de vida} de `ciclo_vida_modelos`."""
    return {x["modelo"]: x for x in cat.get("ciclo_vida_modelos") or []}


def _mas_meses(d: _dt.date, meses: int) -> _dt.date:
    a, m = divmod(d.month - 1 + meses, 12)
    anio, mes = d.year + a, m + 1
    for dia in (d.day, 30, 29, 28):  # 31 de enero + 1 mes → 28 o 29 de febrero
        try:
            return _dt.date(anio, mes, dia)
        except ValueError:
            continue
    raise ValueError("fecha imposible")


def limite_ciclo_vida(fecha_oferta: _dt.date, semanas_gantt: float) -> _dt.date:
    """Fecha mínima de retirada admisible: oferta + duración del Gantt + 12 meses de explotación."""
    if not isinstance(semanas_gantt, (int, float)) or isinstance(semanas_gantt, bool) or not 0 <= semanas_gantt < 1000:
        raise ValueError(f"semanas del Gantt no válidas: {semanas_gantt!r}")
    return _mas_meses(fecha_oferta + _dt.timedelta(weeks=semanas_gantt), MESES_EXPLOTACION)


def modelo_admisible(ciclo: dict | None, fecha_oferta: _dt.date, semanas_gantt: float) -> tuple[bool, str]:
    """Regla de ciclo de vida (fallar cerrado): sin ciclo de vida en el catálogo, no; con retirada publicada anterior al
    límite, no; sin fecha publicada, sí, y la nota del revisor dice «fecha de retirada aún no publicada»."""
    if not ciclo:
        return False, "el modelo no tiene ciclo de vida en el catálogo"
    limite = limite_ciclo_vida(fecha_oferta, semanas_gantt)
    if ciclo.get("retirada") is None:
        return True, "fecha de retirada aún no publicada"
    retirada = _dt.date.fromisoformat(ciclo["retirada"])
    if retirada < limite:
        return False, f"se retira el {retirada.isoformat()}, antes de {limite.isoformat()} (oferta + plazo + 12 meses)"
    return True, f"se retira el {retirada.isoformat()}"


def modelos_fuera_siempre(cat: dict) -> list[str]:
    """Modelos que ninguna oferta desde la fecha del catálogo puede proponer: retirada antes de fecha + 12 meses (Gantt 0).
    El bloque de las instrucciones no los ofrece; el núcleo los rechaza igual."""
    fecha = _dt.date.fromisoformat(cat["fecha"])
    return sorted(m for m, cv in ciclos_vida(cat).items() if not modelo_admisible(cv, fecha, 0)[0])


def problemas_i17(cat: dict) -> list[str]:
    """Forma de lo nuevo de I1.7: factores (referencias, impulsor, desglose), ciclo de vida de cada plantilla de modelo,
    modelo por defecto e «incluye». [] si todo está bien."""
    m, fs, cvs = [], factores(cat), ciclos_vida(cat)
    # Revisión I1.7 (2.ª pasada): los mapas por id colapsan los repetidos; se cuentan en las listas antes de colapsar
    modelos = [x.get("modelo") for x in cat.get("ciclo_vida_modelos") or []]
    claves = [f"{c.get('id')}.{f.get('id')}" for c in cat.get("casos_uso") or [] for f in c.get("factores") or []]
    for nombre, ids in (("ciclo_vida_modelos", modelos), ("factores de casos_uso", claves)):
        if len(set(ids)) != len(ids):
            m.append(f"{nombre}: ids repetidos {sorted({i for i in ids if ids.count(i) > 1})}")
    filas = {c["id"]: c for c in cat["componentes"]}
    for k, f in fs.items():
        partes = [p["valor"] for p in f.get("desglose") or []]
        numeros = [v for v in partes if v is not None]
        if f.get("tipo") == "supuesto" and (len(numeros) != len(partes) or abs(sum(numeros) - f["valor"]) > 1e-9):
            m.append(f"factor {k}: un supuesto lleva todo el desglose con valor y su suma es el factor")
        elif f.get("tipo") == "oficial" and sum(numeros) - f["valor"] > 1e-9:
            m.append(f"factor {k}: el desglose suma más que el factor")
    for c in cat["componentes"]:
        for p in c.get("plantillas_precio") or []:
            ref = p.get("factor_estandar")
            if ref is not None and (ref not in fs or p.get("impulsor") != "volumen"):
                m.append(f"{c['id']}/{p['id']}: factor_estandar {ref!r} desconocido o en una plantilla que no es de volumen")
            if c["id"] == "az-foundry" and ("modelo" not in p or p["modelo"] not in cvs):
                m.append(f"{c['id']}/{p['id']}: plantilla de modelo sin `modelo` o sin ciclo de vida")
            if p.get("por_defecto") is True and p.get("modelo") in modelos_fuera_siempre(cat):
                m.append(f"{c['id']}/{p['id']}: por defecto y fuera por ciclo de vida")
        for x in c.get("incluye") or []:
            if x["catalogo_id"] not in filas or x["catalogo_id"] == c["id"]:
                m.append(f"{c['id']}: incluye {x['catalogo_id']!r}, que no es otra fila del catálogo")
    for mod, cv in cvs.items():
        if cv.get("retirada") is not None and cv["retirada"] <= cv["ga"]:
            m.append(f"ciclo de vida de {mod}: retirada no posterior a la GA")
    d = cat.get("modelo_por_defecto")
    if d:
        fila = filas.get(d["componente"]) or {}
        por_defecto = sorted(p["id"] for p in fila.get("plantillas_precio") or [] if p.get("por_defecto") is True)
        modelos = {p.get("modelo") for p in fila.get("plantillas_precio") or [] if p["id"] in d["plantillas"]}
        if por_defecto != sorted(d["plantillas"]) or modelos != {d["modelo"]} or d["region"] != fila.get("region_ue"):
            m.append("modelo_por_defecto no casa con las plantillas «por defecto», su modelo o la región de la fila")
    return m


# I1.8: unidades de una plantilla de tiempo: las que el núcleo cuenta hoy (experto.UNIDADES_TIEMPO) más «1 GB/Month», el
# almacenamiento aprovisionado de SQL Database y PostgreSQL, que el núcleo AÚN NO cuenta (N7, CAMBIOS-I18-E §3): hasta
# entonces esas dos plantillas fallan cerrado al valorar (unidad_tiempo_desconocida). Lo vigila un xfail estricto
# (tests/test_i18_e_nucleo_pendiente.py). Cualquier otra unidad no pasa de aquí.
UNIDADES_TIEMPO = ("1 Hour", "1/Hour", "1 GiB Hour", "1/Day", "1/Month", "1 GB/Month")


def _ids_validos(lista: object, ids: set) -> bool:
    return isinstance(lista, list) and bool(lista) and all(isinstance(x, str) for x in lista) and set(lista) <= ids


def _entero(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _problemas_instancias(c: dict, n: dict) -> list[str]:
    m, tope, minimo, validas = [], n.get("instancias_max"), n.get("instancias_min"), n.get("instancias_validas")
    for nombre, v in (("instancias_max", tope), ("instancias_min", minimo)):
        if v is not None and not _entero(v):
            m.append(f"{c['id']}/{n['nivel']}: {nombre} {v!r} no es un entero de 1 o más")
    if _entero(tope) and not any(re.search(rf"(?<![\d.,]){tope}(?![\d.,])", x) for x in n.get("limites") or []):
        m.append(f"{c['id']}/{n['nivel']}: instancias_max {tope} sin su límite literal en «limites»")
    if _entero(tope) and _entero(minimo) and minimo > tope:
        m.append(f"{c['id']}/{n['nivel']}: instancias_min mayor que instancias_max")
    if validas is not None and (not isinstance(validas, list) or not validas or any(
            not _entero(v) or v < (minimo if _entero(minimo) else 1) or (_entero(tope) and v > tope) for v in validas)):
        m.append(f"{c['id']}/{n['nivel']}: instancias_validas vacías o fuera del mínimo y el tope")
    return m


def problemas_i18(cat: dict) -> list[str]:
    """Forma de lo nuevo de I1.8 (REVERIF17-2 y -3, LES-G-100.7 y .8), en TODAS las filas: cada plantilla de volumen
    trae factor estándar o un motivo para no tenerlo (nunca los dos); cada base de factor tiene una palabra de 4 letras o
    más (el núcleo ignora las más cortas); cada plantilla de tiempo, una unidad que el núcleo cuenta; obligatorios y
    reglas de medidores nombran plantillas de su fila; el tope de instancias es un entero con su límite literal; y cada
    fila de cómputo con plantillas de tiempo las tiene todas en algún nivel (si no, el núcleo no deja justificarla)."""
    m = []
    for k, f in factores(cat).items():
        cortas = [b for b in f.get("base") or [] if not any(len(t) >= 4 for t in re.split(r"[^a-záéíóúüñ]+", b.lower()))]
        if cortas:
            m.append(f"factor {k}: palabras de base sin ninguna palabra de 4 letras o más {cortas}")
    computo = set((cat.get("computo_por_defecto") or {}).get("filas") or [])
    for c in cat["componentes"]:
        pls = c.get("plantillas_precio") or []
        ids = {p["id"] for p in pls}
        for p in pls:
            con_f, sin_f = bool(p.get("factor_estandar")), bool(str(p.get("sin_factor_motivo") or "").strip())
            if p.get("impulsor") == "volumen" and con_f == sin_f:
                m.append(f"{c['id']}/{p['id']}: plantilla de volumen con factor estándar y motivo a la vez, o sin ninguno")
            if p.get("impulsor") == "tiempo" and sin_f:
                m.append(f"{c['id']}/{p['id']}: sin_factor_motivo solo en plantillas de volumen")
            unidad = (p.get("comprobacion") or {}).get("unidad")
            if p.get("impulsor") == "tiempo" and unidad not in UNIDADES_TIEMPO:
                m.append(f"{c['id']}/{p['id']}: unidad de tiempo «{unidad}» que el núcleo no cuenta")
        for n in c.get("niveles") or []:
            if "medidores_obligatorios" in n and not _ids_validos(n["medidores_obligatorios"], ids):
                m.append(f"{c['id']}/{n['nivel']}: medidores_obligatorios vacíos o ajenos a la fila")
            m += _problemas_instancias(c, n)
        for r in c.get("reglas_medidores") or []:
            listas = [r[k] for k in ("exige", "exige_uno_de") if k in r]
            if not _ids_validos(r.get("si_usa"), ids) or not listas or not all(_ids_validos(x, ids) for x in listas):
                m.append(f"{c['id']}: regla de medidores con ids ajenos a la fila o sin «exige» ni «exige_uno_de»")
        de_niveles = set().union(*(set(n["plantillas"]) for n in c.get("niveles") or []))
        tiempo = {p["id"] for p in pls if p.get("impulsor") == "tiempo"}
        if c["id"] in computo and tiempo - de_niveles:
            m.append(f"{c['id']}: fila de cómputo con plantillas de tiempo fuera de todo nivel {sorted(tiempo - de_niveles)}")
        # Integrador I1.8 (P18-4, E18-2): una fila de cómputo sin niveles no se puede valorar nunca (computo_sin_niveles)
        if c["id"] in computo and pls and not c.get("niveles"):
            m.append(f"{c['id']}: fila de cómputo sin niveles: ningún precio suyo se podría justificar")
    return m


INICIO_V4 = "### Plantillas de precio (generado por catalogo/derivar.py desde el catálogo; no editar a mano)"
FIN_V4 = "### Fin de las plantillas de precio"


def _num(v: float) -> str:
    """5656 → «5.656»; 0,5 con coma decimal (castellano). Arreglos I1.7: sin redondear a dos decimales (0,002 GB por
    documento salía «0,00»): los decimales del valor tal cual."""
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    entero, _, dec = format(__import__("decimal").Decimal(str(v)).normalize(), "f").partition(".")
    return f"{int(entero):,}".replace(",", ".") + "," + dec


def _marca_v4(p: dict) -> str:
    k = p.get("comprobacion") or {}
    n = len(set(k.get("tramos") or [0]))
    marca = "T" if p.get("impulsor") == "tiempo" else f"V/{_corto(p['divisor'])}"
    marca += f" [f={p['factor_estandar']}]" if p.get("factor_estandar") else ""
    marca += " [sin f]" if p.get("sin_factor_motivo") else ""  # I1.8 (LES-G-100.8): el motivo va en su apartado
    if FACTORES_ALTERNATIVOS_EN_BLOQUE and p.get("factores_alternativos"):  # I1.9 (PR18-5): experto.factor_por_base
        marca += " [o f=" + ", ".join(p["factores_alternativos"]) + "]"
    marca += " [opcional]" if p.get("opcional") else ""  # I1.9 (VC18-7): la razón va en su apartado
    pi = p.get("por_instancia")  # PR17-5 (arreglos I1.7)
    marca += f" [×{_num(pi['valor'])} {pi['unidad']}]" if isinstance(pi, dict) else ""
    marca += " (por defecto)" if p.get("por_defecto") is True else ""
    return marca + (" (gratuito)" if p.get("gratuito") else f" ({n} tramos)" if n > 1 else "")


_REGLAS_V4 = [
    "Los precios los pone el código desde una instantánea oficial de Azure Retail Prices en EUR tomada al desplegar. No "
    "tienes herramienta de precios: nunca escribes filtro, precio, unidad ni concepto. Por cada precio eliges la plantilla "
    "de la fila de su componente y das solo la cantidad:",
    "- `T` (tiempo): `instancias` (1 si no hay réplicas ni varias unidades). El código cuenta 730 horas al mes por "
    "instancia (30,42 días o 1 mes si la unidad es el día o el mes) y, si la plantilla lleva `[×…]`, lo multiplica por "
    "esas unidades por instancia (la memoria de una EP1 son 3,5 GB). `base_volumen: null`. Más de 1 instancia solo con "
    "`justificacion_nivel` (una razón de su nivel en «Niveles de servicio» y la cita que la cumple, también en el "
    "cómputo por defecto) y nunca por encima del tope de su nivel («hasta N instancias»).",
    "- `V/n` (volumen): `base_volumen` = {`cita`, `cantidad_base`, `unidad_base`}, con `cita` copiada literal de un "
    "fragmento de la línea «Volumetría:» del brief, sin comillas, y `cantidad_base` el número de esa cita. Con `[f=…]`, el "
    "código multiplica por ese factor estándar y divide por n: `factor_override: null`. Sin `[f=…]`, `factor_override` es "
    "obligatorio (`[sin f]`: solo si un requisito citado lo permite; el motivo va abajo). Con `[o f=…]`, el código "
    "elige entre `[f=…]` y esos factores el de la base que cuenta la cita («acciones al mes» → por acción): "
    "`unidad_base` solo con esa palabra; consultas y acciones, en precios distintos. `instancias: null`.",
    "- `factor_override` = {`valor`, `cita`, `justificacion`}: solo cuando una frase LITERAL de los requisitos obliga a "
    "otro factor (o la plantilla no lo tiene); `cita` es esa frase y `justificacion` explica la cuenta. El revisor ve cada "
    "cambio y el verificador lo juzga.",
    "- El precio de la instantánea es el de la región de la fila: un componente con precio va en la «Región UE» de su fila "
    "en la tabla del catálogo (o en la que indique su fila si el precio se publica como `Global`).",
    "- Con varios tramos, el código los aplica a la cantidad total de cada plantilla en toda la respuesta (aunque vaya en "
    "varias líneas o componentes): partirla no cambia el importe; no calcules los tramos tú.",
]


def bloque_v4(cat: dict, auxiliares_con_plantillas: bool = False) -> str:
    """Bloque compacto de las instrucciones del experto con la regla v4 (precio por instantánea): plantillas por id con su
    impulsor y su factor estándar, cuándo se cambia un factor, modelo por defecto, modelos fuera por ciclo de vida,
    niveles, inclusiones declaradas y arquitecturas de referencia por id. Sin filtros: el experto no consulta precios."""
    fuera, cvs = modelos_fuera_siempre(cat), ciclos_vida(cat)
    # I1.8: sin la justificación de cada factor (29 en v7): la ponen el núcleo en la nota del revisor y el catálogo.
    lineas = [INICIO_V4, *_REGLAS_V4, "", "Factores estándar (el código hace la cuenta; su fuente y su justificación van a "
              "la nota del revisor; la cita de `base_volumen` cuenta lo que dice «por …»):"]
    lineas += [f"- `{k}` = {_num(f['valor'])} {f['unidad']} ({f['tipo']})." for k, f in factores(cat).items()]
    d = cat.get("modelo_por_defecto")
    if d:
        fila = next(c for c in cat["componentes"] if c["id"] == d["componente"])
        otros = sorted({p["modelo"] for p in fila.get("plantillas_precio") or []
                        if p.get("modelo") and p["modelo"] not in fuera and p["modelo"] != d["modelo"]})
        sin_fecha = ", ".join(f"`{m}`" for m in sorted(cvs) if cvs[m]["retirada"] is None)
        # I1.9 (VC18-5): otro modelo, como otro nivel: justificacion_nivel con una razón cerrada de sus plantillas.
        lineas += ["", f"Modelo por defecto: `{d['modelo']}` en Data Zone (`{d['region']}`), plantillas "
                   + " y ".join(f"`{x}`" for x in d["plantillas"]) + ", con `justificacion_nivel: null`. Otro modelo solo "
                   "con `justificacion_nivel` = {`nivel`: el modelo, `razon`, `cita`}: "
                   + "; ".join(f"`{m}`: " + _razones_texto(razones_de_modelo(cat, m)) for m in otros)
                   + ". Contexto largo, solo si los requisitos citan peticiones de cientos de miles de tokens de entrada; "
                   f"caché, solo si la citan. Retirada aún no publicada: {sin_fecha}."]
    cp = cat.get("computo_por_defecto")  # PR17-4 (arreglos I1.7)
    if cp:
        fila = next(c for c in cat["componentes"] if c["id"] == cp["componente"])
        lineas += ["", f"Cómputo por defecto: {fila['nombre_oficial']} (`{cp['componente']}`), nivel `{cp['nivel']}`, "
                   "plantilla " + " y ".join(f"`{x}`" for x in cp["plantillas"]) + f", con `justificacion_nivel: null`. "
                   f"{cp['motivo']} Fuente: {cp['fuente_url']}."]
    if fuera:
        lineas.append("Fuera por ciclo de vida (se retiran antes de la oferta + plazo + 12 meses; el código los rechaza): "
                      + ", ".join(f"`{m}` ({cvs[m]['retirada']})" for m in fuera) + ".")
    lineas += ["", "Plantillas por servicio (`id` impulsor [factor estándar] — qué mide). Las de modelo se leen por su id: "
               "modelo, entrada o salida, caché y `-largo` para contexto largo (sin `-largo`, contexto corto):"]
    for c in cat["componentes"]:
        ps = [p for p in c.get("plantillas_precio") or [] if p.get("modelo") not in fuera]
        if ps:
            lineas.append(f"- {c['nombre_oficial']} (`{c['id']}`): "
                          + "; ".join(f"`{p['id']}` {_marca_v4(p)}" + ("" if p.get("modelo") else f" — {p['descripcion']}")
                                      for p in ps) + ".")  # el id de una plantilla de modelo ya dice qué mide
    con_niveles = [c for c in cat["componentes"] if c.get("niveles")]
    if con_niveles:  # I1.9 (VC18-1, PR18-3): valor por defecto sin justificar y razones cerradas, sin límites
        lineas += ["", INTRO_NIVELES_V8]
        lineas += [f"- Lista {n}: {_palabras(k)}." for k, n in listas_repetidas(cat).items()]
        lineas += [_linea_niveles_v8(c, cat) for c in con_niveles]
    obl = [c for c in cat["componentes"] if c.get("medidores_obligatorios")]  # PR17-3 (arreglos I1.7)
    if obl:
        lineas += ["", "Medidores obligatorios (si el componente lleva algún precio propio, lleva también estos; el código "
                   "lo rechaza si falta alguno):"]
        lineas += [f"- {c['nombre_oficial']} (`{c['id']}`): " + ", ".join(f"`{x}`" for x in c["medidores_obligatorios"]) + "."
                   for c in obl]
    reglas = [(c, r) for c in cat["componentes"] for r in c.get("reglas_medidores") or []]  # I1.8 (REVERIF17-2)
    if reglas:
        lineas += ["", "Reglas de medidores (con cualquier plantilla de la izquierda, el componente lleva también las de "
                   "la derecha; los de cada nivel van entre corchetes en «Niveles de servicio»):"]
        lineas += [f"- {c['nombre_oficial']} (`{c['id']}`): " + ", ".join(f"`{x}`" for x in r["si_usa"]) + " → "
                   + _lado_derecho(r) + "." for c, r in reglas]
    sin_f: dict[str, list[str]] = {}  # I1.8 (LES-G-100.8): por qué una plantilla de volumen no trae factor estándar
    for c in cat["componentes"]:
        for p in c.get("plantillas_precio") or []:
            if p.get("sin_factor_motivo") and p.get("modelo") not in fuera:
                sin_f.setdefault(p["sin_factor_motivo"], []).append(f"`{p['id']}`")
    if sin_f:
        lineas += ["", "Plantillas de volumen sin factor estándar (`[sin f]`; solo con `factor_override` citando el "
                   "requisito que se indica):"]
        lineas += [f"- {', '.join(ids)}: {motivo}" for motivo, ids in sin_f.items()]
    opc = [(c, p) for c in cat["componentes"] for p in c.get("plantillas_precio") or [] if p.get("opcional")]
    if opc:  # I1.9 (VC18-7): plantilla opcional con su valor por defecto declarado
        lineas += ["", "Plantillas opcionales (`[opcional]`; por defecto no se valoran: solo si una cita de los requisitos "
                   "cumple su razón, dicha en un supuesto con esa cita y el C-nn):"]
        lineas += [f"- `{p['id']}` ({c['nombre_oficial']}): " + _razones_texto(p["opcional"]["razones"],
                                                                               listas_repetidas(cat)) + "."
                   for c, p in opc]
    nv = [(c, x) for c in cat["componentes"] for x in c.get("no_valorables") or []]
    if nv:
        lineas += ["", "Sin plantilla a propósito (no se valoran; el supuesto dice el motivo):"]
        lineas += [f"- {c['nombre_oficial']}: {x['concepto']}. Motivo: {MOTIVOS_NO_VALORABLE[x['motivo']]}." for c, x in nv]
    inc = [(c, x) for c in cat["componentes"] for x in c.get("incluye") or []]
    if inc:
        lineas += ["", "Inclusiones declaradas (las únicas que valen para `incluido_en_otro_componente`):"]
        lineas += [f"- `{x['catalogo_id']}` va incluido en `{c['id']}`: {x['concepto']} (fuente {x['fuente_url']})."
                   for c, x in inc]
    if auxiliares_con_plantillas:
        for a in cat.get("precios_auxiliares") or []:
            ps = plantillas_de_auxiliar(a, cat)
            if ps:
                lineas += ["", f"Precio auxiliar `{a['service_name']}`: plantilla "
                           + ", ".join(f"`{p['id']}` {_marca_v4(p)}" for p in ps) + "; su `componente_id` es el del "
                           "componente al que da acceso privado, cuyo `catalogo_id` es uno de "
                           + ", ".join(f"`{i}`" for i in a["componentes"]) + ". No cubre al componente."]
    arqs = cat.get("arquitecturas_referencia") or []
    if arqs:
        lineas += ["", "Arquitecturas de referencia (`arquitectura_id`; el código pone su URL):"]
        lineas += [f"- `{a['id']}`: {a['titulo']}. {a['cuando_usar']}" for a in arqs]
    return "\n".join(lineas + [FIN_V4])


def insertar_bloque_v4(texto: str, bloque: str) -> str:
    """Sustituye el bloque v4 entre INICIO_V4 y FIN_V4. Falla en alto si faltan, sobran o están desordenadas las marcas,
    o si sigue el bloque de filtros de I1.5/I1.6 (el experto ya no consulta precios)."""
    if INICIO in texto or FIN in texto:
        raise ValueError("las instrucciones siguen llevando el bloque de filtros de precio anterior a I1.7")
    i, f = texto.find(INICIO_V4), texto.find(FIN_V4)
    if texto.count(INICIO_V4) != 1 or texto.count(FIN_V4) != 1 or f < i:
        raise ValueError("faltan, sobran o están desordenadas las líneas del bloque de plantillas de precio (v4)")
    return texto[:i] + bloque + texto[f + len(FIN_V4):]


# ---------------------------------------------------------------------------------------------------------------------
# I1.9 (papel E): valor por defecto con fuente, razones cerradas de subida, disponibilidad por nivel y región (VC18-1,
# VC18-3, VC18-5, VC18-7, PR18-3, PR18-5). La forma de cada razón es la que lee el núcleo (experto.razones_validas).
# ---------------------------------------------------------------------------------------------------------------------
# PR18-5 (E19-2): el núcleo elige el factor por la base de la cita entre el estándar y los factores alternativos
# (experto.factor_por_base, cierre de P del 16-10-2026): el bloque los enseña con «[o f=…]». Con False, el experto no
# sabría que puede contar acciones (citarlas daría base_no_casa).
FACTORES_ALTERNATIVOS_EN_BLOQUE = True
CAMPOS_RAZON = ("objetivo", "nubes", "alcance_funcional", "canales_integraciones", "ubicacion_usuarios", "marco_normativo",
                "volumetria", "identidad_acl_origen", "red_privada")
CAMPOS_RAZON_TEXTO = {"volumetria": "Volumetría", "red_privada": "Red privada", "alcance_funcional": "Alcance funcional",
                      "canales_integraciones": "Canales e integraciones", "identidad_acl_origen": "Identidad y permisos",
                      "marco_normativo": "Marco normativo", "ubicacion_usuarios": "Ubicación de los usuarios"}
REGIONES_UE = ("swedencentral", "francecentral", "westeurope", "northeurope", "germanywestcentral", "spaincentral",
               "italynorth", "polandcentral")
_ID_RAZON = re.compile(r"[a-z0-9][a-z0-9_.-]{0,59}")
INTRO_NIVELES_V8 = (
    "Niveles de servicio (§6.1): «por defecto», con `justificacion_nivel: null`; otro nivel, o más de una instancia, con "
    "una de sus razones (umbral: número con esa unidad mayor que el límite; característica: una de esas palabras) y la "
    "cita que la cumple. En la clase cómputo solo el cómputo por defecto va sin razón:")


def _palabras(lista: list) -> str:
    return " / ".join(f"«{w}»" for w in lista)


def listas_repetidas(cat: dict) -> dict:
    """{tupla de palabras clave: «L1»…} de las listas que se repiten en 3 razones o más: el bloque las escribe una vez
    en una leyenda (viaja en cada vuelta del modelo)."""
    vistas: dict = {}
    for c in cat["componentes"]:
        rs = [r for n in c.get("niveles") or [] for r in n.get("razones_subida") or []]
        rs += [r for p in c.get("plantillas_precio") or [] for r in (p.get("opcional") or {}).get("razones") or []]
        for r in rs:
            if r.get("tipo") == "caracteristica":
                vistas[tuple(r["palabras_clave"])] = vistas.get(tuple(r["palabras_clave"]), 0) + 1
    return {k: f"L{i}" for i, k in enumerate((k for k, v in vistas.items() if v >= 3), 1)}


def _razon_texto(r: dict, listas: dict | None = None) -> str:
    """«`id` (Volumetría: más de 300 «simultáneas»)» o «`id` («a» / «b»; Red privada)» (o «`id` (L1)» con leyenda)."""
    campo = CAMPOS_RAZON_TEXTO.get(r.get("campo"), r.get("campo"))
    if r.get("tipo") == "umbral":
        unidades = list(r["unidad"]) + list(r.get("unidad_corta") or [])  # «GB»: palabra entera (numeros_con_unidad)
        por = r.get("por_instancia")  # VC19-1 (I1.10): la razón da las instancias del nivel, una por cada `por` citadas
        extra = f"; una instancia por cada {_num(por)}, exactas" if por else ""
        return (f"`{r['id']}` ({campo}: más de {_num(r['limite'])} " + " o ".join(f"«{u}»" for u in unidades)
                + extra + ")")
    claves = (listas or {}).get(tuple(r["palabras_clave"])) or _palabras(r["palabras_clave"])
    return f"`{r['id']}` ({claves}" + (f"; {campo}" if campo else "") + ")"


def _razones_texto(razones: list, listas: dict | None = None) -> str:
    return ", ".join(_razon_texto(r, listas) for r in razones) if razones else "ninguna (no se puede elegir)"


def razones_de_modelo(cat: dict, modelo: str) -> list:
    """Razones de un modelo: las `razones_subida` de sus plantillas (iguales en todas; lo vigila problemas_i19)."""
    for c in cat["componentes"]:
        for p in c.get("plantillas_precio") or []:
            if p.get("modelo") == modelo and p.get("razones_subida"):
                return p["razones_subida"]
    return []


def _linea_niveles_v8(c: dict, cat: dict) -> str:
    cp, listas = cat.get("computo_por_defecto") or {}, listas_repetidas(cat)
    computo = c["id"] in (cp.get("filas") or [])
    defecto = cp.get("nivel") if c["id"] == cp.get("componente") else None if computo else (
        (c.get("nivel_por_defecto") or {}).get("nivel"))
    partes = []
    for n in c["niveles"]:
        cab = f"`{n['nivel']}` ({', '.join(n['plantillas'])}){_extra_nivel(n)}"
        if n["nivel"] == defecto:
            cab += " por defecto" + (f"; más instancias: {_razones_texto(n['razones_subida'], listas)}"
                                     if n.get("razones_subida") else "")
        else:
            cab += ": " + _razones_texto(n.get("razones_subida") or [], listas)
        partes.append(cab)
    return f"- {c['nombre_oficial']} (`{c['id']}`): " + " · ".join(partes) + "."


INICIO_DISP = "### Disponibilidad por nivel y región (generado por catalogo/derivar.py desde el catálogo; no editar a mano)"
FIN_DISP = "### Fin de la disponibilidad por nivel y región"


def bloque_disponibilidad(cat: dict) -> str:
    """Bloque del verificador (VC18-3, VC18-11): por servicio y nivel (o modelo), las regiones de la UE donde Learn lo da
    disponible, con su fuente. Es un dato del catálogo: un DISCREPA de región contra él pasa a OBSERVACION."""
    ue = [r for r in REGIONES_UE if r != "polandcentral"]
    lineas = [INICIO_DISP,
              "Comprobado en Learn por el catálogo (`nivel`: tabla de Learn por nivel; `servicio`: Learn solo lo publica "
              "por servicio; las páginas cuelgan de https://learn.microsoft.com/azure/). Un componente de ese nivel en una "
              "de esas regiones está disponible: no des DISCREPA de región por disponibilidad; si dudas, OBSERVACION con "
              f"`campo` = `region`. UE7 = {', '.join(ue)}."]
    for c in cat["componentes"]:
        grupos: dict = {}  # niveles con las mismas regiones, alcance y fuente, en una línea (viaja en cada lote)
        for nivel, d in (c.get("disponibilidad") or {}).items():
            grupos.setdefault((tuple(d["regiones"]), d["alcance"], d["fuente"]), []).append(nivel)
        for (regs, alcance, fuente), niveles in grupos.items():
            texto = "UE7" if sorted(regs) == sorted(ue) else ", ".join(regs)
            lineas.append(f"- {c['nombre_oficial']} · {', '.join(niveles)}: {texto} ({alcance}; "
                          f"{fuente.removeprefix('https://learn.microsoft.com/azure/')}).")
    return "\n".join(lineas + [FIN_DISP])


def insertar_bloque_disponibilidad(texto: str, bloque: str) -> str:
    i, f = texto.find(INICIO_DISP), texto.find(FIN_DISP)
    if texto.count(INICIO_DISP) != 1 or texto.count(FIN_DISP) != 1 or f < i:
        raise ValueError("faltan, sobran o están desordenadas las líneas del bloque de disponibilidad")
    return texto[:i] + bloque + texto[f + len(FIN_DISP):]


def _problemas_razones(donde: str, razones: object) -> list[str]:
    """La forma que exige el núcleo (experto.razones_validas): si una falla, el núcleo rechaza todas las del nivel."""
    if not isinstance(razones, list) or not razones:
        return [f"{donde}: razones_subida vacías o que no son una lista"]
    m, ids = [], [r.get("id") if isinstance(r, dict) else None for r in razones]
    if len(set(ids)) != len(ids):
        m.append(f"{donde}: ids de razón repetidos")
    for r in razones:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not _ID_RAZON.fullmatch(r["id"]):
            m.append(f"{donde}: razón sin id válido ({r!r:.80})")
            continue
        q = f"{donde}/{r['id']}"
        if not str(r.get("fuente") or "").startswith("https://learn.microsoft.com/") or len(r.get("texto") or "") < 10:
            m.append(f"{q}: sin fuente de Learn o sin texto")
        if r.get("campo") is not None and r["campo"] not in CAMPOS_RAZON:
            m.append(f"{q}: campo {r['campo']!r} fuera de los campos de los requisitos que dimensionan")
        if r.get("tipo") == "umbral":
            unidad, lim = r.get("unidad"), r.get("limite")
            if r.get("campo") is None or not isinstance(lim, (int, float)) or isinstance(lim, bool) or lim < 0:
                m.append(f"{q}: un umbral lleva campo y un límite numérico ≥ 0")
            if not isinstance(unidad, list) or not unidad or not all(
                    isinstance(u, str) and any(len(t) >= 4 for t in re.split(r"[^a-záéíóúüñ0-9]+", u.lower()))
                    for u in unidad):
                m.append(f"{q}: cada palabra de unidad necesita una de 4 letras o más (el núcleo ignora las cortas)")
        elif r.get("tipo") == "caracteristica":
            claves = r.get("palabras_clave")
            if not isinstance(claves, list) or not claves or not all(
                    isinstance(w, str) and len(re.sub(r"[^0-9a-záéíóúüñ]", "", w.lower())) >= 3 for w in claves):
                m.append(f"{q}: palabras_clave vacías o de menos de 3 letras")
        else:
            m.append(f"{q}: tipo {r.get('tipo')!r} fuera de umbral y caracteristica")
        # ARR1 (Revisión, I1.10): `por_instancia`, como en experto.razones_validas: solo en «umbral» y número > 0. Mal
        # declarado, el núcleo rechaza las razones del nivel y la regla de instancias dejaría de avisar.
        por = r.get("por_instancia")
        if por is not None and (r.get("tipo") != "umbral" or isinstance(por, bool)
                                or not isinstance(por, (int, float)) or not math.isfinite(por) or not por > 0):
            m.append(f"{q}: por_instancia solo en un umbral y con un número > 0 ({por!r:.20})")
    return m


def problemas_i19(cat: dict) -> list[str]:
    """Forma de lo nuevo de I1.9 en TODAS las filas (LES-G-100.7): cada fila con niveles declara su nivel por defecto
    con fuente; cada nivel que no es el valor por defecto tiene razones cerradas bien formadas (en la clase cómputo,
    todos salvo el del cómputo por defecto), y también el valor por defecto que admite más de una instancia; cada nivel tiene su disponibilidad en regiones de la UE, con la «Región UE»
    de la fila y sin sus regiones vetadas; cada modelo que no es el por defecto lleva las mismas razones en todas sus
    plantillas; las plantillas opcionales y los factores alternativos están bien formados. [] si todo está bien."""
    m, fs = [], factores(cat)
    cp = cat.get("computo_por_defecto") or {}
    fuera = set(modelos_fuera_siempre(cat))
    for c in cat["componentes"]:
        niveles = c.get("niveles") or []
        nombres = [n["nivel"] for n in niveles]
        vetadas = {v["region"] for v in c.get("regiones_no_admitidas") or []}
        if niveles:
            nd = c.get("nivel_por_defecto")
            nd_mal = (not isinstance(nd, dict) or nd.get("nivel") not in nombres or not str(nd.get("fuente") or "")
                      .startswith("https://learn.microsoft.com/") or not nd.get("motivo") or not nd.get("consultado"))
            if nd_mal:  # sin valor por defecto válido no se sabe qué nivel va sin razones: un solo problema, este
                m.append(f"{c['id']}: nivel_por_defecto sin nivel de la fila, fuente de Learn, motivo o fecha")
            computo = c["id"] in (cp.get("filas") or [])
            libre = cp.get("nivel") if c["id"] == cp.get("componente") else None if computo else (nd or {}).get("nivel")
            for n in niveles:
                # Revisión E1: un nivel por defecto que admite más de una instancia necesita razones para las de más
                # (sin ellas, el tope del catálogo no se podría usar nunca: falla cerrado, pero contradictorio)
                varias = isinstance(n.get("instancias_max"), int) and n["instancias_max"] > 1
                if not nd_mal and (n["nivel"] != libre or n.get("razones_subida") is not None or varias):
                    m += _problemas_razones(f"{c['id']}/{n['nivel']}", n.get("razones_subida"))
            if sorted(c.get("disponibilidad") or {}) != sorted(nombres):
                m.append(f"{c['id']}: disponibilidad no tiene exactamente una entrada por nivel")
        elif c.get("nivel_por_defecto") is not None:
            m.append(f"{c['id']}: nivel_por_defecto en una fila sin niveles")
        disp = c.get("disponibilidad")
        if disp is not None and not isinstance(disp, dict):
            m.append(f"{c['id']}: disponibilidad no es un objeto {{nivel: {{regiones, alcance, fuente, consultado}}}}")
            disp = {}
        for nivel, d in (disp or {}).items():
            regs = d.get("regiones") if isinstance(d, dict) else None
            if not isinstance(regs, list) or not regs or len(set(regs)) != len(regs) or set(regs) - set(REGIONES_UE)                     or set(regs) & vetadas:
                m.append(f"{c['id']}/{nivel}: regiones vacías, repetidas, fuera de la UE o vetadas en la fila")
                continue
            if c.get("region_ue") and c.get("region_ue") not in regs:
                m.append(f"{c['id']}/{nivel}: la «Región UE» de la fila ({c.get('region_ue')}) no está")
            if not str(d.get("fuente") or "").startswith("https://learn.microsoft.com/") or d.get("alcance") not in (
                    "nivel", "servicio") or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(d.get("consultado"))):
                m.append(f"{c['id']}/{nivel}: disponibilidad sin fuente de Learn, alcance o fecha")
            if set(d) - {"regiones", "alcance", "fuente", "consultado", "nota"}:
                m.append(f"{c['id']}/{nivel}: disponibilidad con campos desconocidos")
        for p in c.get("plantillas_precio") or []:
            if p.get("opcional"):
                op = p["opcional"]
                if op.get("por_defecto") not in ("sin", "con") or not op.get("motivo"):
                    m.append(f"{c['id']}/{p['id']}: opcional sin valor por defecto o sin motivo")
                m += _problemas_razones(f"{c['id']}/{p['id']} (opcional)", op.get("razones"))
            for alt in p.get("factores_alternativos") or []:
                if alt not in fs or alt == p.get("factor_estandar") or p.get("impulsor") != "volumen":
                    m.append(f"{c['id']}/{p['id']}: factor alternativo {alt!r} desconocido, repetido o en tiempo")
    d = cat.get("modelo_por_defecto") or {}
    fila = next((c for c in cat["componentes"] if c["id"] == d.get("componente")), {})
    modelos = sorted({p["modelo"] for p in fila.get("plantillas_precio") or [] if p.get("modelo")} - fuera)
    for mod in modelos:
        listas = [p.get("razones_subida") for p in fila["plantillas_precio"] if p.get("modelo") == mod]
        if mod == d.get("modelo"):
            if any(x is not None for x in listas):
                m.append(f"modelo {mod}: el modelo por defecto no lleva razones")
        elif any(x != listas[0] for x in listas):
            m.append(f"modelo {mod}: sus plantillas no llevan las mismas razones")
        else:
            m += _problemas_razones(f"modelo {mod}", listas[0])
    if fila and sorted(fila.get("disponibilidad") or {}) != modelos:
        m.append("az-foundry: disponibilidad no tiene exactamente una entrada por modelo vigente")
    return m
