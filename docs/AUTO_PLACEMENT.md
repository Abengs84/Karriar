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

1. **Dubblett i val 1–3** – Om samma inspiratör står på flera val (t.ex. val 1 och val 3) räknas bara det första; det senare ersätts av **reserv** om eleven har reservval (annars ignoreras dubbletten).
2. **Ett pass per tid** – Pass 2a och 2b räknas som samma tid (`pass2`). Eleven kan bara ha ett av dem.
3. **En gång per inspiratör** – Eleven kan bara träffa varje inspiratör en gång under dagen.
4. **Val krävs** – Inspiratören måste finnas bland elevens val 1–3 eller reserv.
5. **Rumskapacitet** – Varje session (rum + passtyp + inspiratör) har högst `capacity` elever.
6. **Max tre tidspass per inspiratör** – Pass 1, pass 2 och pass 3. Pass 2 = antingen 2a eller 2b (lunchspår låses vid första session).
7. **Ett rum per pass och inspiratör** – Samma inspiratör kan inte ligga i två rum samtidigt (samma passtyp). Om rummet är fullt: använd ett **annat tidspass**, inte ett annat rum samma tid.
8. **Samma rum på flera pass** – Auto-placering försöker lägga samma inspiratör i **samma rum** på pass 1, 2 och 3 när den tiden är ledig i rummet (mjuk prioritering om inget rumslås finns).
9. **Ett rum per inspiratör (kryssruta)** – Varje inspiratör har **ett** rum för alla pass; rum väljs efter **antal val** (flest val → största lediga sal). Befintliga sessioner flyttas till tilldelat rum. Med *Försök reserv* räknas även reservval in i efterfrågan. Med färre rum än inspiratörer får bara de **mest valda** ett eget rum (strikt läge).
10. **Hybrid vid rumsbrist** (kräver kryss 9) – Om fler inspiratörer med val än rum: de **mest valda** (högst antal val 1–3) får eget rum som vanligt; **övriga** (minst valda) får **dela** rum med varandra på olika tider (samma pass = fortfarande ett rum per inspiratör).
11. **Prioritera stora grupper (kryssruta, standard på)** – Rumslås och placering sorteras efter **efterfrågan** (antal val 1–3 per inspiratör). Inspiratörer med låg efterfrågan kan flyttas bort från stora sal innan omplacering. Kombinera med **tröskel** för att dölja små inspiratörer helt.
12. **Ett inspiratörnamn per ruta** – I ett givet rum och passtyp kan bara **en** inspiratör ligga.

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
- Med **Balansera lunchspår** planeras olåsta inspiratörer till 2a eller 2b utifrån förväntad elevmängd (minimerar skillnad 2a/2b). Elever får **inte** lunchspår i förväg utifrån fel val – bara inspiratörens planerade spår styr vid pass 2.
- Om det bara finns plats i ett spår används det som finns (balansen kan då bli skev p.g.a. rumskapacitet).

### Steg 4 – Förbättringsvarv

Efter huvudloopen körs några extra varv som försöker placera kvarvarande behov på **vilken** lediga tid som helst (fortfarande med samma regler).

### Steg 4b – Reserv för elever som saknar pass (valfritt)

Om **Försök reserv för elever som saknar pass** är ikryssat: efter förbättringsvarven försöker systemet placera **reserv** för elever som fortfarande har kvarvarande val 1–3:

1. På ett **ledigt** tidspass om reserv har plats där.
2. Genom att **flytta** ett befintligt pass till en annan tid där samma inspiratör har lediga platser, och sedan lägga reserv på det frigjorda passet (t.ex. flytta val 1 från pass 2 till pass 3 och lägga reserv på pass 2).

Eleven måste ha reservval. De räknas inte längre som «val 1–3 utan pass» i resultatet om reserv lyckades.

### Steg 5 – Rum och sessioner

- Finns redan en session med samma inspiratör + passtyp och lediga platser → eleven läggs där.
- Annars väljs ett **ledigt rum** för den passtypen (eller samma rum om samma inspiratör redan ligger där).
- Vid **stor förväntad grupp** (eller kryssat «få sessioner») väljs **större rum först** vid nya sessioner.
- Om sessionen är **full** men fler elever väntar: systemet försöker **flytta** sessionen till ett större ledigt rum, eller **byta rum** med en annan inspiratör som får plats i det mindre rummet (samma passtyp).
- Efter förbättringsvarven körs extra varv som expanderar fulla sessioner innan reserv steg 4b.

### Steg 5c – Samla små grupper (valfritt, standard på)

Om **Samla små grupper på ett pass per inspiratör** är ikryssat:

- Under placering: befintliga sessioner fylls först och större rum väljs vid stora grupper (färre parallella träffar).
- Efter placering: elever som träffar samma inspiratör på **flera** tidspass samlas till **en** session när det går. Tomma sessioner tas bort. Gäller grupper upp till ca 40 elever.

### Steg 5b – Större rum vid fullt rum

Efter huvudloopen: om t.ex. KRIMINOLOG ligger i F506 (20 platser) och är full, men fler elever valt kriminolog, försöker algoritmen flytta hela sessionen till ett större rum samma tid. Om det större rummet redan har en annan inspiratör byts rummen om den andra gruppen får plats i det mindre.

## Varför kan val ändå bli kvar?

Även med smart pussling går det inte alltid att placera alla val:

| Orsak | Förklaring |
|-------|------------|
| **Fyra val, tre pass** | Reserv förväntas ofta vara oplacerad – systemet försöker bara fylla **val 1–3**. |
| **Fulla rum** | Total kapacitet i rummen räcker inte för alla som valt samma inspiratör samma pass. |
| **Rum upptagna** | Alla rum har redan en annan inspiratör den tiden och det finns inget fler rum. |
| **Befintliga placeringar** | I läget *Fyll tomma* kan tidigare manuella val blockera bättre kombinationer. |

Kvarvarande **val 1–3** utan **ledigt tidspass** visas i förhandsgranskningen (elevnamn, inspiratör, valtyp). Elever som redan har tre pass räknas inte, även om ett lägre prioriterat val ersatts av ett annat (t.ex. val 1 på både pass 1 och 3). Reserv visas inte där.

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
  "dry_run": true,
  "try_reserve_for_unplaced": true
}
```

Svaret innehåller `placed_new`, `slots_created`, `unplaced_count`, `score`, `by_choice_field` och `summary`.

## Tips för bästa resultat

1. Importera elever och skapa **alla rum** med rätt kapacitet först.
2. Kör **Förhandsgranska** och kontrollera statistik-fliken (oplacerade per inspiratör).
3. Med **få rum** och *Ett rum per inspiratör*: kryssa i **Prioritera stora grupper** och prova **tröskel** (t.ex. 5–10) så små inspiratörer inte tar stora sal.
4. Grupper större än största sal (t.ex. 64 elever, max 40 platser) kan inte få alla på **ett** pass – de delas på flera tider eller blir delvis oplacerade.
5. Justera manuellt i **Placering** eller **Elever** där det behövs.
6. Använd **Omplacera allt** bara när du vill börja om från scratch.

## Begränsningar (medvetet)

- Ingen garanti för global optimum.
- Tar inte hänsyn till geografisk närhet mellan rum eller önskemål utöver val 1–3/reserv.
- Skapar inte sessioner om det inte finns **något** ledigt rum för passtypen.

Framtida förbättringar kan t.ex. vara manuella låsningar (“den här eleven ska ha val 1 på pass 1”) eller omoptimering med extern solver (OR-Tools).
