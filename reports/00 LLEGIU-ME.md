# Informes

Tot el que hi ha aquí **es regenera**, i per tant no s'edita a mà. Per on continuar
viu com a issues del teu repositori a GitHub, no com a fitxer: vegeu el README.

| Fitxer | Qui l'escriu | Què és |
| --- | --- | --- |
| `frontier.md` | `tools.frontier` | a qui val la pena atacar, per ordre, i a quin arxiu |
| `worklist.md` | `tools.worklist` | enllaços de cerca per als que només es resolen anant a l'arxiu |
| `match-report.md` | `tools.match` | qui és qui entre el teu arbre i FamilySearch |
| `apv-verificacio.md` | `tools.apv.verify` | quines comprovacions pot resoldre l'índex diocesà |
| `candidates-*.yaml` | `tools.research` | propostes que **esperen una decisió teva** |
| `fsftid-*.yaml` | `tools.match` | propostes per escriure identificadors de FamilySearch |
| `correccions-*.yaml` | tu, a mà | correccions per a `tools.correct` |
| `aplicades/` | `tools.archive` | el que ja és al GEDCOM. No s'hi torna |

Els `.yaml` que queden a `reports/` han de ser **només els que esperen decisió**. Els
que ja estan fets se'n van a `aplicades/` amb `tools.archive`, i això no és cosmètica:
un fitxer que és tot `accept: true` té la mateixa pinta que un que està a punt de
passar, i tornar-lo a passar per `tools.apply` insereix cada línia una segona vegada.

## Com es decideix una proposta

Obre el `.yaml`, llegeix-lo contra `frontier.md`, i per cada entrada posa:

```yaml
  accept: true            # s'incorpora
  accept: false           # es descarta
  accept: null            # pendent, no es fa res
  accept_ancestors: true  # incorpora també les generacions de més amunt
```

El que **no** es mou mai a `aplicades/` són les descartades: `tools.research` llegeix
els `accept: false` de `reports/candidates-*.yaml` per no tornar-te a proposar algú que
ja vas dir que no, i no mira dins de l'arxiu.
