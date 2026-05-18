# Personuppgifter och GDPR – Karriär placering

Detta dokument riktar sig till **personuppgiftsansvarig** (t.ex. skola eller arrangör) som använder verktyget.

## Syfte med behandlingen

Planering och genomförande av Karriär-evenemanget: import av elevval, placering i sessioner och utskrift av scheman (PDF).

## Vilka uppgifter behandlas?

| Uppgift | Källa |
|--------|--------|
| För- och efternamn | Excel / Google Form |
| Skola | Excel |
| Val av inspirationsträffar (1–3 + reserv) | Excel |
| Placeringar, lunchspår (2a/2b) | Skapas i appen |

**Excel-filen lagras inte** på servern efter import – endast fälten ovan i databasen.

## Rättslig grund

För skolors arrangemang av obligatorisk/organiserad aktivitet är vanlig grund **berättigat intresse** (art. 6.1 f) eller **offentlig uppgift** (art. 6.1 e) beroende på verksamhet. Dokumentera valet i er behandlingsförteckning.

## Tekniska åtgärder (TOM)

- Lösenordsskyddad åtkomst (`KARRIAR_PASSWORD`)
- Sessionscookie (HttpOnly, SameSite=Lax)
- HTTPS i produktion (`KARRIAR_COOKIE_SECURE=true`)
- Databas i Docker-volym – begränsa serveråtkomst (AWS security groups)
- Valfri begränsning till **finska IP-adresser** (`KARRIAR_FINLAND_IP_ONLY=true`)
- **Automatisk radering** av elevdata ca 3 timmar efter Excel-import (`KARRIAR_RETENTION_HOURS`)

## Lagringstid

**Radera uppgifterna när evenemanget är avslutat** via «Töm elever/databas» i appen. Ta backup av volymen endast om ni har juridisk anledning – radera backup i så fall enligt samma tidsplan.

## Registrerades rättigheter

| Rättighet | Så uppfylls den i verktyget |
|-----------|------------------------------|
| Information (art. 13–14) | Integritetstext i appen + detta dokument |
| Tillgång (art. 15) | JSON-export under fliken Integritet |
| Radering (art. 17) | «Töm elever/databas» |
| Dataportabilitet (art. 20) | JSON-export |
| Invändning m.m. | Hanteras av personuppgiftsansvarig utanför appen |

## Personuppgiftsbiträde

Om en extern leverantör (t.ex. AWS) hostar servern kan ett **biträdesavtal (DPA)** behövas med leverantören. Appen i sig lagrar data endast på den instans ni deployar.

## Incident och kontakt

Ange intern kontakt (t.ex. studievägledning / dataskyddsombud) för frågor från elever och vårdnadshavare. Vid personuppgiftsincident – följ er organisations rutin och ev. anmälan till IMY.

## Checklista före produktion

- [ ] Starkt `KARRIAR_PASSWORD`, delas bara med behörig personal
- [ ] HTTPS och `KARRIAR_COOKIE_SECURE=true`
- [ ] Servern inte öppen för hela internet utan behov (VPN / IP-begränsning om möjligt)
- [ ] Rutin för radering efter evenemanget
- [ ] Behandlingsförteckning uppdaterad
