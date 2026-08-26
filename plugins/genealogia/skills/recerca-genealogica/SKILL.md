---
name: recerca-genealogica
description: Recerca genealògica amb mètode. Fes-lo servir quan es parli de genealogia, arbre genealògic, avantpassats, GEDCOM, Ancestris, FamilySearch, número de Sosa, bateig, partida, quinque libri, arxiu parroquial o diocesà, registre civil, o quan algú vulgui buscar d'on ve una persona, resoldre una filiació dubtosa, citar un document o decidir a quin arxiu anar.
---

# Recerca genealògica

Aquest skill fa dues coses alhora: porta el **mètode** —el Genealogical Proof
Standard, l'anàlisi de proves, les citacions— i porta la **manera concreta de
treballar d'aquest repositori**, que és el que fa que el mètode no es quedi en
teoria.

Deriva de [claude-family-history-research-skill](https://github.com/emaynard/claude-family-history-research-skill)
d'Erik Maynard (MIT). Vegeu `ATRIBUCIO.md`.

## La regla que va abans que totes

**No cerquis res fins que hi hagi un pla.** Quan algú anomeni un avantpassat i
demani ajuda, no obris el navegador ni facis cap cerca: pregunta què se'n sap ja,
acorda quina és la pregunta, i escriu el pla. Executar-lo és una decisió seva i
posterior.

Això no és prudència abstracta. Ací té una forma mecànica i una raó comptable:
els arxius tenen quotes, les consultes es paguen amb temps o amb diners, i **un
zero és una troballa** que no s'ha de pagar dues vegades. `tools.apv.verify`
comprova cada consulta que proposa contra el registre de les ja fetes precisament
per això.

I té una segona forma, que és la que protegeix les dades:

> **Cap eina no toca el GEDCOM pel seu compte.** Proposen, tu decideixes, i només
> llavors s'escriu. Les eines només **afegeixen** línies —mai no n'esborren ni en
> reescriuen cap—, o siga que un `git diff` sempre ensenya exactament què ha
> canviat.

Quan facis servir les eines, no te la saltis mai: generar una proposta és
gratis, acceptar-la no.

## Per on comences, segons què et demanin

| Et demanen | Vés a |
| --- | --- |
| «d'on venia el meu rebesavi?» | el pla de recerca, més avall, i `references/eines.md` |
| «a quin arxiu he d'anar?» | `references/arxius.md` — i el `config.yaml`, que és qui ho sap |
| «aquestes dues fonts es contradiuen» | `references/evidencia.md` |
| «com cito això?» | `references/citacions.md` |
| «puc donar això per provat?» | `references/gps.md` |
| «on desa això, i com ho escric?» | `references/fonts.md` |

## El pla de recerca

1. **Què se sap ja**, i **d'on ho sabem**. Un nom que ve de l'arbre d'un
   desconegut a FamilySearch no és el mateix que un que ve d'una partida. Si no
   se sap d'on ve, això ja és la primera troballa.
2. **La pregunta**, una i concreta. «De qui era fill l'X» es pot respondre;
   «investigar els X» no.
3. **Qui hi entra**: la persona, el cònjuge, els pares si es coneixen, i els
   veïns i padrins —el principi FAN (*Family, Associates, Neighbors*), que és el
   que desencalla els casos on la persona sola no surt enlloc.
4. **Quins documents ho podrien dir**, i **quin arxiu els té**. Ací és on entra
   el `config.yaml`: quina parròquia hauria registrat el sagrament, quins anys
   cobreix i com de fàcil és arribar-hi.
5. **Per ordre de barat.** Primer el que és gratis (preguntar a casa, un índex en
   línia, comprovar la cobertura), després el que costa una consulta, i al final
   el que demana escriure a un arxiu i esperar setmanes.
6. **Què comptarà com a resposta.** Digues-ho abans de començar, perquè si no,
   qualsevol cosa que aparegui semblarà que hi val.

El pla surt a un **fitxer de cas** (`assets/templates/cas.md`), que és on viu el
raonament. No a una transcripció, no a una fitxa de persona, no a un informe.

## Les tres regles d'aquest repositori

Aquestes tres no són estil: cadascuna ve d'un error que ja ha passat.

**1. Una transcripció no argumenta.** Diu què posa el document i prou. Si cal
explicar què vol dir, hi ha un punter al fitxer de cas. El 27-07-2026 es va
escriure un raonament dins d'una transcripció, i quan una dada nova el va
desmentir va caldre corregir la mateixa frase falsa **en cinc llocs alhora**.

**2. El raonament viu en un sol lloc**, i és el fitxer de cas. Un cas és una
pregunta oberta, amb el que està establert, **el que hem dit i era fals** (tatxat,
no esborrat) i què queda per mirar. Un cas net és un cas que ningú no ha tornat a
mirar.

**3. Una fitxa de persona no pot contenir cap número que una eina puga calcular.**
Ni naixement, ni defunció, ni pares, ni Sosa: això és del GEDCOM. Així no pot
derivar, perquè no repeteix res.

## El cicle de treball

```
fs.fetch  →  match  →  frontier  →  worklist  →  research  →  [tu decideixes]  →  apply  →  lint
```

Detall a `references/eines.md`. El resum:

- **`frontier`** diu **a qui val la pena atacar i per quin ordre**, barrejant la
  generació, si FamilySearch ja en sap els pares i com d'accessible és l'arxiu.
- **`worklist`** agrupa per arxiu, per a qui només es pot resoldre anant-hi.
- **`research`** escriu propostes a un `.yaml` que **tu obres i decideixes**.
- **`apply`** escriu al GEDCOM només el que has acceptat.
- **`lint`** comprova que res no s'ha desfasat: rutes, xifres, xrefs, informes.

## Privacitat

Dues regles, i totes dues es fan complir amb eines:

- **Res de persones vives a cap sistema d'IA**, ni ací ni enlloc. Els índexs
  d'arxiu ja tenen embargaments legals (sovint 100 anys) i `tools.apv.coverage`
  els respecta: si et diu que no, la resposta és que no.
- **El que no es pot tornar a demanar a cap arxiu entra al repositori** —memòria
  de casa, fotografies, testimonis— i **els escanejos a mida completa, no**.
  `tools.lint --privacitat` és qui ho comprova.

Quan generis text que anirà a un fitxer del repositori, escriu-hi el raonament i
les fonts, no dades de gent viva.

## Els errors que costen més

Cada un d'aquests ja ha passat i ha costat temps o consultes:

- **Cercar amb el nom escrit com el diem nosaltres** i no com l'escriu l'índex.
  `nom=eustaqui` per a un home que l'índex diu Enric: zero resultats i una
  consulta gastada. Cerca per cognom i lloc, no per nom de pila.
- **Confondre el lloc de naixement amb la parròquia.** Un llogaret sense llibres
  propis té els bateigs antics dins dels de la parròquia mare. Cercar-lo pel seu
  nom no dona res, i el zero sembla que digui «no hi és».
- **Prendre una edat declarada per una data.** «Tenia 24 anys» en un matrimoni el
  va dir ell o ho va calcular el rector. Val per acotar la cerca, no per omplir
  el `BIRT`.
- **Confondre una citació amb una línia esgotada.** Que un document anomeni algú
  *com a avi* prova que existia i no diu res d'on venia. Qui no té pares a
  l'arbre no està mai acabat.
- **Estrènyer la forquilla d'anys al voltant d'un any inventat.** Un «1775» rodó
  sol ser una estimació de FamilySearch; ±2 al voltant seu és un zero quasi
  garantit, que després es llegeix com «no és a l'índex».
