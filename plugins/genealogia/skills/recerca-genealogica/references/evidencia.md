# Proves que es contradiuen

## Les tres classificacions, que són independents

**El document**

| | |
| --- | --- |
| Original | el document tal com es va crear: la partida al llibre, l'acta al registre |
| Derivat | una còpia, una transcripció, un índex, una traducció |
| D'autor | algú que ha raonat a partir d'altres fonts: una genealogia publicada, un arbre en línia |

**La informació**

| | |
| --- | --- |
| Primària | qui ho va dir hi era, i ho va dir a prop del fet |
| Secundària | ho va sentir a dir, o ho recordava molt després |
| Indeterminada | no se sap qui ho va declarar |

**La prova**

| | |
| --- | --- |
| Directa | respon la pregunta tota sola |
| Indirecta | hi porta combinada amb una altra |
| Negativa | l'absència, quan la cobertura és certa |

Les tres són independents, i confondre-les és l'error més comú. **Un original pot
dur informació secundària**: una partida de defunció és original per a la mort i
secundària per al naixement, perquè qui ho va declarar no era present quan va
néixer.

## Qui ho va declarar

La pregunta que decideix gairebé tot: **qui li ho va dir al rector o al
funcionari, i com ho sabia?**

- Un pare que declara un bateig sap qui són els pares.
- Un veí que declara una defunció potser no sap l'edat del mort.
- Una edat en un matrimoni la va dir l'interessat, i sovint arrodonida.
- Un padrí que signa dona fe que hi era, no de les dates.

## L'ordre de fiabilitat

1. Original + primària + directa
2. Original + primària + indirecta
3. Original + secundària
4. Derivat d'un original conegut
5. D'autor **amb** les fonts adjuntes
6. D'autor **sense** fonts — que és el cas de la majoria d'arbres en línia

**Es pesa, no es compta.** Cinc arbres en línia que diuen el mateix solen ser un
arbre copiat cinc vegades: no és corroboració, és propagació. Corrobora una font
que **no podia** haver copiat l'altra.

## Com es resol un conflicte

1. **Anomena el fet**, exactament. No «qui era l'X» sinó «l'any de naixement de
   l'X».
2. **Fes la taula**: què diu cada font, quina classe és, qui ho va declarar.
3. **Busca l'explicació abans de triar.** La majoria de conflictes no són
   mentides: una edat arrodonida, un calendari diferent, un nom de fonts que no
   és el que gastava, dues persones del mateix nom al mateix poble, un llogaret
   que registrava a la parròquia mare.
4. **Si una explicació ho resol tot, escriu-la.** Si no, digues quina font pesa
   més i **per què**, en termes de les tres classificacions.
5. **Si no es resol, digues-ho.** Un conflicte obert i escrit val més que una
   conclusió falsa i neta.

## El que hem dit i era fals

Cada cas porta aquesta secció, i és la que fa que el fitxer serveixi de res:

```markdown
## El que hem dit i era fals

- ~~«El bateig ha de ser a la parròquia de Z»~~ — **fals.** Z no va tenir llibres
  propis fins al 1755; abans batejaven a la parròquia mare. Dit el DD-MM-AAAA,
  desmentit el DD-MM-AAAA per la taula de cobertura de l'arxiu.
```

**Això no s'esborra mai.** Sense la llista, l'error torna: algú el redescobreix,
el torna a escriure, i es paguen les mateixes consultes una altra vegada.

## Dues persones o una

Abans de fusionar dues persones que semblen la mateixa:

- **Podien coincidir en el temps i en l'espai?** Comprova que no es contradiguin
  amb un fet datat de l'altra.
- **Els noms es repeteixen dins d'una família.** Un avi i un nét amb el mateix nom
  al mateix poble és el cas normal, no l'excepció.
- **`tools.lint --duplicacio`** ensenya passatges idèntics entre fitxers, que és
  sovint el primer senyal que dues fitxes parlen de la mateixa persona —o que
  algú ha copiat un raonament en lloc d'encastar-lo.
