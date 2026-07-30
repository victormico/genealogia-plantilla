"""Walk the diocesan catalogue from the command line, and pull the pages you need.

    python -m tools.adg.browse --parroquia vilafant       # find the parish
    python -m tools.adg.browse --node 500                 # what is under it
    python -m tools.adg.browse --arbre 500                # the series, in one go
    python -m tools.adg.browse --serie 1203193            # the books in a series
    python -m tools.adg.browse --llibre 14233             # the fiche: can I read it?
    python -m tools.adg.browse --pagines 14233            # how many pages, by bisection
    python -m tools.adg.browse --baixa 14233 --pagina 73  # save one page

`--assaig` rehearses any of them without touching the network.

The order above is the order to use them in, and the third step is the one people
skip: **do not stop at «Llibres originals».** A parish whose original books start
in 1918 can still have «Còpies, extractes i certificats» covering the 1880s, and
each certificate is a literal extract of the entry, with the full filiation of
both parties. A burnt book can survive in the certificates issued from it. That is
why `--arbre` lists every series and not just the first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import config
from . import catalog, images
from .session import ROOT, Session


def _print_nodes(nodes: list[catalog.Node], show_prose: bool = False) -> None:
    if not nodes:
        print("  (cap)")
        return
    for node in nodes:
        docs = " · té llibres" if node.has_documents else ""
        print(f"  {node.id:>8}  {node.title}{docs}")
        if show_prose and node.description:
            text = " ".join(node.description.split())
            print(f"            {text[:300]}{'…' if len(text) > 300 else ''}")


def cmd_parish(session: Session, text: str) -> None:
    found = catalog.find_parish(session, text)
    print(f"\nParròquies que concorden amb «{text}»: {len(found)}\n")
    _print_nodes(found, show_prose=True)
    if found:
        print("\nEl resum en prosa és de l'arxiu i **es queda curt**: n'hi ha que diuen "
              "que els llibres «no s'han conservat» i tanmateix tenen sèries de "
              "certificats amb imatges. Mira l'arbre, no el resum:")
        print(f"  python -m tools.adg.browse --arbre {found[0].id}")


def cmd_node(session: Session, node_id: str) -> None:
    kids = catalog.children(session, node_id)
    print(f"\nSota el node {node_id}: {len(kids)}\n")
    _print_nodes(kids)


def cmd_tree(session: Session, node_id: str, depth: int) -> None:
    nodes = catalog.walk_series(session, node_id, depth=depth)
    print(f"\nL'arbre sota el node {node_id}, {depth} nivells: {len(nodes)} nodes\n")
    for node in nodes:
        indent = "  " * max(0, len(node.path) - 2)
        docs = "  ←  té llibres" if node.has_documents else ""
        print(f"  {node.id:>8}  {indent}{node.title}{docs}")
    holders = [n for n in nodes if n.has_documents]
    if holders:
        print(f"\n{len(holders)} nodes amb llibres. Per veure'ls:")
        print(f"  python -m tools.adg.browse --serie {holders[-1].id}")


def cmd_series(session: Session, node_id: str) -> None:
    docs = catalog.documents(session, node_id)
    print(f"\nLlibres a la sèrie {node_id}: {len(docs)}\n")
    if not docs:
        print("  (cap) — i compte: si has passat un `_idserie` d'una fitxa en lloc de "
              "l'id del node de l'arbre, la resposta és buida igualment i sembla que "
              "la sèrie no tinga res. Són dues numeracions diferents.")
        return
    for doc in docs:
        print(f"  {doc.id:>8}  {doc.title}")
        if doc.code:
            print(f"            {doc.code}")
    print("\nLa llista no diu si es poden mirar. Això és a la fitxa:")
    print(f"  python -m tools.adg.browse --llibre {docs[0].id}")


def cmd_book(session: Session, udoc_id: str) -> None:
    book = catalog.fiche(session, udoc_id)
    if book is None:
        print(f"no hi ha fitxa per al llibre {udoc_id}")
        return
    print(f"\n{book.title}")
    print(f"  id            {book.id}")
    print(f"  codi          {book.code or '(cap)'}")
    print(f"  fons          {book.fonds}")
    print(f"  sèrie         {book.group} › {book.series}")
    print(f"  anys          {book.years}")
    print(f"  llengua       {book.language or '(no consta)'}")
    print(f"  volum         {' '.join(book.volume.split())[:140] or '(no consta)'}")
    print(f"  accés         {book.access or '(no consta)'} [{book.access_kind}]")
    print(f"  digitalitzat  {'sí' if book.digitised else 'NO'}  (bucket)")
    if book.contents:
        print(f"  contingut     {' '.join(book.contents.split())[:300]}")
    print()
    if book.readable:
        print("  **Es pot llegir des de casa.**")
        print(f"  visor:  {book.viewer_url}")
        print(f"  imatge: {images.image_url(book.s3_id or book.id, 1)}")
        print(f"\n  python -m tools.adg.browse --pagines {book.id}")
    else:
        print(f"  **No es pot llegir des de casa**: {book.why_not()}.")
        print(f"  visor (per si de cas): {book.viewer_url}")


def cmd_pages(session: Session, udoc_id: str, resolution: str) -> None:
    book = catalog.fiche(session, udoc_id)
    if book is not None and not book.digitised:
        print(f"\n{book.title}\n  `bucket: false` — no hi ha imatges. {book.why_not()}.")
        print("  No es busca el final d'un llibre que no és al bucket.")
        return
    s3_id = (book.s3_id if book else "") or str(udoc_id)
    print(f"\nBuscant el final del llibre {s3_id} per bisecció (peticions HEAD)…")
    last = images.bisect_last_page(session, s3_id, resolution)
    if last is None:
        print("  la pàgina 1 no hi és. O el llibre no està digitalitzat, o l'id no és "
              "aquest. Mira primer la fitxa amb --llibre.")
        return
    print(f"\n  **{last} pàgines.**")
    print(f"  primera: {images.image_url(s3_id, 1, resolution)}")
    print(f"  última:  {images.image_url(s3_id, last, resolution)}")
    print("\nAl marge superior dret de cada pàgina hi sol haver la data en xifres, que "
          "és el que permet situar-se sense llegir el text: mira dues o tres pàgines "
          "separades i interpola.")
    print(f"\n  python -m tools.adg.browse --baixa {udoc_id} --pagina 1-4")


def cmd_download(session: Session, udoc_id: str, spec: str, resolution: str,
                 out: Path | None, max_pages: int) -> None:
    book = catalog.fiche(session, udoc_id)
    if book is not None and not book.digitised:
        print(f"\n`bucket: false` — {book.why_not()}. No hi ha res a baixar.")
        return
    s3_id = (book.s3_id if book else "") or str(udoc_id)
    pages = images.parse_pages(spec)
    target = out or (ROOT / "cache" / "adg" / "imatges" / str(udoc_id))
    print(f"\nBaixant {len(pages)} pàgina(es) del llibre {s3_id} a {target}\n")
    saved = images.download_pages(session, s3_id, pages, target, resolution,
                                  max_pages=max_pages)
    if saved:
        total = sum(s.size for s in saved) / 1_048_576
        print(f"\n{len(saved)} fitxer(s), {total:.1f} MB a {target}")
        print("Si en surt una partida, transcriu-la a `Fonts/` amb la plantilla i "
              "cita el llibre i la pàgina. La imatge no es publica: `Fonts/` és al "
              ".gitignore tret dels .md, i ha de continuar sent així.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="El catàleg de l'Arxiu Diocesà de Girona, i les seues imatges.",
        epilog="Fes-ne un ús de persona que consulta: aquestes crides serveixen per "
               "situar-te i per baixar les pàgines que et fan falta, no per buidar el fons.")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--parroquia", metavar="TEXT",
                      help="cerca una parròquia pel nom (accents i majúscules igual)")
    what.add_argument("--node", metavar="ID", help="els fills d'un node de l'arbre")
    what.add_argument("--arbre", metavar="ID",
                      help="tot l'arbre sota un node: parròquia → sagraments → sèries")
    what.add_argument("--serie", metavar="ID",
                      help="els llibres d'una sèrie (id del NODE, no l'_idserie d'una fitxa)")
    what.add_argument("--llibre", metavar="ID",
                      help="la fitxa d'un llibre: anys, accés i si està digitalitzat")
    what.add_argument("--pagines", metavar="ID",
                      help="quantes pàgines té, per bisecció amb peticions HEAD")
    what.add_argument("--baixa", metavar="ID", help="baixa pàgines d'un llibre")

    parser.add_argument("--pagina", metavar="SPEC", default="1",
                        help="quines pàgines: «73», «3-7», «3,9,11-13» (amb --baixa)")
    parser.add_argument("--resolucio", choices=images.RESOLUTIONS,
                        default=config.get("adg", "resolucio",
                                           default=images.DEFAULT_RESOLUTION),
                        help="l = baixa · m = mitjana (per defecte) · h = alta, per a lletra difícil")
    parser.add_argument("--out", metavar="CARPETA", type=Path,
                        help="on desar les imatges (per defecte cache/adg/imatges/<id>)")
    parser.add_argument("--profunditat", type=int, default=3,
                        help="quants nivells baixa --arbre (per defecte 3)")
    parser.add_argument("--max-pagines", type=int,
                        default=config.get("adg", "max_pagines",
                                           default=images.MAX_PAGES_PER_RUN),
                        help="sostre de pàgines per execució; pujar-lo ha de ser una "
                             "decisió teva i no un descuit")
    parser.add_argument("--assaig", action="store_true",
                        help="no demana res: només diu què demanaria")
    args = parser.parse_args(argv)

    session = Session(dry_run=args.assaig)
    try:
        if args.parroquia:
            cmd_parish(session, args.parroquia)
        elif args.node:
            cmd_node(session, args.node)
        elif args.arbre:
            cmd_tree(session, args.arbre, args.profunditat)
        elif args.serie:
            cmd_series(session, args.serie)
        elif args.llibre:
            cmd_book(session, args.llibre)
        elif args.pagines:
            cmd_pages(session, args.pagines, args.resolucio)
        elif args.baixa:
            cmd_download(session, args.baixa, args.pagina, args.resolucio,
                         args.out, args.max_pagines)
    except (ValueError, RuntimeError) as exc:
        print(f"\n{exc}")
        return 1
    finally:
        print(f"\n[{session.stats()}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
