# Fonts

Tot el que sosté l'arbre. **Només els `.md` són al repositori**: el `.gitignore`
deixa fora escanejos, fotos, PDF i àudio, que pesen i que sovint no es poden
republicar. Convé tenir-ne una còpia de seguretat a part, perquè el que hi ha
aquí no el recupera cap `git clone`.

Aquesta carpeta ve **buida i amb les instruccions**. Les carpetes que hi trobes
són l'estructura; el que has d'anar posant tu és el contingut.

## Com està organitzat, i per què

Hi ha **dos eixos**, i barrejar-los és el que porta a un fitxer de 280 línies que
fa tres feines a la vegada.

**Per arxiu**, que és el que determina *com aconsegueixes el document*: quins
llibres estan filmats, quins no, com s'hi busca i a qui s'escriu. Cada carpeta
d'arxiu té el seu `00 LLEGIU-ME.md` amb la taula de cobertura, que és el que
estalvia viatges. En crees una la primera vegada que en tens un document, no
abans: una carpeta buida amb el nom d'un arxiu no diu res.

**Per classe de document**, que és el que determina *quanta confiança mereix i
quant de temps durarà escrit*. Una transcripció és un fet i no canvia mai; un
raonament es revisa; un diari de recerca es data i no es toca més.

| Carpeta | Què hi va | Com es manté |
| --- | --- | --- |
| `Arxiu (plantilla)/` | **model de carpeta d'arxiu.** Copia-la i posa-li el nom de l'arxiu | una per arxiu |
| `Registre Civil/` | certificats civils, que a Espanya arrenquen el 1871 | creix |
| `Família/` | el que **no ve de cap arxiu**: memòria, quadres de casa, fotos | vegeu el seu LLEGIU-ME |
| `Casos/` | **un fitxer per pregunta oberta.** Ací viu el raonament | es revisa sovint |
| `Recerques/` | diaris de cerca, **datats i no revisats mai** | només s'hi afig |
| `Informes/` | el que s'envia a la família | es regenera |

## Les quatre regles que fan que això funcione

**1. Una transcripció no argumenta.** Diu què posa el document i prou. Si algú vol
saber què vol dir, hi ha un punter al fitxer de cas. Això no és pedanteria: quan
un raonament s'escriu dins d'una transcripció i una dada nova el desmenteix,
resulta que la mateixa frase falsa viu en cinc llocs alhora i s'ha de corregir
cinc vegades. Passa de seguida i costa una tarda.

**2. El raonament viu en un sol lloc**, i és el fitxer de cas. Un cas és una
pregunta —«de qui era fill l'X»— que va acumulant proves de fonts diferents
durant mesos. No és un document ni un arxiu, i necessita casa pròpia.

**3. Es diu com s'ha obtingut cada cosa, no només d'on ve.** Dues dades del mateix
llibre parroquial no valen igual si d'una en tenim la imatge i de l'altra només
les notes de qui hi va anar: la primera es pot rellegir i la segona no. Per això
val la pena tenir una carpeta per a les **consultes en persona sense imatge**, amb
**qui ho va llegir** apuntat.

**4. Els diaris de recerca no es revisen.** `Recerques/` diu què es va mirar un dia
concret i què s'hi va trobar, **inclòs el que no hi era**. Un «això no és a
FamilySearch, comprovat llibre per llibre» val tant com una partida, i si es
reescriu es perd la data que el fa creïble.

## Convenció de noms

`Persona_Sagrament_Any.md` per a les partides, amb minúscula-majúscula com el nom
real i accents inclosos. Res de sufixos d'arxiu: la carpeta ja diu de quin arxiu
és.

Els noms no es retrofiten en massa; s'arreglen quan un fitxer es mou per un altre
motiu. El cas típic és un accent que no lliga entre el `.md` i el `.pdf` del
mateix document, i que el GEDCOM ja ha copiat.

## El GEDCOM cita rutes d'ací

Quan adjuntes un document a una persona, el GEDCOM es queda la ruta: dins d'un
`2 FILE` sota `OBJE`, o dins del text d'una `NOTE` o una `SOUR`. **Moure un fitxer
les trenca**, i no hi ha res que avise.

Es reparen amb `tools.correct` i un `find`/`replace` per línia, que és exactament
per a què serveix. La comprovació és aquesta, i val la pena passar-la **després de
cada trasllat**:

```bash
python3 - <<'EOF'
import os, re
from tools.config import tree_path
from tools.gedcom.lines import GedcomFile

g = GedcomFile(tree_path())
bad = ok = 0
for i, raw in enumerate(g.raw):
    for m in re.finditer(r'Fonts/.*?\.(?:md|pdf|jpg|jpeg|png|svg|txt|xlsx|ogg)', raw):
        if os.path.exists(m.group()):
            ok += 1
        else:
            print(f'TRENCADA l.{i+1}: {m.group()}')
            bad += 1
print(f'{ok} bones, {bad} trencades')
EOF
```

El que importa és el segon número. El primer creix cada vegada que s'adjunta un
document **o que una `NOTE` nova cita una transcripció**, i **si baixa sense que
s'haja esborrat res, alguna cosa s'ha mogut**. Apunta't el número d'avui en aquest
fitxer, i així el dia que baixe ho sabràs.

> **Això NO cobreix les línies que citen una carpeta** en lloc d'un fitxer, perquè
> el regex acaba en una extensió i les salta. Es troben amb
> `grep -n "Fonts/" el-teu-arbre.ged` i mirant les que no acaben en extensió.

> **Aquí hi va haver dues trampes, i val la pena saber-les perquè totes dues venen
> de tenir espais i accents als noms de les carpetes.**
>
> **La primera**: el regex era `Fonts/[^\s"]*`, que **talla al primer espai**. Amb
> carpetes que es diuen «Arxiu Parroquial València», això vol dir que no
> comprovava gairebé res: donava «cap trencada» mentre n'hi havia quatre, i totes
> justament de la carpeta amb espais al nom.
>
> **La segona**: agafar de `Fonts/` fins al final de línia arregla els espais però
> falla quan **una línia porta dues rutes**, i n'hi ha. Donava un fals positiu.
>
> La versió de dalt fa `.*?` **no cobdiciós fins a l'extensió**, que resol les dues
> coses: aguanta espais i troba totes les rutes de cada línia.
>
> Moralitat: **una comprovació que sempre passa és sospitosa, i una que acaba de
> canviar val la pena provar-la trencant una ruta a posta.**

## Arxius on has d'escriure i encara no tens res

Val la pena mantenir una taula d'aquests aquí mateix: quin arxiu, què s'hi demana,
per quina persona, i l'adreça. No tenen carpeta perquè encara no hi ha cap
document; quan arribe el primer, se'ls en fa una.

| Arxiu | Què s'hi demana | Per a qui |
| --- | --- | --- |
| | | |

## Condicions d'ús

**Cada arxiu té les seves, i no són iguals.** N'hi ha que prohibeixen la descàrrega
massiva i la republicació; n'hi ha que permeten expressament la còpia per a ús
personal. Apunta-les al `00 LLEGIU-ME.md` de la carpeta de cada arxiu **la primera
vegada que hi baixes res**, que és quan les acabes de llegir.

El `.gitignore` deixa fora tot el que no és `.md`, i és el que garanteix que això
no es publica per accident. Que continue així.
