# On va cada cosa, i per què

`Fonts/` va per **dos eixos**, i barrejar-los és el que porta a fitxers de 280
línies que fan tres feines alhora.

**Per arxiu** — determina *com aconsegueixes el document*: quins llibres estan
filmats, quins no, com s'hi busca i a qui s'escriu. Cada carpeta d'arxiu té el seu
`00 LLEGIU-ME.md` amb la taula de cobertura, que és el que estalvia viatges.

**Per classe de document** — determina *quanta confiança mereix i quant durarà
escrit*:

| Carpeta | Què hi va | Quant dura |
| --- | --- | --- |
| `<Arxiu>/` | transcripcions, amb les captures | un fet: no canvia mai |
| `Família/` | el que **no ve de cap arxiu**: memòria, quadres de casa, fotos | no es pot tornar a demanar enlloc |
| `Casos/` | **un fitxer per pregunta oberta: ací viu el raonament** | es revisa sovint |
| `Recerques/` | diaris de cerca, datats | no es revisen mai |
| `Informes/` | el que s'envia a la família | es regenera |

## Les tres regles

**1. Una transcripció no argumenta.** Diu què posa el document i apunta al fitxer
de cas. Barrejar-ho va fer que una frase falsa visqués en cinc llocs alhora i
calgués corregir-la cinc vegades.

**2. El raonament viu en un sol lloc**: el fitxer de cas. Un cas té el que està
establert amb qui ho diu i quina classe de prova és, **el que hem dit i era fals**
—tatxat, mai esborrat—, què queda obert per ordre de barat, i quin efecte té al
GEDCOM. Que hi hagi errors tatxats és el senyal que el cas s'ha revisat; **un cas
net és un cas que ningú no ha tornat a mirar**.

**3. Una fitxa de persona no pot contenir cap número que una eina puga calcular.**
Ni naixement, ni defunció, ni pares, ni Sosa: això és del GEDCOM. Una fitxa és el
judici que no és cap pregunta oberta i que cap eina no calcula. I el raonament d'un
cas **no es copia, s'encasta** amb `![[Cas#secció]]`; `tools.lint --frontmatter`
comprova que la secció encara existeix.

## Com es diuen les fitxes de persona

`I00098 Nom.md`, amb el xref al davant. No és burocràcia: entre unes quantes
centenes de persones hi ha desenes de col·lisions de nom, i el xref les fa úniques
i sobreviu a qualsevol canvi de nom al programa d'edició.

## El GEDCOM cita rutes d'ací

Moure un fitxer de `Fonts/` trenca les citacions del GEDCOM **sense avisar**. Es
reparen amb `tools.correct`, i la comprovació és `python -m tools.lint --rutes`.

## Què entra al repositori i què no

Hi entren les transcripcions, les **còpies de lectura** dels escanejos i tot
`Família/`, perquè **això és el que no es pot tornar a demanar a cap arxiu**. Els
escanejos a mida completa queden fora —viuen a l'ordinador que els va fotografiar—
i `Fonts/MANIFEST.sha256` és el que permet saber si en falta cap:

```bash
python -m tools.assets --check      # contra el MANIFEST
python -m tools.assets --lectura    # refà les còpies de lectura que falten
```

## Classificar una font, abans d'escriure-la

Tres preguntes, i les tres es contesten per separat (vegeu `evidencia.md`):

1. **El document**: original, derivat o d'autor?
2. **La informació**: primària (qui ho sabia de primera mà, en el moment) o
   secundària?
3. **La prova**: directa (respon la pregunta), indirecta (hi porta combinada amb
   una altra) o negativa (l'absència, que també diu coses)?

Un original pot dur informació secundària: una partida de defunció és original
per a la mort i secundària per al naixement, perquè qui la va declarar no hi era.
