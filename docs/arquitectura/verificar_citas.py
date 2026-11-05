"""Comprueba con HTTP que cada URL de la banda responde 200 y contiene la cita literal (texto visible normalizado)."""
import html, json, re, sys, urllib.request
from urllib.parse import urlsplit


def es_learn(url: str) -> bool:
    try:
        u = urlsplit(url)
        return u.scheme == "https" and u.hostname == "learn.microsoft.com" and not u.username and not u.port
    except ValueError:  # puerto o autoridad mal formados
        return False


spec = json.load(open(sys.argv[1], encoding="utf-8"))
fallos = 0
cache = {}
for p in spec["practicas"]["catalogo"]:
    url = p["url"]
    if not es_learn(url):
        fallos += 1
        print(f"FALLA {p['id']} URL que no es de https://learn.microsoft.com/: {url}")
        continue
    if url not in cache:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                codigo, cuerpo = r.status, r.read(5_000_000).decode("utf-8", "replace")
                if not es_learn(r.geturl()):  # una redirección fuera de Learn no cuenta como fuente
                    codigo = f"redirigida a {r.geturl()}"
        except (OSError, ValueError) as ex:  # HTTPError, tiempo agotado, TLS: cuenta como fallo y sigue
            codigo, cuerpo = f"error {ex}", ""
        cuerpo = re.sub(r"<!--.*?-->", " ", cuerpo, flags=re.S)
        cuerpo = re.sub(r"<(script|style)\b.*?</\1>", " ", cuerpo, flags=re.S | re.I)
        texto = html.unescape(re.sub(r"<[^>]+>", " ", cuerpo))
        cache[url] = (codigo, re.sub(r"\s+", " ", texto))
    codigo, texto = cache[url]
    norm = lambda s: re.sub(r"\s+([.,:;])", r"\1", re.sub(r"\s+", " ", s.replace("’", "'")))
    ok = codigo == 200 and norm(p["cita"]) in norm(texto)
    fallos += not ok
    print(f"{'OK ' if ok else 'FALLA'} {p['id']} HTTP {codigo} {url}")
print(f"VEREDICTO: {len(spec['practicas']['catalogo']) - fallos}/{len(spec['practicas']['catalogo'])} citas encontradas")
sys.exit(1 if fallos else 0)
