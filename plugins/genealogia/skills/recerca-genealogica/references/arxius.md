# Els arxius, i com saber quin toca

**Aquest fitxer no anomena cap poble a posta.** Els pobles, els arxius, les
puntuacions i els enllaços són al `config.yaml` del repositori, que és l'únic
lloc on viuen. Ací hi ha com llegir-los i com afegir-ne.

## On és cada cosa

```yaml
regions:            # quins pobles són de cada regió
  <regio>: [poble, poble, ...]

regions_per_defecte:  # si el poble no surt enlloc, què buscar dins del lloc
  <text>: <regio>

guies:              # què s'ha de saber de l'arxiu de cada regió
  <regio>:
    title: ...
    puntuacio: 0-5  # com de fàcil és arribar als llibres
    nota: ...       # una línia, la que surt al frontier
    blurb: ...      # el paràgraf que surt al worklist
    links: {...}
    extra: ...

arxius:             # excepcions per poble
  <Poble>:
    puntuacio: 0-5
    nota: ...
```

Ho llegeix `tools.config.archive_hint(poble, lloc)`: primer mira si el poble és
una excepció, i si no, cau a la guia de la seva regió.

## La puntuació és sobre l'accés, no sobre la família

De 0 a 5, i entra al rànquing de `tools.frontier`. Vol dir **com de fàcil és
arribar als llibres**:

| | |
| --- | --- |
| 5 | digitalitzat i consultable en línia de franc, o filmat a FamilySearch |
| 3 | hi ha un índex en línia, però els llibres es demanen a part |
| 2 | cal anar-hi, o escriure i esperar |
| 1 | un arxiu estranger, o amb accés difícil |
| 0 | no ho sabem encara |

Una parròquia amb els llibres en línia val la pena d'atacar abans que una que
demana una carta i tres setmanes, **hi haja qui hi haja a dins**. La família no
entra en aquest número.

> **Un poble que no és a cap llista val zero i baixa al final del rànquing**, i
> això sol ser un error i no una dada. Fins al 26-08-2026 hi havia dues llistes
> de pobles escrites a mà, una a `frontier.py` i una a `worklist.py`, i ja no
> deien el mateix: 17 pobles que una coneixia, l'altra els puntuava a zero.
> Quan vegis algú puntuat a zero, la primera pregunta és si el poble és al
> `config.yaml`.

## Afegir un arxiu nou

1. **Posa els pobles** a `regions:`. Els accents i les majúscules no importen.
2. **Escriu la guia**: `title`, `puntuacio`, `nota` (una línia), `blurb` (el
   paràgraf que surt al `worklist.md`), `links` i `extra`.
3. **Digues què cobreix**, si té índex: la taula de `tools/apv/coverage.py` és
   parròquia → sagrament → anys, i és el que fa que una consulta impossible no es
   pagui.
4. **Comprova-ho**: `python -m tools.worklist` i mira si la gent hi cau on toca.

El que ha d'anar a la guia és **el que estalvia un viatge o una quota**: què està
filmat i què no, fins a quin any arriba, si demana ser soci, si hi ha embargament
legal, i sobretot les trampes.

## Les trampes que val la pena escriure

Aquestes surten un cop i un altre, i a cada arxiu prenen una forma:

- **El llogaret sense llibres propis.** Un poble que no va tenir parròquia fins al
  segle XIX té els bateigs antics dins dels *quinque libri* de la parròquia mare.
  Cercar-lo pel seu nom no dona res. Això va a `apv: parroquies:`, amb `abans_de:`
  i `llavors:`, perquè és una regla d'any i no de lloc.
- **La diòcesi que no existia.** Si el bisbat es va crear tard, el material
  anterior pot estar catalogat sota el bisbat veí. Si una cerca no dona res, prova
  amb els d'abans.
- **L'embargament.** Els índexs solen tallar a 100 anys per protecció de dades.
  No és un error de l'eina: és la llei, i la resposta és que no.
- **Les grafies.** El mateix poble escrit de tres maneres i el mateix cognom de
  cinc. `tools/normalize.py` en porta les equivalències; si en trobes una de nova,
  va allí.
- **Els padrons d'habitants.** Quan n'hi ha, són molt bons per situar una família
  entre dos sagraments: hi surt tota la casa amb edats, cosa que confirma
  filiacions que un bateig sol no demostra.
