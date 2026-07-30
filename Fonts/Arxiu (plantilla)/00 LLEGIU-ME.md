# Nom de l'arxiu

> **Aquesta carpeta és un model.** Copia-la, posa-li el nom de l'arxiu de veritat i
> esborra aquest avís. Se'n fa una **la primera vegada que en tens un document**, no
> abans.

Una línia dient què és aquest arxiu i quina banda de la família cobreix.

| Fitxer | Persona | Què és |
| --- | --- | --- |
| | | |

## Com s'hi consulta

- **En línia / en persona / per correu**, i l'adreça.
- **Si demana cita, quota de soci o carta**, digues-ho aquí. És el que fa decidir
  entre aquest arxiu i un altre.
- **Si compta consultes**, quantes i cada quant. Un sostre diari canvia l'ordre en
  què es fan les coses.

## Si l'arxiu és un catàleg amb API i imatges a S3

Alguns arxius diocesans publiquen el catàleg com una aplicació web (sovint un
`iframe` amb un frontend que es penja) però al darrere tenen una **API senzilla en
JSON/PHP** que és molt més fiable que fer clics. Val la pena mirar-ho abans de
donar per fet que cal navegar a mà: obre les eines de xarxa del navegador mentre
navegues el catàleg i mira quines crides fa.

El patró sol tindre quatre nivells:

| Crida (forma típica) | Què torna |
| --- | --- |
| llista arrel (p. ex. `?parroquies=true`) | totes les parròquies/fons, cada una amb un resum |
| node per `id` | els fills d'un node de l'arbre (sagrament → sèrie → llibre) |
| llista de documents d'una sèrie | els llibres que hi ha dins |
| fitxa d'un document per `id` | metadades del llibre concret |

De la fitxa d'un document, el camp que decideix si es pot llegir des de casa sol
dir-se alguna cosa com `bucket` o `digitalitzat`:

| Valor | Significa |
| --- | --- |
| `true` | **està digitalitzat** i les imatges són accessibles en línia |
| `false` | no hi ha imatges, encara que el catàleg descrigui el contingut |

**Comprova sempre aquest camp abans de donar per fet que un llibre es pot mirar.**
La fitxa del document existeix igual estigui digitalitzat o no.

**Les imatges solen viure a un bucket S3 amb un patró previsible**:

```
https://<bucket>.s3.<regio>.amazonaws.com/<id>/<id>_<pagina>_<res>.jpg
                                              pagina: sol anar amb zeros davant (01, 02…)
                                              res:    l = baixa · m = mitjana · h = alta
```

**El número de pàgina sense els zeros davant sol tornar 403** encara que el llibre
existeixi: no ho confonguis amb «no digitalitzat». Una pàgina que va més enllà del
final del llibre també torna 403, cosa que serveix per trobar-ne la fi per bisecció
si el catàleg no diu quantes pàgines té.

**Fes-ne un ús de persona que consulta, no d'una màquina que buida el fons**:
aquestes crides serveixen per situar-se i per baixar les pàgines concretes que et
calen, no per descarregar el catàleg o els llibres sencers. Mira les condicions
d'ús de l'arxiu (sota) abans de descarregar res.

> Si l'arxiu que estàs documentant és el **Diocesà de Girona**, això ja està fet:
> `tools/adg/` parla amb el seu catàleg i baixa les pàgines. Vegeu el README.
> Per a un altre arxiu amb aquest mateix patró, `tools/adg/` és el model a copiar
> — el que canvia són les quatre URL i els noms dels camps.

## Cobertura

**Aquesta taula és la que estalvia viatges.** L'arxiu sol publicar-la; transcriure-la
una vegada és la millor hora que hi invertiràs, perquè evita anar a buscar una
partida que no és allà.

| Parròquia / registre | Bateigs | Matrimonis | Defuncions | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

Els **forats** són el que importa, no els extrems. Que els bateigs vagen «del 1616
al 1902» sovint vol dir que falten vint anys pel mig, i és justament on cau qui
busques. Apunta els forats explícitament.

I una cosa que canvia l'estratègia sencera: **quan el bateig cau en un forat, prova
el matrimoni.** Una fitxa de matrimoni dona els pares i sovint els quatre avis de qui
busques, o siga que per a filiació val igual o més, i als llibres de matrimonis els
falten menys anys.

## Compte amb això

- **Que l'índex tinga l'apunt no vol dir que el llibre tinga la partida.** Un índex
  dona llibre, foli i número; el manuscrit es demana a part, i de vegades resulta que
  el foli no hi és.
- **Els llogarets no tenen llibres propis.** Un poble que no va ser parròquia fins al
  segle XIX té els bateigs antics dins dels de la parròquia mare, i cercar-los pel seu
  nom no dona res.
- **Els embargaments legals.** La protecció de dades tanca els anys recents, i el
  límit no és el mateix per a bateigs que per a defuncions.

## Condicions d'ús

**Apunta-les la primera vegada que hi baixes res**, que és quan les acabes de llegir.
Diguen què deixen fer amb les imatges i què no: ús personal, republicació, descàrrega
massiva. No són iguals a tots els arxius, i suposar-ho és com es fan les coses
malament de bona fe.
