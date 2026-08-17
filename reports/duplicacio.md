# Duplicació de prosa

**Generat per `python -m tools.lint --duplicacio`.**

No és una llista d'errors: **la redundància d'un fet estable no costa res.**
El que costa és un fet que *canvia* i viu a diversos llocs, perquè corregir-lo
vol dir trobar-los tots i corregir-los tots.

Ordenat per **passatge idèntic més llarg**, no per nombre de coincidències.
Això és a posta: dues fitxes de l'índex de la mateixa classe comparteixen
moltes coincidències *curtes* —les capçaleres de la seua pròpia taula— i això
està bé. Un raonament copiat és **una de llarga**. Ordenar per nombre treu
la plantilla a la superfície i amaga la còpia.

3 parelles de fitxers comparteixen almenys 12 paraules.

| Paraules seguides | Coincidències | Fitxers | Comença per |
| --- | --- | --- | --- |
| **29** | 18 | `reports/frontier.md`<br>`reports/worklist.md` | …No s edita a mà FamilySearch no s ha pogut consultar ni cache pedigree json ni reports frontier… |
| **14** | 4 | `Fonts/00 LLEGIU-ME.md`<br>`Fonts/Arxiu (plantilla)/00 LLEGIU-ME.md` | …la primera vegada que hi baixes res que és quan les acabes de llegir… |
| **13** | 2 | `Fonts/Arxiu (plantilla)/00 LLEGIU-ME.md`<br>`reports/worklist.md` | …de la parròquia mare i cercar los pel seu nom no dona res… |
