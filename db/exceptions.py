class CrudError(Exception):
    def __init__(self, message: str = "Произошла ошибка при работе с базой данных"):
        self.message = message
        super().__init__(self.message)

class NotFoundError(CrudError):
    def __init__(self, entity_name: str, identifier):
        self.entity_name = entity_name
        self.identifier = identifier
        message = f"{entity_name} с идентификатором '{identifier}' не найден(а)."
        super().__init__(message)

class UserNotFoundError(NotFoundError):
    def __init__(self, user_id: int):
        super().__init__("Пользователь", user_id)

class ProjectNotFoundError(NotFoundError):
    def __init__(self, project_id: int):
        super().__init__("Проект", project_id)

class MemberNotFoundError(NotFoundError):
    def __init__(self, project_id: int, user_id: int):
        super().__init__("Участник проекта", f"(project={project_id}, user={user_id})")

class TaskNotFoundError(NotFoundError):
    def __init__(self, identifier):
        super().__init__("Задача", identifier)

class InviteNotFoundError(NotFoundError):
    def __init__(self, invite_code: str):
        super().__init__("Приглашение", invite_code)

class ChatNotFoundError(NotFoundError):
    def __init__(self, chat_id: int):
        super().__init__("Чат", chat_id)


class ConflictError(CrudError):
    """Базовый класс для ошибок конфликта данных или состояния."""
    pass

class ProjectNameConflictError(ConflictError):
    def __init__(self, name: str):
        self.name = name
        message = f"Проект с названием '{name}' уже существует."
        super().__init__(message)

class UserAlreadyMemberError(ConflictError):
    def __init__(self, user_id: int, project_id: int):
        self.user_id = user_id
        self.project_id = project_id
        message = f"Пользователь {user_id} уже является участником проекта {project_id}."
        super().__init__(message)

class InviteCodeConflictError(ConflictError):
    def __init__(self, invite_code: str):
        self.invite_code = invite_code
        message = f"Приглашение с кодом '{invite_code}' уже существует."
        super().__init__(message)

class ChatAlreadyExistsError(ConflictError):
     def __init__(self, chat_id: int):
        self.chat_id = chat_id
        message = f"Чат с ID '{chat_id}' уже существует."
        super().__init__(message)

class UserAlreadyExistsError(ConflictError):
    def __init__(self, user_id: int):
        self.user_id = user_id
        message = f"Пользователь с ID '{user_id} уже существует.'"
        super().__init__(message)

class UserAlreadyProjectOwner(ConflictError):
    def __init__(self, user_id: int, project_id: int):
        self.user_id = user_id
        self.project_id = project_id
        message = f"Пользователь с ID '{user_id}' уже является владельцем проекта с ID '{project_id}'"
        super().__init__(message)


class InviteExpiredError(ConflictError):
    def __init__(self, invite_code: str):
        self.invite_code = invite_code
        message = f"Срок действия приглашения '{invite_code}' истек."
        super().__init__(message)

class InviteMaxUsesReachedError(ConflictError):
    def __init__(self, invite_code: str):
        self.invite_code = invite_code
        message = f"Приглашение '{invite_code}' достигло лимита использований."
        super().__init__(message)

class InvalidTaskStatusError(ConflictError):
    def __init__(self, status: str, valid_statuses: list):
        self.status = status
        self.valid_statuses = valid_statuses
        message = f"Недопустимый статус задачи: '{status}'. Допустимые статусы: {', '.join(valid_statuses)}."
        super().__init__(message)

class OwnerCannotBeMemberError(ConflictError):
    def __init__(self, user_id: int, project_id: int):
        self.user_id = user_id
        self.project_id = project_id
        message = f"Пользователь {user_id} является владельцем проекта {project_id} и не может быть добавлен как участник."
        super().__init__(message)

class ChatAlreadyLinkedToProjectError(ConflictError):
    def __init__(self, chat_id: int, project_id: int):
        self.chat_id = chat_id
        self.project_id = project_id
        message = f"Чат {chat_id} уже связан с проектом {project_id}."
        super().__init__(message)

class ChatNotLinkedToProjectError(ConflictError):
    def __init__(self, chat_id: int, project_id: int):
        self.chat_id = chat_id
        self.project_id = project_id
        message = f"Чат {chat_id} не связан с проектом {project_id}."
        super().__init__(message)


class DatabaseError(CrudError):
    def __init__(self, original_exception: Exception | None = None):
        self.original_exception = original_exception
        message = "Произошла внутренняя ошибка базы данных."
        if original_exception:
            message += f" ({type(original_exception).__name__})"
        super().__init__(message)
