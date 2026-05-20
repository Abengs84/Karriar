import { useEffect } from "react";
import { createPortal } from "react-dom";

type Props = {
  onClose: () => void;
};

export function PrivacyNotice({ onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="privacy-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-title"
      onClick={onClose}
    >
      <div
        className="privacy-dialog card"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        <h2 id="privacy-title">Integritet och personuppgifter (GDPR)</h2>
        <div className="privacy-body">
          <p>
            Detta verktyg behandlar personuppgifter om elever (namn, skola och val av
            inspirationsträffar) i syfte att planera och genomföra Karriär-evenemanget.
          </p>
          <h3>Vilka uppgifter lagras tillfälligt?</h3>
          <ul>
            <li>För- och efternamn</li>
            <li>Skola</li>
            <li>Val av inspirationsträffar</li>
            <li>Placeringar som skapas i systemet</li>
          </ul>
          <p>
            Importerad Excel-fil sparas <strong>inte</strong> på servern – endast uppgifterna
            från filen skrivs till databasen.
          </p>
          <h3>Rättslig grund</h3>
          <p>
            Behandlingen sker för att arrangera en skolaktivitet som eleverna deltar i.
          </p>
          <h3>Lagring och säkerhet</h3>
          <ul>
            <li>Uppgifterna lagras tillfälligt i en databas på den server där appen körs.</li>
            <li>Åtkomst skyddas med lösenord.</li>
            <li>
              Radera uppgifterna när evenemanget är avslutat (knappen «Töm elever/databas»), eller
              låt dem raderas automatiskt ca 3 timmar efter Excel-import.
            </li>
            <li>Åtkomst begränsas till finska IP-adresser.</li>
          </ul>
          <h3>Dina rättigheter</h3>
          <ul>
            <li>
              <strong>Radering:</strong> alla elevuppgifter kan tas bort via «Töm elever/databas».
            </li>
            <li>
              <strong>Registerutdrag / portabilitet:</strong> under fliken Integritet kan behörig
              personal ladda ner en JSON-export av alla elevuppgifter.
            </li>
          </ul>
          <h3>Inloggningscookie</h3>
          <p>
            En teknisk sessionscookie används för att hålla dig inloggad. Den är nödvändig för
            säker åtkomst och kräver inte separat samtycke enligt ePrivacy när den används enbart
            för autentisering.
          </p>
        </div>
        <div className="privacy-actions">
          <button type="button" className="primary" onClick={onClose}>
            Stäng
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
