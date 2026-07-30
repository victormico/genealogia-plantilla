# Fonts de casa

El que **no ve de cap arxiu**: el que la família recorda, el que la família ha
escrit i el que la família ha guardat. Cap d'aquestes coses no és font primària,
però **diuen on és el document que sí que ho seria**, i alguna diu coses que cap
arxiu no dirà mai.

| Carpeta | Què hi ha | Classe de prova |
| --- | --- | --- |
| `Testimonis/` | memòria oral, transcrita i **datada** | memòria; val el que val qui la conta |
| `Memòria escrita/` | històries familiars escrites, amb quadres | **secundària, però documentada** |
| `Quadres/` | arbres i genealogies fetes a casa o publicades | secundària |
| `Fotografies/` | retrats identificats | context |

## Testimonis/

Sempre amb **qui ho diu, quan ho va dir i de qui ho va sentir**, perquè és el que
permet valorar-ho: dues filles que conten el mateix per separat no és el mateix que
una néta que ho ha sentit contar.

L'àudio original es queda fora del repositori; hi entra la transcripció literal.

Si transcrius amb un model automàtic, **passa-hi més d'un model i compara**. Un
model petit es menja els noms propis rars —justament els que resolen els casos— i
ho fa sense avisar, deixant una frase que sona bé.

## Memòria escrita/

Treballs de recerca, memòries, cartes. Poden ser molt bons, i tenen dues trampes:

**Els quadres fets a mà es contradiuen entre ells.** La mateixa persona amb dues
dates de naixement en dos quadres del mateix autor és habitual. Cada data vol
comprovació.

**El text val tant com els quadres.** Les dades que no van al requadre sinó a la
prosa —un ofici, una parròquia concreta— són les que no s'extrauen a la primera
lectura, i sovint són les úniques que no estan al GEDCOM encara.

I la pregunta que s'ha de contestar per escrit: **això és una segona font que
corrobora el que ja tens, o és l'original d'on ho vas treure?** Si la banda d'una
família ve d'un treball i el treball és l'única cosa que la sosté, no s'hi val a
comptar-lo dues vegades.

## Quadres/

Arbres de casa i genealogies publicades. Val la pena apuntar de cada un:

- **si té aparell**: si cita partides i protocols, o si no cita res. Un quadre sense
  aparell pot ser correcte i no es pot comprovar.
- **quina part és de la teva branca** i quina no.
- **quin `SOUR` és al GEDCOM**, si hi és.
- **quantes generacions sosté tot sol.** Si la resposta és «nou», escriu-ho ben gros:
  és el punt on l'arbre s'aguanta en una sola font secundària.

## Fotografies/

Retrats identificats. No sostenen filiacions; hi són perquè posen cara a una banda
de la família.

**Un avís que val per a tota la carpeta.** Un fitxer que es diu com una persona pot
ser un retrat o pot ser l'escaneig del manuscrit del seu bateig. Passa, i pot estar
mal classificat mesos. **Un nom de fitxer que és només un nom de persona no diu de
quina classe de document es tracta**: si trobes res sense transcripció al costat,
obre'l abans de suposar què és.

## Condicions d'ús

Tot això és **material de la família**, i sovint **obra de persones vives**. No es
publica ni se'n reprodueixen fragments fora de casa, i quan se'n transcriu alguna
cosa, l'autoria s'anomena. `Fonts/` està al `.gitignore` tret dels `.md`, i és el
que ho garanteix — però un `.md` amb una transcripció sencera d'obra d'algú altre
també es publica si publiques el repositori. Pensa-hi abans, no després.
