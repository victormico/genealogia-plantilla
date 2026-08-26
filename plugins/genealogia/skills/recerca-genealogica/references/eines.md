# Les eines, i quan toca cadascuna

Vénen del paquet `genealogia-tools`. S'instal·len, no es copien:

```bash
pip install -r requirements.txt
```

Cap no porta cap nom, cap xref ni cap poble escrit al codi: tot surt del
`config.yaml`. Si has d'escriure un nom, un xref o un poble, va allí —i
`python -m tools.lint --generic` falla si algú se salta la regla.

## El cicle

### 1. Baixar l'arbre de FamilySearch

```bash
python -m tools.fs.session --whoami   # que la sessió va
python -m tools.fs.probe              # quins punts de l'API responen
python -m tools.fs.fetch              # cache/pedigree.json
```

Es pot repetir: les respostes queden a la memòria cau, i regenerar informes no
costa cap petició.

### 2. Veure què hi ha per fer

```bash
python -m tools.match --live   # reports/match-report.md — qui és qui
python -m tools.frontier       # reports/frontier.md — a qui atacar, per ordre
python -m tools.worklist       # reports/worklist.md — agrupat per arxiu
python -m tools.estat          # reports/estat.md — els comptadors
```

**`frontier.md` és el que has de llegir primer.** Cada persona hi surt amb un
estat:

| Estat | Vol dir |
| --- | --- |
| `ready` | FamilySearch ja en sap els pares: la feina és comprovar-ho i incorporar-ho |
| `stuck` | FamilySearch també s'hi atura: cal anar a l'arxiu |
| `unknown` | no s'ha pogut comprovar, ni en viu ni amb la instantània |
| `unlinked` | encara no s'ha trobat a FamilySearch |

L'ordre suma la generació (com més a prop de l'arrel, més amunt), si hi ha
documents que el corroborin, i **la puntuació d'accés de l'arxiu** (0-5). Aquesta
darrera és un judici sobre **com de fàcil és arribar als llibres**, no sobre la
família: una parròquia amb els llibres en línia val la pena d'atacar abans que
una que demana escriure una carta i esperar.

### 3. Generar propostes

```bash
python -m tools.research --top 5 --depth 2   # reports/candidates-<data>.yaml
```

**Ací s'atura tot sol.** Obre el `.yaml`, compara'l amb `frontier.md`, i decideix
persona per persona: `accept: true` o `accept: false`. Una proposta amb
`accept: false` no es llença —va a `reports/descartades/`, i `tools.research` la
llegeix igual, per no tornar a proposar algú que ja s'ha dit que no.

### 4. Acceptar

```bash
python -m tools.apply reports/candidates-<data>.yaml
```

Només escriu el que has acceptat, i només **afegint** línies. Mira el `git diff`:
ha de dir exactament el que esperaves.

### 5. Comprovar

```bash
python -m tools.lint            # tot
python -m tools.lint --rutes    # les rutes de Fonts/ que cita el GEDCOM
python -m tools.lint --xifres   # les xifres escrites a mà als .md
python -m tools.lint --xrefs    # que cap xref no anomeni algú altre
python -m tools.lint --informes # que els informes no estiguin desfasats
python -m tools.tests.test_gedcom  # el round-trip del teu arbre
```

**`test_gedcom` és la important.** Comprova que llegir el teu arbre i tornar-lo a
escriure dona un fitxer idèntic byte a byte. Si això no passa, no et fiïs de res
més: vol dir que qualsevol escriptura et remenarà el fitxer sencer i el `git diff`
deixarà de servir per veure què has canviat.

## Els arxius sense API

### `tools/apv/` — l'índex diocesà de València

```bash
python -m tools.apv.coverage    # què cobreix cada parròquia, gratis
python -m tools.apv.verify      # el pla, sense fer cap petició
python -m tools.apv.verify --quota          # quantes consultes queden
python -m tools.apv.verify --top 5 --fetch  # consultar-ne cinc de veres
```

`verify` va **de baix a dalt**: recorre els avantpassats per número de Sosa, del
més proper cap amunt, i salta qui ja té una font d'arxiu. Si un graó falla, els de
damunt no valen una consulta.

Tres coses que fa i que val la pena saber:

- **Creua amb el que ja s'ha demanat.** Una cerca que va tornar buida no deixa cap
  transcripció, o siga que sense això es tornaria a proposar demà. Un zero és una
  troballa.
- **Sap quins llibres són perduts** (`apv: llibres_perduts:`). On el llibre de
  matrimonis no existeix, l'índex només dona el pare de l'interessat i cap imatge
  per demanar després: allí el bateig va primer, perquè val set persones i el
  matrimoni una.
- **Eixampla la forquilla quan l'any és estimat.** ±2 al voltant d'una data llegida
  d'una partida, ±8 o més al voltant d'un any que s'ha calculat.

> Que l'índex tingui l'apunt **no vol dir que el llibre tingui la partida.** Amb el
> número de registre a la mà, el manuscrit es demana a l'arxiu diocesà.

### `tools/adg/` — el catàleg de l'Arxiu Diocesà de Girona

```bash
python -m tools.adg.browse --cerca <poble>
python -m tools.adg.browse --baixa <id> --pagina <n>
```

Pregunta el catàleg i no porta cap poble escrit. El sostre de pàgines per
execució (`adg: max_pagines:`) hi és a posta: l'arxiu permet còpies per a ús
personal i cobra drets per republicar, i la diferència entre les dues coses és si
et baixes les vuit pàgines que et fan falta o el llibre sencer. Pujar-lo ha de ser
una decisió, no un descuit.

## L'Obsidian

Obre la carpeta arrel com a vault i ja està: enllaços, *embeds* de seccions i
taules són tot del nucli. Cap connector no és un requisit.

Si vols veure l'arbre al connector Charted Roots, cal una passa que no es pot
saltar:

```bash
python -m tools.obsidian     # escriu «<arbre> (Obsidian).ged»
```

i importes **aquest** fitxer, no el canònic. El canònic declara la seva forma de
lloc a la capçalera i és posicional —una coma inicial vol dir «això no és cap
aldea»—; el connector ignora el `FORM` i parteix per comes, cosa que trenca el
frontmatter i converteix un codi postal en una jurisdicció.
