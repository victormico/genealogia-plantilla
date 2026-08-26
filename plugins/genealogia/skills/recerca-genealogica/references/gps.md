# El Genealogical Proof Standard

Els cinc elements. Una conclusió no és provada si en falta cap.

## 1. Recerca raonablement exhaustiva

Prou fonts perquè el fet es pugui sostenir, no totes les fonts del món. En
concret: **s'han mirat els documents que podrien contradir-ho?** Una recerca que
només busca confirmació no és exhaustiva per molts documents que aplegui.

Ací això té una forma concreta: mentre una persona no tingui pares a l'arbre,
la seva línia no està acabada, **per molts documents que l'anomenin**. Que quatre
fitxes el citin *com a avi* prova que existia i no diu res d'on venia.

## 2. Citacions completes i exactes

De cada font: què és, on és, i com s'hi arriba. Vegeu `citacions.md`. Una
citació no és un adorn: és el que permet que algú altre —o tu d'ací tres anys—
comprovi que la conclusió aguanta.

## 3. Anàlisi i correlació

Classificar cada font (original/derivat, primària/secundària, directa/indirecta) i
mirar què diuen **juntes**. La prova indirecta és la que resol els casos difícils:
cap document no diu la resposta, però tres documents junts només deixen una
possibilitat.

## 4. Resolució dels conflictes

Cap conflicte no es deixa sense explicar. Si dues fonts es contradiuen, o s'explica
per què una és millor, o es diu obertament que la cosa no està resolta. Vegeu
`evidencia.md`.

## 5. Conclusió raonada i escrita

Escrita, i que es pugui seguir. Si el raonament no es pot escriure, no està fet.
Ací s'escriu al fitxer de cas.

## Els graus, i com s'anomenen

| Grau | Vol dir | Al GEDCOM |
| --- | --- | --- |
| **Provat** | els cinc elements, sense conflictes oberts | s'escriu |
| **Probable** | bona prova, algun buit conegut | s'escriu, i el cas diu què falta |
| **Possible** | una hipòtesi amb alguna cosa a favor | **no s'escriu**: viu al cas |
| **No provat** | no hi ha prou | no s'escriu |
| **Desmentit** | la prova diu que no | al cas, tatxat |

**La regla operativa:** si el grau no és almenys «probable», la proposta es marca
`accept: false` i va a `reports/descartades/`. No es llença —`tools.research` la
llegeix per no tornar a proposar el mateix— però no entra al GEDCOM.

## La prova negativa

Que un document **no** hi sigui també és una troballa, i sovint la més barata. Si
l'índex cobreix aquella parròquia i aquells anys i la persona no hi surt, això és
evidència que no va néixer allí. Val, però, només si:

- **la cobertura és certa** (`tools.apv.coverage` ho diu abans de gastar res), i
- **la cerca era prou ampla** —una forquilla estreta al voltant d'un any inventat
  torna zero per motius que no tenen res a veure amb la família.

I un zero només val alguna cosa si **no es paga dues vegades**: es registra, i
`tools.apv.verify` el creua abans de tornar a proposar la mateixa consulta.
