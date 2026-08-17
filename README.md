# Genealogia — eines i estructura

Eines per ampliar un arbre genealògic amb FamilySearch i amb els arxius que no
tenen API, i **una manera d'organitzar les fonts** que aguanta anys de recerca.

Ve buit i amb un arbre d'exemple. No hi ha cap dada de ningú.

La idea que ho ordena tot: **cap eina no toca el GEDCOM pel seu compte.** Proposen,
tu decideixes, i només llavors s'escriu. I les eines només **afegeixen** línies —mai
no n'esborren ni en reescriuen cap—, així que un `git diff` sempre ensenya
exactament què ha canviat.

## Què hi ha

| | |
| --- | --- |
| `config.yaml` | **l'únic fitxer que has d'editar per començar.** Quin és el teu arbre, quins són els teus arxius |
| `.env.sample` | les credencials que fan falta. Copia'l a `.env`, que no entra al repositori |
| `exemple.ged` | un arbre inventat de 18 persones, per veure què fa cada eina abans de posar-hi les teves dades |
| `tools/` | les eines. Cap no porta cap nom ni cap poble escrit al codi |
| `Fonts/` | l'estructura per a les fonts, amb les instruccions. Comença per **`Fonts/00 LLEGIU-ME.md`** |
| `reports/` | on surten els informes. Comença per **`reports/pendents.md`** |
| `.github/workflows/` | la CI: proves a cada PR, informes refets a cada merge, recerca setmanal opcional |

## Comença aquí

### 1. L'entorn

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Prova que tot va, contra l'arbre d'exemple i sense tocar la xarxa:

```bash
.venv/bin/python -m tools.tests.test_gedcom       # el fitxer es reescriu byte a byte igual
.venv/bin/python -m tools.tests.test_render       # noms, dates i llocs
.venv/bin/python -m tools.tests.test_estat        # les generacions i els comptadors
.venv/bin/python -m tools.tests.test_frontmatter  # el vocabulari de les fitxes .md
.venv/bin/python -m tools.tests.test_obsidian     # l'exportació per a Charted Roots
.venv/bin/python -m tools.tests.test_frontier     # ready/stuck/unknown/unlinked
.venv/bin/python -m tools.tests.test_apv          # 30 proves de l'índex diocesà
.venv/bin/python -m tools.tests.test_adg          # 20 proves del catàleg de Girona
.venv/bin/python -m tools.frontier --top 5        # qui bloqueja l'arbre d'exemple
```

**La primera és la important.** Quan hi posis el teu arbre, comprovarà que llegir-lo
i tornar-lo a escriure dona un fitxer idèntic. Si això no passa, no et fies de res
més: vol dir que qualsevol escriptura et remenarà el fitxer sencer i el `git diff`
deixarà de servir per veure què has canviat.

### 2. El teu arbre

Exporta'l en GEDCOM d'Ancestris —o del programa que facis servir—, desa'l a l'arrel
del repositori i posa'n el nom al `config.yaml`:

```yaml
arbre: El_meu_arbre.ged
```

Torna a passar `tools.tests.test_gedcom`. Ara comprovarà el teu fitxer també.

> **Per què Ancestris.** Aquestes eines estan fetes contra el GEDCOM que escriu
> Ancestris: BOM, salts de línia LF, cognoms en majúscules, llocs en sis nivells i
> l'etiqueta `_SOSADABOVILLE` per als números de Sosa. Amb un altre programa
> funcionaran, però la prova de round-trip és el que t'ho dirà de veres, i és la
> primera cosa que has de mirar.

### 3. Els teus arxius

Al `config.yaml` hi ha les regions d'un arbre català i valencià, com a exemple que
funciona. **Esborra el que no et serveixi i posa-hi els teus pobles**: és el que fa
que `tools.worklist` agrupe la gent per l'arxiu on cal anar a buscar-la, i que
`tools.frontier` sàpiga que una parròquia amb els llibres en línia val la pena
d'atacar abans que una que demana escriure una carta.

### 4. FamilySearch

Les credencials van a `.env`, que és al `.gitignore`. Copia la mostra i omple-la:

```bash
cp .env.sample .env
```

És el teu compte de FamilySearch de sempre, el que fas servir al navegador: no hi ha
clau d'API que et puguis demanar. Les altres eines no volen credencials — `.env.sample`
diu quines i per què.

I al `config.yaml`, el PID de la persona per on vols arrencar. Obre el seu perfil a
FamilySearch i copia el codi de la URL, que té la forma `XXXX-XXX`:

```yaml
familysearch:
  arrel: XXXX-XXX
```

Comprova que la sessió funciona:

```bash
.venv/bin/python -m tools.fs.session --whoami
.venv/bin/python -m tools.fs.probe        # quins punts de l'API responen
```

## El cicle de treball

### Baixar l'arbre de FamilySearch

```bash
.venv/bin/python -m tools.fs.fetch
```

Desa el resultat a `cache/pedigree.json`. Es pot repetir quan vulguis: les respostes
queden a la memòria cau, així que regenerar informes no costa cap petició.

### Veure què hi ha per fer

```bash
.venv/bin/python -m tools.match --live    # reports/match-report.md
.venv/bin/python -m tools.frontier        # reports/frontier.md
.venv/bin/python -m tools.worklist        # reports/worklist.md
.venv/bin/python -m tools.estat           # reports/estat.md
```

- **`match-report.md`** — qui és qui entre el teu arbre i FamilySearch.
- **`frontier.md`** — a qui val la pena atacar, per ordre, i a quin arxiu. Cada
  persona hi surt `ready` (FamilySearch ja en sap els pares), `stuck`
  (FamilySearch també s'hi atura), `unknown` (no s'ha pogut comprovar, ni amb
  pedigrí en viu ni amb la instantània de sota) o `unlinked` (encara no s'ha
  trobat a FamilySearch).
- **`worklist.md`** — enllaços de cerca per a les persones que només es poden
  resoldre anant als arxius.
- **`estat.md`** — els comptadors de l'arbre (persones, famílies, generacions
  d'avantpassats), calculats i no retipiats. `tools.lint --xifres` compara
  aquests números amb el que digui el `README.md` a mà, si hi repeteixes cap.

Cada cop que `tools.frontier` es pot connectar a FamilySearch amb credencials
(`cache/pedigree.json`), desa a `reports/frontier-fs.json` una instantània de
només els fets que l'informe imprimeix. Els dies que no hi ha credencials —a
la CI, per exemple— `frontier.md` i `worklist.md` es refan igualment a partir
d'aquesta instantània, en lloc de tractar tothom amb `_FSFTID` com si
FamilySearch també s'hi haguera encallat.

### Generar propostes i acceptar-les

```bash
.venv/bin/python -m tools.research --top 5 --depth 2
```

Escriu `reports/candidates-<data>.yaml`. Obre'l, compara'l amb `reports/frontier.md`,
i per cada proposta posa `accept: true`, `false` o `null`. Després:

```bash
.venv/bin/python -m tools.apply reports/candidates-<data>.yaml           # ensenya el diff
.venv/bin/python -m tools.apply reports/candidates-<data>.yaml --write   # escriu
```

En escriure, la versió anterior queda com a `<arbre>_<data>-<hora>.ged`, igual que fa
Ancestris. Revisa-ho amb `git diff` i **obre el fitxer amb Ancestris** per confirmar
que carrega bé; ell recalcula la numeració de Sosa.

### Treure de la vista el que ja està fet

```bash
.venv/bin/python -m tools.archive           # ensenya què mouria
.venv/bin/python -m tools.archive --write   # ho mou
```

Una entrada amb `accept: true` ja és a l'arbre i no la tornaràs a mirar, però es queda
al fitxer i tapa les tres que sí que has de decidir. Això les mou a
`reports/aplicades/` amb els comentaris inclosos.

De passada tanca un parany: un fitxer que és tot `accept: true` té la mateixa pinta
que un que està a punt de passar, i tornar-lo a passar per `tools.apply` insereix cada
línia una segona vegada.

### Corregir el que ja hi és

`tools.apply` només afig. Per canviar una línia que ja hi és, `tools.correct`, que
demana la línia **verbatim** i es nega a endevinar. És l'única eina que pot esborrar
línies, i té guards per a això: no et deixarà esborrar un pare i deixar-hi els fills
penjant, ni esborrar un `CHAN`, ni un registre sencer.

## Mantenir-ho net: `tools/lint.py` i companyia

| | |
| --- | --- |
| `tools.estat` | recompta persones, famílies, generacions d'avantpassats i rutes de `Fonts/` citades pel GEDCOM. Escriu `reports/estat.md` |
| `tools.lint` | comprovacions que fallen, sense escriure mai cap prosa |
| `tools.frontmatter` | valida el vocabulari `.md` de `Fonts/`: `tipus`, `classe`, `confiança`, `xrefs` |
| `tools.assets` | inventari amb sha256 dels binaris de `Fonts/` i còpies de lectura reduïdes |
| `tools.obsidian` | exporta una còpia del GEDCOM per a l'extensió obsidian-charted-roots |

Un número copiat a mà a una prosa se't desfasa la primera vegada que l'arbre canvia, i
pot desfasar-se **dues vegades a la mateixa prosa** sense que ningú se n'adoni, perquè
res compara les dues mencions entre elles. `tools.estat` calcula els números un sol cop
i `tools.lint --xifres` compara qualsevol fila `| Etiqueta | número |` del teu
`README.md` que faci servir la mateixa etiqueta que `reports/estat.md` — si en poses
cap, no cal fer-hi res més.

```bash
.venv/bin/python -m tools.lint                # totes les comprovacions
.venv/bin/python -m tools.lint --xifres        # xifres desfasades al README
.venv/bin/python -m tools.lint --rutes         # rutes de Fonts/ que el GEDCOM cita i no existeixen
.venv/bin/python -m tools.lint --xrefs         # un @I00001@ que anomena algú altre al costat
.venv/bin/python -m tools.lint --cr-id         # cap fitxa no arma cap connector d'Obsidian
.venv/bin/python -m tools.lint --frontmatter   # el vocabulari de tools.frontmatter, sencer
.venv/bin/python -m tools.lint --privacitat    # binaris seguits sota Fonts/, i el repositori és privat?
.venv/bin/python -m tools.lint --duplicacio    # reports/duplicacio.md: text idèntic en diversos fitxers
.venv/bin/python -m tools.lint --informes      # frontier.md i worklist.md concorden amb el GEDCOM
```

Si fas servir les fitxes `.md` de `Fonts/` amb Obsidian, `tools.frontmatter` és el que
en manté el vocabulari coherent: quin `tipus` de fitxa és, de quina `classe` és la font
—**un índex no és una segona lectura independent del manuscrit**—, i quins `xrefs`
declara. Un document que declara qui hi surt es pren **al peu de la lletra**: sense
això, `tools.frontier` ha d'endevinar-ho pel nom del fitxer, i endevinar-ho és el que
pot acreditar un avantpassat amb el bateig del seu propi net perquè comparteixen
cognom. Quins arxius acceptes al camp `arxiu:` és cosa teva: `config.yaml`, a
`frontmatter: arxius:`, ve buit i, mentre ho estigui, `tools.frontmatter --check`
accepta qualsevol valor.

`tools.assets` és per a qui guarda escanejos i fotografies dins de `Fonts/`: separa els
originals (irreemplaçables o refetibles d'un arxiu) de còpies de lectura reduïdes que sí
que val la pena tenir al repositori. **Aquesta plantilla, tal com ve, només versiona els
`.md`** —mira-ho al `.gitignore` i a `Fonts/00 LLEGIU-ME.md`—, així que l'eina només et
fa falta si decideixes relaxar aquesta política per als teus propis binaris.

`tools.obsidian` no toca l'arbre canònic: escriu una còpia amb els llocs replegats a una
cadena separada per comes, perquè el connector d'Obsidian **obsidian-charted-roots**
encara no entén el format de sis nivells que fa servir Ancestris i, sense això, pot
escriure fitxes amb un `PLAC` que no és YAML vàlid.

## L'índex diocesà de València: `tools/apv/`

Només et fa falta si investigues a la diòcesi de València. **És la font amb el sostre
més baix: quinze consultes al dia**, i és l'arxiu qui les compta.

```bash
.venv/bin/python -m tools.apv.verify              # el pla, sense demanar res
.venv/bin/python -m tools.apv.verify --quota      # quantes consultes queden avui
.venv/bin/python -m tools.apv.verify --fetch --top 3
```

Verifica **de baix a dalt**: des de l'última persona que un document confirma cap
amunt. Si un graó falla, els de damunt no valen una consulta. On acaba el terreny
documentat es diu al `config.yaml`, a `apv: terra_documentada:`.

Tres coses que val la pena saber abans de tocar-ho:

- **El sostre de 15/dia és al codi, amb comptador persistent** a `cache/apv-quota.json`,
  datat, i **el compte de l'arxiu manda sobre el nostre**. Un sostre que es reinicia amb
  el procés no és un sostre.
- **Pregunta primer la cobertura, que és gratis.** `tools/apv/coverage.py` sap quins anys
  té indexats cada parròquia. Quan el bateig cau en un forat, **el camí és el matrimoni**:
  una fitxa de matrimoni dona els pares i els quatre avis de qui busques.
- **Cloudflare hi té un repte gestionat**, o siga que des d'un script pelat es rep un 403.
  Al navegador va. `tools.apv.verify` imprimeix totes les URL per a això, i `parse.py`
  llegeix la pàgina desada. Una cerca feta al navegador **gasta consulta i el comptador
  no la veu**, així que s'apunta: `--record "què has buscat"`.

## El catàleg de l'Arxiu Diocesà de Girona: `tools/adg/`

Només et fa falta si investigues al bisbat de Girona. La pàgina del «Quadre de
classificació» és una aplicació que es penja; al darrere hi ha quatre crides JSON que
van bé, i les imatges es baixen sense passar pel visor. **No hi ha res a configurar**:
l'eina pregunta el catàleg i no porta cap poble escrit.

```bash
.venv/bin/python -m tools.adg.browse --parroquia vilafant   # troba la parròquia
.venv/bin/python -m tools.adg.browse --arbre 500            # les sèries que té
.venv/bin/python -m tools.adg.browse --serie 1203193        # els llibres de la sèrie
.venv/bin/python -m tools.adg.browse --llibre 14233         # es pot llegir des de casa?
.venv/bin/python -m tools.adg.browse --pagines 14233        # quantes pàgines té
.venv/bin/python -m tools.adg.browse --baixa 14233 --pagina 73
```

`--assaig` assaja qualsevol d'aquestes ordres sense tocar la xarxa.

Quatre coses que val la pena saber abans de tocar-ho:

- **`bucket` és el camp que ho decideix tot.** El catàleg descriu llibres de què no té
  imatges, o siga que trobar la fitxa no prova que el puguis mirar. `--llibre` t'ho diu
  i distingeix els dos casos, que demanen coses molt diferents: «consulta física a la
  sala» és un viatge a Girona, i `bucket: false` és un llibre que potser ja no existeix.
- **No et quedis amb la sèrie «Llibres originals».** És el parany que fa perdre mig dia:
  una parròquia amb els llibres originals des del 1918 pot tenir «Còpies, extractes i
  certificats» que cobreixen els anys 1880, i **cada certificat és un extracte literal
  de la partida**, amb la filiació sencera dels dos contraents. Un llibre cremat
  sobreviu en els certificats que se'n van expedir. Per això `--arbre` llista **totes**
  les sèries.
- **El número de pàgina va amb dos dígits** (`_07_`, no `_7_`), i a partir de la 100 amb
  tres (`_100_`, no `_0100_`). Les dues errades tornen 403, i el final del llibre també,
  de manera que equivocar-se sembla exactament «aquest llibre no està digitalitzat».
  `--pagines` troba el final per bisecció amb peticions HEAD, que és barat.
- **`fills` menteix.** La llista de parròquies dona a cada node un camp `fills` que
  sembla la llista de fills i no ho és: Adri diu `fills: [31]` i té quatre fills, i 31
  és l'id **d'una altra parròquia**. L'eina no el llegeix mai i sempre pregunta.

```bash
.venv/bin/python -m tools.tests.test_adg     # 20 proves, sense xarxa
```

**Les imatges no es publiquen.** Van a `cache/`, que és al `.gitignore`; quan una
partida val la pena, el que entra al repositori és **la transcripció en `.md`**, no
l'escaneig. L'arxiu permet còpies per a ús personal i cobra drets per republicar.

## Coses que val la pena saber

**Els duplicats només es detecten per `_FSFTID`.** Abans d'acceptar uns pares, mira si ja
hi són. `tools.apply` reutilitza una persona si la proposta i el fitxer comparteixen
identificador de FamilySearch, i prou; tothom que ha entrat des d'un arxiu parroquial no
en té cap. En un poble on tothom es diu igual, dues branques arriben a la mateixa parella
més sovint del que sembla, i llavors el que toca no és `tools.apply` sinó un
`tools.correct` que penja la persona de la família que ja existeix.

**Els llocs no s'inventen.** Quan s'importa una persona, l'eina reutilitza la grafia i les
coordenades que ja hi ha al teu fitxer. Un poble que el teu arbre no coneix es deixa en
blanc i s'avisa, en lloc d'heretar les coordenades de la capital de la província —que és
un error que et mou un avantpassat quaranta quilòmetres i no es veu.

**Sobre les condicions d'ús.** Les de FamilySearch prohibeixen la descàrrega massiva i el
rastreig del web. Aquestes eines es queden al costat bo: sessió autenticada amb el teu
compte, recerca personal del teu arbre, ritme molt per sota del límit publicat, memòria
cau per no repetir peticions, i res que es redistribueixi. **No és un recol·lector de
dades i no s'ha de convertir en un.**

**L'inici de sessió és fràgil.** Fa servir la clau d'aplicació d'un tercer, com tots els
programes lliures que parlen amb FamilySearch, i s'espatlla cada sis o dotze mesos quan
canvien alguna cosa. Si un dia falla, entra amb el navegador, copia el testimoni d'una
petició a l'API i passa'l amb `--token`.

**`_SOSADABOVILLE` no es toca.** Ancestris el regenera en desar. El que no arregla és que
n'escriu **duplicats**: la mateixa persona acaba amb la mateixa numeració repetida, i cada
desat n'afig una còpia més. Cap eina d'aquí no les llegeix i no fan mal a res, però és una
fuita lenta. Si algun dia molesta, es netegen amb un `tools.correct` que hi deixe una sola
línia per valor; el que no s'ha de fer és esperar que Ancestris ho faça.

## Llicència

MIT — vegeu `LICENSE`. Les eines són teves per fer-hi el que vulguis; el que baixis dels
arxius es regeix per les condicions de cada arxiu, que no són les mateixes.
