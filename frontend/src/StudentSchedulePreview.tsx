import { Student } from "./api";
import footerImg from "@img/Vi7_bredd.png";
import silhouetteImg from "@img/karriar-yrken-silhuet_karriar.png";
import { buildStudentScheduleRows, EVENT_DATE, EVENT_PLACE } from "./studentScheduleRows";

type Props = {
  student: Student;
};

export function StudentSchedulePreview({ student }: Props) {
  const rows = buildStudentScheduleRows(student);

  return (
    <div className="schema-student-card">
      <div className="schema-student-header">
        <p className="schema-student-name">
          {student.school}, {student.first_name} {student.last_name}
        </p>
        <img
          className="schema-student-silhouette"
          src={silhouetteImg}
          alt=""
          aria-hidden
        />
      </div>
      <div className="schema-student-spacer" aria-hidden="true" />
      <div className="schema-student-lower">
        <p className="schema-student-event">
          {EVENT_DATE.toUpperCase()}, {EVENT_PLACE.toUpperCase()}
        </p>
        <table className="schema-student-schedule">
          <tbody>
            {rows.map((row, i) => (
              <tr key={`${row.time}-${i}`} className={i % 2 === 1 ? "stripe" : ""}>
                <th scope="row">{row.time}</th>
                <td>
                  {row.kind === "text" ? (
                    <span className="schema-student-text">{row.text}</span>
                  ) : (
                    <>
                      <span className="schema-student-inspiration">{row.inspiration}</span>
                      <span className="schema-student-room">{row.room}</span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <img className="schema-student-footer" src={footerImg} alt="" aria-hidden />
      </div>
    </div>
  );
}
