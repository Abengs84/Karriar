# Automatisk placering (auto-pussel)

Det här dokumentet beskriver hur **Auto-placering** fungerar i Karriär-placeringssystemet.

## Syfte

Med många elever och inspiratörer blir det tidskrävande att manuellt dra varje grupp till rätt rum och pass. Den automatiska placeringen föreslår en lösning som:

- respekterar **elevernas val** (val 1–3 och **reserv**),
- fördelar **högst tre pass per elev** (pass 1, pass 2, pass 3),
- minimerar **krockar** (samma tid två gånger, samma inspiratör två gånger, fulla rum),
- prioriterar **val 1** framför val 2 och val 3.
- **Reserv** räknas inte som obligatoriskt och placeras inte automatiskt (eleven har bara tre pass).

Algoritmen är **heuristisk** – den hittar en bra lösning snabbt, men inte nödvändigtvis den matematiskt optimala.

## Var i appen

Fliken **Auto-placering**:

1. **Förhandsgranska** – räknar ut förslag utan att spara.
2. **Verkställ placering** – skriver resultatet till databasen.

### Lägen

| Läge | Betydelse |
|------|-----------|
| **Fyll tomma platser** | Befintliga placeringar behålls. Endast saknade inspiratörspass fylls i. |
| **Omplacera allt** | Alla placeringar och sessioner tas bort och ersätts av systemets nya förslag. |

Använd alltid förhandsgranskning först.

## Regler (samma som vid manuell placering)

1. **Ett pass per tid** – Pass 2a och 2b räknas som samma tid (`pass2`). Eleven kan bara ha ett av dem.
2. **En gång per inspiratör** – Eleven kan bara träffa varje inspiratör en gång under dagen.
3. **Val krävs** – Inspiratören måste finnas bland elevens val 1–3 eller reserv.
4. **Rumskapacitet** – Varje session (rum + passtyp + inspiratör) har högst `capacity` elever.
5. **Ett inspiratörnamn per ruta** – I ett givet rum och passtyp (t.ex. A0208 + pass 1) kan bara **en** inspiratör ligga. Systemet skapar fler sessioner i andra rum om gruppen inte får plats.

## Hur algoritmen tänker

### Poäng för val

| Fält | Vikt |
|------|------|
| Val 1 | 1000 |
| Val 2 | 500 |
| Val 3 | 200 |
| Reserv | 50 (används bara om plats finns kvar; räknas inte som «kvar utan pass») |

Högre poäng i resultatet = fler prioriterade val har fått en plats.

### Steg 1 – Behov

För varje elev och varje val som **inte** redan har en placering med den inspiratören skapas ett *behov* `(elev, inspiratör, prioritet)`.

### Steg 2 – Pass för pass

Systemet går igenom tidsspåren i ordning: **pass 1 → pass 2 → pass 3**.

För varje pass:

- Elever som saknar det passet sorteras efter hur många val de fortfarande behöver (svårast först).
- För varje elev väljs det **högst prioriterade** valet som:
  - får plats i ett rum,
  - inte bryter mot reglerna,
  - har ledig kapacitet i en befintlig eller ny session.

### Steg 3 – Pass 2: 2a eller 2b (lunch)

Pass 2 kan ligga i kolumn **pass 2a** eller **pass 2b** – olika lunchtider. Regler:

- Om eleven redan har lunchspår **2a** eller **2b** (t.ex. från tidigare manuell placering) behålls det spåret.
- Annars väljs spåret med **färre elever hittills**, så ungefär **hälften** av eleverna hamnar på 2a och hälften på 2b över hela evenemanget.
- Om det bara finns plats i ett spår används det som finns (balansen kan då bli skev p.g.a. rumskapacitet).

### Steg 4 – Förbättringsvarv

Efter huvudloopen körs några extra varv som försöker placera kvarvarande behov på **vilken** lediga tid som helst (fortfarande med samma regler).

### Steg 5 – Rum och sessioner

- Finns redan en session med samma inspiratör + passtyp och lediga platser → eleven läggs där.
- Annars väljs ett **ledigt rum** för den passtypen (eller samma rum om samma inspiratör redan ligger där).
- Om alla platser är fulla skapas en **ny session** i nästa lediga rum med störst kapacitet.

## Varför kan val ändå bli kvar?

Även med smart pussling går det inte alltid att placera alla val:

| Orsak | Förklaring |
|-------|------------|
| **Fyra val, tre pass** | Reserv förväntas ofta vara oplacerad – systemet försöker bara fylla **val 1–3**. |
| **Fulla rum** | Total kapacitet i rummen räcker inte för alla som valt samma inspiratör samma pass. |
| **Rum upptagna** | Alla rum har redan en annan inspiratör den tiden och det finns inget fler rum. |
| **Befintliga placeringar** | I läget *Fyll tomma* kan tidigare manuella val blockera bättre kombinationer. |

Kvarvarande **val 1–3** utan pass visas i förhandsgranskningen (elev-id, inspiratör, valtyp). Reserv visas inte där.

I fliken **Placering** visas bara oplacerade grupper för **val 1–3**. Elever som bara har kvar sitt reservval syns inte i vänsterkolumnen (reserv kan fortfarande sättas under **Elever**).

## Tekniskt

| Del | Fil |
|-----|-----|
| Algoritm | `backend/app/auto_placer.py` |
| API | `POST /api/placements/auto-solve` |
| Gränssnitt | `frontend/src/AutoPlaceTab.tsx` |

### API-exempel

```json
POST /api/placements/auto-solve
{
  "mode": "fill",
  "dry_run": true
}
```

Svaret innehåller `placed_new`, `slots_created`, `unplaced_count`, `score`, `by_choice_field` och `summary`.

## Tips för bästa resultat

1. Importera elever och skapa **alla rum** med rätt kapacitet först.
2. Kör **Förhandsgranska** och kontrollera statistik-fliken (oplacerade per inspiratör).
3. Justera manuellt i **Placering** eller **Elever** där det behövs.
4. Använd **Omplacera allt** bara när du vill börja om från scratch.

## Begränsningar (medvetet)

- Ingen garanti för global optimum.
- Tar inte hänsyn till geografisk närhet mellan rum eller önskemål utöver val 1–3/reserv.
- Skapar inte sessioner om det inte finns **något** ledigt rum för passtypen.

Framtida förbättringar kan t.ex. vara manuella låsningar (“den här eleven ska ha val 1 på pass 1”) eller omoptimering med extern solver (OR-Tools).
