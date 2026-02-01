import re
from datetime import datetime

from vkbottle.bot import BotLabeler, Message
from vkbottle import Keyboard, Text, KeyboardButtonColor

from bot.core.config import settings
from bot.db import (
    create_clan,
    create_player,
    deposit_to_clan_treasury,
    get_clan_member_count,
    get_clan_members,
    get_clan_treasury_log,
    get_member_clan_role,
    get_player,
    get_player_clan,
    get_top_clans,
    log_collection_with_user,
    subtract_treasury,
    update_player_balance,
    upgrade_clan,
    update_clan_name,
    get_clan_by_tag,
    get_clan_by_name_search,
    delete_clan,
    update_clan_description,
    get_clan_log,
    log_clan_action,
    get_clan_requirements,
    get_player_contributions,
    update_clan_settings,
    get_all_clans,
)
from bot.services.clans import get_clan_bonuses
from bot.utils import format_number
from bot.utils.clan_helpers import (
    check_clan_permissions,
    validate_clan_membership,
    format_clan_members,
    format_clan_bonuses,
)

clan_labeler = BotLabeler()
clan_labeler.vbml_ignore_case = True

# Глобальная переменная для хранения ID последнего сообщения помощи
last_help_message_id = None


# ======================
# КОМАНДЫ КЛАНОВ
# ======================


@clan_labeler.message(text=["к создать <cmd_args>", "/к создать <cmd_args>"])
async def create_clan_handler(message: Message, cmd_args: str):
    """Создание клана"""
    user_id = message.from_id

    parts = cmd_args.strip().split(maxsplit=1)

    if len(parts) < 2:
        return "❌ Неверный формат команды!\n📝 Использование: /к создать [ТЭГ] [название]\nПример: /к создать LEG Легенда"

    tag = parts[0]
    clan_name = parts[1]

    player = await get_player(user_id)
    if not player:
        player = await create_player(user_id, str(message.from_id))

    # Проверяем баланс - 300 монет
    CLAN_CREATE_COST = 300
    if player["balance"] < CLAN_CREATE_COST:
        return f"❌ Недостаточно монет для создания клана!\n💵 Нужно: {format_number(CLAN_CREATE_COST)} монет\n💰 У вас: {format_number(player['balance'])} монет"

    # Проверяем тег клана
    if not re.match(r"^[A-Z]{3}$", tag.upper()):
        return "❌ Тег клана должен состоять из 3х английских букв!\n📝 Пример: LEG, GYM, FIT"

    # Проверяем название клана
    if len(clan_name) < 3 or len(clan_name) > 20:
        return "❌ Название клана должно быть от 3 до 20 символов!"

    # Проверяем, не состоит ли игрок уже в клане
    if player["clan_id"]:
        return "❌ Вы уже состоите в клане! Сначала выйдите из текущего клана."

    # Создаем клан
    result = await create_clan(tag, clan_name, user_id)

    if result["success"]:
        # Снимаем деньги за создание клана
        await update_player_balance(
            user_id,
            -CLAN_CREATE_COST,
            "clan_creation",
            f"Создание клана {tag.upper()}",
            None,
        )

        clan_bonuses = get_clan_bonuses(1)

        response_text = (
            f"🏰 Клан создан!\n\n"
            f"🔰 Тег: [{tag.upper()}]\n"
            f"🏷️ Название: {clan_name}\n"
            f"👑 Владелец: [id{player['user_id']}|{player['username']}]\n"
            f"💰 Потрачено: {format_number(CLAN_CREATE_COST)} монет\n"
            f"⭐ Уровень: 1\n\n"
            f"🎯 Бонусы клана:\n"
            f"├─ 💼 +{clan_bonuses['business_bonus_percent']}% к доходам с бизнесов\n"
            f"├─ 🏋️ +{clan_bonuses['lift_bonus_coins']} монет за поднятие\n"
            f"└─ 👥 Без ограничений по участникам!\n\n"
            f"💡 Используйте К помощь для списка команд клана"
        )
        await message.answer(response_text, disable_mentions=True)
    else:
        return f"❌ {result['error']}"


@clan_labeler.message(text=["к улучшить <option>", "/к улучшить <option>"])
async def upgrade_clan_handler(message: Message, option: str = "1"):
    """Улучшение уровня клана"""
    user_id = message.from_id
    clan = await get_player_clan(user_id)

    if not clan:
        return "❌ Вы не состоите в клане!"

    # Проверяем, является ли игрок владельцем
    if clan["owner_id"] != user_id:
        return "❌ Только владелец клана может улучшать его уровень!"

    option = option.lower()
    
    if option not in ["1", "максимум"]:
        return "❌ Используйте: К улучшить 1 - улучшить на 1 уровень\nили К улучшить максимум - улучшить максимально"

    # Получаем текущие бонусы
    current_bonuses = get_clan_bonuses(clan["level"])
    
    if option == "1":
        # Улучшаем на 1 уровень
        result = await upgrade_clan(clan["id"], upgrade_one_level=True)
        
        if result["success"]:
            # Получаем новые бонусы
            new_bonuses = get_clan_bonuses(result["new_level"])
            
            return (
                f"⭐ Клан улучшен на 1 уровень!\n\n"
                f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
                f"📈 Уровень: {clan['level']} → {result['new_level']}\n"
                f"💰 Потрачено из казны: {format_number(result['cost'])} монет\n"
                f"🏦 Остаток в казне: {format_number(clan['treasury'] - result['cost'])} монет\n\n"
                f"🎯 Новые бонусы:\n"
                f"├─ 💼 Бизнесы: +{current_bonuses['business_bonus_percent']}% → +{new_bonuses['business_bonus_percent']}%\n"
                f"├─ 🏋️ Поднятия: +{current_bonuses['lift_bonus_coins']} → +{new_bonuses['lift_bonus_coins']} монет\n"
                f"└─ 👥 Лимит участников: {current_bonuses.get('member_limit', '∞')} → {new_bonuses.get('member_limit', '∞')}"
            )
        else:
            return f"❌ {result['error']}"
    
    else:  # максимум
        # Улучшаем максимально на сколько хватит денег
        result = await upgrade_clan(clan["id"], upgrade_one_level=False)
        
        if result["success"]:
            # Получаем новые бонусы
            new_bonuses = get_clan_bonuses(result["new_level"])
            levels_upgraded = result["new_level"] - clan["level"]
            
            return (
                f"🚀 Клан улучшен максимально!\n\n"
                f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
                f"📈 Уровень: {clan['level']} → {result['new_level']} (+{levels_upgraded})\n"
                f"💰 Потрачено из казны: {format_number(result['total_cost'])} монет\n"
                f"🏦 Остаток в казне: {format_number(clan['treasury'] - result['total_cost'])} монет\n\n"
                f"🎯 Новые бонусы:\n"
                f"├─ 💼 Бизнесы: +{current_bonuses['business_bonus_percent']}% → +{new_bonuses['business_bonus_percent']}%\n"
                f"├─ 🏋️ Поднятия: +{current_bonuses['lift_bonus_coins']} → +{new_bonuses['lift_bonus_coins']} монет\n"
                f"└─ 👥 Лимит участников: {current_bonuses.get('member_limit', '∞')} → {new_bonuses.get('member_limit', '∞')}"
            )
        else:
            return f"❌ {result['error']}"


@clan_labeler.message(text=["к казна", "/к казна"])
async def clan_treasury_handler(message: Message):
    """Просмотр казны клана"""
    user_id = message.from_id
    clan = await get_player_clan(user_id)

    if not clan:
        return "❌ Вы не состоите в клане!"

    # Получаем участников клана
    members = await get_clan_members(clan["id"], 10)

    # Получаем лог операций
    log = await get_clan_treasury_log(clan["id"], 5)

    # Получаем бонусы клана
    clan_bonuses = get_clan_bonuses(clan["level"])

    # Форматируем информацию о участниках
    members_text = ""
    for i, member in enumerate(members[:5], 1):
        role_emoji = (
            "👑"
            if member["role"] == "owner"
            else ("⭐" if member["role"] == "officer" else "👤")
        )
        members_text += f"{i}. {role_emoji} [id{member['user_id']}|{member['username']}] - {format_number(member['contributions'])} монет\n"

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
                    else ("🏦" if entry["action_type"] == "business_income" else "📊")
                )
            )
        )
        username = entry["username"] or "Система"
        time_str = datetime.fromisoformat(entry["created_at"]).strftime("%d.%m %H:%M")
        log_text += f"{action_emoji} {username}: {entry['description']} ({time_str})\n"

    response_text = (
        f"🏦 КАЗНА КЛАНА [{clan['tag']}]\n\n"
        f"🏷️ Название: {clan['name']}\n"
        f"⭐ Уровень: {clan['level']}\n"
        f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        f"👥 Участников: {len(members)}\n\n"
        f"🎯 Бонусы клана:\n"
        f"├─ 💼 +{clan_bonuses['business_bonus_percent']}% от бизнесов в казну\n"
        f"├─ 🏋️ +{clan_bonuses['lift_bonus_coins']} монет в казну с каждого поднятия\n\n"
        f"🏆 Топ вкладчиков:\n{members_text}\n"
        f"📜 Последние операции:\n{log_text}\n"
        f"💡 Положить деньги: К положить [сумма]\n"
        f"💡 Снять деньги: К снять [сумма]"
    )

    await message.answer(response_text, disable_mentions=True)


@clan_labeler.message(text=["к", "К", "к профиль", "/к профиль"])
async def clan_profile_handler(message: Message):
    """Профиль клана"""
    user_id = message.from_id
    clan = await get_player_clan(user_id)

    if not clan:
        return "❌ Вы не состоите в клане!"

    # Получаем количество участников
    member_count = await get_clan_member_count(clan["id"])

    # Получаем владельца
    owner = await get_player(clan["owner_id"])
    owner_id = owner["user_id"]
    owner_name = owner["username"] if owner else "Неизвестно"

    # Получаем бонусы клана
    clan_bonuses = get_clan_bonuses(clan["level"])

    # Форматируем дату создания
    created_date = datetime.fromisoformat(clan["created_at"]).strftime("%d.%m.%Y")
    
    # Получаем требования
    requirements = await get_clan_requirements(clan["id"])
    min_level = requirements.get("min_level", 1)

    # Получаем описание
    description = clan.get("description", "Нет описания")

    # Формируем сообщение
    response_parts = [
        f"🏰 ПРОФИЛЬ КЛАНА [{clan['tag']}]",
        "",
        f"🏷️ Название: {clan['name']}",
        f"👑 Владелец: [id{owner_id}|{owner_name}]",
        f"⭐ Уровень: {clan['level']}",
        f"👥 Участников: {member_count}",
        f"💰 Казна: {format_number(clan['treasury'])} монет",
        f"📅 Основан: {created_date}",
        f"🎯 Требования: {min_level}+ уровень гантели",
        "",
        f"📝 Описание:\n{description}",
        "",
        "💡 Команды клана: К помощь",
    ]

    await message.answer("\n".join(response_parts), disable_mentions=True)


@clan_labeler.message(text=["к топ", "/к топ"])
async def clan_top_handler(message: Message):
    """Топ кланов"""
    clans = await get_top_clans(10)

    if not clans:
        return "🏆 Пока нет созданных кланов. Создайте первый!"

    top_text = "🏆 ТОП КЛАНОВ GYM LEGEND\n\n"

    for i, clan in enumerate(clans, 1):
        medal = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "🔸"))

        # Рассчитываем бонусы клана
        business_bonus = 5 + (clan["level"] - 1)
        lift_bonus = 1 + (clan["level"] - 1)

        top_text += (
            f"{medal} {i}. [{clan['tag']}] {clan['name']}\n"
            f"   ⭐ Уровень: {clan['level']} | 👥 {clan['member_count']} участников\n"
            f"   🏦 Казна: {format_number(clan['treasury'])} монет\n"
            f"   🎯 Бонусы: +{business_bonus}% от бизнесов, +{lift_bonus} монет с поднятий\n\n"
        )

    top_text += "💡 Создать клан: К создать [ТЭГ] [название]"

    return top_text


@clan_labeler.message(text=["к положить <amount>", "/к положить <amount>"])
async def clan_deposit_handler(message: Message, amount: str):
    """Внесение денег в казну клана"""
    try:
        amount = int(amount)
        if amount <= 0:
            return "❌ Сумма должна быть положительным числом!"
    except ValueError:
        return "❌ Сумма должна быть числом!"

    user_id = message.from_id
    player = await get_player(user_id)

    # Проверяем баланс игрока
    if player["balance"] < amount:
        return f"❌ Недостаточно средств на балансе!\n💰 Нужно: {format_number(amount)} монет\n💳 У вас: {format_number(player['balance'])} монет"

    result = await deposit_to_clan_treasury(user_id, amount)

    if result["success"]:
        clan = await get_player_clan(user_id)

        return (
            f"💰 Деньги внесены в казну клана!\n\n"
            f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
            f"💸 Внесено: {format_number(amount)} монет\n"
            f"🏦 Новая казна: {format_number(clan['treasury'])} монет\n"
            f"💳 Ваш баланс: {format_number(player['balance'] - amount)} монет\n\n"
            f"📈 Ваш вклад: {format_number(result['total_contributions'])} монет"
        )
    else:
        return f"❌ {result['error']}"


@clan_labeler.message(text=["к снять <amount>", "/к снять <amount>"])
async def withdraw_from_clan_treasury_handler(message: Message, amount: str):
    """Снять деньги из казны клана"""
    try:
        amount = int(amount)
        if amount <= 0:
            return "❌ Сумма должна быть положительным числом!"
    except ValueError:
        return "❌ Сумма должна быть числом!"
    
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Проверяем наличие средств в казне
    if clan["treasury"] < amount:
        return (
            f"❌ Недостаточно средств в казне!\n"
            f"💰 Нужно: {format_number(amount)} монет\n"
            f"🏦 В казне: {format_number(clan['treasury'])} монет"
        )
    
    # Снимаем деньги с казны
    await subtract_treasury(clan["id"], amount)
    
    # Зачисляем игроку
    await update_player_balance(
        user_id,
        amount,
        "clan_withdrawal",
        f"Снятие из казны клана [{clan['tag']}]",
        None,
    )
    
    # Логируем операцию
    await log_collection_with_user(
        clan["id"],
        user_id,
        "withdrawal",
        amount,
        f"Снятие {format_number(amount)} монет из казны",
    )
    
    await log_clan_action(
        clan["id"], user_id, "withdraw",
        f"Снял {format_number(amount)} монет из казны"
    )
    
    player = await get_player(user_id)
    
    return (
        f"💰 Деньги сняты из казны!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"💸 Снято: {format_number(amount)} монет\n"
        f"🏦 Остаток в казне: {format_number(clan['treasury'] - amount)} монет\n"
        f"💳 Ваш баланс: {format_number(player['balance'])} монет"
    )


@clan_labeler.message(text=["к распустить", "/к распустить"])
async def disband_clan_handler(message: Message):
    """Распустить клан"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    # Проверяем что пользователь владелец
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Запрашиваем подтверждение
    return (
        f"⚠️ ВНИМАНИЕ: Вы собираетесь распустить клан!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        f"👥 Участников: {await get_clan_member_count(clan['id'])}\n\n"
        f"❗ Это действие необратимо!\n"
        f"❓ Для подтверждения напишите: К распустить подтвердить"
    )


@clan_labeler.message(text=["к распустить подтвердить", "/к распустить подтвердить"])
async def disband_clan_confirm_handler(message: Message):
    """Подтверждение роспуска клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Удаляем клан
    await delete_clan(clan["id"])
    
    return (
        f"💥 Клан распущен!\n\n"
        f"🏰 [{clan['tag']}] {clan['name']} больше не существует.\n"
        f"👥 Все участники исключены из клана.\n"
        f"💰 Казна ({format_number(clan['treasury'])} монет) утеряна.\n\n"
        f"💡 Вы можете создать новый клан командой К создать"
    )


@clan_labeler.message(text=["к переименовать <new_name>", "/к переименовать <new_name>"])
async def rename_clan_handler(message: Message, new_name: str):
    """Переименовать клан"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Проверяем длину названия
    if len(new_name) < 3 or len(new_name) > 20:
        return "❌ Название клана должно быть от 3 до 20 символов!"
    
    old_name = clan["name"]
    await update_clan_name(clan["id"], new_name)
    await log_clan_action(
        clan["id"], user_id, "rename",
        f"Изменено название с '{old_name}' на '{new_name}'"
    )
    
    return (
        f"🏷️ Название клана изменено!\n\n"
        f"🏰 Клан: [{clan['tag']}]\n"
        f"📝 Было: {old_name}\n"
        f"📝 Стало: {new_name}"
    )


@clan_labeler.message(text=["к передать <user>", "/к передать <user>"])
async def transfer_clan_handler(message: Message, user: str):
    """Передача клана другому игроку"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    # Проверяем что пользователь владелец
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Парсим ID пользователя
    target_id = None
    if user.startswith("[id"):
        try:
            target_id = int(user.split("|")[0][3:])
        except:
            pass
    elif user.isdigit():
        target_id = int(user)
    
    if not target_id:
        return "❌ Укажите ID пользователя или упоминание!"
    
    # Нельзя передать самому себе
    if target_id == user_id:
        return "❌ Вы уже являетесь владельцем!"
    
    # Проверяем что цель состоит в том же клане
    target_clan = await get_player_clan(target_id)
    if not target_clan or target_clan["id"] != clan["id"]:
        return "❌ Этот игрок не состоит в вашем клане!"
    
    # Получаем информацию об игроках
    player = await get_player(user_id)
    target_player = await get_player(target_id)
    
    # Проверяем баланс игрока
    TRANSFER_COST = 500
    if player["balance"] < TRANSFER_COST:
        return f"❌ Недостаточно монет для передачи клана!\n💵 Нужно: {format_number(TRANSFER_COST)} монет\n💰 У вас: {format_number(player['balance'])} монет"
    
    # Снимаем деньги за передачу клана
    await update_player_balance(
        user_id,
        -TRANSFER_COST,
        "clan_transfer",
        f"Передача клана [{clan['tag']}] игроку {target_player['username']}",
        None,
    )
    
    # Передаем клан
    await db.clans.update_one(
        {"_id": clan["id"]},
        {"$set": {"owner_id": target_id}}
    )
    
    # Меняем роли
    await db.players.update_one(
        {"user_id": user_id},
        {"$set": {"clan_role": "officer"}}  # Бывший владелец становится офицером
    )
    
    await db.players.update_one(
        {"user_id": target_id},
        {"$set": {"clan_role": "owner"}}  # Новый владелец
    )
    
    # Логируем передачу
    await log_clan_action(
        clan["id"], user_id, "transfer",
        f"Передал клан игроку [id{target_id}|{target_player['username']}] за {format_number(TRANSFER_COST)} монет"
    )
    
    return (
        f"🔄 Клан передан новому владельцу!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👑 Новый владелец: [id{target_id}|{target_player['username']}]\n"
        f"💼 Бывший владелец: [id{user_id}|{player['username']}]\n"
        f"💰 Стоимость передачи: {format_number(TRANSFER_COST)} монет\n"
        f"💳 Ваш баланс: {format_number(player['balance'] - TRANSFER_COST)} монет\n\n"
        f"⚠️ Внимание: Вы больше не владелец клана!\n"
        f"⭐ Ваша новая роль: Офицер"
    )


@clan_labeler.message(text=["к вступить <tag>", "/к вступить <tag>"])
async def join_clan_handler(message: Message, tag: str):
    """Вступить в клан"""
    user_id = message.from_id
    player = await get_player(user_id)
    
    # Проверяем не состоит ли уже в клане
    if player.get("clan_id"):
        return "❌ Вы уже состоите в клане! Сначала покиньте текущий клан."
    
    # Ищем клан по тегу
    clan = await get_clan_by_tag(tag.upper())
    if not clan:
        return f"❌ Клан с тегом [{tag.upper()}] не найден!"
    
    # Проверяем требования клана
    requirements = await get_clan_requirements(clan["id"])
    min_level = requirements.get("min_level", 1)
    
    # Проверяем уровень гантели игрока
    player_level = player.get("dumbbell_level", 1)
    if player_level < min_level:
        return f"❌ Для вступления требуется {min_level} уровень гантели!\n📊 Ваш уровень: {player_level}"
    
    # Проверяем список исключенных
    banned_players = clan.get("banned_players", [])
    if user_id in banned_players:
        return "❌ Вы были исключены из этого клана!\n💡 Обратитесь к владельцу для восстановления."
    
    # Получаем бонусы клана для проверки лимита участников
    clan_bonuses = get_clan_bonuses(clan["level"])
    member_limit = clan_bonuses.get("member_limit", 50)
    
    current_members = await get_clan_member_count(clan["id"])
    if current_members >= member_limit:
        return f"❌ В клане достигнут лимит участников!\n👥 Максимум: {member_limit}"
    
    # Вступаем в клан
    await db.players.update_one(
        {"user_id": user_id},
        {"$set": {
            "clan_id": clan["id"],
            "clan_role": "member",
            "clan_joined_at": datetime.now().isoformat()
        }}
    )
    
    # Увеличиваем счетчик участников
    await db.clans.update_one(
        {"_id": clan["id"]},
        {"$inc": {"member_count": 1}}
    )
    
    await log_clan_action(
        clan["id"], user_id, "join",
        "Вступил в клан"
    )
    
    # Отправляем приветственное сообщение если есть
    greeting = clan.get("settings", {}).get("greeting")
    if greeting:
        greeting = greeting.replace("{player}", player["username"])
        greeting = greeting.replace("{clan}", clan["name"])
        greeting = greeting.replace("{tag}", clan["tag"])
    
    welcome_text = (
        f"🎉 Добро пожаловать в клан!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👤 Ваша роль: Участник\n"
        f"👥 Участников: {current_members + 1}/{member_limit}\n"
    )
    
    if greeting:
        welcome_text += f"\n👋 Приветствие от клана:\n{greeting}\n"
    
    welcome_text += f"\n💡 Используйте К для просмотра профиля клана"
    
    return welcome_text


@clan_labeler.message(text=["к кик <user>", "/к кик <user>"])
async def kick_member_handler(message: Message, user: str):
    """Исключить участника из клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Парсим ID пользователя
    target_id = None
    if user.startswith("[id"):
        try:
            target_id = int(user.split("|")[0][3:])
        except:
            pass
    elif user.isdigit():
        target_id = int(user)
    
    if not target_id:
        return "❌ Укажите ID пользователя или упоминание!"
    
    # Нельзя исключить самого себя
    if target_id == user_id:
        return "❌ Используйте К покинуть чтобы выйти из клана!"
    
    # Проверяем что цель состоит в том же клане
    target_clan = await get_player_clan(target_id)
    if not target_clan or target_clan["id"] != clan["id"]:
        return "❌ Этот игрок не состоит в вашем клане!"
    
    # Владелец не может быть исключен
    if clan["owner_id"] == target_id:
        return "❌ Нельзя исключить владельца клана!"
    
    # Проверяем права (офицер не может исключить другого офицера)
    kicker_role = await get_member_clan_role(user_id, clan["id"])
    target_role = await get_member_clan_role(target_id, clan["id"])
    
    if kicker_role[0] == "officer" and target_role[0] == "officer":
        return "❌ Офицер не может исключить другого офицера!"
    
    # Добавляем в список исключенных
    banned_players = clan.get("banned_players", [])
    if target_id not in banned_players:
        banned_players.append(target_id)
        await db.clans.update_one(
            {"_id": clan["id"]},
            {"$set": {"banned_players": banned_players}}
        )
    
    # Исключаем участника
    await db.players.update_one(
        {"user_id": target_id},
        {"$set": {"clan_id": None, "clan_role": None}}
    )
    
    # Уменьшаем счетчик участников
    await db.clans.update_one(
        {"_id": clan["id"]},
        {"$inc": {"member_count": -1}}
    )
    
    target_player = await get_player(target_id)
    await log_clan_action(
        clan["id"], user_id, "kick",
        f"Исключил [id{target_id}|{target_player['username']}]"
    )
    
    return (
        f"👢 Игрок исключен из клана!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👤 Исключен: [id{target_id}|{target_player['username']}]\n"
        f"🚫 В списке исключенных: ДА\n"
        f"👥 Осталось участников: {await get_clan_member_count(clan['id'])}\n\n"
        f"💡 Для восстановления: К восстановить [id{target_id}|{target_player['username']}]"
    )


@clan_labeler.message(text=["к восстановить <user>", "/к восстановить <user>"])
async def restore_member_handler(message: Message, user: str):
    """Восстановить возможность входа в клан"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Парсим ID пользователя
    target_id = None
    if user.startswith("[id"):
        try:
            target_id = int(user.split("|")[0][3:])
        except:
            pass
    elif user.isdigit():
        target_id = int(user)
    
    if not target_id:
        return "❌ Укажите ID пользователя или упоминание!"
    
    # Убираем из списка исключенных
    banned_players = clan.get("banned_players", [])
    if target_id in banned_players:
        banned_players.remove(target_id)
        await db.clans.update_one(
            {"_id": clan["id"]},
            {"$set": {"banned_players": banned_players}}
        )
        
        target_player = await get_player(target_id)
        await log_clan_action(
            clan["id"], user_id, "restore",
            f"Восстановил [id{target_id}|{target_player['username']}]"
        )
        
        return (
            f"✅ Игрок восстановлен!\n\n"
            f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
            f"👤 Восстановлен: [id{target_id}|{target_player['username']}]\n"
            f"🚫 В списке исключенных: НЕТ\n\n"
            f"💡 Теперь игрок может вступить в клан: К вступить {clan['tag']}"
        )
    else:
        return "❌ Этот игрок не в списке исключенных!"


@clan_labeler.message(text=["к покинуть", "/к покинуть"])
async def leave_clan_handler(message: Message):
    """Покинуть клан"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    # Владелец не может просто покинуть клан
    if clan["owner_id"] == user_id:
        return (
            "❌ Владелец не может покинуть клан!\n"
            "💡 Распустите клан или передайте владение:\n"
            "• К распустить\n"
            "• К передать [@игрок]\n"
        )
    
    player = await get_player(user_id)
    
    # Покидаем клан
    await db.players.update_one(
        {"user_id": user_id},
        {"$set": {"clan_id": None, "clan_role": None}}
    )
    
    # Уменьшаем счетчик участников
    await db.clans.update_one(
        {"_id": clan["id"]},
        {"$inc": {"member_count": -1}}
    )
    
    await log_clan_action(
        clan["id"], user_id, "leave",
        "Покинул клан"
    )
    
    return (
        f"👋 Вы покинули клан!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"💼 Ваш вклад остался в истории клана\n\n"
        f"💡 Вы можете создать новый клан или вступить в другой"
    )


@clan_labeler.message(text=["к список", "/к список"])
async def clan_members_list_handler(message: Message):
    """Список участников клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    members = await get_clan_members(clan["id"])
    members_text = await format_clan_members(members, 15)
    
    # Получаем бонусы
    clan_bonuses = get_clan_bonuses(clan["level"])
    
    return (
        f"👥 СОСТАВ КЛАНА [{clan['tag']}]\n\n"
        f"🏷️ Название: {clan['name']}\n"
        f"⭐ Уровень: {clan['level']}\n"
        f"👤 Участников: {len(members)}/{clan_bonuses.get('member_limit', '∞')}\n\n"
        f"{members_text}\n\n"
        f"💡 Подробнее: К состав"
    )


@clan_labeler.message(text=["к состав", "/к состав"])
async def clan_detailed_roster_handler(message: Message):
    """Подробный состав клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    members = await get_clan_members(clan["id"])
    
    # Группируем по ролям
    owners = [m for m in members if m["role"] == "owner"]
    officers = [m for m in members if m["role"] == "officer"]
    regular_members = [m for m in members if m["role"] == "member"]
    
    text = f"📊 ПОДРОБНЫЙ СОСТАВ [{clan['tag']}]\n\n"
    
    # Владельцы
    if owners:
        text += "👑 ВЛАДЕЛЬЦЫ:\n"
        for member in owners:
            contributions = member.get("contributions", 0)
            text += f"• [id{member['user_id']}|{member['username']}]"
            if contributions > 0:
                text += f" - {format_number(contributions)} монет"
            text += "\n"
        text += "\n"
    
    # Офицеры
    if officers:
        text += "⭐ ОФИЦЕРЫ:\n"
        for member in officers:
            contributions = member.get("contributions", 0)
            text += f"• [id{member['user_id']}|{member['username']}]"
            if contributions > 0:
                text += f" - {format_number(contributions)} монет"
            text += "\n"
        text += "\n"
    
    # Участники
    if regular_members:
        text += f"👤 УЧАСТНИКИ ({len(regular_members)}):\n"
        for i, member in enumerate(regular_members[:10], 1):
            contributions = member.get("contributions", 0)
            text += f"{i}. [id{member['user_id']}|{member['username']}]"
            if contributions > 0:
                text += f" - {format_number(contributions)} монет"
            text += "\n"
        
        if len(regular_members) > 10:
            text += f"...и ещё {len(regular_members) - 10} участников\n"
    
    text += f"\n📈 Всего участников: {len(members)}"
    
    await message.answer(text, disable_mentions=True)


@clan_labeler.message(text=["к назначить <user>", "/к назначить <user>"])
async def assign_officer_handler(message: Message, user: str):
    """Назначить офицера"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    # Только владелец может назначать офицеров
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Парсим ID пользователя
    target_id = None
    if user.startswith("[id"):
        try:
            target_id = int(user.split("|")[0][3:])
        except:
            pass
    elif user.isdigit():
        target_id = int(user)
    
    if not target_id:
        return "❌ Укажите ID пользователя или упоминание!"
    
    # Нельзя назначить самого себя
    if target_id == user_id:
        return "❌ Вы уже являетесь владельцем!"
    
    # Проверяем что цель состоит в том же клане
    target_clan = await get_player_clan(target_id)
    if not target_clan or target_clan["id"] != clan["id"]:
        return "❌ Этот игрок не состоит в вашем клане!"
    
    # Проверяем текущую роль
    target_role = await get_member_clan_role(target_id, clan["id"])
    
    if target_role[0] == "owner":
        return "❌ Этот игрок уже является владельцем!"
    
    if target_role[0] == "officer":
        return "❌ Этот игрок уже является офицером!"
    
    # Назначаем офицером
    await db.players.update_one(
        {"user_id": target_id},
        {"$set": {"clan_role": "officer"}}
    )
    
    target_player = await get_player(target_id)
    await log_clan_action(
        clan["id"], user_id, "assign_officer",
        f"Назначил офицером [id{target_id}|{target_player['username']}]"
    )
    
    return (
        f"⭐ Назначен новый офицер!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👤 Офицер: [id{target_id}|{target_player['username']}]\n\n"
        f"🎯 Права офицера:\n"
        f"• Может исключать участников\n"
        f"• Может снимать деньги из казны\n"
        f"• Может распределять казну\n"
        f"• Может просматривать лог действий"
    )


@clan_labeler.message(text=["к снять <user>", "/к снять <user>"])
async def demote_member_handler(message: Message, user: str):
    """Снять участника с должности офицера"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    # Только владелец может снимать офицеров
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    # Парсим ID пользователя
    target_id = None
    if user.startswith("[id"):
        try:
            target_id = int(user.split("|")[0][3:])
        except:
            pass
    elif user.isdigit():
        target_id = int(user)
    
    if not target_id:
        return "❌ Укажите ID пользователя или упоминание!"
    
    # Нельзя снять самого себя
    if target_id == user_id:
        return "❌ Вы не можете снять самого себя!"
    
    # Проверяем что цель состоит в том же клане
    target_clan = await get_player_clan(target_id)
    if not target_clan or target_clan["id"] != clan["id"]:
        return "❌ Этот игрок не состоит в вашем клане!"
    
    # Получаем текущую роль
    target_role = await get_member_clan_role(target_id, clan["id"])
    
    # Если уже участник, нечего снимать
    if target_role[0] == "member":
        return "❌ Этот игрок уже имеет базовую роль участника!"
    
    # Если владелец, нельзя снять
    if target_role[0] == "owner":
        return "❌ Нельзя снять владельца!"
    
    # Снимаем до участника
    await db.players.update_one(
        {"user_id": target_id},
        {"$set": {"clan_role": "member"}}
    )
    
    target_player = await get_player(target_id)
    await log_clan_action(
        clan["id"], user_id, "demote",
        f"Снял с должности офицера [id{target_id}|{target_player['username']}]"
    )
    
    return (
        f"📉 Игрок снят с должности офицера!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👤 Игрок: [id{target_id}|{target_player['username']}]\n"
        f"🎯 Новая роль: Участник"
    )


@clan_labeler.message(text=["к распределить всем <amount>", "/к распределить всем <amount>"])
async def clan_distribute_all_handler(message: Message, amount: str):
    """Распределить казну всем участникам поровну"""
    try:
        amount_per_member = int(amount)
        if amount_per_member <= 0:
            return "❌ Сумма должна быть положительной!"
    except ValueError:
        return "❌ Сумма должна быть числом!"
    
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Получаем всех участников
    members = await get_clan_members(clan["id"])
    total_amount = amount_per_member * len(members)
    
    if clan["treasury"] < total_amount:
        return f"❌ Недостаточно средств в казне!\n💰 Нужно: {format_number(total_amount)} монет\n🏦 В казне: {format_number(clan['treasury'])} монет"
    
    # Распределяем деньги
    distributed = []
    for member in members:
        await update_player_balance(
            member["user_id"],
            amount_per_member,
            "clan_distribution",
            f"Распределение из казны клана [{clan['tag']}]",
            None,
        )
        distributed.append(
            f"[id{member['user_id']}|{member['username']}]: {format_number(amount_per_member)} монет"
        )
    
    # Снимаем деньги с казны
    await subtract_treasury(clan["id"], total_amount)
    
    # Логируем операцию
    await log_collection_with_user(
        clan["id"],
        user_id,
        "distribution",
        total_amount,
        f"Распределение {format_number(amount_per_member)} монет каждому участнику",
    )
    
    await log_clan_action(
        clan["id"], user_id, "distribute_all",
        f"Распределил {format_number(total_amount)} монет всем участникам"
    )
    
    return (
        f"💰 Казна распределена всем участникам!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👥 Участников: {len(members)}\n"
        f"💸 Каждому: {format_number(amount_per_member)} монет\n"
        f"💰 Всего выдано: {format_number(total_amount)} монет\n"
        f"🏦 Остаток в казне: {format_number(clan['treasury'] - total_amount)} монет\n\n"
        f"📋 Получили:\n" + "\n".join(distributed[:5]) + 
        (f"\n...и ещё {len(distributed) - 5} участников" if len(distributed) > 5 else "")
    )


@clan_labeler.message(text=["к распределить топ <amount>", "/к распределить топ <amount>"])
async def clan_distribute_top_handler(message: Message, amount: str):
    """Распределение казны топ-участникам по вкладам"""
    try:
        amount_per_member = int(amount)
        if amount_per_member <= 0:
            return "❌ Сумма должна быть положительной!"
    except ValueError:
        return "❌ Сумма должна быть числом!"
    
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Получаем топ участников по вкладам
    members = await get_clan_members(clan["id"])
    if not members:
        return "❌ В клане нет участников!"
    
    # Сортируем по вкладам (по убыванию)
    members.sort(key=lambda x: x.get("contributions", 0), reverse=True)
    
    # Берем топ-3 (или меньше если участников меньше)
    top_n = min(3, len(members))
    top_members = members[:top_n]
    
    total_amount = amount_per_member * len(top_members)
    
    if clan["treasury"] < total_amount:
        return (
            f"❌ Недостаточно средств в казне!\n"
            f"💰 Нужно: {format_number(total_amount)} монет\n"
            f"🏦 В казне: {format_number(clan['treasury'])} монет"
        )
    
    # Распределяем деньги
    distributed = []
    for member in top_members:
        await update_player_balance(
            member["user_id"],
            amount_per_member,
            "clan_distribution_top",
            f"Топ-распределение из казны [{clan['tag']}]",
            None,
        )
        distributed.append(
            f"[id{member['user_id']}|{member['username']}]: {format_number(amount_per_member)} монет"
        )
    
    # Снимаем деньги с казны
    await subtract_treasury(clan["id"], total_amount)
    
    # Логируем операцию
    await log_collection_with_user(
        clan["id"],
        user_id,
        "distribution_top",
        total_amount,
        f"Топ-распределение {format_number(amount_per_member)} монет топ-{top_n} участникам",
    )
    
    await log_clan_action(
        clan["id"], user_id, "distribute_top",
        f"Распределил {format_number(total_amount)} монет топ-{top_n} участникам"
    )
    
    return (
        f"💰 Казна распределена топ-участникам!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👥 Топ-{top_n} участников по вкладам\n"
        f"💸 Каждому: {format_number(amount_per_member)} монет\n"
        f"💰 Всего выдано: {format_number(total_amount)} монет\n"
        f"🏦 Остаток в казне: {format_number(clan['treasury'])} монет\n\n"
        f"🏆 Получили:\n" + "\n".join(distributed)
    )


@clan_labeler.message(text=["к вклады <user>", "/к вклады <user>"])
async def player_contributions_handler(message: Message, user: str = ""):
    """Просмотр вкладов игрока в казну клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    target_id = user_id  # По умолчанию смотрим свои вклады
    
    if user:
        # Парсим ID пользователя
        if user.startswith("[id"):
            try:
                target_id = int(user.split("|")[0][3:])
            except:
                pass
        elif user.isdigit():
            target_id = int(user)
        
        # Проверяем что цель состоит в том же клане
        target_clan = await get_player_clan(target_id)
        if not target_clan or target_clan["id"] != clan["id"]:
            return "❌ Этот игрок не состоит в вашем клане!"
    
    # Получаем вклады игрока
    contributions = await get_player_contributions(target_id, clan["id"])
    
    # Получаем информацию об игроке
    target_player = await get_player(target_id)
    if not target_player:
        return "❌ Игрок не найден!"
    
    # Получаем место в рейтинге вкладов
    members = await get_clan_members(clan["id"])
    members.sort(key=lambda x: x.get("contributions", 0), reverse=True)
    
    player_rank = None
    for i, member in enumerate(members, 1):
        if member["user_id"] == target_id:
            player_rank = i
            break
    
    rank_text = f"🏆 Место в рейтинге вкладов: {player_rank}" if player_rank else ""
    
    # Форматируем процент от общей казны
    if clan["treasury"] > 0:
        percentage = (contributions / clan["treasury"]) * 100
        percentage_text = f"📊 Процент от казны: {percentage:.1f}%"
    else:
        percentage_text = ""
    
    player_name = target_player["username"]
    
    return (
        f"💰 ВКЛАДЫ В КАЗНУ КЛАНА\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"👤 Игрок: [id{target_id}|{player_name}]\n"
        f"💵 Всего внесено: {format_number(contributions)} монет\n"
        f"{rank_text}\n"
        f"{percentage_text}\n\n"
        f"📊 Статистика клана:\n"
        f"├─ 🏦 Всего в казне: {format_number(clan['treasury'])} монет\n"
        f"├─ 👥 Участников: {len(members)}\n"
        f"└─ 💰 Средний вклад: {format_number(clan['treasury'] // len(members) if members else 0)} монет\n\n"
        f"💡 Внести деньги: К положить [сумма]"
    )


@clan_labeler.message(text=["к инфо <tag>", "/к инфо <tag>"])
async def clan_info_handler(message: Message, tag: str):
    """Информация о любом клане"""
    clan = await get_clan_by_tag(tag.upper())
    if not clan:
        return f"❌ Клан с тегом [{tag.upper()}] не найден!"
    
    # Получаем владельца
    owner = await get_player(clan["owner_id"])
    owner_name = owner["username"] if owner else "Неизвестно"
    
    # Получаем участников
    members = await get_clan_members(clan["id"])
    
    # Получаем бонусы
    clan_bonuses = get_clan_bonuses(clan["level"])
    
    # Форматируем дату создания
    created_date = datetime.fromisoformat(clan["created_at"]).strftime("%d.%m.%Y")
    
    # Получаем требования
    requirements = await get_clan_requirements(clan["id"])
    min_level = requirements.get("min_level", 1)
    
    description = clan.get("description", "Нет описания")
    
    response = (
        f"🏰 ИНФОРМАЦИЯ О КЛАНЕ [{clan['tag']}]\n\n"
        f"🏷️ Название: {clan['name']}\n"
        f"👑 Владелец: [id{clan['owner_id']}|{owner_name}]\n"
        f"⭐ Уровень: {clan['level']}\n"
        f"👥 Участников: {len(members)}/{clan_bonuses.get('member_limit', '∞')}\n"
        f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        f"📅 Основан: {created_date}\n"
        f"🎯 Требования: {min_level}+ уровень гантели\n"
    )
    
    response += f"\n📝 Описание:\n{description}\n\n"
    
    response += (
        f"🎯 Бонусы клана:\n"
        f"├─ 💼 +{clan_bonuses['business_bonus_percent']}% от бизнесов в казну\n"
        f"└─ 🏋️ +{clan_bonuses['lift_bonus_coins']} монет в казну с каждого поднятия\n\n"
    )
    
    response += f"💡 Для вступления: К вступить {clan['tag']}"
    
    await message.answer(response, disable_mentions=True)


@clan_labeler.message(text=["к поиск <tag>", "/к поиск <tag>"])
async def clan_search_handler(message: Message, tag: str):
    """Поиск клана по тегу"""
    if len(tag) < 3:
        return "❌ Тег должен содержать 3 буквы!"
    
    clan = await get_clan_by_tag(tag.upper())
    if not clan:
        return f"❌ Клан с тегом [{tag.upper()}] не найден!"
    
    # Используем уже существующий обработчик для показа информации
    return await clan_info_handler(message, clan["tag"])


@clan_labeler.message(text=["к описание <description>", "/к описание <description>"])
async def clan_description_handler(message: Message, description: str):
    """Изменить описание клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    # Проверяем длину описания
    if len(description) > 500:
        return "❌ Описание не должно превышать 500 символов!"
    
    old_description = clan.get("description", "Нет описания")
    await update_clan_description(clan["id"], description)
    
    await log_clan_action(
        clan["id"], user_id, "update_description",
        f"Обновлено описание клана"
    )
    
    return (
        f"📝 Описание клана обновлено!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n\n"
        f"📖 Новое описание:\n{description}\n\n"
        f"💡 Просмотреть: К инфо {clan['tag']}"
    )


@clan_labeler.message(text=["к требование <level>", "/к требование <level>"])
async def clan_requirements_handler(message: Message, level: str):
    """Установить требования для вступления"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner"]
    )
    if not has_permission:
        return error_msg
    
    try:
        min_level = int(level)
        if min_level < 1:
            return "❌ Уровень должен быть положительным числом!"
    except ValueError:
        return "❌ Уровень должен быть числом!"
    
    # Устанавливаем требования
    clan_settings = clan.get("settings", {})
    clan_settings["requirements"] = {"min_level": min_level}
    await update_clan_settings(clan["id"], clan_settings)
    
    await log_clan_action(
        clan["id"], user_id, "set_requirements",
        f"Установил требования: {min_level}+ уровень гантели"
    )
    
    return (
        f"📋 Требования для вступления установлены!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n"
        f"🎯 Минимальный уровень гантели: {min_level}+\n\n"
        f"💡 Игроки с уровнем ниже {min_level} не смогут вступить в клан"
    )


@clan_labeler.message(text=["к приветствие <greeting>", "/к приветствие <greeting>"])
async def clan_greeting_handler(message: Message, greeting: str):
    """Установить приветственное сообщение"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    if greeting.lower() == "нет" or greeting.lower() == "off":
        # Убираем приветствие
        clan_settings = clan.get("settings", {})
        clan_settings["greeting"] = None
        await update_clan_settings(clan["id"], clan_settings)
        
        await log_clan_action(
            clan["id"], user_id, "remove_greeting",
            "Убрал приветственное сообщение"
        )
        
        return "✅ Приветственное сообщение убрано!"
    
    # Проверяем длину
    if len(greeting) > 200:
        return "❌ Приветствие не должно превышать 200 символов!"
    
    # Устанавливаем приветствие
    clan_settings = clan.get("settings", {})
    clan_settings["greeting"] = greeting
    await update_clan_settings(clan["id"], clan_settings)
    
    await log_clan_action(
        clan["id"], user_id, "set_greeting",
        "Установил приветственное сообщение"
    )
    
    return (
        f"👋 Приветственное сообщение установлено!\n\n"
        f"🏰 Клан: [{clan['tag']}] {clan['name']}\n\n"
        f"📝 Сообщение:\n{greeting}\n\n"
        f"💡 Это сообщение будет отправляться новым участникам при вступлении"
    )


@clan_labeler.message(text=["к лог", "/к лог"])
async def clan_log_handler(message: Message):
    """Просмотр лога действий клана"""
    user_id = message.from_id
    clan, error = await validate_clan_membership(user_id)
    if error:
        return error
    
    has_permission, error_msg = await check_clan_permissions(
        user_id, clan, ["owner", "officer"]
    )
    if not has_permission:
        return error_msg
    
    log_entries = await get_clan_log(clan["id"], 15)
    
    if not log_entries:
        return "📜 Лог действий пуст"
    
    log_text = f"📜 ЛОГ ДЕЙСТВИЙ КЛАНА [{clan['tag']}]\n\n"
    
    for entry in log_entries:
        user = await get_player(entry["user_id"])
        username = user["username"] if user else "Неизвестно"
        
        time = datetime.fromisoformat(entry["created_at"]).strftime("%d.%m %H:%M")
        
        action_icons = {
            "kick": "👢",
            "join": "🎉",
            "leave": "👋",
            "rename": "🏷️",
            "assign_officer": "⭐",
            "demote": "📉",
            "withdraw": "💰",
            "update_description": "📝",
            "set_requirements": "📋",
            "set_greeting": "👋",
            "remove_greeting": "❌",
            "distribute_all": "💰",
            "distribute_top": "🏆",
            "restore": "✅",
            "transfer": "🔄"
        }
        
        icon = action_icons.get(entry["action_type"], "📝")
        
        log_text += f"{icon} {time} [id{entry['user_id']}|{username}]: {entry['details']}\n"
    
    await message.answer(log_text, disable_mentions=True)


# ======================
# КОМАНДА ПОМОЩИ С КНОПКАМИ
# ======================


@clan_labeler.message(text=["к помощь", "К помощь", "клан помощь", "Клан помощь"])
async def clan_help_handler(message: Message):
    """Справка по командам клана с интерактивными кнопками"""
    global last_help_message_id
    
    # Получаем имя игрока
    user_id = message.from_id
    player = await get_player(user_id)
    player_name = player["username"] if player else "Игрок"
    
    # Проверяем, состоит ли игрок в клане
    clan_info = ""
    clan = await get_player_clan(user_id)
    if clan:
        # Получаем бонусы клана
        clan_bonuses = get_clan_bonuses(clan["level"])
        member_count = await get_clan_member_count(clan["id"])
        
        clan_info = (
            f"\n📊 Вы состоите в клане [{clan['tag']}] {clan['name']}\n"
            f"⭐ Уровень: {clan['level']}\n"
            f"👥 Участников: {member_count}\n"
            f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        )
    else:
        clan_info = "\n📊 Вы не состоите в клане\n💡 Создайте свой клан: К создать [ТЭГ] [название]"
    
    # Создаем клавиатуру с кнопками
    keyboard = Keyboard(one_time=False, inline=True)
    
    # 1. Главная кнопка - Создание и роспуск (синяя, большая, сверху по центру)
    keyboard.row()
    keyboard.add(Text("🏰 Создание и роспуск"), color=KeyboardButtonColor.PRIMARY)
    
    # 2-3. Второй ряд: Основные команды (справа) и Управление составом (слева)
    keyboard.row()
    keyboard.add(Text("🗂️ Основные команды"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("👑 Управление составом"), color=KeyboardButtonColor.PRIMARY)
    
    # 4-5. Третий ряд: Управление казной (справа) и Команды владельца (слева)
    keyboard.row()
    keyboard.add(Text("💲 Управление казной"), color=KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("🤴 Команды владельца"), color=KeyboardButtonColor.NEGATIVE)
    
    # 6-7. Четвертый ряд: Управление ролями (справа) и Поиск и инфо (слева)
    keyboard.row()
    keyboard.add(Text("👷‍♂️ Управление ролями"), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("🔎 Поиск и инфо"), color=KeyboardButtonColor.SECONDARY)
    
    # Основное сообщение с инструкцией
    help_text = (
        "📋 Список команд кланов 📋\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        f"👤 [id{user_id}|{player_name}], выберите нужную категорию команд:\n\n"
        f"{clan_info}\n\n"
        "👇 Нажмите на кнопку ниже"
    )
    
    # Если есть предыдущее сообщение - редактируем его
    if last_help_message_id:
        try:
            await message.ctx_api.messages.edit(
                peer_id=message.peer_id,
                conversation_message_id=last_help_message_id,
                message=help_text,
                keyboard=keyboard.get_json(),
                keep_forward_messages=True,
                keep_snippets=True,
                dont_parse_links=True
            )
            return
        except:
            pass  # Если не удалось отредактировать - отправляем новое
    
    # Отправляем новое сообщение
    msg = await message.answer(help_text, keyboard=keyboard.get_json())
    # Сохраняем ID сообщения для будущего редактирования
    last_help_message_id = msg.conversation_message_id


@clan_labeler.message(text="🏰 Создание и роспуск")
async def creation_disband_help_handler(message: Message):
    """Справка по созданию и роспуску клана"""
    help_text = (
        "🏰 СОЗДАНИЕ И РАСПУСК\n\n"
        "🎯 К создать [ТЭГ] [название]\n"
        "🎯 К распустить\n"
        "🎯 К распустить подтвердить\n\n"
        "🏷️ 3 английские буквы\n"
        "📝 3-20 символов\n"
        "💸 300 монет\n\n"
        "📌 К создать LEG Легенда\n"
        "⚠️ Необратимо!"
    )
    await show_help_with_back_button(message, help_text, "creation_disband")


@clan_labeler.message(text="🗂️ Основные команды")
async def basic_commands_help_handler(message: Message):
    """Справка по основным командам"""
    help_text = (
        "🗂️ ОСНОВНЫЕ КОМАНДЫ\n\n"
        "👑 К или К профиль\n"
        "👑 К топ\n"
        "👑 К казна\n"
        "👑 К вклады [@игрок]\n\n"
        "📊 Доступно всем участникам\n"
        "👀 Основная информация о клане"
    )
    await show_help_with_back_button(message, help_text, "basic_commands")


@clan_labeler.message(text="👑 Управление составом")
async def roster_management_help_handler(message: Message):
    """Справка по управлению составом"""
    help_text = (
        "👥 УПРАВЛЕНИЕ СОСТАВОМ\n\n"
        "🎯 К список\n"
        "🎯 К состав\n"
        "🎯 К вступить [ТЭГ]\n"
        "🎯 К покинуть\n"
        "🎯 К кик [@игрок]\n"
        "🎯 К восстановить [@игрок]\n\n"
        "👢 К кик [id123|Игрок]\n"
        "✅ К восстановить [id123|Игрок]\n"
        "🎯 К вступить LEG"
    )
    await show_help_with_back_button(message, help_text, "roster_management")


@clan_labeler.message(text="💲 Управление казной")
async def treasury_management_help_handler(message: Message):
    """Справка по управлению казной"""
    help_text = (
        "💰 УПРАВЛЕНИЕ КАЗНОЙ\n\n"
        "🎯 К положить [сумма]\n"
        "🎯 К снять [сумма]\n"
        "🎯 К распределить всем [сумма]\n"
        "🎯 К распределить топ [сумма]\n\n"
        "👑 Владелец и офицеры\n"
        "📈 К распределить всем 1000\n"
        "🏆 К распределить топ 5000\n"
        "💵 К положить 10000"
    )
    await show_help_with_back_button(message, help_text, "treasury_management")


@clan_labeler.message(text="🤴 Команды владельца")
async def clan_settings_help_handler(message: Message):
    """Справка по командам владельца"""
    help_text = (
        "🤴 КОМАНДЫ ВЛАДЕЛЬЦА\n\n"
        "🎯 К улучшить 1\n"
        "🎯 К улучшить максимум\n"
        "🎯 К переименовать [название]\n"
        "🎯 К описание [текст]\n"
        "🎯 К требование [уровень]\n"
        "🎯 К приветствие [текст]\n"
        "🎯 К приветствие нет\n"
        "🎯 К лог\n"
        "🎯 К передать [@игрок]\n\n"
        "⭐ Больше % от бизнесов\n"
        "⭐ Больше монет с поднятий\n"
        "📝 К описание Лучший клан!\n"
        "🎯 К требование 5"
    )
    await show_help_with_back_button(message, help_text, "clan_settings")


@clan_labeler.message(text="👷‍♂️ Управление ролями")
async def role_management_help_handler(message: Message):
    """Справка по управлению ролями"""
    help_text = (
        "⭐ УПРАВЛЕНИЕ РОЛЯМИ\n\n"
        "🎯 К назначить [@игрок]\n"
        "🎯 К снять [@игрок]\n\n"
        "👑 Только владелец\n"
        "⭐ Офицеры могут:\n"
        "👢 Исключать участников\n"
        "💸 Снимать деньги\n"
        "💰 Распределять казну\n"
        "📜 Просматривать лог\n"
        "⚙️ Менять настройки\n\n"
        "📌 К назначить [id123|Игрок]\n"
        "📉 К снять [id123|Игрок]"
    )
    await show_help_with_back_button(message, help_text, "role_management")


@clan_labeler.message(text="🔎 Поиск и инфо")
async def search_info_help_handler(message: Message):
    """Справка по поиску и информации"""
    help_text = (
        "🔍 ПОИСК И ИНФО\n\n"
        "🎯 К инфо [ТЭГ]\n"
        "🎯 К поиск [ТЭГ]\n\n"
        "👀 Доступно всем игрокам\n"
        "🏷️ 3 английские буквы\n\n"
        "📊 К инфо LEG\n"
        "🔎 К поиск GYM\n\n"
        "📋 Показывает:\n"
        "🏷️ Название и владелец\n"
        "⭐ Уровень и участники\n"
        "💰 Казна и требования\n"
        "📝 Описание и бонусы"
    )
    await show_help_with_back_button(message, help_text, "search_info")


# Функция для показа справки с кнопкой "Назад"
async def show_help_with_back_button(message: Message, help_text: str, section: str):
    """Показать справку с кнопкой возврата к главному меню"""
    global last_help_message_id
    
    # Добавляем красивый заголовок к каждой секции
    formatted_text = f"📚 КОМАНДЫ КЛАНА\n\n{help_text}\n\n👇 Нажмите 'Назад' чтобы вернуться"
    
    keyboard = Keyboard(one_time=False, inline=True)
    keyboard.add(Text("⬅️ Назад"), color=KeyboardButtonColor.SECONDARY)
    
    # Редактируем существующее сообщение
    if last_help_message_id:
        try:
            await message.ctx_api.messages.edit(
                peer_id=message.peer_id,
                conversation_message_id=last_help_message_id,
                message=formatted_text,
                keyboard=keyboard.get_json(),
                keep_forward_messages=True,
                keep_snippets=True,
                dont_parse_links=True
            )
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое
            msg = await message.answer(formatted_text, keyboard=keyboard.get_json())
            last_help_message_id = msg.conversation_message_id


# Обработчик возврата к главному меню
@clan_labeler.message(text="⬅️ Назад")
async def back_to_main_help_handler(message: Message):
    """Вернуться к главному меню команд"""
    global last_help_message_id
    
    # Получаем имя игрока
    user_id = message.from_id
    player = await get_player(user_id)
    player_name = player["username"] if player else "Игрок"
    
    # Проверяем, состоит ли игрок в клане
    clan_info = ""
    clan = await get_player_clan(user_id)
    if clan:
        # Получаем бонусы клана
        clan_bonuses = get_clan_bonuses(clan["level"])
        member_count = await get_clan_member_count(clan["id"])
        
        clan_info = (
            f"\n📊 Вы состоите в клане [{clan['tag']}] {clan['name']}\n"
            f"⭐ Уровень: {clan['level']}\n"
            f"👥 Участников: {member_count}\n"
            f"💰 Казна: {format_number(clan['treasury'])} монет\n"
        )
    else:
        clan_info = "\n📊 Вы не состоите в клане\n💡 Создайте свой клан: К создать [ТЭГ] [название]"
    
    # Создаем клавиатуру с кнопками
    keyboard = Keyboard(one_time=False, inline=True)
    
    # 1. Главная кнопка - Создание и роспуск (синяя, большая, сверху по центру)
    keyboard.row()
    keyboard.add(Text("🏰 Создание и роспуск"), color=KeyboardButtonColor.PRIMARY)
    
    # 2-3. Второй ряд: Основные команды (справа) и Управление составом (слева)
    keyboard.row()
    keyboard.add(Text("🗂️ Основные команды"), color=KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("👑 Управление составом"), color=KeyboardButtonColor.PRIMARY)
    
    # 4-5. Третий ряд: Управление казной (справа) и Команды владельца (слева)
    keyboard.row()
    keyboard.add(Text("💲 Управление казной"), color=KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("🤴 Команды владельца"), color=KeyboardButtonColor.NEGATIVE)
    
    # 6-7. Четвертый ряд: Управление ролями (справа) и Поиск и инфо (слева)
    keyboard.row()
    keyboard.add(Text("👷‍♂️ Управление ролями"), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("🔎 Поиск и инфо"), color=KeyboardButtonColor.SECONDARY)
    
    help_text = (
        "📋 Список команд кланов 📋\n"
        "𝐆𝐘𝐌 𝐋𝐄𝐆𝐄𝐍𝐃\n\n"
        f"👤 [id{user_id}|{player_name}], выберите нужную категорию команд:\n\n"
        f"{clan_info}\n\n"
        "👇 Нажмите на кнопку ниже"
    )
    
    # Редактируем существующее сообщение
    if last_help_message_id:
        try:
            await message.ctx_api.messages.edit(
                peer_id=message.peer_id,
                conversation_message_id=last_help_message_id,
                message=help_text,
                keyboard=keyboard.get_json(),
                keep_forward_messages=True,
                keep_snippets=True,
                dont_parse_links=True
            )
        except:
            # Если не удалось отредактировать, отправляем новое
            msg = await message.answer(help_text, keyboard=keyboard.get_json())
            last_help_message_id = msg.conversation_message_id
    else:
        # Если нет сохраненного ID, отправляем новое
        msg = await message.answer(help_text, keyboard=keyboard.get_json())
        last_help_message_id = msg.conversation_message_id
