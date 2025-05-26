from __future__ import annotations

from .database import Base
from sqlalchemy import (Column,Integer,String, Boolean, DateTime, UniqueConstraint, Table, ForeignKey, Text, BigInteger)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.sql import func
import enum

class UserRole(enum.Enum):
    """
    Класс с ролями участников в проекте
    """
    MEMBER = "member"
    HELPER = "helper"
    OWNER = "owner"

class TaskStatus(enum.Enum):
    """
    Класс со статусами выполнения задачи
    """
    NEW = "new"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = 'users'
    user_id = Column(BigInteger, primary_key=True, autoincrement=False) # ID из Telegram
    username = Column(String, nullable=True, unique=True)
    first_name = Column(String, nullable=False)
    is_bot = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    memberships = relationship(
        "ProjectMember",
        back_populates="user",
        cascade="all, delete-orphan", # Удаление User удаляет его записи о членстве
        lazy="selectin"
    )
    projects = association_proxy('memberships', 'project')

    created_tasks = relationship("Task", foreign_keys="[Task.creator_user_id]", back_populates="creator", lazy="selectin")
    assigned_tasks = relationship("Task", foreign_keys="[Task.assignee_user_id]", back_populates="assignee", lazy="selectin")
    generated_invites = relationship("Invites", back_populates="generated_by", foreign_keys="[Invites.generated_by_user_id]", lazy="selectin")
    def __repr__(self):
        return f"<User(user_id={self.user_id}, username='{self.username}')>"

class ProjectMember(Base):
    __tablename__ = 'project_members'

    project_id = Column(BigInteger, ForeignKey('projects.project_id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True)
    role = Column(String(50), default='member', nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="memberships")
    project = relationship("Project", back_populates="memberships")

    def __repr__(self):
        return f"<ProjectMember(proj={self.project_id}, user={self.user_id}, role='{self.role}')>"

project_chats_association = Table(
    'project_chats', Base.metadata,
    Column('project_id', BigInteger, ForeignKey('projects.project_id', ondelete='CASCADE'), primary_key=True),
    Column('chat_id', BigInteger, ForeignKey('chats.chat_id', ondelete='CASCADE'), primary_key=True)
)

class Chat(Base):
    __tablename__ = 'chats'
    chat_id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    title = Column(String, nullable=True)
    type = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    projects = relationship(
        "Project",
        secondary=project_chats_association,
        back_populates="chats",
        lazy="selectin"
    )

    tasks_created_here = relationship("Task", foreign_keys="[Task.chat_id_created_in]", back_populates="chat_created_in", lazy="selectin")

    def __repr__(self):
        return f"<Chat(chat_id={self.chat_id}, title='{self.title}', type='{self.type}')>"

class Project(Base):
    __tablename__ = 'projects'
    project_id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    owner_user_id = Column(BigInteger, ForeignKey('users.user_id'), nullable=False) # Ссылка на владельца
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    description = Column(Text, nullable=True)

    memberships = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan", # Удаление проекта удаляет записи о членстве
        lazy="selectin"
    )
    members = association_proxy('memberships', 'user')

    chats = relationship(
        "Chat",
        secondary=project_chats_association,
        back_populates="projects",
        lazy="selectin"
    )

    tasks = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan", # Удаление проекта удаляет все его задачи
        lazy="selectin"
        )
    owner = relationship("User", foreign_keys=[owner_user_id], lazy="joined")
    invites = relationship("Invites", back_populates="project", cascade="all, delete-orphan", lazy="selectin")
    def __repr__(self):
        return f"<Project(project_id={self.project_id}, name='{self.name}')>"

class Task(Base):
    __tablename__ = 'tasks'
    title = Column(String(255), nullable=False)
    task_id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False, index=True)
    task_id_in_project = Column(BigInteger, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(50), default='new', nullable=False, index=True)
    creator_user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True)
    assignee_user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True, index=True)
    chat_id_created_in = Column(BigInteger, ForeignKey('chats.chat_id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('project_id', 'task_id_in_project', name='uq_project_task_identifier'),)


    project = relationship("Project", back_populates="tasks", lazy="joined")
    creator = relationship("User", foreign_keys=[creator_user_id], back_populates="created_tasks", lazy="joined")
    assignee = relationship("User", foreign_keys=[assignee_user_id], back_populates="assigned_tasks", lazy="joined")
    chat_created_in = relationship("Chat", foreign_keys=[chat_id_created_in], back_populates="tasks_created_here",
                                   lazy="joined")

    def __repr__(self):
        return f"<Task(id={self.task_id}, proj={self.project_id}, id_in_proj={self.task_id_in_project}, st='{self.status}')>"

class Invites(Base):
    __tablename__ = "invites"

    invite_id = Column(BigInteger, primary_key=True, autoincrement=True)
    invite_code = Column(String, unique=True, index=True, nullable=False)
    project_id = Column(BigInteger, ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False)
    max_uses = Column(BigInteger, nullable=True, default=None)
    current_uses = Column(BigInteger, default=0, nullable=False)
    generated_by_user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="invites")
    generated_by = relationship("User", back_populates="generated_invites", foreign_keys=[generated_by_user_id])

    def __repr__(self):
        return (
            f"<Invite(code='{self.invite_code}', project_id={self.project_id}, "
            f"uses={self.current_uses}/{self.max_uses}, expires_at={self.expires_at.isoformat()})>"
        )
