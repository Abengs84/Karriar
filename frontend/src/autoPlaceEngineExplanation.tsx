/** Teknisk dokumentation för auto-placeringsmotorn (visas under Placeringsmotor). */

export function AutoPlaceEngineExplanation() {
  return (
    <details className="auto-place-engine-doc">
      <summary>Teknisk förklaring – hur placerar motorn elever?</summary>
      <div className="auto-place-engine-doc-body">
        <section>
          <h4>Indata</h4>
          <p>
            Motorn läser alla elever med <strong>val 1–3</strong> och eventuell{" "}
            <strong>reserv</strong>, samt alla <strong>rum</strong> med kapacitet. Befintliga
            placeringar kan behållas (läge «Fyll tomma») eller nollställas («Omplacera allt»).
          </p>
          <p>
            Val 1–3 normaliseras först: om samma inspiratör står på flera val räknas bara den
            första; en senare dubblett kan ersättas av reserv om eleven har det.
          </p>
        </section>

        <section>
          <h4>Vad ska uppnås?</h4>
          <p>Varje elev ska få exakt <strong>tre tidspass</strong> under dagen:</p>
          <ul>
            <li>
              <strong>Pass 1</strong>, <strong>Pass 2</strong> (antingen 2a eller 2b – lunchspår)
              och <strong>Pass 3</strong>
            </li>
            <li>På varje pass träffar eleven <strong>en</strong> inspiratör från sina val</li>
            <li>
              Varje inspiratör får eleven träffa <strong>högst en gång</strong> (tre olika
              inspiratörer totalt)
            </li>
          </ul>
          <p>
            Målet är att så många som möjligt får sina <strong>obligatoriska val 1–3</strong>{" "}
            placerade. Reserv används bara om ett val 1–3 fortfarande saknar plats efter
            huvudplaceringen.
          </p>
        </section>

        <section>
          <h4>Hårda regler (båda motorerna)</h4>
          <ul>
            <li>
              <strong>Session</strong> = en inspiratör + ett tidspass + ett rum (t.ex. «KRIMINOLOG»
              i F606 på pass 1). Högst så många elever i sessionen som rummets kapacitet.
            </li>
            <li>
              I samma rum och samma passtyp (t.ex. pass 1 i F606) får bara{" "}
              <strong>en</strong> inspiratör ligga samtidigt.
            </li>
            <li>
              Varje inspiratör har högst <strong>tre schemalagda pass</strong> (pass 1, 2 och 3).
              Pass 2 är antingen 2a eller 2b – inte båda för samma inspiratör.
            </li>
            <li>
              Eleven kan inte ha två pass samma tid (pass 2a och 2b räknas som samma tid «pass 2»).
            </li>
          </ul>
        </section>

        <section>
          <h4>1. Snabb heuristik</h4>
          <p>
            En steg-för-steg-algoritm som bygger lösningen snabbt. Den garanterar inte att alla
            val alltid går att placera, men är bra för iterativt arbete.
          </p>
          <ol>
            <li>
              <strong>Rum (valfritt)</strong> – Om «Ett rum per inspiratör» är ikryssat tilldelas
              inspiratörer rum efter antal val (mest valda → största lediga sal). Vid rumsbrist
              (hybrid) får de mest valda egna rum; övriga kan dela rum på olika tider.
            </li>
            <li>
              <strong>Pass för pass</strong> – Går igenom pass 1 → pass 2 → pass 3. Elever
              sorteras efter hur «svåra» de är (många kvarvarande val, populära inspiratörer).
              För varje elev väljs det bästa lediga valet som får plats i ett rum.
            </li>
            <li>
              <strong>Poäng</strong> – Val 1 väger tyngst (1000), val 2 (500), val 3 (200), reserv
              (50). Motorn prioriterar högre poäng när flera val är möjliga.
            </li>
            <li>
              <strong>Förbättringsvarv</strong> – Försöker placera kvarvarande val på vilken ledig
              tid som helst, fylla fulla sessioner, samla grupper på färre pass och fylla tomma
              pass.
            </li>
            <li>
              <strong>Reserv (valfritt)</strong> – För elever som fortfarande saknar val 1–3:
              lägg reserv på ledigt pass, eller flytta ett befintligt pass till annan tid och lägg
              reserv på det frigjorda passet.
            </li>
          </ol>
          <p>
            Ny eller befintlig <strong>session</strong> skapas när en inspiratör behöver ett rum
            vid en viss passtyp; elever läggs i <code>session_slots</code> i databasen via
            kopplingen <code>placements</code>.
          </p>
        </section>

        <section>
          <h4>2. Global optimering (CP-SAT)</h4>
          <p>
            Använder Google OR-Tools och söker en lösning som uppfyller alla regler{" "}
            <strong>samtidigt</strong>, inom en tidsgräns (ofta 1–3 minuter). Kräver läget
            «Omplacera allt».
          </p>
          <ol>
            <li>
              <strong>Beslutvariabler</strong> – För varje elev och varje obligatoriskt val: på
              vilket av pass 1 / 2 / 3 ska mötet med den inspiratören ligga?
            </li>
            <li>
              <strong>Begränsningar</strong> – Exakt ett val per pass och per elev; varje val 1–3
              exakt en gång; inga sessioner under valt minimum (standard 5 elever); rumskapacitet;
              högst en inspiratör per (rum, passtyp); samma rum för en inspiratör på alla sina
              pass (delning tillåten med straff för minst valda vid rumsbrist).
            </li>
            <li>
              <strong>Lunch</strong> – Varje inspiratör låses till 2a eller 2b på pass 2;
              målfunktionen minimerar obalans mellan antal elever på 2a respektive 2b.
            </li>
            <li>
              <strong>Mål</strong> – Maximera viktade val (val 1 &gt; val 2 &gt; val 3) och
              föredra färre delade rum.
            </li>
            <li>
              <strong>Reserv</strong> – Efter en hittad lösning körs samma reservsteg som i
              heuristiken för kvarvarande val 1–3.
            </li>
          </ol>
          <p>
            Om CP-SAT returnerar «ingen lösning» finns ingen tillåten kombination under angivna
            regler (t.ex. för många till samma inspiratör utan fler pass i större sal).
          </p>
        </section>

        <section>
          <h4>Utdata</h4>
          <p>
            Resultatet är en lista <strong>sessioner</strong> (rum + passtyp + inspiratör) med
            elev-ID:n, plus lunchspår (2a/2b) per elev på pass 2. Vid <strong>Förhandsgranska</strong>{" "}
            sparas inget; vid <strong>Verkställ</strong> skrivs sessioner och placeringar till
            databasen.
          </p>
        </section>

        <section>
          <h4>Källkod (backend)</h4>
          <ul className="auto-place-engine-doc-files">
            <li>
              <code>backend/app/auto_placer.py</code> – heuristik
            </li>
            <li>
              <code>backend/app/placement_cp_sat.py</code> – CP-SAT
            </li>
            <li>
              <code>POST /api/placements/auto-solve</code> – API
            </li>
          </ul>
        </section>
      </div>
    </details>
  );
}
