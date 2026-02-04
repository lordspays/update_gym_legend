from datetime import datetime, timedelta
import asyncio
from vkbottle.bot import BotLabeler, Message, Keyboard, KeyboardButtonColor, Text
from vkbottle.dispatch.rules import ABCRule
from vkbottle import API

from bot.core.config import settings
from bot.db import (
    add_magnesia,
    ban_player,
    count_admins,
    count_banned_players,
    count_clans,
    count_players,
    count_table_rows,
    count_total_balance,
    create_promo_code,
    delete_clan,
    delete_player,
    delete_promo_code,
    get_clan_by_tag,
    get_clan_member_count,
    get_clan_members,
    get_clan_treasury_log,
    get_player,
    get_promo_info,
    get_recent_players,
    increment_admin_stat,
    make_admin,
    remove_admin,
    reset_all,
    set_admin_nickname,
    set_custom_income,
    set_dumbbell_level,
    set_total_lifts,
    sum_column,
    sum_promo_uses,
    unban_player,
    update_clan_name,
    update_player_balance,
    update_username,
    update_player_power,
    get_all_clans,
    get_all_players,
    get_player_clan,
    set_info_access,
    remove_info_access,
    get_info_access_status,
    get_info_access_details,
    get_all_info_access,
    extend_info_access,
    set_donate_business_access,
    get_donate_business_status,
    remove_donate_business_access,
    get_all_donate_business_access,
    # Новые функции для системы логов и заявок
    add_admin_log,
    get_admin_logs,
    cleanup_old_logs,
    create_request,
    get_pending_requests,
    get_request_by_id,
    approve_request,
    reject_request,
    delete_request,
    get_request_stats,
    get_requests_by_admin,
    get_admin_usage_stats,
    get_broadcast_usage,
    increment_broadcast_usage,
    reset_broadcast_usage,
    check_broadcast_limit,
    get_admin_level,
    get_moderator_promo_stats,
    update_moderator_promo_stats,
    get_promo_usage_stats,
    update_promo_usage_stats,
    cleanup_old_requests,
)

from bot.services.clans import get_clan_bonuses
from bot.services.users import is_admin
from bot.utils import format_number, pointer_to_screen_name


class AdminRule(ABCRule[Message]):
    async def check(self, event: Message) -> bool:
        return await is_admin(event.from_id)


admin_labeler = BotLabeler()
admin_labeler.vbml_ignore_case = True
admin_labeler.auto_rules = [AdminRule()]

PENDING_DELETIONS = {}
PENDING_RESETS = {}
PENDING_REQUESTS = {}
REQUEST_COUNTER = 1

# ======================
# СИСТЕМА УРОВНЕЙ АДМИНИСТРАЦИИ
# ======================

async def get_admin_access_level(user_id: int) -> int:
    """Получить уровень доступа администратора"""
    # Проверяем создателя
    if user_id == settings.CREATOR_ID:
        return 1
    
    # Получаем уровень из базы
    player = await get_player(user_id)
    if player:
        return player.get("admin_level", 0)
    return 0

async def can_use_command(user_id: int, command_category: str) -> bool:
    """Проверка доступа к команде по категории"""
    admin_level = await get_admin_access_level(user_id)
    
    # 1 уровень (Создатель) - доступ ко всему
    if admin_level == 1:
        return True
    
    # 2 уровень (Старший администратор)
    if admin_level == 2:
        # Доступ ко всем командам КРОМЕ сбросвсех+ и сбросвсех-
        allowed_categories = [
            "main", "senior_admin", "economy", "clans", 
            "donat_services", "info", "players", "broadcast"
        ]
        return command_category in allowed_categories
    
    # 3 уровень (Модератор)
    if admin_level == 3:
        allowed_categories = ["main", "economy", "clans", "broadcast", "info"]
        return command_category in allowed_categories
    
    return False

async def log_admin_action(
    user_id: int, 
    action_type: str, 
    target_id: int = None,
    details: str = "",
    request_id: int = None
):
    """Логирование действий администратора"""
    admin = await get_player(user_id)
    admin_level = await get_admin_access_level(user_id)
    
    admin_name = admin.get("admin_nickname", admin["username"]) if admin else "Неизвестно"
    admin_level_name = {1: "Создатель", 2: "Старший администратор", 3: "Модератор"}.get(admin_level, "Неизвестно")
    
    log_details = details
    
    if target_id:
        target_player = await get_player(target_id)
        target_name = target_player["username"] if target_player else str(target_id)
        log_details = f"{details} | Цель: [id{target_id}|{target_name}]"
    
    if request_id:
        log_details = f"{details} | Заявка #{request_id}"
    
    # Определяем тип лога для категоризации
    log_type_map = {
        "set_dumbbell": "economy",
        "remove_balance": "economy", 
        "add_balance": "economy",
        "set_power": "economy",
        "set_custom_income": "economy",
        "set_lifts": "economy",
        "create_promo": "economy",
        "delete_promo": "economy",
        "make_admin": "senior_admin",
        "remove_admin": "senior_admin",
        "statistics": "senior_admin",
        "reset_all": "senior_admin",
        "approve_request": "senior_admin",
        "reject_request": "senior_admin",
        "broadcast": "broadcast",
        "donate_business": "donat_services",
        "info_access": "donat_services",
        "clan_rename": "clans",
        "clan_delete": "clans",
        "clan_info": "clans",
        "create_request": "requests",
        "ban_player": "bans",
        "permaban": "bans",
        "unban": "bans",
        "delete_player": "main",
        "change_username": "main",
        "set_admin_nickname": "main"
    }
    
    log_type = log_type_map.get(action_type, "other")
    
    await add_admin_log(
        user_id=user_id,
        admin_name=admin_name,
        admin_level=admin_level_name,
        action_type=action_type,
        details=log_details,
        log_type=log_type
    )

# ======================
# СИСТЕМА ЗАЯВОК
# ======================

async def generate_request_id() -> int:
    """Генерация уникального ID заявки"""
    global REQUEST_COUNTER
    request_id = REQUEST_COUNTER
    REQUEST_COUNTER += 1
    
    # Проверяем существующие заявки
    pending_requests = await get_pending_requests()
    if pending_requests:
        max_id = max(r["id"] for r in pending_requests)
        if max_id >= request_id:
            request_id = max_id + 1
            REQUEST_COUNTER = request_id + 1
    
    return request_id

async def create_moderator_request(
    admin_id: int,
    request_type: str,
    target_id: int,
    reason: str,
    additional_info: dict = None
) -> dict:
    """Создание заявки от модератора"""
    admin = await get_player(admin_id)
    request_id = await generate_request_id()
    
    if not admin:
        return {"success": False, "error": "Администратор не найден"}
    
    # Создаем заявку в базе
    result = await create_request(
        request_id=request_id,
        admin_id=admin_id,
        admin_name=admin.get("admin_nickname", admin["username"]),
        request_type=request_type,
        target_id=target_id,
        reason=reason,
        additional_info=additional_info
    )
    
    if result["success"]:
        # Логируем создание заявки
        await log_admin_action(
            admin_id,
            "create_request",
            target_id,
            f"Создал заявку #{request_id} на {request_type} | Причина: {reason}",
            request_id
        )
    
    return result

# ======================
# ФУНКЦИИ ДЛЯ КЛАВИАТУР
# ======================

def create_main_admin_keyboard(admin_level: int):
    """Создание основной клавиатуры администратора"""
    keyboard = Keyboard(inline=True)
    
    # Ряд 1: Экономика (зеленый)
    keyboard.add(Text("💰 Экономика"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Ряд 2: Информационные команды (синий)
    keyboard.add(Text("📊 Информация"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    
    # Ряд 3: Донат услуги (белый)
    keyboard.add(Text("💎 Донат услуги"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    
    # Ряд 4: Команды Старшей администрации (красный) - только для уровней 1-2
    if admin_level in [1, 2]:
        keyboard.add(Text("⭐ Старшая админ"), color=KeyboardButtonColor.NEGATIVE)
    
    return keyboard

def create_creator_keyboard():
    """Создание клавиатуры для создателя"""
    keyboard = Keyboard(inline=True)
    
    # Ряд 1: Команды Логирования (красный)
    keyboard.add(Text("📝 Команды Логирования"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    
    # Ряд 2: Основные команды создателя (зеленый)
    keyboard.add(Text("👑 Команды Создателя"), color=KeyboardButtonColor.POSITIVE)
    
    return keyboard

def create_logging_keyboard():
    """Создание клавиатуры для команд логирования"""
    keyboard = Keyboard(inline=True)
    
    # Первый ряд
    keyboard.add(Text("📋 Алоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("💰 Экологи"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Второй ряд
    keyboard.add(Text("📢 Связьлоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("💎 Донатлоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Третий ряд
    keyboard.add(Text("🏰 Кланлоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("📝 Заявкилоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Четвертый ряд
    keyboard.add(Text("🚫 Банлоги"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

def create_economy_keyboard(admin_level: int):
    """Создание клавиатуры для экономических команд"""
    keyboard = Keyboard(inline=True)
    
    # Первый ряд
    keyboard.add(Text("⚖️ Лгантеля"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("📉 -Баланс"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.add(Text("📈 +Баланс"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Второй ряд
    keyboard.add(Text("💪 Асила"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("💰 Заработок"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🏋️ Поднятия"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Третий ряд (только для уровней 1-2)
    if admin_level in [1, 2]:
        keyboard.add(Text("🎫 Создать промо"), color=KeyboardButtonColor.POSITIVE)
        keyboard.add(Text("🗑️ Удалить промо"), color=KeyboardButtonColor.NEGATIVE)
        keyboard.row()
    
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

def create_info_keyboard():
    """Создание клавиатуры для информационных команд"""
    keyboard = Keyboard(inline=True)
    
    keyboard.add(Text("👥 Аигроки"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🏰 Акинфо"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🎫 Промоинфо"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

def create_donat_keyboard(admin_level: int):
    """Создание клавиатуры для донат услуг"""
    keyboard = Keyboard(inline=True)
    
    keyboard.add(Text("💎 Б донат"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("📋 Б донат список"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("🔓 Доступ инфо"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("📊 Доступ инфо список"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

def create_senior_admin_keyboard(admin_level: int):
    """Создание клавиатуры для старшей администрации"""
    keyboard = Keyboard(inline=True)
    
    # Первый ряд
    keyboard.add(Text("👑 Назначить"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("❌ Снять"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    
    # Второй ряд
    keyboard.add(Text("📊 Статистика"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    
    # Третий ряд
    keyboard.add(Text("✅ Апринять"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("❌ Аотклонить"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    
    # Четвертый ряд
    keyboard.add(Text("📋 Аожидание"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

def create_creator_commands_keyboard():
    """Создание клавиатуры для команд создателя"""
    keyboard = Keyboard(inline=True)
    
    # Первый ряд
    keyboard.add(Text("🔄 Сбросвсех+"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.add(Text("❌ Сбросвсех-"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    
    # Второй ряд
    keyboard.add(Text("✅ Спринять"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("❌ Сотклонить"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    
    # Третий ряд
    keyboard.add(Text("📋 Ссписок"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("🔙 Назад"), color=KeyboardButtonColor.SECONDARY)
    
    return keyboard

# ======================
# ОСНОВНАЯ АДМИН КОМАНДА С КНОПКАМИ
# ======================

@admin_labeler.message(text=["Админ", "админ", "Админ_панель", "админ_панель"])
async def admin_main_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Создаем клавиатуру
    keyboard = create_main_admin_keyboard(admin_level)
    
    # Текст с командами раздела "Основные команды"
    main_commands = (
        "🏛️ Основные команды Администрации -\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        
        "📑 Основные команды:\n"
        "• Админпанель - показать админ панель\n"
        "• Аник [ник] - установить админ-ник\n"
        "• Бан [айди] [дни] [причина] - заблокировать игрока\n"
        "• Пермбан [айди] [причина] - перманентный бан\n"
        "• Разбан [айди] - разблокировать игрока\n"
        "• Удалить [айди] [причина] - удалить профиль игрока\n"
        "• Сгник [айди] [новый_ник] - сменить ник игроку\n"
        "• Рассылка [сообщение] - массовая рассылка (лимит 5/24ч для модераторов)\n\n"
        
        "💡 Используйте кнопки ниже для быстрого доступа к другим командам"
    )
    
    await message.answer(main_commands, keyboard=keyboard)

# ======================
# КОМАНДЫ СОЗДАТЕЛЯ
# ======================

@admin_labeler.message(text=["Схелп", "схелп", "Создатель", "создатель"])
async def creator_help_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    # Создаем клавиатуру
    keyboard = create_creator_keyboard()
    
    # Текст команд создателя
    creator_commands = (
        "👑 Команды создателя 👑\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        
        "Основные команды создателя:\n"
        "• Сбросвсех+ - подтвердить массовый сброс всех аккаунтов\n"
        "• Сбросвсех- - отменить массовый сброс\n"
        "• Спринять [номер] - принять заявку от старшей администрации\n"
        "• Сотклонить [номер] - отклонить заявку от старшей администрации\n"
        "• Ссписок - список непринятых заявок на массовый сброс\n\n"
        
        "💡 Используйте кнопки для доступа к специальным командам"
    )
    
    await message.answer(creator_commands, keyboard=keyboard)

# ======================
# ОБРАБОТЧИКИ КНОПОК
# ======================

@admin_labeler.message(text="💰 Экономика")
async def economy_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к этому разделу!"
    
    keyboard = create_economy_keyboard(admin_level)
    
    economy_text = (
        "💰 ЭКОНОМИЧЕСКИЕ КОМАНДЫ\n\n"
        "• Лгантеля [айди] [уровень] - установить уровень гантели\n"
        "• -Баланс [айди] [сумма] - убрать сумму с баланса игрока\n"
        "• +Баланс [айди] [сумма] - добавить сумму на баланс игрока\n"
        "• Асила [айди] [сила] - выдать игроку силу\n"
        "• Заработок [айди] [сумма] - установить кастомный доход\n"
        "• Поднятия [айди] [количество] - установить количество поднятий\n"
    )
    
    if admin_level in [1, 2]:
        economy_text += (
            "\n🎫 Команды промокодов (только для 1-2 уровня):\n"
            "• Создать промо [код] [использования] [тип] [сумма] - создать промокод\n"
            "• Удалить промо [код] - удалить промокод\n"
        )
    
    await message.answer(economy_text, keyboard=keyboard)

@admin_labeler.message(text="📊 Информация")
async def info_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    if not await can_use_command(user_id, "info"):
        return "❌ У вас нет доступа к этому разделу!"
    
    keyboard = create_info_keyboard()
    
    info_text = (
        "📊 ИНФОРМАЦИОННЫЕ КОМАНДЫ\n\n"
        "• Аигроки - полный список всех игроков\n"
        "• Акинфо [тег] - подробная информация о клане\n"
        "• Промоинфо [код] - информация о промокоде\n"
    )
    
    await message.answer(info_text, keyboard=keyboard)

@admin_labeler.message(text="💎 Донат услуги")
async def donat_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    if not await can_use_command(user_id, "donat_services"):
        return "❌ У вас нет доступа к этому разделу!"
    
    admin_level = await get_admin_access_level(user_id)
    keyboard = create_donat_keyboard(admin_level)
    
    donat_text = (
        "💎 ДОНАТ УСЛУГИ\n\n"
        "• Б донат [айди] [дни] - выдать доступ к донатному бизнесу\n"
        "• Б донат список - список игроков с доступом к донатному бизнесу\n"
        "• Доступ инфо [айди] [дни] - выдать доступ к команде Инфа\n"
        "• Доступ инфо список - список игроков с доступом к команде Инфа\n"
    )
    
    await message.answer(donat_text, keyboard=keyboard)

@admin_labeler.message(text="⭐ Старшая админ")
async def senior_admin_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ (только уровни 1-2)
    if admin_level not in [1, 2]:
        return "❌ Этот раздел доступен только Старшей администрации!"
    
    keyboard = create_senior_admin_keyboard(admin_level)
    
    senior_text = (
        "⭐ КОМАНДЫ СТАРШЕЙ АДМИНИСТРАЦИИ\n"
        f"{'❗' * 3} Команды ограничены {'❗' * 3}\n\n"
        
        "👑 Назначение администраторов:\n"
        "• Назначить [айди] [уровень] - назначить администратора\n"
        f"  {'❗' * 3} Уровень 2 может назначать только на уровень 3 {'❗' * 3}\n"
        "• Снять [айди] - снять с должности администратора\n\n"
        
        "📊 Статистика:\n"
        "• Статистика - полная статистика бота\n\n"
        
        "📋 Управление заявками:\n"
        "• Апринять [номер] - принять заявку от модератора\n"
        "• Аотклонить [номер] - отклонить заявку от модератора\n"
        "• Аожидание - список непринятых заявок\n\n"
        
        "🔄 Массовые операции:\n"
        "• Сбросвсех - создать заявку на массовый сброс\n"
        f"  {'❗' * 3} Для подтверждения обратитесь к создателю {'❗' * 3}"
    )
    
    await message.answer(senior_text, keyboard=keyboard)

@admin_labeler.message(text="📝 Команды Логирования")
async def logging_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    keyboard = create_logging_keyboard()
    
    logging_text = (
        "📝 КОМАНДЫ ЛОГИРОВАНИЯ\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        
        "Доступные команды:\n"
        "• Алоги - логи использования команд из раздела Старшей администрации\n"
        "• Экологи - логи использования команд из раздела Экономика\n"
        "• Связьлоги - логи использования команды Рассылка\n"
        "• Донатлоги - логи использования команд из раздела Донат услуги\n"
        "• Кланлоги - логи использования админ команд связанных с кланом\n"
        "• Заявкилоги - логи о созданных заявках\n"
        "• Банлоги - логи о использовании команд блокировок\n\n"
        
        "ℹ️ Логи автоматически очищаются каждые 15 дней"
    )
    
    await message.answer(logging_text, keyboard=keyboard)

@admin_labeler.message(text="👑 Команды Создателя")
async def creator_commands_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    keyboard = create_creator_commands_keyboard()
    
    commands_text = (
        "👑 КОМАНДЫ СОЗДАТЕЛЯ\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        
        "Массовые операции:\n"
        "• Сбросвсех+ - подтвердить массовый сброс всех аккаунтов\n"
        "• Сбросвсех- - отменить массовый сброс\n\n"
        
        "Управление заявками:\n"
        "• Спринять [номер] - принять заявку от старшей администрации\n"
        "• Сотклонить [номер] - отклонить заявку от старшей администрации\n"
        "• Ссписок - список непринятых заявок на массовый сброс"
    )
    
    await message.answer(commands_text, keyboard=keyboard)

@admin_labeler.message(text="🔙 Назад")
async def back_button_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    
    if admin_level == 1:
        # Возврат в меню создателя
        return await creator_help_handler(message)
    else:
        # Возврат в главное меню админа
        return await admin_main_handler(message)

# ======================
# КОМАНДЫ ЛОГИРОВАНИЯ (ТОЛЬКО ДЛЯ СОЗДАТЕЛЯ)
# ======================

@admin_labeler.message(text=["Алоги", "алоги"])
async def admin_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи команд старшей администрации
    logs = await get_admin_logs(log_type="senior_admin", limit=50)
    
    if not logs:
        return "📭 Логи команд Старшей администрации отсутствуют!"
    
    logs_text = "📋 ЛОГИ СТАРШЕЙ АДМИНИСТРАЦИИ\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Экологи", "экологи"])
async def economy_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи экономических команд
    logs = await get_admin_logs(log_type="economy", limit=50)
    
    if not logs:
        return "📭 Логи экономических команд отсутствуют!"
    
    logs_text = "💰 ЛОГИ ЭКОНОМИЧЕСКИХ КОМАНД\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Связьлоги", "связьлоги"])
async def broadcast_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи рассылок
    logs = await get_admin_logs(log_type="broadcast", limit=50)
    
    if not logs:
        return "📭 Логи рассылок отсутствуют!"
    
    logs_text = "📢 ЛОГИ РАССЫЛОК\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Донатлоги", "донатлоги"])
async def donat_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи донат услуг
    logs = await get_admin_logs(log_type="donat_services", limit=50)
    
    if not logs:
        return "📭 Логи донат услуг отсутствуют!"
    
    logs_text = "💎 ЛОГИ ДОНАТ УСЛУГ\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Кланлоги", "кланлоги"])
async def clan_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи клановых команд
    logs = await get_admin_logs(log_type="clans", limit=50)
    
    if not logs:
        return "📭 Логи клановых команд отсутствуют!"
    
    logs_text = "🏰 ЛОГИ КЛАНОВЫХ КОМАНД\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Заявкилоги", "заявкилоги"])
async def request_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи заявок
    logs = await get_admin_logs(log_type="requests", limit=50)
    
    if not logs:
        return "📭 Логи заявок отсутствуют!"
    
    logs_text = "📝 ЛОГИ ЗАЯВОК\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

@admin_labeler.message(text=["Банлоги", "банлоги"])
async def ban_logs_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ У вас нет прав администратора!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эти команды доступны только создателю!"
    
    # Получаем логи банов
    logs = await get_admin_logs(log_type="bans", limit=50)
    
    if not logs:
        return "📭 Логи блокировок отсутствуют!"
    
    logs_text = "🚫 ЛОГИ БЛОКИРОВОК\n\n"
    
    for log in logs:
        log_time = datetime.fromisoformat(log["created_at"]).strftime("%d.%m.%Y %H:%M:%S")
        logs_text += f"⏰ {log_time}\n"
        logs_text += f"👤 {log['admin_name']} ({log['admin_level']})\n"
        logs_text += f"📝 Действие: {log['action_type']}\n"
        logs_text += f"ℹ️ Детали: {log['details']}\n"
        logs_text += "─" * 30 + "\n"
    
    logs_text += f"\n📊 Всего записей: {len(logs)}"
    
    keyboard = create_logging_keyboard()
    await message.answer(logs_text, keyboard=keyboard)

# ======================
# КОМАНДЫ СТАРШЕЙ АДМИНИСТРАЦИИ
# ======================

@admin_labeler.message(text=["Назначить <cmd_args>", "назначить <cmd_args>"])
async def make_admin_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и уровень!\n📝 Использование: Назначить [айди] [уровень]\nУровни: 2 (Старший администратор), 3 (Модератор)"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        new_admin_level = int(parts[1])
    except ValueError:
        return "❌ Уровень админа должен быть числом (2 или 3)!"
    
    if new_admin_level not in [2, 3]:
        return "❌ Уровень админа может быть только 2 (Старший администратор) или 3 (Модератор)!"
    
    # Проверка для уровня 2 (Старший администратор)
    if admin_level == 2:
        if new_admin_level != 3:
            return "❌ Старший администратор может назначать только на уровень 3 (Модератор)!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Проверяем, не является ли уже админом
    if target_player.get("admin_level", 0) > 0:
        return f'❌ Игрок "{target_username}" уже является администратором!'
    
    # Назначаем админа
    admin_id = await make_admin(target_id, user_id, new_admin_level)
    
    level_name = "⭐ Старший администратор" if new_admin_level == 2 else "👮 Модератор"
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "make_admin",
        target_id,
        f"Назначил на должность {level_name}",
        None
    )
    
    return (
        f"✅ Игрок назначен администратором!\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"💎 Должность: {level_name}\n"
        f"🆔 Админ ID: {admin_id}\n"
        f"👮 Назначил: {level_name}\n\n"
        f"💡 Игрок получил доступ к админ панели: Админпанель"
    )

@admin_labeler.message(text=["Снять <cmd_args>", "снять <cmd_args>"])
async def remove_admin_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    try:
        target_id = int(pointer_to_screen_name(cmd_args))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    if target_player.get("admin_level", 0) == 0:
        return f'❌ Игрок "{target_username}" не является администратором!'
    
    target_admin_level = target_player["admin_level"]
    
    # Нельзя снимать самого себя
    if target_id == user_id:
        return "❌ Нельзя снять с должности самого себя!"
    
    # Для создателя: может снимать всех
    if admin_level == 1:
        pass  # Создатель может снимать всех
    # Для старшего администратора: может снимать только модераторов
    elif admin_level == 2:
        if target_admin_level not in [3]:
            return "❌ Старший администратор может снимать только модераторов!"
    
    # Нельзя снимать администраторов высшего уровня
    if target_admin_level < admin_level:
        return "❌ Вы не можете снять администратора высшего уровня!"
    
    # Снимаем с должности
    await remove_admin(target_id, user_id)
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "remove_admin",
        target_id,
        f"Снял с должности (бывший уровень: {target_admin_level})",
        None
    )
    
    return (
        f"✅ Администратор снят с должности!\n\n"
        f"👤 Администратор: [id{target_id}|{target_username}]\n"
        f"💎 Бывшая должность: Уровень {target_admin_level}\n"
        f"👮 Снял: {'Создатель' if admin_level == 1 else 'Старший администратор'}\n\n"
        f"⚠️ Игрок лишился всех админ прав и статистики"
    )

@admin_labeler.message(text=["Статистика", "статистика"])
async def bot_statistics_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    # Статистика игроков
    total_players = await count_players(False)
    banned_players = await count_banned_players()
    admin_players = await count_admins()
    total_balance = await count_total_balance()
    
    total_lifts = await sum_column("players", "total_lifts")
    total_earned = await sum_column("players", "total_earned")
    
    # Статистика кланов
    total_clans = await count_table_rows("clans")
    total_clan_treasury = await sum_column("clans", "treasury")
    total_clan_income = await sum_column("clans", "total_income_per_hour")
    
    # Статистика промокодов
    total_promos = await count_table_rows("promo_codes")
    total_promo_uses = await sum_promo_uses()
    
    # Последние регистрации
    recent_players = await get_recent_players()
    
    recent_text = ""
    for i, (username, created_at) in enumerate(recent_players, 1):
        date_str = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
        recent_text += f"{i}. {username} ({date_str})\n"
    
    stats_text = (
        f"📊 СТАТИСТИКА БОТА 📊\n"
        f"𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃 \n\n"
        f"💻 Игроки 💻\n"
        f"🎖️ Всего игроков: {total_players}\n"
        f"🎖️ Забанено: {banned_players}\n"
        f"🎖️ Администраторов: {admin_players}\n"
        f"🎖️ Активных: {total_players - banned_players}\n"
        f"🎖️ Общий баланс: {format_number(total_balance)} монет\n"
        f"🎖️ Всего поднятий: {format_number(total_lifts)}\n"
        f"🎖️ Всего заработано: {format_number(total_earned)} монет\n\n"
        f"🏰 Кланы 🏰\n"
        f"🛡️ Всего кланов: {total_clans}\n"
        f"🛡️ Общая казна: {format_number(total_clan_treasury)} монет\n"
        f"🛡️ Общий доход/час: {format_number(total_clan_income)} магнезии\n\n"
        f"🎫 Промокоды 🎫\n"
        f"🧾 Создано промокодов: {total_promos}\n"
        f"🔘 Всего активаций: {total_promo_uses}\n\n"
        f"📊 Последние регистрации 📊\n{recent_text}"
    )
    
    # Не логируем статистику (по требованию)
    
    return stats_text

@admin_labeler.message(text=["Апринять <request_id>", "апринять <request_id>"])
async def approve_moderator_request_handler(message: Message, request_id: str):
    """Принять заявку от модератора"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    try:
        request_id_int = int(request_id)
    except ValueError:
        return "❌ Номер заявки должен быть числом!"
    
    # Получаем информацию о заявке
    request_info = await get_request_by_id(request_id_int)
    
    if not request_info:
        return f"❌ Заявка #{request_id} не найдена!"
    
    if request_info["status"] != "pending":
        return f"❌ Заявка #{request_id} уже обработана!"
    
    # Проверяем, может ли администратор обработать эту заявку
    if admin_level == 2 and request_info["request_type"] == "reset_all":
        return "❌ Старший администратор не может принимать заявки на массовый сброс!"
    
    # Обрабатываем заявку
    result = await approve_request(request_id_int, user_id)
    
    if result["success"]:
        # Логируем действие
        await log_admin_action(
            user_id,
            "approve_request",
            request_info["target_id"],
            f"Принял заявку #{request_id} на {request_info['request_type']}",
            request_id_int
        )
        
        # Выполняем действие в зависимости от типа заявки
        if request_info["request_type"] == "delete_player":
            # Удаляем игрока
            await delete_player(request_info["target_id"], user_id)
            await increment_admin_stat(user_id, "deletions")
            
            response_text = (
                f"✅ Заявка #{request_id} принята и выполнена!\n\n"
                f"📋 Тип заявки: Удаление игрока\n"
                f"👤 Создал: {request_info['admin_name']}\n"
                f"🎯 Игрок: [id{request_info['target_id']}|{request_info['additional_info'].get('username', 'Неизвестно')}]\n"
                f"📝 Причина: {request_info['reason']}\n"
                f"✅ Принял: {'Создатель' if admin_level == 1 else 'Старший администратор'}"
            )
        
        elif request_info["request_type"] == "delete_clan":
            # Удаляем клан
            tag = request_info["additional_info"].get("tag", "")
            result_delete = await delete_clan(tag, user_id)
            
            if result_delete["success"]:
                response_text = (
                    f"✅ Заявка #{request_id} принята и выполнена!\n\n"
                    f"📋 Тип заявки: Удаление клана\n"
                    f"👤 Создал: {request_info['admin_name']}\n"
                    f"🏰 Клан: [{request_info['additional_info'].get('tag', '')}] {request_info['additional_info'].get('name', '')}\n"
                    f"📝 Причина: {request_info['reason']}\n"
                    f"✅ Принял: {'Создатель' if admin_level == 1 else 'Старший администратор'}"
                )
            else:
                response_text = f"✅ Заявка #{request_id} принята, но возникла ошибка при удалении клана: {result_delete['error']}"
        
        else:
            response_text = (
                f"✅ Заявка #{request_id} принята!\n\n"
                f"📋 Тип заявки: {request_info['request_type']}\n"
                f"👤 Создал: {request_info['admin_name']}\n"
                f"📝 Причина: {request_info['reason']}\n"
                f"✅ Принял: {'Создатель' if admin_level == 1 else 'Старший администратор'}"
            )
        
        return response_text
    else:
        return f"❌ Ошибка при обработке заявки: {result['error']}"

@admin_labeler.message(text=["Аотклонить <request_id>", "аотклонить <request_id>"])
async def reject_moderator_request_handler(message: Message, request_id: str):
    """Отклонить заявку от модератора"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    try:
        request_id_int = int(request_id)
    except ValueError:
        return "❌ Номер заявки должен быть числом!"
    
    # Получаем информацию о заявке
    request_info = await get_request_by_id(request_id_int)
    
    if not request_info:
        return f"❌ Заявка #{request_id} не найдена!"
    
    if request_info["status"] != "pending":
        return f"❌ Заявка #{request_id} уже обработана!"
    
    # Проверяем, может ли администратор обработать эту заявку
    if admin_level == 2 and request_info["request_type"] == "reset_all":
        return "❌ Старший администратор не может обрабатывать заявки на массовый сброс!"
    
    # Отклоняем заявку
    result = await reject_request(request_id_int, user_id, "Отклонено администратором")
    
    if result["success"]:
        # Логируем действие
        await log_admin_action(
            user_id,
            "reject_request",
            request_info["target_id"],
            f"Отклонил заявку #{request_id} на {request_info['request_type']}",
            request_id_int
        )
        
        return (
            f"❌ Заявка #{request_id} отклонена!\n\n"
            f"📋 Тип заявки: {request_info['request_type']}\n"
            f"👤 Создал: {request_info['admin_name']}\n"
            f"📝 Причина заявки: {request_info['reason']}\n"
            f"❌ Отклонил: {'Создатель' if admin_level == 1 else 'Старший администратор'}\n\n"
            f"💡 Создатель заявки получит уведомление"
        )
    else:
        return f"❌ Ошибка при отклонении заявки: {result['error']}"

@admin_labeler.message(text=["Аожидание", "аожидание"])
async def pending_requests_handler(message: Message):
    """Список непринятых заявок от модераторов"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    # Получаем ожидающие заявки
    pending_requests = await get_pending_requests()
    
    # Фильтруем заявки на массовый сброс для старшей администрации
    if admin_level == 2:
        pending_requests = [r for r in pending_requests if r["request_type"] != "reset_all"]
    
    if not pending_requests:
        return "📭 Нет ожидающих заявок!"
    
    requests_text = "📋 ОЖИДАЮЩИЕ ЗАЯВКИ\n\n"
    
    for i, request in enumerate(pending_requests, 1):
        created_time = datetime.fromisoformat(request["created_at"]).strftime("%d.%m.%Y %H:%M")
        
        requests_text += f"#{request['id']}. {request['request_type'].upper()}\n"
        requests_text += f"👤 Создал: {request['admin_name']}\n"
        
        if request["target_id"]:
            target_player = await get_player(request["target_id"])
            if target_player:
                requests_text += f"🎯 Цель: [id{request['target_id']}|{target_player['username']}]\n"
        
        requests_text += f"📝 Причина: {request['reason'][:50]}...\n"
        requests_text += f"⏰ Создана: {created_time}\n"
        
        if request["request_type"] == "reset_all" and admin_level == 2:
            requests_text += f"{'❗' * 3} Для подтверждения обратитесь к создателю {'❗' * 3}\n"
        
        requests_text += "─" * 30 + "\n"
    
    requests_text += f"\n📊 Всего заявок: {len(pending_requests)}\n"
    requests_text += "💡 Для принятия заявки: Апринять [номер]\n"
    requests_text += "💡 Для отклонения заявки: Аотклонить [номер]"
    
    keyboard = create_senior_admin_keyboard(admin_level)
    await message.answer(requests_text, keyboard=keyboard)

@admin_labeler.message(text=["Сбросвсех", "сбросвсех"])
async def reset_all_accounts_handler(message: Message):
    """Создание заявки на массовый сброс"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам старшей администрации
    if admin_level not in [1, 2]:
        return "❌ Эта команда доступна только Старшей администрации!"
    
    # Для уровня 2 (Старший администратор) создаем заявку
    if admin_level == 2:
        # Создаем заявку на массовый сброс
        result = await create_moderator_request(
            admin_id=user_id,
            request_type="reset_all",
            target_id=0,
            reason="Заявка на массовый сброс всех аккаунтов"
        )
        
        if result["success"]:
            return (
                f"📝 Заявка #{result['request_id']} создана!\n\n"
                f"🔄 Тип: Массовый сброс всех аккаунтов\n"
                f"{'❗' * 3} Для подтверждения обратитесь к создателю {'❗' * 3}\n\n"
                f"💡 Создатель может принять заявку командой:\n"
                f"Спринять {result['request_id']}"
            )
        else:
            return f"❌ Ошибка при создании заявки: {result['error']}"
    
    # Для создателя показываем обычное меню
    regular_players = await count_players(regular_only=True)
    total_clans = await count_clans()
    
    # Сохраняем запрос на сброс
    PENDING_RESETS[user_id] = {"timestamp": datetime.now()}
    
    return (
        f"⚠️ ПОДТВЕРЖДЕНИЕ СБРОСА ВСЕХ АККАУНТОВ\n\n"
        f"📊 Статистика:\n"
        f"🚨 Обычных игроков: {regular_players}\n"
        f"🚨 Кланов: {total_clans}\n"
        f"🚨 Администраторов:\n Не будут затронуты❗\n\n"
        f"❗ ВНИМАНИЕ! Это действие:\n"
        f"• Удалит ВСЕХ обычных игроков\n"
        f"• Удалит ВСЕ кланы\n"
        f"• Сбросит всю статистику\n"
        f"• Действие НЕОБРАТИМО!\n\n"
        f"✅ Для подтверждения: Сбросвсех+\n"
        f"❌ Для отмены: Сбросвсех-"
    )

# ======================
# КОМАНДЫ СОЗДАТЕЛЯ
# ======================

@admin_labeler.message(text=["Сбросвсех+", "сбросвсех+"])
async def confirm_reset_all_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    # Проверяем, есть ли запрос на сброс
    if user_id not in PENDING_RESETS:
        return "❌ Нет ожидающих подтверждения сбросов!"
    
    # Считаем статистику перед удалением
    deleted_players = await count_players(regular_only=True)
    deleted_clans = await count_clans()
    deleted_balance = await count_total_balance()
    
    await reset_all()
    
    # Удаляем запрос на сброс
    del PENDING_RESETS[user_id]
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "reset_all",
        0,
        f"Массовый сброс | Удалено: {deleted_players} игроков, {deleted_clans} кланов",
        None
    )
    
    return (
        f"🔄 Все аккаунты сброшены!\n\n"
        f"📊 Статистика удаления:\n"
        f" Удалено игроков: {deleted_players}\n"
        f" Удалено кланов: {deleted_clans}\n"
        f" Утеряно монет: {format_number(deleted_balance)}\n"
        f" Администраторы: Сохранены\n\n"
        f"✅ Бот готов к новому сезону!"
    )

@admin_labeler.message(text=["Сбросвсех-", "сбросвсех-"])
async def cancel_reset_all_handler(message: Message):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    # Проверяем, есть ли запрос на сброс
    if user_id not in PENDING_RESETS:
        return "❌ Нет ожидающих подтверждения сбросов!"
    
    # Отменяем сброс
    del PENDING_RESETS[user_id]
    
    return "✅ Сброс всех аккаунтов отменен!"

@admin_labeler.message(text=["Спринять <request_id>", "спринять <request_id>"])
async def approve_senior_request_handler(message: Message, request_id: str):
    """Принять заявку от старшей администрации"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    try:
        request_id_int = int(request_id)
    except ValueError:
        return "❌ Номер заявки должен быть числом!"
    
    # Получаем информацию о заявке
    request_info = await get_request_by_id(request_id_int)
    
    if not request_info:
        return f"❌ Заявка #{request_id} не найдена!"
    
    if request_info["status"] != "pending":
        return f"❌ Заявка #{request_id} уже обработана!"
    
    # Проверяем тип заявки (должен быть от старшей администрации)
    if request_info["request_type"] != "reset_all":
        return f"❌ Заявка #{request_id} не требует подтверждения создателя!"
    
    # Обрабатываем заявку
    result = await approve_request(request_id_int, user_id)
    
    if result["success"]:
        # Выполняем массовый сброс
        deleted_players = await count_players(regular_only=True)
        deleted_clans = await count_clans()
        deleted_balance = await count_total_balance()
        
        await reset_all()
        
        # Логируем действие
        await log_admin_action(
            user_id,
            "approve_request",
            0,
            f"Принял заявку #{request_id} на массовый сброс | Удалено: {deleted_players} игроков",
            request_id_int
        )
        
        return (
            f"✅ Заявка #{request_id} принята и выполнена!\n\n"
            f"📋 Тип заявки: {request_info['request_type']}\n"
            f"👤 Создал: {request_info['admin_name']} (Старший администратор)\n"
            f"✅ Принял: Создатель\n\n"
            f"📊 Результат:\n"
            f" Удалено игроков: {deleted_players}\n"
            f" Удалено кланов: {deleted_clans}\n"
            f" Утеряно монет: {format_number(deleted_balance)}\n\n"
            f"✅ Бот готов к новому сезону!"
        )
    else:
        return f"❌ Ошибка при обработке заявки: {result['error']}"

@admin_labeler.message(text=["Сотклонить <request_id>", "сотклонить <request_id>"])
async def reject_senior_request_handler(message: Message, request_id: str):
    """Отклонить заявку от старшей администрации"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    try:
        request_id_int = int(request_id)
    except ValueError:
        return "❌ Номер заявки должен быть числом!"
    
    # Получаем информацию о заявке
    request_info = await get_request_by_id(request_id_int)
    
    if not request_info:
        return f"❌ Заявка #{request_id} не найдена!"
    
    if request_info["status"] != "pending":
        return f"❌ Заявка #{request_id} уже обработана!"
    
    # Проверяем тип заявки (должен быть от старшей администрации)
    if request_info["request_type"] != "reset_all":
        return f"❌ Заявка #{request_id} не требует подтверждения создателя!"
    
    # Отклоняем заявку
    result = await reject_request(request_id_int, user_id, "Отклонено создателем")
    
    if result["success"]:
        # Логируем действие
        await log_admin_action(
            user_id,
            "reject_request",
            0,
            f"Отклонил заявку #{request_id} на массовый сброс от {request_info['admin_name']}",
            request_id_int
        )
        
        return (
            f"❌ Заявка #{request_id} отклонена!\n\n"
            f"📋 Тип заявки: {request_info['request_type']}\n"
            f"👤 Создал: {request_info['admin_name']} (Старший администратор)\n"
            f"📝 Причина заявки: {request_info['reason']}\n"
            f"❌ Отклонил: Создатель\n\n"
            f"💡 Старший администратор получит уведомление об отказе"
        )
    else:
        return f"❌ Ошибка при отклонении заявки: {result['error']}"

@admin_labeler.message(text=["Ссписок", "ссписок"])
async def creator_pending_requests_handler(message: Message):
    """Список заявок от старшей администрации на массовый сброс"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    if admin_level != 1:
        return "❌ Эта команда доступна только создателю!"
    
    # Получаем заявки от старшей администрации на массовый сброс
    pending_requests = await get_pending_requests()
    
    # Фильтруем только заявки на сброс от старшей администрации
    reset_requests = [r for r in pending_requests if r["request_type"] == "reset_all"]
    
    if not reset_requests:
        return "📭 Нет непринятых заявок от Старшей администрации на массовый сброс!"
    
    requests_text = "📋 ЗАЯВКИ НА МАССОВЫЙ СБРОС\n\n"
    
    for i, request in enumerate(reset_requests, 1):
        created_time = datetime.fromisoformat(request["created_at"]).strftime("%d.%m.%Y %H:%M")
        
        requests_text += f"#{request['id']}. ЗАЯВКА НА СБРОС\n"
        requests_text += f"👤 Создал: {request['admin_name']} (Старший администратор)\n"
        requests_text += f"📝 Причина: {request['reason']}\n"
        requests_text += f"⏰ Создана: {created_time}\n"
        requests_text += "─" * 30 + "\n"
    
    requests_text += f"\n📊 Всего заявок: {len(reset_requests)}\n"
    requests_text += "💡 Для принятия заявки: Спринять [номер]\n"
    requests_text += "💡 Для отклонения заявки: Сотклонить [номер]"
    
    keyboard = create_creator_commands_keyboard()
    await message.answer(requests_text, keyboard=keyboard)

# ======================
# ЭКОНОМИЧЕСКИЕ КОМАНДЫ
# ======================

@admin_labeler.message(text=["Лгантеля <cmd_args>", "лгантеля <cmd_args>"])
async def set_dumbbell_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и уровень гантели!\n📝 Использование: Лгантеля [айди] [уровень (1-20)]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        new_level = int(parts[1])
        if new_level < 1 or new_level > 20:
            return "❌ Уровень гантели должен быть от 1 до 20!"
    except:
        return "❌ Уровень гантели должен быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Устанавливаем уровень гантели
    if await set_dumbbell_level(target_id, new_level, user_id):
        dumbbell_info = settings.DUMBBELL_LEVELS[new_level]
        
        # Логируем действие
        await log_admin_action(
            user_id,
            "set_dumbbell",
            target_id,
            f"Установил гантель: {dumbbell_info['name']} (уровень {new_level})",
            None
        )
        
        return (
            f"✅ Уровень гантели изменен!\n\n"
            f"👤 Игрок: [id{target_id}|{target_username}]\n"
            f"⚖️ Новая гантеля: {dumbbell_info['name']}\n"
            f"⭐ Новый уровень: {new_level}\n"
            f"💰 Доход за подход: {dumbbell_info['income_per_use']} монет\n"
            f"👮 Изменил: [id{user_id}|{admin_nickname}]"
        )
    else:
        return "❌ Ошибка при изменении уровня гантели!"

@admin_labeler.message(text=["-Баланс <cmd_args>", "-баланс <cmd_args>"])
async def remove_balance_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и сумму!\n📝 Использование: -Баланс [айди] [сумма]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            return "❌ Сумма должна быть положительным числом!"
    except:
        return "❌ Сумма должна быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    if target_player["balance"] < amount:
        amount = target_player["balance"]  # Убираем весь баланс
    
    await update_player_balance(
        target_id,
        -amount,
        "admin_remove_balance",
        f"Администратор убрал {amount} монет",
        user_id,
    )
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "remove_balance",
        target_id,
        f"Убрал баланс: {format_number(amount)} монет | Новый баланс: {format_number(target_player['balance'] - amount)}",
        None
    )
    
    return (
        f"✅ Баланс уменьшен!\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"💰 Убрано: {format_number(amount)} монет\n"
        f"💳 Новый баланс: {format_number(target_player['balance'] - amount)} монет\n"
        f"👮 Изменил: [id{user_id}|{admin_nickname}]"
    )

@admin_labeler.message(text=["+Баланс <cmd_args>", "+баланс <cmd_args>"])
async def add_balance_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и сумму!\n📝 Использование: +Баланс [айди] [сумма]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            return "❌ Сумма должна быть положительным числом!"
    except:
        return "❌ Сумма должна быть числом!"
    
    if amount > 2_147_483_647:
        return "❌ Сумма слишком большая!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    await update_player_balance(
        target_id,
        amount,
        "admin_add_balance",
        f"Администратор добавил {amount} монет",
        user_id,
    )
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "add_balance",
        target_id,
        f"Добавил баланс: {format_number(amount)} монет | Новый баланс: {format_number(target_player['balance'] + amount)}",
        None
    )
    
    return (
        f"✅ Баланс увеличен!\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"💰 Добавлено: {format_number(amount)} монет\n"
        f"💳 Новый баланс: {format_number(target_player['balance'] + amount)} монет\n"
        f"👮 Изменил: [id{user_id}|{admin_nickname}]"
    )

@admin_labeler.message(text=["Асила <cmd_args>", "асила <cmd_args>"])
async def admin_set_power_handler(message: Message, cmd_args: str):
    """Выдать игроку силу"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и количество силы!\n📝 Использование: Асила [айди] [количество]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        power = int(parts[1])
        if power < 0:
            return "❌ Количество силы не может быть отрицательным!"
    except:
        return "❌ Количество силы должно быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Обновляем силу игрока
    await update_player_power(target_id, power, user_id)
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "set_power",
        target_id,
        f"Установил силу: {format_number(power)}",
        None
    )
    
    return (
        f"✅ Сила игрока изменена!\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"💪 Новая сила: {format_number(power)}\n"
        f"👮 Изменил: [id{user_id}|{admin_nickname}]"
    )

@admin_labeler.message(text=["Заработок <cmd_args>", "заработок <cmd_args>"])
async def set_custom_income_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и сумму дохода!\n📝 Использование: Заработок [айди] [сумма]\nДля сброса: Заработок [айди] сброс"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    income_str = parts[1]
    
    # Проверяем существование игрока
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    if income_str.lower() == "сброс":
        # Сбрасываем кастомный доход
        custom_income = None
        message_text = f"✅ Кастомный доход сброшен!\n\n👤 Игрок: [id{target_id}|{target_username}]\n💰 Теперь используется доход от гантели\n👮 Сбросил: Администратор"
        log_text = "Сбросил кастомный доход"
    else:
        try:
            custom_income = int(income_str)
            if custom_income < 1:
                return "❌ Доход должен быть положительным числом!"
            message_text = f"✅ Кастомный доход установлен!\n\n👤 Игрок: [id{target_id}|{target_username}]\n💰 Новый доход за подход: {format_number(custom_income)} монет\n👮 Установил: Администратор"
            log_text = f"Установил кастомный доход: {format_number(custom_income)} монет"
        except:
            return '❌ Доход должен быть числом или "сброс"!'
    
    # Устанавливаем кастомный доход
    await set_custom_income(target_id, custom_income, user_id)
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "set_custom_income",
        target_id,
        log_text,
        None
    )
    
    return message_text

@admin_labeler.message(text=["Поднятия <cmd_args>", "поднятия <cmd_args>"])
async def set_lifts_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "economy"):
        return "❌ У вас нет доступа к экономическим командам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и количество поднятий!\n📝 Использование: Поднятия [айди] [количество]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        new_total = int(parts[1])
        if new_total < 0:
            return "❌ Количество поднятий не может быть отрицательным!"
    except:
        return "❌ Количество поднятий должно быть числом!"
    
    # Проверяем существование игрока
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Устанавливаем количество поднятий
    await set_total_lifts(target_id, new_total, user_id)
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "set_lifts",
        target_id,
        f"Установил поднятия: {format_number(new_total)}",
        None
    )
    
    return (
        f"✅ Количество поднятий изменено!\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"💪 Новое количество: {format_number(new_total)} поднятий\n"
        f"👮 Изменил: [id{user_id}|{admin_nickname}]""
    )

@admin_labeler.message(text=["Создать промо <cmd_args>", "создать промо <cmd_args>"])
async def create_promo_handler(message: Message, cmd_args: str):
    """Создание промокода"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам промокодов
    if admin_level not in [1, 2]:
        return "❌ Команды промокодов доступны только для Старшей администрации и выше!"
    
    parts = cmd_args.split()
    if len(parts) < 4:
        return "❌ Недостаточно параметров!\n📝 Использование: Создать промо [код] [использования] [тип_награды] [сумма]\n\nТипы наград: монеты, магнезия, сила\nПример: Создать промо NEWYEAR2024 100 монеты 5000"
    
    code = parts[0].upper()
    
    try:
        uses_total = int(parts[1])
        if uses_total <= 0:
            return "❌ Количество использований должно быть положительным числом!"
    except:
        return "❌ Количество использований должно быть числом!"
    
    reward_type = parts[2].lower()
    if reward_type not in ["монеты", "магнезия", "сила"]:
        return "❌ Неверный тип награды!\n✅ Допустимые типы: монеты, магнезия, сила"
    
    try:
        reward_amount = int(parts[3])
        if reward_amount <= 0:
            return "❌ Сумма награды должна быть положительным числом!"
    except:
        return "❌ Сумма награды должна быть числом!"
    
    # Проверка лимитов для модераторов (уровень 3)
    if admin_level == 3:
        promo_stats = await get_moderator_promo_stats(user_id)
        
        # Проверяем лимиты
        if reward_type == "монеты" and reward_amount > 500:
            return "❌ Модератор не может создавать промокоды с наградой больше 500 монет!"
        
        if reward_type == "сила" and reward_amount > 300:
            return "❌ Модератор не может создавать промокоды с наградой больше 300 силы!"
        
        # Обновляем статистику
        await update_moderator_promo_stats(user_id, reward_type, reward_amount)
    
    # Проверяем срок действия (опциональный 5-й параметр)
    expires_days = None
    if len(parts) > 4:
        try:
            expires_days = int(parts[4])
            if expires_days <= 0:
                return "❌ Срок действия должен быть положительным числом дней!"
        except:
            return "❌ Срок действия должен быть числом дней!"
    
    if await create_promo_code(
        code, uses_total, reward_type, reward_amount, user_id, expires_days
    ):
        if expires_days:
            expires_date = (datetime.now() + timedelta(days=expires_days)).strftime(
                "%d.%m.%Y"
            )
            expires_text = f"⏳ Срок действия: {expires_days} дней (до {expires_date})"
        else:
            expires_text = "⏳ Срок действия: Не ограничен"
        
        # Логируем действие
        await log_admin_action(
            user_id,
            "create_promo",
            0,
            f"Создал промокод: {code} | Награда: {format_number(reward_amount)} {reward_type} | Использований: {uses_total}",
            None
        )
        
        return (
            f"🎫 Промокод создан!\n\n"
            f"🔑 Код: {code}\n"
            f"🎯 Использований: {uses_total}\n"
            f"💰 Награда: {format_number(reward_amount)} {reward_type}\n"
            f"{expires_text}\n\n"
            f"📢 Игроки могут активировать промокод командой:\n"
            f"Промо {code}"
        )
    else:
        return "❌ Промокод с таким кодом уже существует!"

@admin_labeler.message(text=["Удалить промо <code>", "удалить промо <code>"])
async def delete_promo_handler(message: Message, code: str):
    """Удаление промокода"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    # Проверяем доступ к командам промокодов
    if admin_level not in [1, 2]:
        return "❌ Команды промокодов доступны только для Старшей администрации и выше!"
    
    code = code.upper()
    promo_info = await get_promo_info(code)
    
    if not promo_info:
        return f"❌ Промокод {code} не найден!"
    
    await delete_promo_code(code, user_id)
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "delete_promo",
        0,
        f"Удалил промокод: {code} | Было использовано: {promo_info['uses_total'] - promo_info['uses_left']}/{promo_info['uses_total']}",
        None
    )
    
    return (
        f"🗑️ Промокод удален!\n\n"
        f"🔑 Код: {code}\n"
        f"🔄 Использовано: {promo_info['uses_total'] - promo_info['uses_left']}/{promo_info['uses_total']}\n"
        f"👮 Удалил: [id{user_id}|{admin_nickname}]""
    )

# ======================
# ИНФОРМАЦИОННЫЕ КОМАНДЫ
# ======================

@admin_labeler.message(text=["Аигроки", "аигроки"])
async def admin_all_players_handler(message: Message):
    """Полный список всех игроков"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "info"):
        return "❌ У вас нет доступа к информационным командам!"
    
    all_players = await get_all_players(limit=100)
    
    if not all_players:
        return "❌ Игроков не найдено!"
    
    players_text = ""
    for i, player in enumerate(all_players[:50], 1):
        banned = "🚫" if player.get("is_banned", 0) == 1 else ""
        admin = "👑" if player.get("admin_level", 0) == 1 else "⭐" if player.get("admin_level", 0) == 2 else "👮" if player.get("admin_level", 0) == 3 else ""
        players_text += f"{i}. {admin}{banned}[id{player['user_id']}|{player['username']}] | 💰{format_number(player['balance'])} | 💪{player['power']}\n"
    
    total_players = await count_players(False)
    shown_players = min(50, len(all_players))
    
    keyboard = create_info_keyboard()
    
    return (
        f"👥 ПОЛНЫЙ СПИСОК ИГРОКОВ\n\n"
        f"Всего игроков: {total_players}\n"
        f"Показано: {shown_players} из {len(all_players)}\n\n"
        f"{players_text}"
    )

@admin_labeler.message(text=["Акинфо <tag>", "акинфо <tag>"])
async def admin_clan_info_command(message: Message, tag: str):
    """Подробная информация о клане для администратора"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "info"):
        return "❌ У вас нет доступа к информационным командам!"
    
    clan = await get_clan_by_tag(tag)
    if not clan:
        return f"❌ Клан с тегом [{tag.upper()}] не найден!"
    
    # Получаем участников
    members = await get_clan_members(clan["id"], 50)
    
    # Получаем владельца
    owner = await get_player(clan["owner_id"])
    
    # Получаем лог операций
    log = await get_clan_treasury_log(clan["id"], 10)
    
    # Получаем бонусы клана
    clan_bonuses = get_clan_bonuses(clan["level"])
    
    # Форматируем информацию об участниках
    members_text = ""
    for i, member in enumerate(members[:15], 1):
        role_emoji = (
            "👑"
            if member["role"] == "owner"
            else ("⭐" if member["role"] == "officer" else "👤")
        )
        join_date = datetime.fromisoformat(member["joined_at"]).strftime("%d.%m")
        members_text += f"{i}. {role_emoji} {member['username']} (ID: {member['user_id']}) - {format_number(member['contributions'])} монет ({join_date})\n"
    
    # Форматируем лог операций
    log_text = ""
    for entry in log:
        action_emoji = (
            "➕"
            if entry["action_type"] == "deposit"
            else (
                "⬆️"
                if entry["action_type"] == "upgrade"
                else (
                    "💰"
                    if entry["action_type"] == "lift_income"
                    else (
                        "🏦"
                        if entry["action_type"] == "business_income"
                        else ("📊" if entry["action_type"] == "distribution" else "📝")
                    )
                )
            )
        )
        username = entry["username"] or "Система"
        time_str = datetime.fromisoformat(entry["created_at"]).strftime("%d.%m %H:%M")
        log_text += (
            f"• {action_emoji} {entry['description']} - {username} ({time_str})\n"
        )
    
    # Форматируем даты
    created_date = datetime.fromisoformat(clan["created_at"]).strftime("%d.%m.%Y %H:%M")
    days_exist = (datetime.now() - datetime.fromisoformat(clan["created_at"])).days
    
    response_text = (
        f"📊 ИНФОРМАЦИЯ О КЛАНЕ [{clan['tag']}]\n\n"
        f"🏷️ Название: {clan['name']}\n"
        f"👑 Владелец: {owner['username'] if owner else 'Не найден'} (ID: [id{owner['owner_id']}|{clan['owner_id']}])\n"
        f"⭐ Уровень: {clan['level']}\n"
        f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        f"👥 Участников: {len(members)}\n"
        f"📈 Доход/час: {format_number(clan['total_income_per_hour'])} магнезии\n"
        f"💪 Всего поднятий: {format_number(clan['total_lifts'])}\n"
        f"📅 Создан: {created_date} ({days_exist} дней)\n"
        f"🎯 Бонусы клана:\n"
        f" 💼 +{clan_bonuses['business_bonus_percent']}% от бизнесов в казну\n"
        f" ⚖️ +{clan_bonuses['lift_bonus_coins']} монет в казну с поднятий\n\n"
        f"🏆 Участники (топ-15):\n{members_text}\n"
        f"📜 Последние операции с казной:\n{log_text}"
    )
    
    keyboard = create_info_keyboard()
    await message.answer(response_text, keyboard=keyboard)

@admin_labeler.message(text=["Промоинфо <code>", "промоинфо <code>"])
async def promo_info_handler(message: Message, code: str):
    """Информация о промокоде"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "info"):
        return "❌ У вас нет доступа к информационным командам!"
    
    code = code.upper()
    promo_info = await get_promo_info(code)
    
    if not promo_info:
        return f"❌ Промокод {code} не найден!"
    
    created_date = datetime.fromisoformat(promo_info["created_at"]).strftime("%d.%m.%Y %H:%M")
    creator = await get_player(promo_info["created_by"])
    creator_name = creator["username"] if creator else "Неизвестно"
    
    expires_text = "Не ограничен"
    if promo_info.get("expires_at"):
        expires_date = datetime.fromisoformat(promo_info["expires_at"]).strftime("%d.%m.%Y %H:%M")
        expires_text = expires_date
        
        # Проверяем, не истек ли промокод
        if datetime.fromisoformat(promo_info["expires_at"]) < datetime.now():
            expires_text += " (Истек)"
    
    response_text = (
        f"🎫 ИНФОРМАЦИЯ О ПРОМОКОДЕ\n\n"
        f"🔑 Код: {code}\n"
        f"💰 Награда: {format_number(promo_info['reward_amount'])} {promo_info['reward_type']}\n"
        f"🔄 Использований: {promo_info['uses_total'] - promo_info['uses_left']}/{promo_info['uses_total']}\n"
        f"👤 Создал: [id{promo_info['created_by']}|{creator_name}]\n"
        f"📅 Создан: {created_date}\n"
        f"⏳ Срок действия: {expires_text}"
    )
    
    keyboard = create_info_keyboard()
    await message.answer(response_text, keyboard=keyboard)

# ======================
# ДОНАТ УСЛУГИ
# ======================

@admin_labeler.message(text=["Б донат <cmd_args>", "Бизнес донат <cmd_args>"])
async def admin_donate_business_handler(message: Message, cmd_args: str):
    """Выдать/отозвать доступ к донатному бизнесу"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "donat_services"):
        return "❌ У вас нет доступа к донат услугам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и срок в днях!\n📝 Использование: Б донат [айди] [срок_в_днях]\n📝 Для отзыва: Б донат [айди] 0"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        days = int(parts[1])
        if days < 0:
            return "❌ Срок должен быть положительным числом или 0!"
    except:
        return "❌ Срок должен быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Проверяем текущий доступ
    current_access = await get_donate_business_status(target_id)
    
    if days == 0:
        # Отзываем доступ
        if current_access:
            await remove_donate_business_access(target_id, user_id)
            
            # Логируем действие
            await log_admin_action(
                user_id,
                "donate_business",
                target_id,
                "Отозвал доступ к донатному бизнесу",
                None
            )
            
            return (
                f"❌ Доступ к донатному бизнесу отозван!\n\n"
                f"👤 Игрок: [id{target_id}|{target_username}]\n"
                f"👮 Отозвал: [id{user_id}|{admin_nickname}]"
            )
        else:
            return f"❌ У игрока [id{target_id}|{target_username}] нет доступа к донатному бизнесу!"
    else:
        # Выдаем или продлеваем доступ
        if current_access:
            # Продлеваем существующий доступ
            await set_donate_business_access(target_id, days, user_id)
            action_text = "продлён"
        else:
            # Выдаем новый доступ
            await set_donate_business_access(target_id, days, user_id)
            action_text = "выдан"
        
        expires_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
        
        # Логируем действие
        await log_admin_action(
            user_id,
            "donate_business",
            target_id,
            f"{action_text.capitalize()} доступ к донатному бизнесу на {days} дней",
            None
        )
        
        return (
            f"✅ Доступ к донатному бизнесу {action_text}!\n\n"
            f"👤 Игрок: [id{target_id}|{target_username}]\n"
            f"💎 Бизнес: Сеть элитных FITNESS клубов\n"
            f"⏳ Срок: {days} дней\n"
            f"📅 Истекает: {expires_date}\n\n"
            f"🎯 Теперь игрок может:\n"
            f"1. Купить бизнес #4 в магазине\n"
            f"2. Улучшать бизнес за монеты\n"
            f"3. Получать доход 500+ монет/час\n\n"
            f"👮 Выдал: [id{user_id}|{admin_nickname}]"
        )

@admin_labeler.message(text=["Б донат список", "Бизнес донат список"])
async def admin_donate_business_list_handler(message: Message):
    """Список игроков с доступом к донатному бизнесу"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "donat_services"):
        return "❌ У вас нет доступа к донат услугам!"
    
    all_access = await get_all_donate_business_access()
    
    if not all_access:
        return "❌ Ни у кого нет доступа к донатному бизнесу!"
    
    players_text = ""
    current_time = datetime.now()
    
    for i, access in enumerate(all_access, 1):
        player = await get_player(access["user_id"])
        admin = await get_player(access["admin_id"])
        
        if not player:
            continue
        
        granted_date = datetime.fromisoformat(access["granted_at"]).strftime("%d.%m.%Y")
        expires_at = datetime.fromisoformat(access["expires_at"])
        expires_date = expires_at.strftime("%d.%m.%Y")
        
        # Проверяем, не истек ли доступ
        if expires_at < current_time:
            status = "❌ Истек"
        else:
            days_left = (expires_at - current_time).days
            status = f"✅ {days_left} дней"
        
        admin_name = admin["username"] if admin else "Неизвестно"
        
        players_text += f"{i}. [id{player['user_id']}|{player['username']}] - выдал [id{access['admin_id']}|{admin_name}]\n"
        players_text += f"   📅 Выдан: {granted_date} | Истекает: {expires_date} | Статус: {status}\n"
    
    keyboard = create_donat_keyboard(await get_admin_access_level(user_id))
    
    return (
        f"📋 Игроки с доступом к донатному бизнесу:\n\n"
        f"Всего: {len(all_access)} игроков\n\n"
        f"{players_text}\n"
        f"👮 Для выдачи/продления/отзыва доступа:\n"
        f"Б донат [айди] [дни]"
    )

@admin_labeler.message(text=["Доступ инфо <cmd_args>", "доступ инфо <cmd_args>"])
async def grant_info_access_handler(message: Message, cmd_args: str):
    """Выдать/отозвать доступ к команде Инфа"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "donat_services"):
        return "❌ У вас нет доступа к донат услугам!"
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и срок в днях!\n📝 Использование: Доступ инфо [айди] [срок_в_днях]\n📝 Для отзыва: Доступ инфо [айди] 0"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    try:
        days = int(parts[1])
        if days < 0:
            return "❌ Срок должен быть положительным числом или 0!"
    except:
        return "❌ Срок должен быть числом!"
    
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Проверяем текущий доступ
    current_access = await get_info_access_details(target_id)
    
    if days == 0:
        # Отзываем доступ
        if current_access:
            await remove_info_access(target_id, user_id)
            expires_date = datetime.fromisoformat(current_access["expires_at"]).strftime("%d.%m.%Y")
            
            # Логируем действие
            await log_admin_action(
                user_id,
                "info_access",
                target_id,
                "Отозвал доступ к команде Инфа",
                None
            )
            
            return (
                f"❌ Доступ к команде Инфа отозван!\n\n"
                f"👤 Игрок: [id{target_id}|{target_username}]\n"
                f"📅 Истекал: {expires_date}\n"
                f"👮 Отозвал:[id{user_id}|{admin_nickname}]
            )
        else:
            return f"❌ У игрока [id{target_id}|{target_username}] нет доступа к команде Инфа!"
    else:
        # Выдаем или продлеваем доступ
        if current_access:
            # Продлеваем существующий доступ
            await extend_info_access(target_id, days, user_id)
            new_expires_at = (datetime.fromisoformat(current_access["expires_at"]) + timedelta(days=days))
            expires_date = new_expires_at.strftime("%d.%m.%Y")
            action_text = "продлён"
        else:
            # Выдаем новый доступ
            await set_info_access(target_id, days, user_id)
            expires_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
            action_text = "выдан"
        
        # Логируем действие
        await log_admin_action(
            user_id,
            "info_access",
            target_id,
            f"{action_text.capitalize()} доступ к команде Инфа на {days} дней",
            None
        )
        
        return (
            f"✅ Доступ к команде Инфа {action_text}!\n\n"
            f"👤 Игрок: [id{target_id}|{target_username}]\n"
            f"⏳ Срок: {days} дней\n"
            f"📅 Истекает: {expires_date}\n"
            f"🎯 Теперь игрок может использовать команду:\n"
            f"Инфа [айди_игрока]\n"
            f"👮 Выдал: [id{user_id}|{admin_nickname}]"
        )

@admin_labeler.message(text=["Доступ инфо список", "доступ инфо список"])
async def list_info_access_handler(message: Message):
    """Список игроков с доступом к команде Инфа"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    if not await can_use_command(user_id, "donat_services"):
        return "❌ У вас нет доступа к донат услугам!"
    
    all_access = await get_all_info_access()
    
    if not all_access:
        return "❌ Ни у кого нет доступа к команде Инфа!"
    
    players_text = ""
    current_time = datetime.now()
    
    for i, access in enumerate(all_access, 1):
        player = await get_player(access["user_id"])
        admin = await get_player(access["admin_id"])
        
        if not player:
            continue
        
        granted_date = datetime.fromisoformat(access["granted_at"]).strftime("%d.%m.%Y")
        expires_at = datetime.fromisoformat(access["expires_at"])
        expires_date = expires_at.strftime("%d.%m.%Y")
        
        # Проверяем, не истек ли доступ
        if expires_at < current_time:
            status = "❌ Истек"
        else:
            days_left = (expires_at - current_time).days
            status = f"✅ {days_left} дней"
        
        admin_name = admin["username"] if admin else "Неизвестно"
        
        players_text += f"{i}. [id{player['user_id']}|{player['username']}] - выдал [id{access['admin_id']}|{admin_name}]\n"
        players_text += f"   📅 Выдан: {granted_date} | Истекает: {expires_date} | Статус: {status}\n"
    
    keyboard = create_donat_keyboard(await get_admin_access_level(user_id))
    
    return (
        f"📋 Игроки с доступом к Инфа:\n\n"
        f"Всего: {len(all_access)} игроков\n\n"
        f"{players_text}\n"
        f"👮 Для выдачи/продления/отзыва доступа:\n"
        f"Доступ инфо [айди] [дни]"
    )

# ======================
# ОСНОВНЫЕ КОМАНДЫ (С ЗАЯВКАМИ ДЛЯ МОДЕРАТОРОВ)
# ======================

@admin_labeler.message(text=["Удалить <cmd_args>", "удалить <cmd_args>"])
async def delete_player_handler(message: Message, cmd_args: str):
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    parts = cmd_args.split()
    if len(parts) < 2:
        return "❌ Укажите айди игрока и причину!\n📝 Использование: Удалить [айди] [причина]"
    
    try:
        target_id = int(pointer_to_screen_name(parts[0]))
    except ValueError:
        return "❌ Айди игрока должно быть числом!"
    
    reason = " ".join(parts[1:])
    
    # Проверяем существование игрока
    target_player = await get_player(target_id)
    
    if not target_player:
        return "❌ Игрок с таким айди не найден!"
    
    target_username = target_player["username"]
    
    # Нельзя удалять администраторов
    if target_player.get("admin_level", 0) > 0:
        return "❌ Нельзя удалить администратора! Используйте Снять"
    
    # Для модераторов создаем заявку
    if admin_level == 3:
        result = await create_moderator_request(
            admin_id=user_id,
            request_type="delete_player",
            target_id=target_id,
            reason=reason,
            additional_info={
                "username": target_username,
                "balance": target_player["balance"],
                "power": target_player["power"]
            }
        )
        
        if result["success"]:
            return (
                f"📝 Заявка #{result['request_id']} создана!\n\n"
                f"👤 Игрок: [id{target_id}|{target_username}]\n"
                f"🆔 ID: {target_id}\n"
                f"💰 Баланс: {format_number(target_player['balance'])} монет\n"
                f"💪 Сила: {format_number(target_player['power'])}\n"
                f"📝 Причина: {reason}\n\n"
                f"💡 Старший администратор может принять заявку командой:\n"
                f"Апринять {result['request_id']}"
            )
        else:
            return f"❌ Ошибка при создании заявки: {result['error']}"
    
    # Для старшей администрации и создателя - прямое удаление
    created_date = datetime.fromisoformat(target_player["created_at"]).strftime(
        "%d.%m.%Y"
    )
    days_exist = (
        datetime.now() - datetime.fromisoformat(target_player["created_at"])
    ).days
    
    # Сохраняем запрос на удаление
    PENDING_DELETIONS[target_id] = {
        "admin_id": user_id,
        "username": target_username,
        "reason": reason,
        "timestamp": datetime.now(),
    }
    
    return (
        f"⚠️ ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ИГРОКА\n\n"
        f"👤 Игрок: [id{target_id}|{target_username}]\n"
        f"🆔 ID: {target_id}\n"
        f"💰 Баланс: {format_number(target_player['balance'])} монет\n"
        f"⚖️ Гантеля: {target_player['dumbbell_name']}\n"
        f"💪 Поднятий: {format_number(target_player['total_lifts'])}\n"
        f"📅 Зарегистрирован: {created_date} ({days_exist} дней)\n\n"
        f"📝 Причина удаления:\n{reason}\n\n"
        f"❗ ВНИМАНИЕ❗ Это действие необратимо❗\n"
        f"• Аккаунт будет полностью удален\n"
        f"• Баланс и прогресс будут утеряны\n\n"
        f"✅ Для подтверждения: Удалить+\n"
        f"❌ Для отмены: Удалить-"
    )

@admin_labeler.message(text=["Акудалить <tag>", "акудалить <tag>"])
async def admin_delete_clan_command(message: Message, tag: str):
    """Удаление клана администратором"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    if not await can_use_command(user_id, "clans"):
        return "❌ У вас нет доступа к клановым командам!"
    
    clan = await get_clan_by_tag(tag)
    if not clan:
        return f"❌ Клан с тегом [{tag.upper()}] не найден!"
    
    # Для модераторов создаем заявку
    if admin_level == 3:
        result = await create_moderator_request(
            admin_id=user_id,
            request_type="delete_clan",
            target_id=clan["id"],
            reason="Удаление клана администратором",
            additional_info={
                "tag": clan["tag"],
                "name": clan["name"],
                "treasury": clan["treasury"],
                "members_count": await get_clan_member_count(clan["id"])
            }
        )
        
        if result["success"]:
            return (
                f"📝 Заявка #{result['request_id']} создана!\n\n"
                f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
                f"💰 Казна: {format_number(clan['treasury'])} монет\n"
                f"👥 Участников: {await get_clan_member_count(clan['id'])}\n\n"
                f"💡 Старший администратор может принять заявку командой:\n"
                f"Апринять {result['request_id']}"
            )
        else:
            return f"❌ Ошибка при создании заявки: {result['error']}"
    
    # Проверяем, не находится ли подтверждение в ожидании
    if tag.upper() in PENDING_DELETIONS:
        # Подтверждаем удаление
        result = await delete_clan(tag, user_id)
        
        if result["success"]:
            # Логируем действие
            await log_admin_action(
                user_id,
                "clan_delete",
                clan["owner_id"],
                f"Удалил клан: [{clan['tag']}] {clan['name']} | Казна: {format_number(clan['treasury'])}",
                None
            )
            
            del PENDING_DELETIONS[tag.upper()]
            
            return (
                f"🗑️ Клан удален!\n\n"
                f"🔰 Тег: [{tag.upper()}]\n"
                f"🏷️ Название: {clan['name']}\n"
                f"👥 Участников исключено: {result['member_count']}\n"
                f"💰 Утеряно из казны: {format_number(clan['treasury'])} монет\n"
                f"👮 Удалил: [id{user_id}|{admin_nickname}]"
            )
        else:
            return f"❌ {result['error']}"
    else:
        # Запрашиваем подтверждение
        PENDING_DELETIONS[tag.upper()] = {
            "admin_id": user_id,
            "clan_name": clan["name"],
            "timestamp": datetime.now(),
        }
        
        member_count = await get_clan_member_count(clan["id"])
        
        response_text = (
            f"⚠️ ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ КЛАНА\n\n"
            f"🔰 Тег: [{tag.upper()}]\n"
            f"📑 Название: {clan['name']}\n"
            f"👑 Владелец: ID: [id{clan['owner_id']}|{clan['owner_id']}]\n"
            f"👥 Участников: {member_count}\n"
            f"💰 Казна: {format_number(clan['treasury'])} монет\n"
            f"📅 Существует: {(datetime.now() - datetime.fromisoformat(clan['created_at'])).days} дней\n\n"
            f"❗ ВНИМАНИЕ ❗\n"
            f"• Все участники будут исключены\n"
            f"• Казна будет утеряна\n"
            f"• Действие необратимо!\n\n"
            f"✅ Для подтверждения отправьте команду еще раз:\n"
            f"Акудалить {tag.upper()}"
        )
        await message.answer(response_text, disable_mentions=True)

@admin_labeler.message(text=["Рассылка <cmd_args>", "рассылка <cmd_args>"])
async def broadcast_message_handler(message: Message, cmd_args: str):
    """Массовая рассылка сообщений всем игрокам"""
    user_id = message.from_id
    
    if not await is_admin(user_id):
        return "❌ Только администраторы могут использовать эту команду!"
    
    admin_level = await get_admin_access_level(user_id)
    
    if not await can_use_command(user_id, "broadcast"):
        return "❌ У вас нет доступа к команде рассылки!"
    
    message_text = cmd_args
    
    if not message_text:
        return "❌ Укажите текст сообщения для рассылки!"
    
    # Проверяем лимит для модераторов
    if admin_level == 3:
        can_broadcast, stats = await check_broadcast_limit(user_id)
        if not can_broadcast:
            reset_time = stats.get("reset_time")
            if reset_time:
                reset_str = datetime.fromisoformat(reset_time).strftime("%H:%M")
                return f"❌ Лимит рассылок исчерпан! Вы использовали 5/5 рассылок за сутки.\n🔄 Сброс лимита в {reset_str}"
            else:
                return "❌ Лимит рассылок исчерпан! Вы использовали 5/5 рассылок за сутки."
    
    # Получаем всех игроков
    all_players = await get_all_players()
    
    if not all_players:
        return "❌ Нет игроков для рассылки!"
    
    total_players = len(all_players)
    successful_sends = 0
    failed_sends = 0
    
    # Обновляем статистику использования для модераторов
    if admin_level == 3:
        await increment_broadcast_usage(user_id)
    
    # Отправляем сообщение каждому игроку
    for player in all_players:
        try:
            # Используем API VK для отправки сообщения
            api = API(token=settings.VK_TOKEN)
            await api.messages.send(
                user_id=player["user_id"],
                message=f"📢 Рассылка от администрации:\n\n{message_text}\n\n💎 Gym Legend",
                random_id=0
            )
            successful_sends += 1
        except Exception as e:
            failed_sends += 1
            # Логируем ошибку, но продолжаем рассылку
            print(f"Ошибка отправки сообщения игроку {player['user_id']}: {e}")
    
    # Логируем действие
    await log_admin_action(
        user_id,
        "broadcast",
        0,
        f"Создал рассылку | Успешно: {successful_sends}/{total_players} | Текст: {message_text[:100]}...",
        None
    )
    
    return (
        f"📢 Массовая рассылка завершена!\n\n"
        f"📊 Статистика:\n"
        f" Всего игроков: {total_players}\n"
        f" Успешно отправлено: {successful_sends}\n"
        f" Не удалось отправить: {failed_sends}\n"
        f" Процент успеха: {(successful_sends/total_players*100):.1f}%\n\n"
        f"📝 Текст сообщения:\n{message_text}\n\n"
        f"👮 Отправил: [id{user_id}|{admin_nickname}]""
    )

# ======================
# АВТООЧИСТКА ЛОГОВ
# ======================

async def auto_cleanup_logs():
    """Автоочистка старых логов"""
    while True:
        try:
            await asyncio.sleep(15 * 24 * 60 * 60)  # 15 дней в секундах
            cleaned_logs = await cleanup_old_logs(15)
            cleaned_requests = await cleanup_old_requests(15)
            print(f"✅ Автоочистка логов выполнена: {cleaned_logs} логов, {cleaned_requests} заявок")
        except Exception as e:
            print(f"❌ Ошибка автоочистки логов: {e}")
            await asyncio.sleep(3600)  # Ждем час при ошибке

# ======================
# ЗАПУСК АВТООЧИСТКИ ЛОГОВ
# ======================

async def start_auto_cleanup():
    """Запуск автоочистки логов"""
    # Запускаем в фоновом режиме
    asyncio.create_task(auto_cleanup_logs())

# В основном файле бота нужно будет вызвать:
# await start_auto_cleanup()
