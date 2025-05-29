import enum
import html
import logging
from datetime import datetime, timezone

from telebot import types
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_handler_backends import State, StatesGroup
from telebot.asyncio_helper import ApiTelegramException
from telebot.asyncio_storage import memory_storage
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import crud
from db.database import AsyncSessionLocal
from db.exceptions import *
from db.models import (Invites, Project, ProjectMember, TaskStatus, User,
                       UserRole)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MyStates(StatesGroup):
    SET_NEW_NAME = "set_new_name"
    SET_NEW_DESCRIPTION = "set_new_description"

class TaskCreationStates(StatesGroup):
    set_title = State()
    set_description = State()
    set_assignee = State()
    set_due_date = State()


class ManageMemberActions(enum.Enum):
    SH0W_MENU = "show_menu"
    CONFIRM_KICK = "confirm_kick"
    EXECUTE_KICK = "execute_kick"
    CONFIRM_TRANSFER = "confirm_transfer"
    EXECUTE_TRANSFER = "execute_transfer"
    PROMOTE_MEMBER = "promote_member"
    DEMOTE_MEMBER = "demote_member"

class ManageProjectMenuActions(enum.Enum):
    SHOW_MENU = "show_menu"
    CHANGE_NAME = "change_name"
    CHANGE_DESCRIPTION = "change_description"
    CONFIRM_DELETE = "confirm_delete"
    EXECUTE_DELETE = "execute_delete"
    CANCEL = "cancel"

class ManageInviteMenuActions(enum.Enum):
    SHOW_MENU = "show_menu"
    EXECUTE_DELETE = "execute_delete"


def escape_html(text: str) -> str:
    escaped_text = html.escape(text, quote=True)
    escaped_text_for_telegram = escaped_text.replace('|', '&#124;')
    return escaped_text_for_telegram

async def create_user_link(user_id: int, user_name: str, username: str | None = None) -> str:
    escaped_name = escape_html(user_name)
    link_html = f"<a href='tg://user?id={user_id}'>{escaped_name}</a>"

    return link_html


async def handle_start(message: types.Message, bot: AsyncTeleBot):
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_data = message.from_user
    chat_id = message.chat.id

    command_parts = message.text.split(" ")

    escaped_user_name = escape_html(user_name)

    try:
        async with AsyncSessionLocal() as session:
            db_user = await crud.get_or_create_and_update_user(session=session, user_id=user_data.id, username=user_data.username, 
                                                               first_name=user_data.first_name, is_bot=user_data.is_bot)
            db_chat = await crud.create_chat(session=session, chat_id=chat_id, chat_type=message.chat.type, chat_title=message.chat.first_name)
            user_name_from_db = db_user.first_name
        if len(command_parts) == 2:
            invite_code = command_parts[1]
            async with AsyncSessionLocal() as session:
                invite = await crud.get_invite_by_code(session=session, invite_code=invite_code)
                if not invite.max_uses or invite.current_uses < invite.max_uses:
                    new_member = await crud.add_member_to_project(session=session, user_id=user_id, project_id=invite.project_id)
                    project = await crud.get_project_by_id(session=session, project_id=invite.project_id)
                    escaped_project_name = project.name
                    top_message = (f"{escaped_user_name}, вы были добавлены в проект {escaped_project_name} (ID проекта {project.project_id})\n"\
                                   f"Получить информацию о данном проекте вы можете по команде <code>/view_project {project.project_id}</code>")
                    try:
                        await crud.increment_invite_uses(session=session, invite_code=invite.invite_code)
                    except InviteMaxUsesReachedError:
                        await bot.send_message(invite.generated_by_user_id, f"Инвайт с кодом <code>{invite.invite_code}</code> достиг лимита", parse_mode="HTML")
                else:
                    await bot.send_message(user_id, f"Этот инвайт больше не действителен")
        else:

            top_message = f"Приветствую, {escaped_user_name}! \n\n" + \
                f"Я твой помощник по управлению проектами. Я помогу тебе создавать проекты, \n" + \
                f"добавлять участников, ставить задачи и отслеживать их выполнение."
        await bot.send_message(chat_id, top_message, parse_mode="HTML")
    except (DatabaseError, UserNotFoundError) as e:
         await bot.send_message(user_id, "Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже.")
    except InviteNotFoundError:
        await bot.send_message(user_id, f"Этот инвайт больше не действителен")

async def handle_help(message: types.Message, bot: AsyncTeleBot):
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_data = message.from_user
    try:
        async with AsyncSessionLocal() as session:
            db_user = await crud.get_or_create_and_update_user(session=session, user_id=user_data.id, username=user_data.username, 
                                                               first_name=user_data.first_name, is_bot=user_data.is_bot)
            user_name_from_db = db_user.first_name
        help_message = "Потом сделаю мне лень"

        await bot.send_message(user_id, help_message, parse_mode="HTML")
    except (DatabaseError, UserNotFoundError) as e:
         await bot.send_message(user_id, "Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже.")

async def handle_create_project(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await bot.send_message(message.chat.id,
            "Вы неправильно используете команду. \nЧтобы создать новый проект, введите команды в формате:\n"
            "<code>/create_project НазваниеПроекта | Описание</code>. НазваниеПроекта обязательно, описание опционально.",
            parse_mode="HTML")
        return

    args_string = command_parts[1]
    name_description_parts = args_string.split('|', maxsplit=1)

    project_name = name_description_parts[0].strip()
    escaped_project_name = escape_html(project_name)
    project_description = name_description_parts[1].strip() if len(name_description_parts) > 1 else None

    if not project_name:
        await bot.send_message(message.chat.id, "Название проекта не может быть пустым.")
        return

    try:
        async with AsyncSessionLocal() as session:
            new_project = await crud.create_project(session=session, owner_user_id=user_id, name=project_name, description=project_description)

        await bot.send_message(message.chat.id, f"Вы успешно создали новый проект!\n"
                               f"Название проекта: {escaped_project_name}\n"""
                               f"ID проекта: {new_project.project_id}\n"
                               f"ID владельца проекта: {new_project.owner_user_id}\n\n"
                               f"Все команды для управления проектами вы можете найти по команде /help")

    except ProjectNameConflictError:
        await bot.send_message(message.chat.id, f"Ошибка: Проект с названием '{escaped_project_name}' уже существует.")
    except DatabaseError as e:
        await bot.send_message(message.chat.id, "Произошла ошибка при работе с базой данных. Пожалуйста, попробуйте позже.")

async def handle_delete_project(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id

    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2:
        await bot.send_message(chat_id,
            "Вы неправильно используете команду. \nЧтобы удалить проект, введите:\n"
            "<code>/delete_project ID_проекта</code>",
            parse_mode="HTML")
        return

    project_id_str = command_parts[1].strip()

    try:
        project_id = int(project_id_str)
    except ValueError:
        await bot.send_message(chat_id, f"ID проекта должен быть числом. Вы указали: <code>{project_id_str}</code>", parse_mode='HTML')
        return

    try:
        async with AsyncSessionLocal() as session:
            project_to_delete = await crud.get_project_by_id(session, project_id)
            if project_to_delete.owner_user_id != user_id:
                await bot.send_message(chat_id,
                    f"У вас нет прав на удаление проекта с ID <code>{project_id}</code>. Только владелец может удалить проект.",
                    parse_mode='HTML')
                return

            await crud.delete_project(session, project_id)
        escaped_project_name = escape_html(project_to_delete.name)
        await bot.send_message(chat_id, f"✅ Проект <code>{escaped_project_name}</code> (ID: <code>{project_id}</code>) успешно удален.", 
                               parse_mode="HTML")

    except ProjectNotFoundError:
        await bot.send_message(chat_id, f"Проект с ID <code>{project_id}</code> не существует.", parse_mode="HTML")
    except DatabaseError as e:
        await bot.send_message(chat_id, "Произошла ошибка при работе с базой данных во время удаления проекта. Пожалуйста, попробуйте позже.")

async def handle_view_project(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await bot.send_message(chat_id, "Вы неправильно используете команду. \nЧтобы просмотреть проект, введите:\n<code>/view_project ID_проекта</code>", parse_mode="HTML")
        return

    project_id_str = command_parts[1].strip()

    try:
        project_id = int(project_id_str)
    except ValueError:
        await bot.send_message(chat_id, f"Ошибка: ID проекта должен быть числом. Получено: <code>{project_id_str}</code>", parse_mode='HTML')
        return

    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session, project_id)

            user_role_in_project = None
            is_owner = (project.owner_user_id == user_id)

            if is_owner:
                user_role_in_project = UserRole.OWNER.value
            else:
                 try:
                      user_role_in_project = await crud.get_user_project_role(session, project_id, user_id)
                 except MemberNotFoundError:
                      await bot.send_message(chat_id, f"У вас нет доступа к проекту с ID <code>{project_id}</code>. Вы должны быть участником или владельцем этого проекта.", parse_mode='HTML')
                      return

            project_owner: User = project.owner
            owner_info = f"Владелец: {await create_user_link(user_id=project_owner.user_id, user_name=project_owner.first_name, username=project_owner.username)})"

            message_text = f"<b>Проект: {escape_html(project.name)}</b> (ID: <code>{project.project_id}</code>)\n" \
               f"{owner_info}\n" \
               f"Ваша роль: <b>{user_role_in_project.capitalize()}</b>\n" \
               f"Создан: {project.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            if project.description is not None:
                message_text += f"Описание: {escape_html(project.description)}"
            markup = InlineKeyboardMarkup()

            markup.add(InlineKeyboardButton("🔎 Посмотреть мои задачи в этом проекте", callback_data=f"view_my_tasks_in_project:{project_id}"))

            if user_role_in_project in [UserRole.HELPER.value, UserRole.OWNER.value]:
                 markup.add(InlineKeyboardButton("👥 Посмотреть участников", callback_data=f"view_members:{project_id}"))
                 markup.add(InlineKeyboardButton("📋 Посмотреть все задачи", callback_data=f"view_all_tasks:{project_id}"))

            if user_role_in_project == UserRole.OWNER.value:
                 markup.add(InlineKeyboardButton("⚙️ Управление проектом", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.SHOW_MENU.value}"))
                 markup.add(InlineKeyboardButton("✉️ Сгенерировать приглашение", callback_data=f"generate_invite:{project_id}"))

            await bot.send_message(chat_id, message_text, parse_mode="HTML", reply_markup=markup if markup.keyboard else None)

    except ValueError:
        pass
    except ProjectNotFoundError:
        await bot.send_message(chat_id, f"Ошибка: Проект с ID <code>{project_id}</code> не найден.", parse_mode="HTML")
    except (DatabaseError, UserNotFoundError) as e:
        await bot.send_message(chat_id, "Произошла ошибка при работе с базой данных. Пожалуйста, попробуйте позже.")

async def handle_invite(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id

    command_parts = message.text.split(maxsplit=2)

    if len(command_parts) < 2:
        await bot.send_message(chat_id,
            "Вы неправильно используете команду. \nЧтобы сгенерировать приглашение, введите:\n"
            "<code>/invite ID_проекта [Макс_использований]</code>",
            parse_mode="HTML")
        return

    project_id_str = command_parts[1].strip()
    max_uses_str = command_parts[2].strip() if len(command_parts) > 2 else None

    try:
        project_id = int(project_id_str)
    except ValueError:
        await bot.send_message(chat_id,
            f"Ошибка: ID проекта должен быть числом. Получено: <code>{project_id_str}</code>",
            parse_mode='HTML')
        return

    max_uses = None
    if max_uses_str is not None:
        try:
            max_uses = int(max_uses_str)
            if max_uses < 1:
                 await bot.send_message(chat_id,
                     f"Ошибка: Максимальное количество использований должно быть положительным числом (больше 0). Получено: <code>{max_uses_str}</code>",
                     parse_mode='HTML')
                 return
        except ValueError:
            await bot.send_message(chat_id,
                f"Ошибка: Максимальное количество использований должно быть числом. Получено: <code>{max_uses_str}</code>",
                parse_mode='HTML')
            return

    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session, project_id)

            user_role_in_project = None
            is_owner = (project.owner_user_id == user_id)

            if is_owner:
                user_role_in_project = UserRole.OWNER.value
            else:
                 try:
                      user_role_in_project = await crud.get_user_project_role(session, project_id, user_id)
                 except MemberNotFoundError:
                     if project.owner_user_id == user_id:
                         user_role_in_project = UserRole.OWNER.value
                     else:
                         await bot.send_message(chat_id,
                            f"У вас нет прав на генерацию приглашений для проекта с ID <code>{project_id}</code>. Вы должны быть участником с соответствующей ролью.",
                            parse_mode='HTML')
                         return

            if user_role_in_project not in [UserRole.OWNER.value, UserRole.HELPER.value]:
                await bot.send_message(chat_id,
                    f"Ваша роль в проекте с ID <code>{project_id}</code> ({user_role_in_project.capitalize()}) не позволяет генерировать приглашения. Нужна роль owner или helper.",
                    parse_mode='HTML')
                return

            invite_code = None

            while invite_code is None:
                _invite_code = crud.generate_invite_code()
                try:
                    await crud.get_invite_by_code(session=session, invite_code=invite_code)
                except InviteNotFoundError:
                    invite_code = _invite_code

            invite = await crud.create_invite(session=session, project_id=project_id,generated_by_user_id=user_id, max_uses=max_uses, invite_code=invite_code)

        bot_info = await bot.get_me()
        bot_username = bot_info.username

        invite_message_text = f"✅ Приглашение для проекта {escape_html(project.name)} (ID: <code>{project.project_id}</code>) сгенерировано!\n\nКод приглашения: <code>{invite.invite_code}</code>\n\n"

        if max_uses is not None:
            invite_message_text += f"Это приглашение может быть использовано <b>{max_uses}</b> раз(а).\n\n"
        else:
             invite_message_text += "Это приглашение без ограничений по количеству использований.\n\n"


        invite_message_text += (f"Чтобы присоединиться, просто перейдите по ссылке:\n"
                                f"<a href='https://t.me/{bot_username}?start={invite.invite_code}'>Присоединиться к проекту</a>\n\n"
                                f"<i>Этим приглашением можно поделиться.</i>\n"
                                f"Ниже будет представлена сообщение для пересылки пользователям")


        await bot.send_message(chat_id, invite_message_text, parse_mode="HTML")
        invite_message_text = f"Вступай в мой проект {escape_html(invite.project.name)} по ссылке ниже:\n" + \
                               "<a href='https://t.me/{bot_username}?start={invite.invite_code}'>Присоединиться к проекту</a>"
        await bot.send_message(chat_id, invite_message_text, parse_mode="HTML")

    except ValueError:
        pass
    except ProjectNotFoundError:
        await bot.send_message(chat_id, f"Ошибка: Проект с ID <code>{project_id}</code> не найден.", parse_mode="HTML")
    except MemberNotFoundError:
         pass
    except DatabaseError as e:
        await bot.send_message(chat_id,
            "Произошла ошибка при работе с базой данных во время генерации приглашения. Пожалуйста, попробуйте позже.")

async def handle_my_projects(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name

    user_data = message.from_user

    try:
        async with AsyncSessionLocal() as session:
            await crud.get_or_create_and_update_user(session=session, user_id=user_id, username=user_data.username, first_name=user_data.first_name,
                                   is_bot=user_data.is_bot)
            user_projects_with_roles = await crud.get_user_projects_with_roles(session, user_id)

        if not user_projects_with_roles:
            top_message = (f"{escape_html(user_name)}, вы пока что не состоите ни в одном проекте.\n"
                           f"Чтобы создать свой проект используйте команду <code>/create_project</code>\n"
                           f"Чтобы получить помощь воспользуйтесь командой <code>/help</code>")
            await bot.send_message(chat_id, top_message, parse_mode="HTML")

        else:
            owner_projects_text = ""
            helper_projects_text = ""
            member_projects_text = ""

            markup = InlineKeyboardMarkup()

            for project, role in user_projects_with_roles:
                project_line = f"- <code>{project.project_id}</code>: <b>{escape_html(project.name)}</b>\n"

                if role == UserRole.OWNER.value:
                    owner_projects_text += project_line
                elif role == UserRole.HELPER.value:
                    helper_projects_text += project_line
                elif role == UserRole.MEMBER.value:
                    member_projects_text += project_line

                button_text = f"🔎 {project.name}"
                callback_data_str = f"view_project_details:{project.project_id}"
                markup.add(InlineKeyboardButton(button_text, callback_data=callback_data_str))

            top_message_parts = [f"{escape_html(user_name)}, вы состоите в следующих проектах:\n\n"]

            if owner_projects_text:
                top_message_parts.append("<b>Проекты, в которых вы являетесь владельцем:</b>\n")
                top_message_parts.append(owner_projects_text)
                top_message_parts.append("\n")

            if helper_projects_text:
                top_message_parts.append("<b>Проекты, в которых вы являетесь хелпером:</b>\n")
                top_message_parts.append(helper_projects_text)
                top_message_parts.append("\n")

            if member_projects_text:
                top_message_parts.append("<b>Проекты, в которых вы являетесь участником:</b>\n")
                top_message_parts.append(member_projects_text)
                top_message_parts.append("\n")

            top_message = "".join(top_message_parts)

            await bot.send_message(chat_id, top_message, parse_mode="HTML", reply_markup=markup if markup.keyboard else None)
    except DatabaseError as e:
        await bot.send_message(chat_id, "Произошла ошибка при работе с базой данных во время получения списка проектов. Пожалуйста, попробуйте позже.")

async def handle_create_task(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name

    user_data = message.from_user

    message_parts = message.text.split()
    if len(message_parts) != 2:
        try: await bot.send_message(chat_id=chat_id, text="Неправильное использование команды. Используйте в формате <code>/create_task ID_проекта</code>", parse_mode="HTML")
        except: pass
        return
    try: 
        project_id = int(message_parts[1])
    except ValueError:
        try: await bot.send_message(chat_id=chat_id, text="Неправильный ID проекта.", parse_mode="HTML")
        except: pass
        return
    
    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session=session, project_id=project_id)
            user = await crud.get_user_by_id(session=session, user_id=user_id)
            if project.owner_user_id != user_id:
                project_member = await crud.get_project_member(session=session, project_id=project_id, user_id=user_id)
                if project_member.role != UserRole.HELPER.value:
                    try: await bot.send_message(chat_id=chat_id, text="У вас нет прав для создания задач в этом проекте.")
                    except: pass
                    return
        
        message_text = f"Вы начали создание новой задачи для проекта <code>{escape_html(project.name)}</code>. Напишите название вашей задачи:"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="Удалить задачу", callback_data=f"cancel_task_creation"))
        await bot.send_message(chat_id=chat_id, text=message_text, reply_markup=markup, parse_mode="HTML")
        z = await bot.set_state(user_id=user_id, chat_id=chat_id, state=TaskCreationStates.set_title)
        print(z)
        async with bot.retrieve_data(user_id=user_id, chat_id=chat_id) as data:
            data["project_id"] = project_id
            print(data)
        print(await bot.get_state(user_id=user_id, chat_id=chat_id))

    except ProjectNotFoundError:
        try: await bot.send_message(chat_id=chat_id, text=f"Проект с ID <code>{project_id}</code> не найден.", parse_mode="HTML")
        except: pass
    except (UserNotFoundError, MemberNotFoundError):
        try: await bot.send_message(chat_id=chat_id, text="У вас нет прав на этот проект.", parse_mode="HTML")
        except: pass
    except DatabaseError as e:
        try: await bot.send_message(chat_id=chat_id, text="Произошла ошибка в базе данных. Попробуйте позднее")
        except: pass
        print(e)
    except Exception as e:
        print(e)

async def process_task_title(message: types.Message, bot: AsyncTeleBot):
    print(1)
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    async with bot.retrieve_data(user_id, chat_id) as data:
        data['title'] = message.text
    
    await bot.set_state(user_id, TaskCreationStates.set_description, chat_id)
    await bot.send_message(chat_id, "📝 Введите описание задачи (обязательно):")

async def process_task_description(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    description = message.text
    
    async with bot.retrieve_data(user_id, chat_id) as data:
        data['description'] = description
        project_id = data['project_id']
        
    async with AsyncSessionLocal() as session:
        members = await crud.get_project_members(session, project_id)
        project = await crud.get_project_by_id(session, project_id) 
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="Назначить себе", callback_data=f"assignee_{user_id}"))
    for member in members:
        user = member.user
        btn_text = f"{user.first_name} (@{user.username})" if user.username else user.first_name
        markup.add(InlineKeyboardButton(text=btn_text,callback_data=f"assignee_{user.user_id}"))
    markup.add(InlineKeyboardButton(text="🚫 Без исполнителя", callback_data="assignee_none"))

    
    await bot.set_state(user_id, TaskCreationStates.set_assignee, chat_id)
    await bot.send_message(chat_id, "👥 Выберите исполнителя:", reply_markup=markup)

async def process_task_due_date(message: types.Message, bot: AsyncTeleBot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    due_date = None
    if message.text.lower() != 'пропустить':
        try:
            due_date = datetime.strptime(message.text, "%d.%m.%Y")
        except ValueError:
            await bot.send_message(chat_id, "❌ Неверный формат даты. Попробуйте еще раз.")
            return
    
    if due_date and due_date.date() < datetime.now().date():
        await bot.send_message(chat_id, "❌ Дата не может быть в прошлом")
        return
    
    async with bot.retrieve_data(user_id=user_id, chat_id=chat_id) as data:
        try:
            project_id = data['project_id']
            title = data['title']
            description = data['description']
            assignee_id = data.get('assignee_id')
            
            if assignee_id == 'none':
                assignee_id = None
            
            async with AsyncSessionLocal() as session:
                creator_user_role = await crud.get_user_project_role(
                    session=session, 
                    project_id=project_id, 
                    user_id=user_id
                )
                
                if assignee_id:
                    assignee_user_role = await crud.get_user_project_role(
                        session=session, 
                        project_id=project_id, 
                        user_id=assignee_id
                    )
                else:
                    assignee_user_role = None
                
                need_confirm = False
                if assignee_user_role and assignee_user_role != UserRole.MEMBER.value and creator_user_role != UserRole.OWNER.value:
                    need_confirm = True
                
                task_status = TaskStatus.PENDING_ASSIGNMENT.value if need_confirm else TaskStatus.NEW.value
                
                task = await crud.create_task(
                    session=session, 
                    project_id=project_id, 
                    creator_user_id=user_id, 
                    title=title, 
                    description=description, 
                    chat_id_created_in=chat_id, 
                    assignee_user_id=assignee_id, 
                    status=task_status, 
                    due_date=due_date
                )
                
                project = await crud.get_project_by_id(session, project_id)
                creator = await crud.get_user_by_id(session, user_id)
                
                message_text = f"✅ Задача {'отправлена на подтверждение' if need_confirm else 'создана'}!\n\n" \
                              f"🔹 <b>{escape_html(task.title)}</b>\n" \
                              f"🔹 ID в проекте: {task.task_id_in_project}\n" \
                              f"🔹 Проект: {escape_html(project.name)}\n"
                
                if task.assignee:
                    assignee_link = await create_user_link(task.assignee.user_id, task.assignee.first_name, task.assignee.username)
                    message_text += f"🔹 Исполнитель: {assignee_link}\n"
                
                if task.due_date:
                    message_text += f"🔹 Срок: {task.due_date.strftime('%d.%m.%Y')}\n"
                
                await bot.send_message(chat_id, message_text, parse_mode="HTML")
                
                if assignee_id and assignee_id != user_id:
                    assignee_message = f"🔔 Вам {'назначена' if not need_confirm else 'предложена'} задача в проекте {escape_html(project.name)}:\n\n" \
                                      f"<b>{escape_html(task.title)}</b>\n" \
                                      f"Описание: {escape_html(task.description)}\n"
                    
                    if task.due_date:
                        assignee_message += f"Срок: {task.due_date.strftime('%d.%m.%Y')}\n"
                    
                    assignee_message += f"Создатель: {await create_user_link(creator.user_id, creator.first_name, creator.username)}\n"
                    
                    if need_confirm:
                        markup = InlineKeyboardMarkup()
                        markup.add(
                            InlineKeyboardButton(
                                text="✅ Принять", 
                                callback_data=f"confirm_task:{task.task_id}:accept"
                            ),
                            InlineKeyboardButton(
                                text="❌ Отклонить", 
                                callback_data=f"confirm_task:{task.task_id}:reject"
                            )
                        )
                        assignee_message += "\nПодтвердите принятие задачи:"
                    else:
                        markup = None
                        assignee_message += "\nВы были назначены исполнителем этой задачи."
                    
                    try:
                        await bot.send_message(
                            chat_id=assignee_id,
                            text=assignee_message,
                            reply_markup=markup,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send notification to assignee: {str(e)}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"Не удалось отправить уведомление исполнителю. Возможно, он не начал диалог с ботом.",
                            parse_mode="HTML"
                        )
                
        except Exception as e:
            await bot.send_message(chat_id, "❌ Ошибка при создании задачи. Попробуйте позже.")
            logger.error(f"Error creating task: {str(e)}")
        finally:
            await bot.delete_state(user_id, chat_id)


async def handle_test(message: types.Message, bot: AsyncTeleBot):

    chat_id = message.chat.id
    await bot.send_message(chat_id, "[Ваня](tg://user?id=1778641241)", parse_mode="HTML")


async def handle_callback_query_view_project_details(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name

    try:
        await bot.answer_callback_query(call.id)
    except Exception:
        pass

    data_parts = call.data.split(':')
    if len(data_parts) != 2 or data_parts[0] != 'view_project_details':
        await bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.")
        return

    try:
        project_id = int(data_parts[1])
    except ValueError:
        await bot.answer_callback_query(call.id, f"Ошибка обработки запроса. Неверный ID проекта: `{data_parts[1]}`.")
        return

    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session, project_id)

            user_role_in_project = None
            is_owner = (project.owner_user_id == user_id)

            if is_owner:
                user_role_in_project = UserRole.OWNER.value
            else:
                 try:
                      user_role_in_project = await crud.get_user_project_role(session, project_id, user_id)
                 except MemberNotFoundError:
                      await bot.answer_callback_query(call.id, f"У вас нет доступа к проекту с ID `{project_id}`. Вы должны быть участником или владельцем этого проекта.")
                      return

            owner_info = f"Владелец: {escape_html(project.owner.first_name)} (<code>{project.owner.user_id}</code>)"

            message_text = (
                f"<b>Проект: {project.name}</b> (ID: <code>{project.project_id}</code>)\n"
                f"{owner_info}\n"
                f"Ваша роль: <b>{user_role_in_project.capitalize()}</b>\n"
                f"Создан: {project.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )

            if project.description is not None:
                 message_text += f"Описание: {escape_html(project.description)}\n"

            markup = InlineKeyboardMarkup()

            markup.add(InlineKeyboardButton("🔎 Посмотреть мои задачи", callback_data=f"view_my_tasks_in_project:{project_id}:{user_id}"))

            if user_role_in_project in [UserRole.HELPER.value, UserRole.OWNER.value]:
                 markup.add(InlineKeyboardButton("👥 Участники", callback_data=f"view_members:{project_id}"))
                 markup.add(InlineKeyboardButton("📋 Все задачи", callback_data=f"view_all_tasks:{project_id}"))

            if user_role_in_project == UserRole.OWNER.value:
                 markup.add(InlineKeyboardButton("⚙️ Управление", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.SHOW_MENU.value}"))
                 markup.add(InlineKeyboardButton("✉️ Пригласить", callback_data=f"generate_invite:{project_id}"))

            markup.add(InlineKeyboardButton("« Назад к проектам", callback_data="back_to_my_projects"))

            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, 
                                        parse_mode="HTML", reply_markup=markup)

    except ProjectNotFoundError:
        await bot.answer_callback_query(call.id, f"Ошибка: Проект с ID {project_id} не найден.", show_alert=True)
    except DatabaseError:
        await bot.answer_callback_query(call.id, "Произошла ошибка при работе с базой данных. Пожалуйста, попробуйте позже.", show_alert=True)

async def handle_query_back_to_my_projects(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_data = call.from_user
    user_id = user_data.id
    chat_id = call.message.chat.id
    user_name = user_data.first_name
    message_id = call.message.message_id

    async with AsyncSessionLocal() as session:
        await crud.get_or_create_and_update_user(session=session, user_id=user_id, username=user_data.username, first_name=user_data.first_name,
                               is_bot=user_data.is_bot)
        user_projects_with_roles = await crud.get_user_projects_with_roles(session, user_id)

    if not user_projects_with_roles:
        top_message = (f"{escape_html(user_name)}, вы пока что не состоите ни в одном проекте.\n"
                        f"Чтобы создать свой проект используйте команду `/create_project`\n"
                        f"Чтобы получить помощь воспользуйтесь командой /help")
        await bot.answer_callback_query(call.id, text=top_message, show_alert=True)
        return

    owner_projects_text = ""
    helper_projects_text = ""
    member_projects_text = ""

    markup = InlineKeyboardMarkup()

    for project, role in user_projects_with_roles:
        project_line = f"- {project.project_id}: <b>{escape_html(project.name)}</b>\n"

        if role == UserRole.OWNER.value:
            owner_projects_text += project_line
        elif role == UserRole.HELPER.value:
            helper_projects_text += project_line
        elif role == UserRole.MEMBER.value:
            member_projects_text += project_line

        button_text = f"🔎 {project.name}"
        callback_data_str = f"view_project_details:{project.project_id}"
        markup.add(InlineKeyboardButton(button_text, callback_data=callback_data_str))

    top_message_parts = [f"{escape_html(user_name)}, вы состоите в следующих проектах:\n\n"]

    if owner_projects_text:
        top_message_parts.append("<b>Проекты, в которых вы являетесь владельцем:</b>\n")
        top_message_parts.append(owner_projects_text)
        top_message_parts.append("\n")

    if helper_projects_text:
        top_message_parts.append("<b>Проекты, в которых вы являетесь хелпером:</b>\n")
        top_message_parts.append(helper_projects_text)
        top_message_parts.append("\n")

    if member_projects_text:
        top_message_parts.append("<b>Проекты, в которых вы являетесь участником:</b>\n")
        top_message_parts.append(member_projects_text)
        top_message_parts.append("\n")

    top_message = "".join(top_message_parts)

    await bot.edit_message_text(chat_id=chat_id, message_id=call.message.id, text=top_message, reply_markup=markup, parse_mode="HTML")

async def handle_query_view_members(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    first_name = call.from_user.first_name
    username = call.from_user.username

    try: await bot.answer_callback_query(call.id)
    except Exception: pass

    data_parts = call.data.split(':')
    if len(data_parts) != 2:
        try:await bot.answer_callback_query(call.id, "Ошибка обработки запроса. Неверный формат данных.", show_alert=True)
        except Exception: pass
        return

    try:
        project_id = int(data_parts[1])
    except ValueError:
        try:await bot.answer_callback_query(call.id, f"Ошибка обработки запроса. Неверный ID проекта: {data_parts[1]}.", show_alert=True)
        except Exception: pass
        return

    try:
        async with AsyncSessionLocal() as session:
            await crud.get_or_create_and_update_user(session=session, user_id=user_id, username=username, first_name=first_name)
            db_project = await crud.get_project_by_id(session, project_id)

            is_owner = (db_project.owner_user_id == user_id)
            if not is_owner:
                 user_role_in_project = await crud.get_user_project_role(session, project_id, user_id)
                 if user_role_in_project != UserRole.HELPER.value:
                    try: 
                        await bot.answer_callback_query(call.id, "У вас нет прав на просмотр участников.", show_alert=True)
                    except Exception: 
                        pass
                    return
            else:
                 user_role_in_project = UserRole.OWNER.value


            db_project_members = await crud.get_project_members(session=session, project_id=project_id)

        message_text = f"<b>Список участников в проекте {escape_html(db_project.name)} (ID: <code>{db_project.project_id}</code>):</b>\n\n"
        owner_user_link = await create_user_link(user_id=db_project.owner.user_id, user_name=db_project.owner.first_name, username=db_project.owner.username)
        message_text += f"<b>Владелец:</b> {owner_user_link}\n"

        if db_project_members:
            message_text += "\n<b>Участники:</b>\n"
            
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="Настройки пользователей", callback_data="pass"))
        role_order = {UserRole.HELPER.value: 0, UserRole.MEMBER.value: 1}
        db_project_members = sorted(db_project_members, key=lambda member: role_order.get(member.role, 99))
        if user_role_in_project == UserRole.OWNER.value:
            for member in db_project_members:
                user: User = member.user
                user_link = await create_user_link(user_id=user.user_id, user_name=user.first_name, username=user.username)
                user_role = member.role 
                message_text += f" - {user_link} - {user_role} (ID: {user.user_id})\n"
                callback_data_str = f"manage_member:{ManageMemberActions.SH0W_MENU.value}:{project_id}:{member.user_id}"
                markup.add(InlineKeyboardButton(text=f"⚙️ {member.user.first_name}", callback_data=callback_data_str))
        elif user_role_in_project == UserRole.HELPER.value:
            for member in db_project_members:
                user: User = member.user
                user_link = await create_user_link(user_id=user.user_id, user_name=user.first_name, username=user.username)                
                user_role = member.role
                message_text += f" - {user_link} - {user_role} (ID: {user.user_id})\n"
                
                if user_role != UserRole.HELPER.value:
                    callback_data_str = f"manage_member:{project_id}:{member.user_id}"
                    markup.add(InlineKeyboardButton(text=f"⚙️ {member.user.first_name}", callback_data=callback_data_str))

        markup.add(InlineKeyboardButton("« Назад", callback_data=f"view_project_details:{project_id}"))
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, 
                                    parse_mode="HTML", reply_markup=markup)
    except ProjectNotFoundError:
        try: await bot.answer_callback_query(call.id, f"Проект с таким ID ('{project_id}') не был найден.", show_alert=True)
        except Exception: pass
    except ApiTelegramException:
        try:await bot.answer_callback_query(call.id, text="Не удалось обновить сообщение.", show_alert=True)
        except Exception: pass
    except DatabaseError:
        try: await bot.answer_callback_query(call.id, text="Произошла ошибка при отображении участников.", show_alert=True)
        except Exception: pass

async def handle_query_manage_member(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data_parts = call.data.split(':')
    if len(data_parts) != 4:
        await bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.", show_alert=True)
        return
    try:
        action = ManageMemberActions(data_parts[1])
    except ValueError:
        try: await bot.answer_callback_query(call.id, f"Недопустимое действие. Сообщите разработчику", show_alert=True)
        except: pass
        return
    try:
        project_id = int(data_parts[2])
    except ValueError:
        try:await bot.answer_callback_query(call.id, f"Ошибка обработки запроса. Неверный ID проекта: `{data_parts[1]}`.", show_alert=True)
        except: pass
        return
    try:
        managed_user_id = int(data_parts[3])
    except ValueError:
        try: await bot.answer_callback_query(call.id, f"Ошибка обработки запроса. Неверный ID пользователя: `{data_parts[2]}`", show_alert=True)
        except: pass
        return
    
    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session=session, project_id=project_id)
            user = await crud.get_or_create_and_update_user(session=session, user_id=user_id, 
                                                username=call.from_user.username, 
                                                first_name=call.from_user.first_name)
            try:
                project_member = await crud.get_project_member(session=session, project_id=project_id, user_id=user_id)
                if project_member.role == UserRole.MEMBER.value:
                    try: await bot.answer_callback_query(call.id, "У вас нет прав для доступа к пользователям в этом проекте.", show_alert=True)
                    finally: return
            except MemberNotFoundError:
                if project.owner_user_id != user_id:
                    try: await bot.answer_callback_query(call.id, "У вас нет прав для доступа к пользователям в этом проекте.", show_alert=True)
                    finally: return
            managed_project_member = await crud.get_project_member(session=session, project_id=project_id, user_id=managed_user_id)

            managed_user = await crud.get_user_by_id(session=session, user_id=managed_user_id)
        
        if action in (ManageMemberActions.DEMOTE_MEMBER, ManageMemberActions.PROMOTE_MEMBER, ManageMemberActions.SH0W_MENU):
            async with AsyncSessionLocal() as session:
                if action == ManageMemberActions.DEMOTE_MEMBER:
                    managed_project_member = await crud.update_member_role(session=session, project_id=project_id, user_id=managed_user_id, new_role=UserRole.MEMBER.value)
                elif action == ManageMemberActions.PROMOTE_MEMBER:
                    managed_project_member = await crud.update_member_role(session=session, project_id=project_id, user_id=managed_user_id, new_role=UserRole.HELPER.value)
                managed_user = await crud.get_user_by_id(session=session, user_id=managed_user_id)

            managed_user_link = await create_user_link(user_id=managed_user.user_id, user_name=managed_user.first_name, username=managed_user.username)
            message_text = f"Пользователь {managed_user_link} как пользователь проекта <code>{project.project_id}</code>:\n" + \
                        f"(ID пользователя: {managed_user.user_id})\n\n"
            message_text += (f"Роль в проекте: {managed_project_member.role}\n" \
                            f"Добавлен в проект {managed_project_member.added_at}\n")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="Список задач", callback_data=f"view_tasks_in_project:{project_id}:{managed_user.user_id}"))
            
            if project.owner_user_id == user_id:
                if managed_project_member.role == UserRole.MEMBER.value:
                    markup.add(InlineKeyboardButton(text="Повысить", callback_data=f"manage_member:{ManageMemberActions.PROMOTE_MEMBER.value}:{project_id}:{managed_user_id}"))
                else:
                    markup.add(InlineKeyboardButton(text="Понизить", callback_data=f"manage_member:{ManageMemberActions.DEMOTE_MEMBER.value}:{project_id}:{managed_user_id}"))
                markup.add(InlineKeyboardButton(text="❗️ Передать права ❗️", callback_data=f"manage_member:{ManageMemberActions.CONFIRM_TRANSFER.value}:{project_id}:{managed_user_id}"))
            markup.add(InlineKeyboardButton(text="Выгнать", callback_data=f"manage_member:{ManageMemberActions.CONFIRM_KICK.value}:{project_id}:{managed_user_id}"))
            markup.add(InlineKeyboardButton(text="Назад", callback_data=f"view_members:{project_id}"))
            
            try: await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except Exception as e: pass

        elif action == ManageMemberActions.CONFIRM_KICK:
            async with AsyncSessionLocal() as session:
                project = await crud.get_project_by_id(session=session, project_id=project_id)
                try:
                    project_member = await crud.get_project_member(session=session, project_id=project_id, user_id=user_id)
                except MemberNotFoundError:
                    if project.owner_user_id != user_id:
                        try: await bot.answer_callback_query(call.id, "У вас нет прав для доступа к пользователям в этом проекте.", show_alert=True)
                        finally: return

            managed_user_link = await create_user_link(user_id=managed_user_id, user_name=managed_user.first_name, username=managed_user.username)
            message_text = (f"<b>Вы уверены, что хотите выгнать пользователя</b> {managed_user_link} "
                            f"<b>из проекта</b> {escape_html(project.name)} (ID: <code>{project.project_id}</code>)?\n\n"
                            f"Это действие нельзя отменить.")
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="Да", callback_data=f"manage_member:{ManageMemberActions.EXECUTE_KICK.value}:{project_id}:{managed_user_id}"),
                       InlineKeyboardButton(text=f"Нет", callback_data=f"manage_member:{ManageMemberActions.SH0W_MENU.value}:{project_id}:{managed_user_id}"))
            
            try: await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass

        elif action == ManageMemberActions.EXECUTE_KICK:
            async with AsyncSessionLocal() as session:
                await crud.remove_member_from_project(session=session, project_id=project_id, user_id=managed_user_id)
            
            managed_user_link = await create_user_link(user_id=managed_user_id, user_name=managed_user.first_name, username=managed_user.username)
            message_text = f"Пользователь {managed_user_link} (ID пользователя: <code>{managed_user_id}</code>) был удалён из проекта {escape_html(project.name)} (ID проекта: <code>{project_id}</code>)"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="Список пользователей", callback_data=f"view_members:{project_id}"))
            try: await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except Exception as e: print(e)

            message_text = f"Вы были удалены из проекта {project.name} (ID проекта: <code>{project_id}</code>)"
            try: await bot.send_message(chat_id=managed_user_id, text=message_text, parse_mode="HTML")
            except: pass
        
        elif action == ManageMemberActions.CONFIRM_TRANSFER:
            managed_user_link = await create_user_link(user_id=managed_user_id, user_name=managed_user.first_name, username=managed_user.username)
            message_text = f"<b>Вы уверены</b>, что хотите передать owner над проектом {project.name} (ID: <code>{project_id}</code>) пользователю {managed_user_link}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="Да", callback_data=f"manage_member:{ManageMemberActions.EXECUTE_TRANSFER.value}:{project_id}:{managed_user_id}"))
            markup.add(InlineKeyboardButton(text="Назад", callback_data=f"manage_member:{ManageMemberActions.SH0W_MENU.value}:{project_id}:{managed_user_id}"))
            
            try: await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except Exception as e: print(e)

        elif action == ManageMemberActions.EXECUTE_TRANSFER:
            async with AsyncSessionLocal() as session:
                await crud.transfer_project_ownership(session=session, project_id=project_id, new_owner_user_id=managed_user_id)
            
            managed_user_link = await create_user_link(user_id=managed_user_id, user_name=managed_user.first_name, username=managed_user.username)
            message_text = f"Вы успешно передали owner над проектом {project.name} (ID: <code>{project_id}</code>) пользователю {managed_user_link}"
            try: await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=message_text, parse_mode="HTML")
            except: pass
            
            message_text = f"Вам передали права owner над проектом {project.name} (ID: {project_id})"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="Настройки", callback_data=f"view_project_details:{project_id}"))
            try: await bot.send_message(managed_user_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass

    except DatabaseError as e:
        try: await bot.answer_callback_query(call.id, text="Произошла ошибка при работе с базой данных. Попробуйте позже.", show_alert=True)
        except: pass
    except ProjectNotFoundError:
        try: await bot.answer_callback_query(call.id, f"Проект с таким ID ('{project_id}') не был найден.", show_alert=True)
        except: pass
    except Exception as e:
        try: await bot.answer_callback_query(call.id, text="Произошла неизвестная ошибка. Попробуйте позднее.")
        except: pass

async def handle_query_manage_project_menu(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name

    data_parts = call.data.split(':')
    if len(data_parts) != 3 or data_parts[0] != 'manage_project_menu':
        await bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.")
        return
    
    try:
        project_id = int(data_parts[1])
    except ValueError:
        try: await bot.answer_callback_query(call.id, f"Произошла ошибка: неправильный ID проекта: {data_parts[1]}")
        except: pass
        return
    
    try:
        action = ManageProjectMenuActions(data_parts[2])
    except ValueError:
        try: await bot.answer_callback_query(call.id, f"Недопустимое действие. Сообщите разработчику", show_alert=True)
        except: pass
        return

    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session=session, project_id=project_id)
            if user_id != project.owner_user_id:
                try: await bot.answer_callback_query(call.id, "У вас нет прав для доступа к этому проекту", show_alert=True)
                except: pass
                return
    except ProjectNotFoundError:
        try: await bot.answer_callback_query(call.id, text=f"Проект с таким ID не найден.", show_alert=True)
        except: pass
        return
    
    try:
        if action == ManageProjectMenuActions.CANCEL:
            await bot.delete_state(user_id=user_id, chat_id=chat_id)
        
        if action in (ManageProjectMenuActions.SHOW_MENU, ManageProjectMenuActions.CANCEL):
            message_text = (f"⚙️ <b>Управление проектом</b> ⚙️\n\n"
                            f"Название: <code>{escape_html(project.name)}</code>\n"
                            f"ID: <code>{project.project_id}</code>\n"
                            f"Описание: {escape_html(project.description) if project.description else '❌'}")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CHANGE_NAME.value}"))
            markup.add(InlineKeyboardButton(text="📝 Изменить описание", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CHANGE_DESCRIPTION.value}"))
            markup.add(InlineKeyboardButton(text="✉️ Управление инвайтами", callback_data=f"manage_project_invites:{project_id}"))
            markup.add(InlineKeyboardButton(text="🗑️ Удалить проект", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CONFIRM_DELETE.value}"))
            markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_project_details:{project_id}"))
            
            try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass
        
        elif action == ManageProjectMenuActions.CHANGE_NAME:
            await bot.set_state(user_id=user_id, chat_id=chat_id, state=f"{MyStates.SET_NEW_NAME}:{project_id}")
            message_text = (f"<b>Отправьте новое название для вашего проекта</b>\n"
                            f"Предыдущее название: <code>{escape_html(project.name)}</code>")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CANCEL.value}"))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
        
        elif action == ManageProjectMenuActions.CHANGE_DESCRIPTION:
            await bot.set_state(user_id=user_id, chat_id=chat_id, state=f"{MyStates.SET_NEW_DESCRIPTION}:{project_id}")
            message_text = "Отправьте новое описание для вашего проекта"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CANCEL.value}"))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")

        elif action == ManageProjectMenuActions.CONFIRM_DELETE:
            message_text = "🗑️ <b>Вы уверены</b> что хотите удалить этот проект? <b>Это действие нельзя будет отменить</b> 🗑️"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="✅ Да", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.EXECUTE_DELETE.value}"))
            markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.CANCEL.value}"))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
        
        elif action == ManageProjectMenuActions.EXECUTE_DELETE:
            async with AsyncSessionLocal() as session:
                await crud.delete_project(session=session, project_id=project_id)
            message_text = f"✅ Вы успешно удалили проект {escape_html(project.name)}. "
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔙 К списку проектов", callback_data="back_to_my_projects"))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")

    except DatabaseError as e:
        try: await bot.answer_callback_query(call.id, "Произошла ошибка базы данных, попробуйте позднее")
        except: pass
        
async def handle_query_manage_project_invites(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name
    
    data_parts = call.data.split(":")
    if len(data_parts) != 2 or data_parts[0] != 'manage_project_invites':
        await bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.", show_alert=True)
        return
    
    try:
        project_id = int(data_parts[1])
    except ValueError:
        await bot.answer_callback_query(call.id, f"Неверный формат ID проекта: {data_parts[1]}", show_alert=True)
        return
        
    try:
        async with AsyncSessionLocal() as session:
            project = await crud.get_project_by_id(session=session, project_id=project_id)
            if project.owner_user_id != user_id:
                try: await bot.answer_callback_query(call.id, "У вас нет прав на этот проект.", show_alert=True)
                except: pass
                return
            project_invites: list[Invites] = project.invites
        
        message_text = (f"⚙️ <b>Управление приглашениями проекта</b> <code>{escape_html(project.name)}</code> (ID проекта: {project_id})⚙️\n\n"
                        f"Всего приглашений в проекте: <code>{len(project_invites)}</code>\n\n")
        
        markup = InlineKeyboardMarkup()

        if project_invites:
            message_text += "<b>Список активных приглашений:</b>\n"
            for invite in project_invites:
                expires_info = f"до {invite.expires_at.strftime('%Y-%m-%d %H:%M')}" if invite.expires_at else "бессрочное"
                uses_info = f"{invite.current_uses}/{invite.max_uses}" if invite.max_uses else f"{invite.current_uses}/∞"
                id_info = f"(ID: <code>{invite.invite_id}</code>)"
                message_text += (
                    f"🔹 <code>{invite.invite_code}</code> - использовано {uses_info}, {expires_info} {id_info}\n"
                )
                markup.add(InlineKeyboardButton(text=f"Инвайт {invite.invite_id}", callback_data=f"manage_single_invite:{invite.invite_id}:{ManageInviteMenuActions.SHOW_MENU.value}"))
        else:
            message_text += "❌ В этом проекте нет активных приглашений.\n"
        
        markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.SHOW_MENU.value}"))
        
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
        except: pass
            
    except ProjectNotFoundError:
        try: await bot.answer_callback_query(call.id, "Проект не найден.", show_alert=True)
        except: pass
    except DatabaseError as e:
        try: await bot.answer_callback_query(call.id, "Произошла ошибка при работе с базой данных.", show_alert=True)
        except: pass
    except Exception as e:
        try: await bot.answer_callback_query(call.id, "Произошла неизвестная ошибка.", show_alert=True)
        except: pass
            
async def handle_query_manage_single_invite(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name

    data_parts = call.data.split(":")
    if len(data_parts) != 3 or data_parts[0] != 'manage_single_invite':
        await bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.", show_alert=True)
        return

    try:
        invite_id = int(data_parts[1])
    except ValueError:
        try: await bot.answer_callback_query(call.id, "Произошла ошибка с получением ID инвайта.", show_alert=True)
        except: pass
        return

    try:
        action = ManageInviteMenuActions(data_parts[2])
    except ValueError:
        try: await bot.answer_callback_query(call.id, f"Недопустимое действие. Сообщите разработчику", show_alert=True)
        except: pass
        return

    try:
        async with AsyncSessionLocal() as session:
            invite = await crud.get_invite_by_id(session=session, invite_id=invite_id)
            user = await crud.get_user_by_id(session=session, user_id=invite.generated_by_user_id)
            project = await crud.get_project_by_id(session=session, project_id=invite.project_id)
        
        if action == ManageInviteMenuActions.SHOW_MENU:
            creator_user_link = await create_user_link(user_id=user.user_id, user_name=user.first_name, username=user.username)
            try: created_at = invite.created_at.strftime("%d.%m.%Y %H:%M")
            except: created_at = "не указано"
            try: expires_at = invite.expires_at.strftime("%d.%m.%Y %H:%M")
            except: expires_at = "бессрочное"
            message_text = (f"✉️ Настройки приглашения ✉️\n\n"
                            f"🆔 ID приглашения: <code>{invite_id}</code>\n"
                            f"🔑 Код приглашения: <code>{invite.invite_code}</code>\n"
                            f"👤 Создатель: {creator_user_link}\n"
                            f"📌 Проект: <code>{escape_html(project.name)}</code> (ID: {invite.project_id})\n"
                            f"🔄 Использований: {invite.current_uses}{f'/{invite.max_uses}' if invite.max_uses else '/∞'}\n"
                            f"📅 Создано: {created_at}\n"
                            f"⏳ Истекает: {expires_at}\n\n"
                            "Удалить приглашение можно по кнопке ниже")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"manage_single_invite:{invite_id}:{ManageInviteMenuActions.EXECUTE_DELETE.value}"))
            markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_project_invites:{invite.project_id}"))
            try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass
        elif action == ManageInviteMenuActions.EXECUTE_DELETE:
            async with AsyncSessionLocal() as session:
                await crud.delete_invite_by_id(session=session, invite_id=invite_id)
            message_text = f"✅ Инвайт <code>{invite.invite_code}</code> успешно удален!"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 К списку инвайтов", callback_data=f"manage_project_invites:{project.project_id}"))
            await bot.edit_message_text(message_text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    except InviteNotFoundError:
        try: await bot.answer_callback_query(call.id, "Инвайт не найден", show_alert=True)
        except: pass
    except ProjectNotFoundError:
        try: await bot.answer_callback_query(call.id, "Проект не найден", show_alert=True)
        except: pass
    except DatabaseError as e:
        logger.error(f"Database error: {str(e)}")
        try: await bot.answer_callback_query(call.id, "Ошибка базы данных", show_alert=True)
        except: pass
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        try: await bot.answer_callback_query(call.id, "Неизвестная ошибка", show_alert=True)
        except: pass


async def process_task_assignee(call: types.CallbackQuery, bot: AsyncTeleBot):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    assignee_id = None
    if call.data == "assignee_none":
        assignee_id = 'none'
    else:
        assignee_id = int(call.data.split('_')[1])
    
    async with bot.retrieve_data(user_id, chat_id) as data:
        data['assignee_id'] = assignee_id
    
    await bot.answer_callback_query(call.id)
    await bot.set_state(user_id, TaskCreationStates.set_due_date, chat_id)
    await bot.send_message(chat_id, "⏳ Введите срок выполнения задачи в формате ДД.ММ.ГГГГ (или 'пропустить'):")





async def handle_all_messges(message: types.Message, bot: AsyncTeleBot):
    chat_id = message.chat.id
    user_id = message.from_user.id
    first_name = message.from_user.first_name

    
    state = await bot.get_state(user_id=user_id, chat_id=chat_id)
    if state is None:
        return
    
    if state.startswith(f"TaskCreationStates"):
        print("\n\n ", state)
        if state == TaskCreationStates.set_title.name:
            await process_task_title(message, bot)
        elif state == TaskCreationStates.set_description.name:
            await process_task_description(message, bot)
        elif state == TaskCreationStates.set_due_date.name:
            await process_task_due_date(message, bot)
        return

    state_action = state.split(":", maxsplit=1)[0]

    await bot.delete_state(user_id=user_id, chat_id=chat_id)
    try:
        if state_action == MyStates.SET_NEW_NAME:
            project_id = int(state.split(":")[1])
            new_name = escape_html(message.text)
            async with AsyncSessionLocal() as session:
                project: Project = await crud.update_project(session=session, project_id=project_id, name=new_name)
            message_text = (f"Вы успешно поменяли название проекта (ID: <code>{project_id}</code>) на <code>{escape_html(project.name)}</code>")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔙 Настройки", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.SHOW_MENU.value}"))
            try: await bot.send_message(chat_id=chat_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass
        
        elif state_action == MyStates.SET_NEW_DESCRIPTION:
            project_id = int(state.split(":")[1])
            new_description = escape_html(message.text)
            async with AsyncSessionLocal() as session:
                project: Project = await crud.update_project(session=session, project_id=project_id, description=new_description)
            message_text = (f"Вы успешно поменяли описание проекта (ID: <code>{project_id}</code>):\n\n"
                            f"<b>{escape_html(project.description)}</b>")
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🔙 Настройки", callback_data=f"manage_project_menu:{project_id}:{ManageProjectMenuActions.SHOW_MENU.value}"))
            try: await bot.send_message(chat_id=chat_id, text=message_text, reply_markup=markup, parse_mode="HTML")
            except: pass

    except ProjectNameConflictError:
        try: 
            await bot.send_message(chat_id=chat_id, text="Такое имя проекта уже существует. Попробуйте ввести другое.", reply_markup=markup, parse_mode="HTML")
            await bot.set_state(user_id=user_id, chat_id=chat_id, state=f"{MyStates.SET_NEW_NAME}:{project_id}")
        except: pass
    except DatabaseError as e:
        try: await bot.send_message(chat_id=chat_id, text="Произошла ошибка во время работы с базой данных. Попробуйте позднее.")
        except: pass
    except ProjectNotFoundError:
        try: await bot.send_message(chat_id=chat_id, text=f"Проект с ID <code>{project_id}</code> не найден.")
        except: pass

        
    


def register_handlers(bot: AsyncTeleBot):
    logger.info("Началась регистрация хендлеров")
    bot.register_message_handler(lambda message: handle_start(message, bot), commands=["start"])
    bot.register_message_handler(lambda message: handle_help(message, bot), commands=["help"])
    bot.register_message_handler(lambda message: handle_create_project(message, bot), commands=["create_project"])
    bot.register_message_handler(lambda message: handle_delete_project(message, bot), commands=["delete_project"])
    bot.register_message_handler(lambda message: handle_view_project(message, bot), commands=["view_project"])
    bot.register_message_handler(lambda message: handle_invite(message, bot), commands=["invite"])
    bot.register_message_handler(lambda message: handle_my_projects(message, bot), commands=["my_projects"])
    bot.register_message_handler(lambda message: handle_test(message, bot), commands=["test"])
    bot.register_message_handler(lambda message: handle_create_task(message, bot), commands=["create_task"])

    bot.register_callback_query_handler(lambda call: handle_callback_query_view_project_details(call, bot), func=lambda call: call.data and call.data.startswith('view_project_details:'))
    bot.register_callback_query_handler(lambda call: handle_query_back_to_my_projects(call, bot), func=lambda call: call.data and call.data == "back_to_my_projects")
    bot.register_callback_query_handler(lambda call: handle_query_view_members(call, bot), func=lambda call: call.data and call.data.startswith("view_members"))
    bot.register_callback_query_handler(lambda call: handle_query_manage_member(call, bot), func=lambda call: call.data and call.data.startswith("manage_member"))
    bot.register_callback_query_handler(lambda call: handle_query_manage_project_menu(call, bot), func=lambda call: call.data and call.data.startswith("manage_project_menu"))
    bot.register_callback_query_handler(lambda call: handle_query_manage_project_invites(call, bot), func=lambda call: call.data and call.data.startswith("manage_project_invites"))
    bot.register_callback_query_handler(lambda call: handle_query_manage_single_invite(call, bot), func=lambda call: call.data and call.data.startswith("manage_single_invite"))
    bot.register_callback_query_handler(lambda call: process_task_assignee(call, bot), func=lambda call: call.data and call.data.startswith("assignee_"))

    bot.register_message_handler(lambda message: handle_all_messges(message, bot), func=lambda message: True)
