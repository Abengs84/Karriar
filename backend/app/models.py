from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False, default=30)

    session_slots = relationship("SessionSlot", back_populates="room")


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("first_name", "last_name", "school", name="uq_student"),
    )

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    school = Column(String, nullable=False)
    choice1 = Column(String, nullable=True)
    choice2 = Column(String, nullable=True)
    choice3 = Column(String, nullable=True)
    reserve = Column(String, nullable=True)
    # "2a" | "2b" | null (auto from pass2 slot)
    lunch_track = Column(String, nullable=True)

    placements = relationship(
        "Placement",
        back_populates="student",
        cascade="all, delete-orphan",
    )


class SessionSlot(Base):
    __tablename__ = "session_slots"
    __table_args__ = (UniqueConstraint("room_id", "pass_type", name="uq_room_pass"),)

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    pass_type = Column(String, nullable=False)  # pass1 | pass2a | pass2b | pass3
    inspiration = Column(String, nullable=False)

    room = relationship("Room", back_populates="session_slots")
    placements = relationship(
        "Placement",
        back_populates="session_slot",
        cascade="all, delete-orphan",
    )


class Placement(Base):
    __tablename__ = "placements"
    __table_args__ = (
        UniqueConstraint("student_id", "session_slot_id", name="uq_student_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    session_slot_id = Column(Integer, ForeignKey("session_slots.id"), nullable=False)

    student = relationship("Student", back_populates="placements")
    session_slot = relationship("SessionSlot", back_populates="placements")
