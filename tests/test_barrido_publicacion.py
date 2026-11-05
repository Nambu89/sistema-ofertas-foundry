"""El barrido previo a publicar: código de salida = veredicto y nunca pasa en silencio."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("barrido", RAIZ / "herramientas" / "barrido_publicacion.py")
barrido = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(barrido)


def _repo(tmp_path: pathlib.Path, contenido: str) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text(contenido, encoding="utf-8")
    (repo / ".gitignore").write_text("ignorado.txt\n", encoding="utf-8")
    (repo / "ignorado.txt").write_text("PersonaFicticia\n", encoding="utf-8")
    return repo


def _terminos(tmp_path: pathlib.Path, texto: str) -> pathlib.Path:
    ruta = tmp_path / "terminos.txt"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_limpio_da_cero_y_respeta_gitignore(tmp_path):
    repo = _repo(tmp_path, "texto normal con hash " + "a" * 64 + "\n")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 0


def test_termino_secreto_y_guid_dan_uno(tmp_path, capsys):
    clave = "AccountKey=" + "Q" * 30
    guid = "12345678-1234-1234-1234-" + "123456789abc"   # partido: no es un hallazgo del propio barrido
    repo = _repo(tmp_path, f"Hola, PersonaFicticia\n{clave}\nid {guid}\nrol eed3b665-ab3a-47b6-8f48-c9382fb1dad6\n"
                           f'"meterId": "{guid}"\nficticio 00000000-0000-4000-8000-0000000000b1\n')
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 1
    salida = capsys.readouterr().out
    assert "a.txt:1: término local" in salida
    assert "a.txt:2: clave de cuenta de almacenamiento" in salida
    assert "a.txt:3: GUID no público" in salida
    assert not any(f"a.txt:{n}:" in salida for n in (4, 5, 6))   # rol integrado, meterId, ficticio
    assert "Q" * 30 not in salida and guid not in salida   # nunca imprime el valor


def test_limite_de_palabra_y_mayusculas(tmp_path):
    repo = _repo(tmp_path, "alfabeto y Alfa\n")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "ALFA\n"))]) == 0   # mayúsculas
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "alfa\n"))]) == 0   # límite
    (repo / "a.txt").write_text("una alfa suelta\n", encoding="utf-8")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "alfa\n"))]) == 1


def test_configuracion_invalida_da_dos(tmp_path):
    repo = _repo(tmp_path, "x\n")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(tmp_path / "no-existe.txt")]) == 2
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "# solo comentario\n"))]) == 2
    plantilla = (RAIZ / "config" / "terminos-prohibidos.local.txt.ejemplo").read_text(encoding="utf-8")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, plantilla))]) == 2


def test_mira_dentro_de_los_zip_comprimidos(tmp_path, capsys):
    repo = _repo(tmp_path, "nada\n")
    with zipfile.ZipFile(repo / "p.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dentro.txt", "Hola, PersonaFicticia " * 50)
    assert "PersonaFicticia" not in (repo / "p.zip").read_bytes().decode("latin-1")   # DEFLATE lo esconde
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 1
    assert "p.zip!dentro.txt:1: término local" in capsys.readouterr().out


def test_las_excepciones_de_guid_valen_solo_en_su_sitio(tmp_path, capsys):
    otro = "abcdef12-3456-4789-8abc-" + "def012345678"   # partido: no es un hallazgo del propio barrido
    repo = _repo(tmp_path, f'{{"meterId": "{otro}", "tenantId": "{otro}"}}\n')
    (repo / "t.md").write_text(f"| Concepto | meterId | €/mes |\n|---|---|---|\n| A | `{otro}` | 1 € |\n"
                               f"| B `{otro}` | x | 2 € |\n", encoding="utf-8")
    (repo / "d.svg").write_text(f'<g id="i-coord-{otro}"/>\n', encoding="utf-8")
    (repo / "p.html").write_text(f'<div id="{otro}"></div>\n', encoding="utf-8")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 1
    salida = capsys.readouterr().out
    assert salida.count("a.txt:1: GUID no público") == 1          # el meterId sí, el tenantId no
    assert "t.md:4: GUID no público" in salida and "t.md:3:" not in salida
    assert "d.svg" not in salida and "p.html:1: GUID no público" in salida


def test_mira_dentro_de_un_pptx_dentro_de_un_zip(tmp_path, capsys):
    import io
    interior = io.BytesIO()
    with zipfile.ZipFile(interior, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ppt/slides/slide1.xml", "<a:t>PersonaFicticia</a:t>" * 50)
    repo = _repo(tmp_path, "nada\n")
    with zipfile.ZipFile(repo / "p.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("x.pptx", interior.getvalue())
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 1
    assert "p.zip!x.pptx!ppt/slides/slide1.xml" in capsys.readouterr().out


def test_utf16_zip_con_preambulo_y_tablas_contiguas(tmp_path, capsys):
    import io
    otro = "abcdef12-3456-4789-8abc-" + "def012345678"
    repo = _repo(tmp_path, "nada\n")
    (repo / "u.txt").write_bytes("Hola, PersonaFicticia".encode("utf-16"))
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("m.txt", "PersonaFicticia " * 50)
    (repo / "pre.bin").write_bytes(b"preambulo" + zbuf.getvalue())
    (repo / "t.md").write_text(f"| a | meterId |\n|---|---|\n| x | `{otro}` |\n| tenantId | valor |\n|---|---|\n"
                               f"| t | `{otro}` |\n", encoding="utf-8")
    assert barrido.main(["--raiz", str(repo), "--terminos", str(_terminos(tmp_path, "PersonaFicticia\n"))]) == 1
    salida = capsys.readouterr().out
    assert "u.txt:1: término local" in salida and "pre.bin!m.txt:1: término local" in salida
    assert "t.md:6: GUID no público" in salida and "t.md:3:" not in salida
