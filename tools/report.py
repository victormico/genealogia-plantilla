"""Writing a generated report, with the guard that was missing.

`reports/frontier.md` and `reports/worklist.md` are the kind of file that can
end up committed corrupted: the generator's own stdout summary pasted over the
first lines, so `frontier.md` began

    112 dead-ends: 20 ready, 38 stuck, 54 unlinked
    878 ancestors importable from FamilySearch
    wrote reports/frontier.md
    r |

-- the real document resuming mid-table-row. It happens because a tool both
prints a summary and writes the file, and somebody runs
`python -m tools.frontier > reports/frontier.md`.

Nothing detects it if nothing reads a committed generated file. One line of
guard would: a generated report always starts with `# `, so refusing to
overwrite a file that does not, and refusing to write text that does not,
catches the redirect the moment it happens.
"""

from __future__ import annotations

from pathlib import Path


class Refused(Exception):
    """A write that would have produced or overwritten a corrupted report."""


def write(path: str | Path, text: str, force: bool = False) -> Path:
    """Write a generated markdown report, refusing anything shell-mangled.

    `force` is for the one legitimate case: repairing a file that is already
    corrupted. It still checks the text being written.
    """
    out = Path(path)

    if not text.startswith("# "):
        first = text.split("\n", 1)[0][:60]
        raise Refused(
            f"{out.name}: el text generat no comença per «# » sinó per {first!r}. "
            "Això és el que passa quan la sortida de l'eina es redirigeix al fitxer."
        )

    if out.exists() and not force:
        existing = out.read_text(encoding="utf-8")
        if existing and not existing.startswith("# "):
            first = existing.split("\n", 1)[0][:60]
            raise Refused(
                f"{out.name}: el fitxer que hi ha comença per {first!r}, no per «# ». "
                "Sembla corromput; torna a generar-lo amb force=True si n'estàs segur."
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
