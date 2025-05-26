from datetime import datetime, timezone
import random
import string

from sqlalchemy import func
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .exceptions import *
from .models import User, Project, ProjectMember, Task, Invites, TaskStatus, Chat, UserRole

sentinel = object()

def generate_invite_code(length: int = 15) -> str:
    """
    Генерирует случайную строку (код приглашения), содержащую буквы (ASCII,
    верхний и нижний регистр) и цифры, заданной длины.

    По умолчанию длина кода 15 символов.

    :param length: Требуемая длина строки.
    :return: Сгенерированная случайная строка (код приглашения).
    """
    # Набор символов: ASCII буквы (a-z, A-Z) и цифры (0-9)
    characters = string.ascii_letters + string.digits

    # Случайным образом выбираем 'length' символов из набора и объединяем их
    invite_code = ''.join(random.choice(characters) for i in range(length))

    return invite_code

async def create_user(session: AsyncSession, user_id: int, username: str | None, first_name: str, is_bot: bool = False) -> User:
    """
    Добавляет нового пользователя в базу данных.
    :param session: Асинхронная сессия SQLAlchemy
    :param user_id: Уникальный ID пользователя из Telegram
    :param username: Необязательный username пользователя
    :param first_name: Имя пользователя
    :param is_bot: Флаг является ли пользователь ботом (для ручного добавления)

    :return: Объект модели User

    :raises UserAlreadyExistsError: Пользователь уже существует
    :raises DatabaseError: Ошибка в базе данных
    """
    try:
        db_user = User(user_id=user_id, username=username, first_name=first_name, is_bot=is_bot)
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
        return db_user
    except IntegrityError:
        raise UserAlreadyExistsError(user_id=user_id)
    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_user_by_id(session: AsyncSession, user_id: int) -> User:
    """
    Ищет пользователя в базе данных

    :param session: Асинхронная сессия SQLAlchemy
    :param user_id: Уникальный ID пользователя из Telegram

    :return: Объект модели User

    :raises UserNotFoundError: Пользователь с указанным ID не найден
    :raises DatabaseError: Ошибка в базе данных
    """
    try:
        query = select(User).where(User.user_id == user_id)
        result = await session.execute(query)
        user = result.scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(user_id=user_id)
        return user
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e


async def get_or_create_and_update_user(session: AsyncSession, user_id: int, username: str | None, first_name: str, is_bot: bool = False) -> User:
    """
    Получает пользователя по ID, обновляет его данные или создаёт нового, если не найден.

    Гарантирует, что first_name пользователя будет обновлен/установлен.

    :param session: Асинхронная сессия SQLAlchemy.
    :param user_id: Уникальный ID пользователя из Telegram.
    :param username: Необязательный username пользователя (может быть None).
    :param first_name: Имя пользователя (обязательно строка). # <-- Изменено: теперь всегда str
    :param is_bot: Флаг является ли пользователь ботом.
    :return: Обновленный или созданный объект модели User.

    :raises DatabaseError: При ошибках базы данных во время получения, создания или сохранения.
    """
    try:
        user = await get_user_by_id(session, user_id)

    except UserNotFoundError:
        try:
            user = await create_user(session, user_id, username, first_name, is_bot)
            return user
        except (UserAlreadyExistsError, DatabaseError):
             raise
    needs_update = False

    if username is not None and user.username != username:
        user.username = username
        needs_update = True
    elif username is None and user.username is not None:
         user.username = None
         needs_update = True

    if user.first_name != first_name:
        user.first_name = first_name
        needs_update = True

    if user.is_bot != is_bot:
        user.is_bot = is_bot
        needs_update = True

    if needs_update:
        try:
            await session.commit()
            await session.refresh(user)
        except SQLAlchemyError as e:
            await session.rollback()
            raise DatabaseError(original_exception=e) from e
    return user


async def create_project(session: AsyncSession, owner_user_id: int, name: str, description: str | None = None) -> Project:
    """
    Функция создаёт фундамент проекта с его автором, названием и описанием
    :param session: Асинхронная сессия SQLAlchemy
    :param owner_user_id: Уникальный ID пользователя из Telegram который будет являться создателем проекта
    :param name: Название проекта
    :param description: Описание проекта
    :return: Объект модели Project

    :raises UserNotFoundError: Пользователь с указанным ID не найден
    :raises ProjectNameConflictError: Проект с таким названием уже существует
    :raises DatabaseError: При других ошибках базы данных
    """
    await get_user_by_id(session, owner_user_id)

    db_project = Project(owner_user_id=owner_user_id, name=name, description=description)

    session.add(db_project)

    try:
        await session.commit()
        await session.refresh(db_project)
        return db_project

    except IntegrityError as e:
        await session.rollback()
        raise ProjectNameConflictError(name=name) from e
    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_project_by_id(session: AsyncSession, project_id: int) -> Project:
    """
    Получает проект по его уникальному ID
    :param session: Асинхронная сессия SQLAlchemy
    :param project_id: Уникальный ID проекта

    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises DatabaseError: При других ошибках базы данных

    :return: Объект модели Project
    """
    try:
        query = select(Project).where(Project.project_id == project_id)
        result = await session.execute(query)
        project = result.scalar_one_or_none()

        if project is None:
            raise ProjectNotFoundError(project_id=project_id)
        return project
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_projects_by_owner(session: AsyncSession, owner_user_id: int) -> list[Project]:
    """
    Получает список проектов, где пользователь с указанным owner_user_id является владельцем
    :param session: Асинхронная сессия SQLAlchemy
    :param owner_user_id: Уникальный user_id пользователя из Telegram

    :return: Список из объектов модели Project

    :raises DatabaseError: Если произошла ошибка базы данных
    """
    try:
        query = select(Project).where(Project.owner_user_id == owner_user_id)
        result = await session.execute(query)
        list_projects = result.scalars().all()
        return list_projects
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e
    

async def get_projects_user_is_member(session: AsyncSession, user_id: int) -> list[Project]:
    """
    Получает список проектов, УЧАСТНИКОМ которых является пользователь с указанным user_id.

    Использует связь Project.members (association_proxy) для фильтрации.

    :param session: Асинхронная сессия SQLAlchemy.
    :param user_id: Уникальный user_id пользователя из Telegram.
    :return: Список объектов Project, где пользователь является участником (не владельцем),
    или пустой список, если таких проектов нет.

    :raises UserNotFoundError: Если пользователь с указанным user_id не существует в таблице
    :raises DatabaseError: Если произошла ошибка базы данных
    """
    await get_user_by_id(session, user_id)

    try:
        query = select(Project).where(Project.members.any(User.user_id == user_id))

        result = await session.execute(query)
        projects_list = result.scalars().all()
        return projects_list

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def update_project(session: AsyncSession, project_id: int, name: str | None = sentinel, description: str | None = sentinel) -> Project:
    """
    Обновляет имя и/или описание проекта с указанным project_id.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта для обновления.
    :param name: Новое название проекта.
    :param description: Новое описание проекта.
    :return: Обновленный объект модели Project.

    :raises ProjectNotFoundError: Если проект с таким ID не найден (от get_project_by_id).
    :raises DatabaseError: При ошибках базы данных во время получения или сохранения.
    :raises ProjectNameConflictError: Если новое имя проекта конфликтует с существующим. # Добавили
    """
    db_project = await get_project_by_id(session, project_id)


    needs_update = False
    if name is not sentinel and db_project.name != name:
        db_project.name = name
        needs_update = True
    if description is not sentinel and db_project.description != description:
        db_project.description = description
        needs_update = True

    if needs_update:
        try:
            await session.commit()
            await session.refresh(db_project)
        except IntegrityError as e:
            await session.rollback()
            raise ProjectNameConflictError(name=name) from e
        except SQLAlchemyError as e:
            await session.rollback()
            raise DatabaseError(original_exception=e) from e
    return db_project

async def transfer_project_ownership(session: AsyncSession, project_id: int, new_owner_user_id: int) -> Project:
    """
    Передаёт владение (owner) проектом другому пользователю.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param new_owner_user_id: ID пользователя Telegram, которому будут переданы права.

    :return: Обновленный объект модели Project.

    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises UserNotFoundError: Если новый пользователь-владелец не найден.
    :raises DatabaseError: При ошибках базы данных во время сохранения.
    """
    project = await get_project_by_id(session, project_id)        
    new_owner_user = await get_user_by_id(session, new_owner_user_id)

    try:


        old_owner_user_id = project.owner_user_id

        if old_owner_user_id == new_owner_user_id:
            return project
        project.owner_user_id = new_owner_user_id
        session.add(project)

        await session.commit()
        await session.refresh(project)
        try:
            await remove_member_from_project(session=session, project_id=project_id, user_id=new_owner_user_id)
        except MemberNotFoundError:
            pass
        await add_member_to_project(session=session, project_id=project_id, user_id=old_owner_user_id)

        return project
    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e


async def delete_project(session: AsyncSession, project_id: int) -> None:
    """
    Удаляет проект по его project_id.

    Также удаляет связанные объекты (задачи, членства, приглашения)
    благодаря каскадам в моделях.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта для удаления.
    :return: None в случае успеха.

    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises DatabaseError: При ошибках базы данных во время удаления.
    """
    project = await get_project_by_id(session, project_id)

    try:
        await session.delete(project)
        await session.commit()

    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def add_member_to_project(session: AsyncSession, user_id: int, project_id: int, role: str = "member") -> ProjectMember:
    """
    Добавляет пользователя как участника в проект.

    :param session: Асинхронная сессия SQLAlchemy.
    :param user_id: Уникальный user_id пользователя из Telegram.
    :param project_id: Уникальный ID проекта.
    :param role: Роль участника в проекте (например, 'member', 'helper').
    :return: Созданный объект класса ProjectMember.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь не найден.
    :raises UserAlreadyProjectOwner: Если пытаются добавить владельца проекта как участника (Убедитесь, что это исключение определено).
    :raises UserAlreadyMemberError: Если пользователь уже является участником проекта (Убедитесь, что это исключение определено).
    :raises DatabaseError: При других ошибках базы данных.
    """
    project = await get_project_by_id(session, project_id)
    user = await get_user_by_id(session, user_id)

    if project.owner_user_id == user_id:
        raise UserAlreadyProjectOwner(user_id=user_id, project_id=project_id)

    try:
        existing_membership_query = select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                                ProjectMember.user_id == user.user_id)
        result = await session.execute(existing_membership_query)
        existing_membership = result.scalar_one_or_none()
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

    if existing_membership:
        raise UserAlreadyMemberError(user_id=user_id, project_id=project_id)

    try:
        new_membership = ProjectMember(project_id=project_id, user_id=user.user_id, role=role)
        session.add(new_membership)
        await session.commit()
        await session.refresh(new_membership)
        return new_membership
    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_project_member(session: AsyncSession, project_id: int, user_id: int) -> ProjectMember:
    """
    Получает объект членства ProjectMember по ID проекта и ID пользователя.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param user_id: Уникальный user_id пользователя из Telegram.
    :return: Объект ProjectMember, если пользователь является участником проекта.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь не найден.
    :raises MemberNotFoundError: Если членство для данной пары project_id и user_id не найдено.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    await get_project_by_id(session, project_id)
    await get_user_by_id(session, user_id)
    try:
        query = select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        result = await session.execute(query)
        membership = result.scalar_one_or_none()

        if membership is None:
            raise MemberNotFoundError(project_id=project_id, user_id=user_id)
        return membership
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_project_members(session: AsyncSession, project_id: int) -> list[ProjectMember]:
    """
    Получает участников проекта и возвращает их списком

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :return: Список из объектов класса ProjectMember

    :raises ProjectNotFoundError: Если проект с таким ID не найден
    :raises DatabaseError: Если произошла ошибка базы данных во время запроса.
    """
    await get_project_by_id(session=session, project_id=project_id)
    try:
        query = select(ProjectMember).where(ProjectMember.project_id == project_id)
        query = query.options(selectinload(ProjectMember.user))
        result = await session.execute(query)
        members = result.scalars().all()
        return members
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def update_member_role(session: AsyncSession, project_id: int, user_id: int, new_role: str) -> ProjectMember:
    """
    Обновляет роль пользователя в проекте.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param user_id: Уникальный user_id пользователя из Telegram.
    :param new_role: Новая роль участника в проекте.
    :return: Обновленный объект класса ProjectMember.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь не найден.
    :raises MemberNotFoundError: Если членство для данной пары project_id и user_id не найдено.
    :raises DatabaseError: При других ошибках базы данных во время сохранения.
    """
    project_member = await get_project_member(session, project_id, user_id)

    if project_member.role == new_role:
        return project_member

    project_member.role = new_role
    try:
        await session.commit()
        await session.refresh(project_member)
        return project_member

    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def remove_member_from_project(session: AsyncSession, project_id: int, user_id: int) -> None:
    """
    Удаляет пользователя из проекта

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param user_id: Уникальный user_id пользователя из Telegram.

    :return: None в случае успеха
    
    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь не найден.
    :raises MemberNotFoundError: Если членство для данной пары project_id и user_id не найдено.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    await get_project_member(session, project_id, user_id)
    try:
        query = delete(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        await session.execute(query)
        await session.commit()
    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def _get_next_task_id_in_project(session: AsyncSession, project_id: int) -> int:
    """Находит следующий доступный task_id_in_project для данного проекта.
    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта.
    :return: Номер задачи
    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises DatabaseError: При других ошибках базы данных
    """
    await get_project_by_id(session, project_id)
    try:
        max_id_query = select(func.max(Task.task_id_in_project)).where(Task.project_id == project_id)
        max_id_result = await session.execute(max_id_query)
        max_id = max_id_result.scalar_one_or_none()
        return (max_id or 0) + 1
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def create_task(session: AsyncSession, project_id: int, creator_user_id: int, title: str, description: str,
                      chat_id_created_in: int, assignee_user_id: int | None = None, status: str = TaskStatus.NEW.value,
                      due_date: datetime | None = None) -> Task:
    """
    Создает новую задачу в указанном проекте.

    Автоматически вычисляет следующий task_id_in_project.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, к которому относится задача.
    :param creator_user_id: ID пользователя, который создал задачу.
    :param title: Название задачи.
    :param description: Описание задачи.
    :param chat_id_created_in: ID чата, в котором создана задача.
    :param assignee_user_id: ID пользователя-исполнителя. Не указывается если у задачи нет конкретного исполняющего
    :param status: Статус задачи (строка из TaskStatus enum), по умолчанию "new".
    :param due_date: Срок выполнения задачи.
    :return: Созданный объект Task.

    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если создатель или исполнитель (если указан) не найден.
    :raises ChatNotFoundError: Если чат создания не найден.
    :raises InvalidTaskStatusError: Если указан недопустимый статус.
    :raises DatabaseError: При других ошибках базы данных.
    """

    await get_project_by_id(session, project_id)
    await get_user_by_id(session, creator_user_id)
    await get_chat_by_chat_id(session, chat_id_created_in)
    if assignee_user_id is not None:
        await get_user_by_id(session, assignee_user_id)

    valid_statuses = [s.value for s in TaskStatus]
    if status not in valid_statuses:
        raise InvalidTaskStatusError(status=status, valid_statuses=valid_statuses)

    next_task_id_in_project = await _get_next_task_id_in_project(session, project_id)

    try:
        db_task = Task(project_id=project_id, task_id_in_project=next_task_id_in_project, title=title,
                       description=description, status=status, creator_user_id=creator_user_id,
                       assignee_user_id=assignee_user_id, chat_id_created_in=chat_id_created_in, due_date=due_date)
        session.add(db_task)
        await session.commit()
        await session.refresh(db_task)
        return db_task
    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_task_by_id(session: AsyncSession, task_id: int) -> Task: # Убрали | None
    """
    Возвращает объект класса Task по его task_id.

    :param session: Асинхронная сессия SQLAlchemy.
    :param task_id: Внутренний ID задачи.
    :return: Объект класса Task.
    :raises TaskNotFoundError: Если Task с заданным ID не найден.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Task).where(Task.task_id == task_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if task is None:
            raise TaskNotFoundError(identifier=task_id)
        return task
    except SQLAlchemyError as e:

        raise DatabaseError(original_exception=e) from e

async def get_task_by_project_and_task_id_in_project(session: AsyncSession, project_id: int, task_id_in_project: int) -> Task: # Убрали | None
    """
    Возвращает объект Task по ID проекта и ID задачи внутри этого проекта.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param task_id_in_project: Уникальный ID задачи ВНУТРИ проекта.
    :return: Объект Task, если найден.

    :raises TaskNotFoundError: Если Task с заданными project_id и task_id_in_project не найден.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Task).where(Task.project_id == project_id, Task.task_id_in_project == task_id_in_project)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if task is None:
            raise TaskNotFoundError(identifier=f"project_id={project_id}, task_id_in_project={task_id_in_project}")
        return task
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_tasks_for_project(session: AsyncSession, project_id: int, status: str | None = None, assignee_user_id: int | None = None) -> list[Task]:
    """
    Возвращает список задач для указанного проекта с возможностью фильтрации по статусу и/или назначенному исполнителю.

    Если какой-либо из фильтров (status, assignee_user_id) не указан, он не применяется при поиске.
    Возвращает пустой список, если проект существует, но задач нет или ни одна не соответствует фильтрам.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта, задачи которого нужно получить.
    :param status: Статус выполнения задачи (для фильтрации).
    :param assignee_user_id: Уникальный ID пользователя-исполнителя (для фильтрации).
    :return: Список объектов Task, удовлетворяющих условиям (может быть пустым).
    # :raises ProjectNotFoundError: Если проект с таким ID не найден (опционально, если добавить проверку).
    :raises DatabaseError: При ошибках базы данных во время запроса.
    """
    await get_project_by_id(session, project_id)
    try:
        query = select(Task)
        query = query.where(Task.project_id == project_id)
        if status is not None:
            query = query.where(Task.status == status)
        if assignee_user_id is not None:
            query = query.where(Task.assignee_user_id == assignee_user_id)
        query = query.order_by(Task.task_id_in_project)
        result = await session.execute(query)
        tasks_list = result.scalars().all()
        return tasks_list
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_tasks_assigned_to_user(session: AsyncSession, assignee_user_id: int, project_id: int | None = None,
                                     status: str | None = None) -> list[Task]:
    """
    Возвращает список задач, назначенных указанному пользователю.

    Позволяет дополнительно фильтровать задачи по конкретному проекту и/или статусу выполнения. Возвращает пустой
    список, если у пользователя нет назначенных задач или ни одна не соответствует фильтрам.

    :param session: Асинхронная сессия SQLAlchemy.
    :param assignee_user_id: Уникальный ID пользователя-исполнителя, задачи которого нужно найти.
    :param project_id: Уникальный ID проекта для фильтрации (опционально).
    :param status: Статус выполнения задачи для фильтрации (опционально).
    :return: Список объектов Task, удовлетворяющих условиям (может быть пустым).
    :raises UserNotFoundError: Если пользователь-исполнитель не найден.
    :raises ProjectNotFoundError: Если project_id указан и проект не найден.
    :raises DatabaseError: При ошибках базы данных во время запроса.
    """
    await get_user_by_id(session, assignee_user_id)
    if project_id is not None:
        await get_project_by_id(session, project_id)

    try:
        query = select(Task)
        query = query.where(Task.assignee_user_id == assignee_user_id)
        if project_id is not None:
            query = query.where(Task.project_id == project_id)
        if status is not None:
            query = query.where(Task.status == status)
        query = query.order_by(Task.project_id, Task.task_id_in_project)
        result = await session.execute(query)
        tasks_list = result.scalars().all()
        return tasks_list
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_task_global_id(session: AsyncSession, project_id: int, task_id_in_project: int) -> int:
    """
    Получает глобальный ID (первичный ключ) задачи по ID проекта и ID задачи внутри этого проекта.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: Уникальный ID проекта.
    :param task_id_in_project: Уникальный ID задачи ВНУТРИ указанного проекта.
    :return: Глобальный ID задачи (task_id).
    :raises TaskNotFoundError: Если Task с заданными project_id и task_id_in_project не найден.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Task.task_id).where(Task.project_id == project_id, Task.task_id_in_project == task_id_in_project)
        result = await session.execute(query)
        global_task_id = result.scalar_one_or_none()
        if global_task_id is None:
            raise TaskNotFoundError(identifier=f"project_id={project_id}, task_id_in_project={task_id_in_project}")
        return global_task_id
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e


async def update_task(session: AsyncSession, task_id: int, title: str | None = None, description: str | None = None,
                      status: str | None = None, assignee_user_id: int | None = sentinel,
                      due_date: datetime | None = sentinel) -> Task:
    """
    Обновляет указанные поля задачи по её глобальному ID.

    Позволяет обновлять: title, description, status, assignee_user_id, due_date.
    Чтобы снять исполнителя или срок, передайте assignee_user_id=None или due_date=None соответственно.
    Если параметр не передан (оставлен по умолчанию sentinel), соответствующее поле не изменяется.

    Автоматически обновляет поле completed_at при изменении статуса на завершенный или с завершенного.

    :param session: Асинхронная сессия SQLAlchemy.
    :param task_id: Глобальный ID задачи для обновления (первичный ключ).
    :param title: Новое название задачи (если нужно изменить).
    :param description: Новое описание задачи (если нужно изменить).
    :param status: Новый статус задачи (если нужно изменить). Ожидается строка из TaskStatus enum.
    :param assignee_user_id: Новый ID исполнителя. Передайте None, чтобы снять исполнителя. Используйте sentinel (значение по умолчанию), чтобы не изменять исполнителя.
    :param due_date: Новый срок выполнения. Передайте None, чтобы убрать срок. Используйте sentinel (значение по умолчанию), чтобы не изменять срок.
    :return: Обновленный объект Task.

    :raises TaskNotFoundError: Если Task с заданным ID не найден.
    :raises InvalidTaskStatusError: Если указан недопустимый статус.
    :raises UserNotFoundError: Если assignee_user_id указан (не None) и пользователь не найден.
    :raises DatabaseError: При других ошибках базы данных во время получения или сохранения.
    """
    try:
        task = await session.get(Task, task_id)
        if not task:
            raise TaskNotFoundError(identifier=task_id)

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

    updated = False
    previous_status = task.status

    if title is not None and task.title != title:
        task.title = title
        updated = True

    if description is not None and task.description != description:
        task.description = description
        updated = True

    if status is not None:
        if task.status != status:
            valid_statuses = [item.value for item in TaskStatus]
            if status not in valid_statuses:
                raise InvalidTaskStatusError(status=status, valid_statuses=valid_statuses)
            task.status = status
            updated = True

    if assignee_user_id is not sentinel:
        if task.assignee_user_id != assignee_user_id:
            if assignee_user_id is not None:
                 try:
                     await get_user_by_id(session, assignee_user_id)
                 except UserNotFoundError:
                     raise UserNotFoundError(user_id=assignee_user_id)
                 except DatabaseError:
                     raise
            task.assignee_user_id = assignee_user_id
            updated = True

    if due_date is not sentinel:
        if task.due_date != due_date:
            task.due_date = due_date
            updated = True

    is_now_completed = (task.status == TaskStatus.COMPLETED.value)
    was_before_completed = (previous_status == TaskStatus.COMPLETED.value)

    if is_now_completed and not was_before_completed:
        task.completed_at = func.now()
        updated = True
    elif not is_now_completed and was_before_completed:
        task.completed_at = None
        updated = True
    if updated:
        try:
            await session.commit()
            await session.refresh(task)
        except (IntegrityError, SQLAlchemyError) as e:
             await session.rollback()
             raise DatabaseError(original_exception=e) from e
    return task

async def delete_task(session: AsyncSession, task_id: int) -> None:
    """
    Удаляет задание по его глобальному task_id.

    :param session: Асинхронная сессия SQLAlchemy.
    :param task_id: Глобальный ID задачи для удаления (первичный ключ).
    :return: None в случае успеха. # Изменили описание возврата
    :raises TaskNotFoundError: Если Task с заданным ID не найден.
    :raises DatabaseError: При других ошибках базы данных во время удаления.
    """
    try:
        task = await session.get(Task, task_id)

        if not task:
            raise TaskNotFoundError(identifier=task_id)

        await session.delete(task)
        await session.commit()
    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def create_invite(session: AsyncSession, project_id: int, generated_by_user_id: int, invite_code: str,
                        max_uses: int | None = 1, expires_at: datetime | None = None) -> Invites:
    """
    Создает новое приглашение для проекта с заданными параметрами.

    Предполагается, что invite_code уже сгенерирован. Max_uses может быть None, то есть бесконечное использование.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, для которого создается инвайт.
    :param generated_by_user_id: ID пользователя, создающего инвайт.
    :param invite_code: Уникальный код приглашения.
    :param max_uses: Максимальное количество использований инвайта (None для бесконечности).
    :param expires_at: Дата и время истечения срока действия инвайта (None для бессрочного инвайта).
    :return: Объект класса Invites, если успешно.

    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь-создатель не найден.
    :raises InviteCodeConflictError: Если инвайт с таким кодом уже существует.
    :raises DatabaseError: При других ошибках базы данных.
    """
    await get_project_by_id(session, project_id)
    await get_user_by_id(session, generated_by_user_id)

    try:
        db_invite = Invites(project_id=project_id, generated_by_user_id=generated_by_user_id, invite_code=invite_code,
                            max_uses=max_uses, expires_at=expires_at)
        session.add(db_invite)
        await session.commit()
        await session.refresh(db_invite)
        return db_invite
    except IntegrityError as e:
        await session.rollback()
        raise InviteCodeConflictError(invite_code=invite_code) from e
    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_invite_by_code(session: AsyncSession, invite_code: str) -> Invites:
    """
    Получает объект класса Invites по введенному коду приглашения.

    :param session: Асинхронная сессия SQLAlchemy.
    :param invite_code: Уникальный код приглашения.
    :return: Объект класса Invites, если он был найден.
    :raises InviteNotFoundError: Если Invites по заданному коду не найден.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Invites).where(Invites.invite_code == invite_code)
        result = await session.execute(query)
        invite = result.scalar_one_or_none()

        if invite is None:
            raise InviteNotFoundError(invite_code=invite_code)

        return invite

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_invite_by_id(session: AsyncSession, invite_id: int) -> Invites:
    """
    Получает объект класса Invites по ID инвайта.

    :param session: Асинхронная сессия SQLAlchemy.
    :param invite_id: Уникальный ID приглашения.
    :return: Объект класса Invites, если он был найден.
    :raises InviteNotFoundError: Если Invites по заданному ID не найден.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Invites).where(Invites.invite_id == invite_id)
        result = await session.execute(query)
        invite = result.scalar_one_or_none()

        if invite is None:
            raise InviteNotFoundError(invite_code=str(invite_id))
            return

        return invite

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def increment_invite_uses(session: AsyncSession, invite_code: str) -> Invites:
    """
    Увеличивает счетчик использований для инвайта по заданному коду.

    Проверяет, не превышен ли лимит использований до увеличения.

    :param session: Асинхронная сессия SQLAlchemy.
    :param invite_code: Уникальный код приглашения.
    :return: Обновленный объект класса Invites.

    :raises InviteNotFoundError: Если инвайт по указанному коду не найден.
    :raises InviteMaxUsesReachedError: Если лимит использований инвайта уже превышен.
    :raises DatabaseError: При других ошибках базы данных.
    """
    try:
        invite = await get_invite_by_code(session, invite_code)
    except (InviteNotFoundError, DatabaseError):
        raise

    invite.current_uses += 1

    if invite.max_uses is not None and invite.current_uses >= invite.max_uses:
        await session.commit()
        await session.refresh(invite)
        raise InviteMaxUsesReachedError(invite_code=invite_code)


    try:
        await session.commit()
        await session.refresh(invite)
        return invite
    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def delete_invite_by_code(session: AsyncSession, invite_code: str) -> None:
    """
    Удаляет приглашение по его invite_code.

    :param session: Асинхронная сессия SQLAlchemy.
    :param invite_code: Уникальный код приглашения для удаления.
    :return: None в случае успеха.
    :raises InviteNotFoundError: Если инвайт с таким кодом не найден.
    :raises DatabaseError: При других ошибках базы данных во время получения или удаления.
    """
    invite = await get_invite_by_code(session, invite_code)

    try:
        await session.delete(invite)
        await session.commit()

    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def delete_invite_by_id(session: AsyncSession, invite_id: int):
    """
    Удаляет приглашение по его ID.

    :param session: Асинхронная сессия SQLAlchemy.
    :param invite_code: ID приглашения для удаления.
    :return: None в случае успеха.
    :raises InviteNotFoundError: Если инвайт с таким ID не найден.
    :raises DatabaseError: При других ошибках базы данных во время получения или удаления.
    """
    invite = await get_invite_by_id(session=session, invite_id=invite_id)
    try:
        await session.delete(invite)
        await session.commit()

    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e


async def create_chat(session: AsyncSession, chat_id: int, chat_type: str, chat_title: str | None = None) -> Chat:
    """
    Создаёт объект класса Chat по заданным аргументам.

    :param session: Асинхронная сессия SQLAlchemy.
    :param chat_id: Уникальный chat_id из Telegram.
    :param chat_title: Название чата из Telegram.
    :param chat_type: Тип чата из Telegram. ('group', 'private', 'supergroup')
    :return: Объект класса Chat, если он был успешно создан.

    :raises ChatAlreadyExistsError: Если чат с таким chat_id уже существует.
    :raises DatabaseError: При других ошибках базы данных.
    """
    try:
        db_chat = Chat(chat_id=chat_id, title=chat_title, type=chat_type)
        session.add(db_chat)
        await session.commit()
        await session.refresh(db_chat)
        return db_chat

    except IntegrityError as e:
        await session.rollback()
        raise ChatAlreadyExistsError(chat_id=chat_id) from e

    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_chat_by_chat_id(session: AsyncSession, chat_id: int) -> Chat: # Убрали | None
    """
    Ищет чат по заданному chat_id.

    :param session: Асинхронная сессия SQLAlchemy.
    :param chat_id: Уникальный chat_id из Telegram.
    :return: Объект класса Chat, если он был найден.
    :raises ChatNotFoundError: Если чат с заданным chat_id не существует.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    try:
        query = select(Chat).where(Chat.chat_id == chat_id)
        result = await session.execute(query)
        chat = result.scalar_one_or_none()

        if chat is None:
            raise ChatNotFoundError(chat_id=chat_id) # <-- ИЗМЕНЕНО

        return chat

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def handle_invite_acceptance(session: AsyncSession, accepting_user_id: int, invite_code: str) -> ProjectMember:
    """
    Обрабатывает принятие приглашения пользователем.

    :param session: Асинхронная сессия SQLAlchemy.
    :param accepting_user_id: ID пользователя, принимающего приглашение.
    :param invite_code: Код приглашения.
    :return: Объект ProjectMember при успехе.
    :raises InviteNotFoundError: Если инвайт с таким кодом не найден (от get_invite_by_code).
    :raises InviteExpiredError: Если срок действия инвайта истек.
    :raises InviteMaxUsesReachedError: Если лимит использований инвайта уже превышен (от проверки здесь или increment_invite_uses).
    :raises UserNotFoundError: Если пользователь, принимающий инвайт, не найден (от get_user_by_id).
    :raises ProjectNotFoundError: Если проект инвайта не найден (может быть от get_project_member или add_member_to_project).
    :raises UserAlreadyMemberError: Если пользователь уже является участником проекта (от get_project_member или add_member_to_project).
    :raises OwnerCannotBeMemberError: Если пользователь является владельцем проекта (от add_member_to_project).
    :raises DatabaseError: При других ошибках базы данных во время любой операции.
    """
    invite = await get_invite_by_code(session, invite_code)

    now = datetime.now(timezone.utc)
    if invite.expires_at is not None and invite.expires_at < now:
        raise InviteExpiredError(invite_code=invite_code)

    if invite.max_uses is not None and invite.current_uses >= invite.max_uses:
        raise InviteMaxUsesReachedError(invite_code=invite_code)

    await get_user_by_id(session, accepting_user_id)

    try:
        existing_membership = await get_project_member(session, invite.project_id, accepting_user_id)
        if existing_membership:
            raise UserAlreadyMemberError(user_id=accepting_user_id, project_id=invite.project_id)
    except MemberNotFoundError:
        pass
    except (ProjectNotFoundError, UserNotFoundError, DatabaseError):
        raise

    new_membership = await add_member_to_project(session=session, user_id=accepting_user_id,
                                                 project_id=invite.project_id, role=UserRole.MEMBER.value)
    updated_invite = await increment_invite_uses(session, invite_code)
    invite_exhausted = (updated_invite.max_uses is not None and
                       updated_invite.current_uses >= updated_invite.max_uses)
    if invite_exhausted:
        await delete_invite_by_code(session, invite_code)
    return new_membership


async def add_chat_to_project(session: AsyncSession, project_id: int, chat_id: int) -> None:
    """
    Связывает существующий чат с существующим проектом.

    Работает через relationship Project.chats и ассоциативную таблицу.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, к которому нужно привязать чат.
    :param chat_id: ID чата, который нужно привязать к проекту.
    :return: None, если связь успешно установлена.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises ChatNotFoundError: Если чат не найден.
    :raises ChatAlreadyLinkedToProjectError: Если чат уже связан с этим проектом.
    :raises DatabaseError: При других ошибках базы данных во время получения или сохранения.
    """
    project = await get_project_by_id(session, project_id)
    chat = await get_chat_by_chat_id(session, chat_id)

    if chat in project.chats:
        raise ChatAlreadyLinkedToProjectError(chat_id=chat_id, project_id=project_id)

    project.chats.append(chat)
    try:
        await session.commit()

    except (IntegrityError, SQLAlchemyError) as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def remove_chat_from_project(session: AsyncSession, project_id: int, chat_id: int) -> None:
    """
    Удаляет связь между существующим чатом и существующим проектом.

    Работает через relationship Project.chats и ассоциативную таблицу.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, от которого нужно отвязать чат.
    :param chat_id: ID чата, который нужно отвязать от проекта.
    :return: None, если связь успешно удалена или ее не существовало.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises ChatNotFoundError: Если чат не найден (опционально).
    :raises ChatNotLinkedToProjectError: Если чат не был связан с этим проектом.
    :raises DatabaseError: При других ошибках базы данных во время получения или сохранения.
    """
    project = await get_project_by_id(session, project_id)

    chat_to_remove = None
    for chat in project.chats:
        if chat.chat_id == chat_id:
            chat_to_remove = chat
            break

    if chat_to_remove is None:
        raise ChatNotLinkedToProjectError(chat_id=chat_id, project_id=project_id)

    project.chats.remove(chat_to_remove)

    try:
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        raise DatabaseError(original_exception=e) from e

async def get_chats_for_project(session: AsyncSession, project_id: int) -> list[Chat]:
    """
    Получает список всех чатов, связанных с указанным проектом.

    Возвращает пустой список, если проект существует, но с ним не связано ни одного чата.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, чаты которого нужно получить.
    :return: Список объектов Chat, связанных с проектом (может быть пустым).
    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises DatabaseError: При ошибках базы данных во время запроса.
    """
    try:
        query = select(Project).where(Project.project_id == project_id).options(selectinload(Project.chats))

        result = await session.execute(query)
        project = result.scalar_one_or_none()

        if project is None:
            raise ProjectNotFoundError(project_id=project_id)

        return project.chats
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def is_user_project_member(session: AsyncSession, project_id: int, user_id: int) -> bool:
    """
    Проверяет, является ли пользователь участником указанного проекта (исключая владельца).
    Выполняет запрос на существование записи в таблице ProjectMember.

    Возвращает False, если пользователь не является участником (или не существует, или проект не существует).

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта для проверки.
    :param user_id: ID пользователя для проверки.
    :return: True, если пользователь является участником проекта, иначе False.
    :raises ProjectNotFoundError: Если проект не найден.
    :raises UserNotFoundError: Если пользователь не найден.
    :raises DatabaseError: При ошибках базы данных во время запроса.
    """
    await get_project_by_id(session, project_id)
    await get_user_by_id(session, user_id)


    try:
        query = select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id == project_id,
                                                                      ProjectMember.user_id == user_id)
        result = await session.execute(query)
        count = result.scalar_one()

        return count > 0

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_user_project_role(session: AsyncSession, project_id: int, user_id: int) -> str:
    """
    Получает роль пользователя в указанном проекте.

    Проверяет существование проекта и пользователя перед поиском записи о членстве.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта.
    :param user_id: ID пользователя.
    :return: Роль пользователя в проекте.
    :raises ProjectNotFoundError: Если проект с указанным ID не найден.
    :raises UserNotFoundError: Если пользователь с указанным ID не найден.
    :raises MemberNotFoundError: Если пользователь не является участником указанного проекта (нет записи о членстве)
                                   для существующих проекта и пользователя.
    :raises DatabaseError: При других ошибках базы данных во время запроса.
    """
    await get_project_by_id(session, project_id)
    await get_user_by_id(session, user_id)

    try:
        query = select(ProjectMember.role).where(ProjectMember.project_id == project_id,
                                                 ProjectMember.user_id == user_id)

        result = await session.execute(query)
        role = result.scalar_one_or_none()

        if role is None:
            raise MemberNotFoundError(project_id=project_id, user_id=user_id)

        return role

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e


async def get_users_in_project(session: AsyncSession, project_id: int) -> list[User]:
    """
    Получает список объектов User, которые являются участниками указанного проекта (исключая владельца, если он не добавлен как участник).

    Возвращает пустой список, если проект существует, но у него нет участников.

    :param session: Асинхронная сессия SQLAlchemy.
    :param project_id: ID проекта, участников которого нужно получить.
    :return: Список объектов User, являющихся участниками проекта (может быть пустым).
    :raises ProjectNotFoundError: Если проект с таким ID не найден.
    :raises DatabaseError: При ошибках базы данных во время запроса.
    """
    await get_project_by_id(session, project_id)

    try:
        query = (select(User).join(ProjectMember, User.user_id == ProjectMember.user_id)
                 .where(ProjectMember.project_id == project_id).order_by(User.first_name, User.username))
        result = await session.execute(query)
        users_list = result.scalars().all()
        return users_list

    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e

async def get_user_projects_with_roles(session: AsyncSession, user_id: int) -> list[tuple[Project, str]]:
    """
    Получает список всех проектов, в которых пользователь участвует (владелец или участник),
    и его роль в каждом проекте.

    Объединяет проекты, где пользователь является владельцем, и проекты, где он участник,
    определяя финальную роль пользователя в каждом проекте.

    Возвращает список кортежей (Project, role_string).
    Если пользователь не участвует ни в одном проекте, возвращает пустой список.

    :param session: Асинхронная сессия SQLAlchemy.
    :param user_id: ID пользователя Telegram.
    :return: Список кортежей (Project, role_string), где role_string - это строковое представление роли ('owner', 'helper', 'member').
    :raises DatabaseError: При ошибках базы данных.
    """
    try:
        query_1 = select(ProjectMember).where(ProjectMember.user_id == user_id).options(selectinload(ProjectMember.project).selectinload(Project.owner))
        memberships_results = await session.execute(query_1)
        memberships = memberships_results.scalars().all()

        query_2 = select(Project).where(Project.owner_user_id == user_id).options(selectinload(Project.owner))
        owned_projects_results = await session.execute(query_2)
        owned_projects = owned_projects_results.scalars().all()

        projects_with_roles = []
        processed_project_ids = set()

        for membership in memberships:
            project = membership.project
            role = membership.role

            if project.project_id not in processed_project_ids:
                 projects_with_roles.append((project, role))
                 processed_project_ids.add(project.project_id)

        for project in owned_projects:
             if project.project_id not in processed_project_ids:
                  projects_with_roles.append((project, UserRole.OWNER.value))
                  processed_project_ids.add(project.project_id)
        return projects_with_roles
    except SQLAlchemyError as e:
        raise DatabaseError(original_exception=e) from e
