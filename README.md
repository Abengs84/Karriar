# Karriär – Placeringssystem

Webbverktyg för att hantera rum, importera elevval från Excel (Google Form-export), placera elever manuellt via drag-and-drop och generera PDF-scheman per skola.

## Funktioner

- **Rum** – Bekräftade Karriär-rum läggs in automatiskt vid start med uppskattad kapacitet per lokaltyp. Kapacitet synkas vid omstart; du kan också justera under fliken Rum.
- **Excel-import** – kolumner A–H enligt Vi7-formuläret; dubbletter hoppas över vid omimport
- **Statistik** – antal elever per inspirationsträff och pass (val 1–3)
- **Placering** – dra grupper (samma inspiratör) till sessioner (rum + pass + inspirationsträff)
- **Max tre tidspass per inspiratör** – pass 1, pass 2 och pass 3
- **Pass 2 = antingen 2a eller 2b** – samma inspiratör kan inte ligga på båda lunchspåren; systemet väljer spår vid första placering
- **Pass 2a/2b** – samma tidspass uppdelat; lunchspår sätts automatiskt vid placering
- **PDF** – en fil per skola, fyra scheman per sida (2×2)

## Starta med Docker

1. Kopiera `.env.example` till `.env` och sätt ett starkt lösenord:

```bash
cp .env.example .env
# Redigera KARRIAR_PASSWORD
```

2. Starta:

```bash
docker compose up --build
```

Öppna **http://localhost:8000** och logga in med lösenordet. För utveckling med hot reload, kör backend och frontend separat (se nedan).

**Produktion (AWS m.m.):** använd HTTPS och sätt `KARRIAR_COOKIE_SECURE=true`. Se [docs/PERSONUPPGIFTER.md](docs/PERSONUPPGIFTER.md) för GDPR.

**Lokal utveckling (utan Docker):** ladda ner IP-listor och sätt lösenord:

```powershell
cd backend/scripts
./download_fi_cidr.ps1
```

**Säkerhet:** standard är endast finska IP och automatisk radering av elevdata 3 timmar efter Excel-import (nedräkning i sidhuvudet). Konfigurera via `.env`.

Efter build servas frontend från samma port när static mount är konfigurerad – se `app/main.py`.

## Lokal utveckling

**Backend:**

```bash
cd backend
pip install -r requirements.txt
mkdir -p data
# PowerShell: $env:KARRIAR_PASSWORD="ditt-lösenord"
# Bash: export KARRIAR_PASSWORD=ditt-lösenord
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Öppna **http://localhost:5173** (proxy till API).

## Excel-format

| Kolumn | Innehåll |
|--------|----------|
| A | Timestamp |
| B | Efternamn |
| C | Förnamn |
| D | Skola |
| E | INSPIRATIONSTRÄFF 1 |
| F | INSPIRATIONSTRÄFF 2 |
| G | INSPIRATIONSTRÄFF 3 |
| H | INSPIRATIONSTRÄFF - RESERV |

Exempel på val: `Ekonom – Cecilia Ruotsala`

## Placeringsflöde

1. Skapa rum med kapacitet (t.ex. 30).
2. Importera Excel en gång.
3. Under **Statistik** – se hur många unika elever som valt varje inspiratör (kolumn E–G/H).
4. Under **Placering** – skapa session (rum + **tidspass** + inspiratör) och dra gruppen dit.
5. Om fler elever än kapacitet: använd ett **annat tidspass** (högst tre: pass 1, 2 och 3) – inte ett annat rum samma tid.
6. Kolumn E/F/G är önskemål – inte kopplade till pass 1/2/3 i schemat.
7. Ladda ner PDF per skola.

## Schema (PDF)

- 10:00–10:45 Öppning i Akademisalen
- Pass 1: 11:00–11:30
- **Spår 2a:** Pass 2 kl. 11:45–12:15, lunch 12:15–13:00
- **Spår 2b:** Lunch 11:30–12:15, Pass 2 kl. 12:30–13:00
- Pass 3: 13:15–13:45
- 14:00 Hemfärd
