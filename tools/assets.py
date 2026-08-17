"""Reading copies of the scans, and a manifest for the ones we do not commit.

`Fonts/` is meant to hold binaries no `git clone` recovers -- see its own
`00 LLEGIU-ME.md` -- and that only stays true if what is missing is provable.
This closes that hole without Git LFS, and it also fixes the more common
problem: a scan straight off a phone or a flatbed is usually far bigger than
anything that needs to be *read*. A 7000px-wide JPEG with 4:4:4 chroma, or a
lossless PNG crop of a photograph, reads exactly as well at 2000px and a
fraction of the size.

So three classes, deliberately:

  reading copies  `*_lectura.jpg`, <=2000 px, committed. What you actually read.
  irreplaceable   oral testimony, family photographs, anything nobody else can
                  re-issue. Committed as they are.
  masters         full-size scans and archive PDFs. Not committed; re-fetchable
                  from the archive reference recorded in the transcription.

The suffix is explicit rather than replacing the file in place, for two
reasons: `imatges:` links in frontmatter name a file, so a silent
`.png` -> `.jpg` conversion breaks them; and a filename that does not say what
class of thing it is invites exactly the mistake it is meant to prevent -- a
manuscript scan filed under a name that looks like a portrait.

    python -m tools.assets --manifest    # write Fonts/MANIFEST.sha256
    python -m tools.assets --check       # verify what is on disk against it
    python -m tools.assets --lectura     # make missing reading copies
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "Fonts"
MANIFEST = FONTS / "MANIFEST.sha256"

IMAGES = {".jpg", ".jpeg", ".png"}
# Everything a manifest row is worth having for. `.svg` is deliberately absent:
# an SVG export of a scanned page is text pretending to be a picture, and
# `Fonts/00 LLEGIU-ME.md` is the place to say why, not this list.
TRACKED = IMAGES | {".pdf", ".ogg", ".xlsx", ".docx", ".eml", ".txt", ".html"}

LECTURA = "_lectura.jpg"
MAX_WIDTH = 2000
QUALITY = 3

# FamilySearch arks and DGS/film numbers, as written in the transcriptions.
_ARK = re.compile(r"ark:/61903/[0-9]:[0-9]:[A-Z0-9-]+")
_DGS = re.compile(r"\b(?:DGS|grup|film)\s*([0-9]{6,9})\b", re.IGNORECASE)


def assets() -> list[Path]:
    """Every binary under Fonts/, excluding nested vault metadata and our own copies."""
    return sorted(
        p
        for p in FONTS.rglob("*")
        if p.is_file()
        and ".obsidian" not in p.parts
        and p.suffix.lower() in TRACKED
        and not p.name.endswith(LECTURA)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def origins() -> dict[str, list[str]]:
    """Map each asset basename to the arks named by the notes that mention it.

    Best-effort and stated as such: it reads the transcription that references the
    file and lifts any ark or DGS number from it. The transcription remains the
    authority -- this only saves opening it to find out where a scan came from.
    """
    out: dict[str, list[str]] = {}
    names = {p.name: p for p in assets()}
    for note in FONTS.rglob("*.md"):
        if ".obsidian" in note.parts:
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        found = sorted(set(_ARK.findall(text))) + [
            f"DGS {n}" for n in sorted(set(_DGS.findall(text)))
        ]
        if not found:
            continue
        for name in names:
            if name in text or Path(name).stem in text:
                out.setdefault(name, [])
                for reference in found:
                    if reference not in out[name]:
                        out[name].append(reference)
    return out


def write_manifest() -> tuple[Path, int, int]:
    where = origins()
    rows = []
    total = 0
    for path in assets():
        size = path.stat().st_size
        total += size
        relative = path.relative_to(ROOT)
        rows.append((str(relative), size, sha256(path), where.get(path.name, [])))

    lines = [
        "# Inventari dels fitxers binaris de Fonts/",
        "#",
        "# Generat per `python -m tools.assets --manifest`. Comprovat amb `--check`.",
        "#",
        "# Els originals a mida completa NO són al repositori. Això és el que permet",
        "# saber si en falta cap i tornar-lo a demanar: mida, sha256 i, quan la",
        "# transcripció el diu, l'ark o el DGS d'on va eixir. La transcripció mana;",
        "# l'ark d'ací només estalvia obrir-la.",
        "#",
        f"# {len(rows)} fitxers, {total / 1048576:.1f} MB.",
        "",
    ]
    for relative, size, digest, references in rows:
        lines.append(f"{digest}  {size:>9}  {relative}")
        for reference in references:
            lines.append(f"#   {reference}")

    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return MANIFEST, len(rows), total


def read_manifest() -> dict[str, tuple[str, int]]:
    if not MANIFEST.exists():
        return {}
    out: dict[str, tuple[str, int]] = {}
    for line in MANIFEST.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        digest, size, relative = line.split(None, 2)
        out[relative] = (digest, int(size))
    return out


def check() -> int:
    """Compare the manifest with what is on disk. Missing and altered both fail."""
    recorded = read_manifest()
    if not recorded:
        print(f"no hi ha {MANIFEST.relative_to(ROOT)}; passa --manifest primer")
        return 1

    on_disk = {str(p.relative_to(ROOT)): p for p in assets()}
    missing = sorted(set(recorded) - set(on_disk))
    added = sorted(set(on_disk) - set(recorded))
    changed = []
    for relative, path in sorted(on_disk.items()):
        if relative not in recorded:
            continue
        digest, size = recorded[relative]
        if path.stat().st_size != size or sha256(path) != digest:
            changed.append(relative)

    for relative in missing:
        print(f"FALTA     {relative}")
    for relative in changed:
        print(f"CANVIAT   {relative}")
    for relative in added:
        print(f"nou       {relative}")

    print(
        f"{len(recorded)} a l'inventari, {len(missing)} que falten, "
        f"{len(changed)} canviats, {len(added)} nous"
    )
    return 1 if missing or changed else 0


def reading_copy(path: Path) -> Path:
    return path.with_name(path.stem + LECTURA)


def make_reading_copies(force: bool = False) -> tuple[int, int, int]:
    """Re-encode every image to a committed reading copy. Returns (made, skipped, saved)."""
    made = skipped = 0
    before = after = 0
    for path in assets():
        if path.suffix.lower() not in IMAGES:
            continue
        out = reading_copy(path)
        if out.exists() and not force:
            skipped += 1
            before += path.stat().st_size
            after += out.stat().st_size
            continue
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                "-i", str(path),
                "-vf", f"scale='min({MAX_WIDTH},iw)':-2",
                "-q:v", str(QUALITY),
                str(out),
            ],
            check=True,
        )
        made += 1
        before += path.stat().st_size
        after += out.stat().st_size
        print(
            f"  {out.relative_to(FONTS)}  "
            f"{path.stat().st_size / 1048576:.1f} -> {out.stat().st_size / 1048576:.1f} MB"
        )
    return made, skipped, before - after


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", action="store_true", help="write the manifest")
    parser.add_argument("--check", action="store_true", help="verify against the manifest")
    parser.add_argument("--lectura", action="store_true", help="make reading copies")
    parser.add_argument("--force", action="store_true", help="remake existing copies")
    args = parser.parse_args(argv)

    if not any((args.manifest, args.check, args.lectura)):
        parser.error("tria --manifest, --check o --lectura")

    status = 0
    if args.lectura:
        made, skipped, saved = make_reading_copies(args.force)
        print(
            f"{made} còpies de lectura noves, {skipped} que ja hi eren, "
            f"{saved / 1048576:.1f} MB estalviats"
        )
    if args.manifest:
        path, count, total = write_manifest()
        print(f"{count} fitxers, {total / 1048576:.1f} MB -> {path.relative_to(ROOT)}")
    if args.check:
        status |= check()
    return status


if __name__ == "__main__":
    sys.exit(main())
