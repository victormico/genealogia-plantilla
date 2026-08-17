# Front de recerca

**Generat per `python -m tools.frontier`. No s'edita a mà.**

FamilySearch: no s'ha pogut consultar (ni `cache/pedigree.json` ni `reports/frontier-fs.json`). Executa `python -m tools.fs.fetch` per refer-la.

Persones de l'arbre principal sense pares: **9** de 18.

| Situació | Persones | Què cal fer |
| --- | --- | --- |
| A punt d'importar | **0** | FamilySearch ja en sap els pares |
| Encallades | **0** | FamilySearch també s'atura aquí: cal arxiu |
| Sense comprovar | **1** | Cal `tools.fs.fetch` per saber-ho |
| Sense enllaçar | **8** | Primer cal trobar-les a FamilySearch |

Per damunt de les 0 primeres hi ha **0 avantpassats nous** disponibles a FamilySearch. L'arbre passaria de 18 a unes 18 persones.

L'ordre suma: generació (com més a prop de qui arrenca l'arbre, més amunt), ser
avantpassat directe i no col·lateral, que FamilySearch ja tingui la feina
feta, tenir lloc i any de naixement per poder cercar, la cobertura de
l'arxiu corresponent i els documents que ja tenim a `Fonts/`.

---

## A punt d'importar (0)

Aquestes no necessiten cap recerca: els pares ja són a FamilySearch. Cal
revisar-los i incorporar-los.

## Encallades també a FamilySearch (0)

Enllaçades amb FamilySearch, però allà tampoc no en saben els pares. Aquestes són la recerca de veritat: cal anar als llibres parroquials.

| Persona | G | Naixement | Lloc | Documents | Arxiu on buscar |
| --- | --- | --- | --- | --- | --- |

## Sense comprovar a FamilySearch (1)

Enllaçades amb FamilySearch, però ni el pedigrí ni la instantània diuen si allà ja en saben els pares. Torna a executar `python -m tools.fs.fetch` amb credencials per saber-ho.

| Persona | G | Naixement | Lloc | Documents | Arxiu on buscar |
| --- | --- | --- | --- | --- | --- |
| @I00016@ Rita VIVES ALCARAZ | 5 | 14 FEB 1878 | ontinyent | — | Arxiu Parroquial de Santa Maria d'Ontinyent, quinque libri des del 1616. L'índex diocesà en línia dona referències; els llibres, no. |

## Sense enllaçar amb FamilySearch (8)

Encara no s'han trobat a FamilySearch. El primer pas és cercar-les-hi; després ja es veurà si hi ha ascendència.

| Persona | G | Naixement | Lloc | Documents | Arxiu on buscar |
| --- | --- | --- | --- | --- | --- |
| @I00005@ Rosa PUJALT ALMENAR | 3 | 2 AUG 1945 | terrades | — | Arxiu Diocesà de Girona: uns 4.500 llibres sacramentals digitalitzats i consultables en línia, amb cobertura fins al 1920. |
| @I00007@ Empar BELLVER CARDONER | 3 | 30 NOV 1948 | fontanars dels alforins | — | Arxiu Parroquial d'Ontinyent: Fontanars era part del terme d'Ontinyent i els bateigs antics són dins dels seus quinque libri, no en llibres propis. |
| @I00009@ Dolors MASCARELL NOGUÉS | 4 | 28 MAY 1915 | llado | — | Arxiu Diocesà de Girona: uns 4.500 llibres sacramentals digitalitzats i consultables en línia, amb cobertura fins al 1920. |
| @I00011@ Maria TORRENT ESPÍ | 4 | 17 OCT 1912 | ontinyent | — | Arxiu Parroquial de Santa Maria d'Ontinyent, quinque libri des del 1616. L'índex diocesà en línia dona referències; els llibres, no. |
| @I00012@ Joan FIGUEROLA CASELLES | 5 | 11 SEP 1880 | llado | — | Arxiu Diocesà de Girona: uns 4.500 llibres sacramentals digitalitzats i consultables en línia, amb cobertura fins al 1920. |
| @I00013@ Francesca VILADOMAT PONT | 5 | 23 DEC 1884 | sant pere pescador | — | Arxiu Diocesà de Girona: uns 4.500 llibres sacramentals digitalitzats i consultables en línia, amb cobertura fins al 1920. |
| @I00017@ Tomàs SEGARRA FERRANDIS | 6 | 27 MAR 1845 | ontinyent | — | Arxiu Parroquial de Santa Maria d'Ontinyent, quinque libri des del 1616. L'índex diocesà en línia dona referències; els llibres, no. |
| @I00018@ Àngela MOLINS RIPOLL | 6 | 6 JUN 1849 | fontanars dels alforins | — | Arxiu Parroquial d'Ontinyent: Fontanars era part del terme d'Ontinyent i els bateigs antics són dins dels seus quinque libri, no en llibres propis. |

