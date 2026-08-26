# Citar

Segons *Evidence Explained*, adaptat al que hi ha ací. Una citació ha de dir
**què és, on és i com hi tornes**.

## La forma general

> Classe de document, persona i data (o número d'assentament), *llibre o sèrie*,
> foli/pàgina, arxiu i lloc; com s'hi ha accedit i quan.

## Els casos que surten ací

**Partida sacramental (bateig, matrimoni, defunció)**

> Bateig de [nom], [data], *Quinque libri* de la parròquia de [parròquia], llibre
> [n], foli [n]; Arxiu [nom], [lloc]. Consultat [data] [en línia a <URL> | en
> persona | còpia rebuda de l'arxiu].

**Fitxa d'un índex diocesà** — i la distinció importa:

> [Sagrament] de [nom], [any], fitxa de l'índex del [servei], registre núm. [n].
> Consultat en línia [data]. **Índex, no el llibre**: dona la referència, no la
> partida.

Que l'índex tingui l'apunt no vol dir que el llibre tingui la partida. Cita
l'índex com el que és, i quan aconseguiràs el manuscrit, cita'l a part.

**Registre civil**

> [Naixement/matrimoni/defunció] de [nom], [data], Registre Civil de [municipi],
> tom [n], pàgina [n]. Certificat expedit el [data] a petició de [qui].

**Padró d'habitants**

> Padró d'habitants de [municipi], [any], full [n], casa [n]; [arxiu]. Consultat
> [data].

**FamilySearch (arbre)**

> [Nom] (PID [XXXX-XXX]), FamilySearch Family Tree, consultat [data]. **Arbre
> col·laboratiu: font d'autor, i les seves fonts s'han de mirar a part.**

**FamilySearch (imatge filmada)**

> [Document], [lloc], [data]; imatge [n] de [n], FamilySearch, DGS [n], consultat
> [data]. Original a [arxiu].

**Memòria de casa**

> [Qui ho explica], [què], [data en què ho va explicar], recollit a
> `Fonts/Família/[fitxer]`. **Testimoni: informació secundària**, amb la distància
> en anys que hi haja.

**Un llibre publicat de genealogies**

> [Autor], *[Títol]* ([lloc]: [editorial], [any]), p. [n]. **Font d'autor**: mira
> quines fonts dona, i si no en dona cap, digues-ho.

## Al GEDCOM i a les transcripcions

Al GEDCOM, la font i la ruta del document; a la transcripció, la citació sencera i
el que diu el document. **La transcripció no argumenta** (vegeu `fonts.md`).

Comprova sempre que la ruta existeix:

```bash
python -m tools.lint --rutes
```

## Tres coses que la citació ha de deixar clares

1. **Si has vist el document o només una referència.** És la diferència entre
   citar el llibre i citar l'índex, i és la que més sovint es perd.
2. **Qui va declarar la informació**, si el document ho diu. Sense això no es pot
   pesar (vegeu `evidencia.md`).
3. **Què no diu.** «La partida no anomena els avis materns» és informació útil, i
   la que evita que algú hi torne. Si la transcripció anomena algú *per negar-lo*,
   marca-ho perquè les eines no ho comptin com a documentat:

   ```html
   <!-- apv:no-documenta I00161 I00162 -->
   ```

   Sense això, anomenar algú per dir que el document **no** el documenta el treu
   del pla de recerca, que és exactament el contrari del que vols.
