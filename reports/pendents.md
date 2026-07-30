# Pendents

> Aquest fitxer **no el genera cap eina**: s'escriu a mà i s'ha d'anar mantenint. La
> resta de `reports/` es regenera, i **el que diguen els generats mana sobre el que
> diga aquest**. Quan comences, esborra el que hi ha i escriu el teu estat.

Estat a **DD de mes de AAAA**.
**N persones, N famílies, la generació N completa de N.**

## Per on continuar

1. …
2. …
3. …

## Casos oberts

| Cas | Qui bloqueja | On és el raonament |
| --- | --- | --- |
| | | `Fonts/Casos/…md` |

## Propostes que esperen decisió

| Fitxer | Què proposa | Per què no s'ha decidit |
| --- | --- | --- |
| | | |

---

## Dues coses que val la pena tenir escrites aquí des del primer dia

### ⚠ `accept: true` és una decisió, no una prova que s'haja executat

`tools.archive` es fia de `accept: true` per moure una proposta a `aplicades/`, on la
capçalera diu que aquestes entrades **ja són al GEDCOM**. Si marques `accept: true` i
no passes el fitxer per `tools.apply` o `tools.correct`, l'arxivador se l'endurà igual
i et quedarà una mentida difícil de descobrir, perquè ningú no torna a mirar el que ja
està arxivat.

**Abans d'arxivar, comprova al GEDCOM que la dada hi és**, no al `.yaml`. Un
`git diff` o un `grep` al fitxer, no una relectura de la teva pròpia decisió.

### Obre el fitxer amb Ancestris després de cada escriptura

Per dues raons: perquè confirmes que carrega bé, i perquè és Ancestris qui recalcula
la numeració de Sosa (`_SOSADABOVILLE`). Cap eina d'aquí no la toca.
