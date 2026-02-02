import json
from datetime import datetime, timedelta

# ======================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ЛОГАМИ
# ======================

async def add_admin_log(
    user_id: int,
    admin_name: str,
    admin_level: str,
    action_type: str,
    details: str = "",
    log_type: str = "other"
) -> bool:
    """Добавление записи в логи администратора"""
    query = """
    INSERT INTO admin_logs 
    (user_id, admin_name, admin_level, action_type, details, log_type)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    await db.execute(query, user_id, admin_name, admin_level, action_type, details, log_type)
    return True


async def get_admin_logs(
    log_type: str = None,
    admin_id: int = None,
    limit: int = 50,
    offset: int = 0
) -> list:
    """Получение логов администратора"""
    query = "SELECT * FROM admin_logs WHERE 1=1"
    params = []
    
    if log_type:
        query += " AND log_type = %s"
        params.append(log_type)
    
    if admin_id:
        query += " AND user_id = %s"
        params.append(admin_id)
    
    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    return await db.fetch_all(query, *params)


async def cleanup_old_logs(days: int = 15) -> int:
    """Очистка старых логов"""
    query = """
    DELETE FROM admin_logs 
    WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
    """
    result = await db.execute(query, days)
    return result.rowcount


# ======================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ЗАЯВКАМИ
# ======================

async def create_request(
    request_id: int,
    admin_id: int,
    admin_name: str,
    request_type: str,
    target_id: int = None,
    reason: str = "",
    additional_info: dict = None
) -> dict:
    """Создание заявки"""
    query = """
    INSERT INTO admin_requests 
    (id, admin_id, admin_name, request_type, target_id, reason, additional_info)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    
    additional_info_json = json.dumps(additional_info) if additional_info else None
    
    try:
        await db.execute(
            query, request_id, admin_id, admin_name, request_type, 
            target_id, reason, additional_info_json
        )
        return {"success": True, "request_id": request_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_pending_requests() -> list:
    """Получение ожидающих заявок"""
    query = """
    SELECT * FROM admin_requests 
    WHERE status = 'pending'
    ORDER BY created_at ASC
    """
    return await db.fetch_all(query)


async def get_request_by_id(request_id: int) -> dict:
    """Получение заявки по ID"""
    query = "SELECT * FROM admin_requests WHERE id = %s"
    result = await db.fetch_one(query, request_id)
    
    if result and result.get("additional_info"):
        try:
            result["additional_info"] = json.loads(result["additional_info"])
        except:
            result["additional_info"] = {}
    
    return result


async def approve_request(request_id: int, approved_by: int) -> dict:
    """Подтверждение заявки"""
    query = """
    UPDATE admin_requests 
    SET status = 'approved', approved_by = %s, approved_at = NOW()
    WHERE id = %s AND status = 'pending'
    """
    
    try:
        result = await db.execute(query, approved_by, request_id)
        if result.rowcount > 0:
            return {"success": True}
        else:
            return {"success": False, "error": "Заявка не найдена или уже обработана"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def reject_request(request_id: int, rejected_by: int, reason: str = None) -> dict:
    """Отклонение заявки с указанием причины"""
    query = """
    UPDATE admin_requests 
    SET status = 'rejected', 
        approved_by = %s, 
        approved_at = NOW(),
        additional_info = JSON_SET(
            COALESCE(additional_info, '{}'), 
            '$.reject_reason', %s
        )
    WHERE id = %s AND status = 'pending'
    """
    
    try:
        result = await db.execute(query, rejected_by, reason or "Отклонено администратором", request_id)
        if result.rowcount > 0:
            return {"success": True}
        else:
            return {"success": False, "error": "Заявка не найдена или уже обработана"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_request(request_id: int) -> bool:
    """Удаление заявки"""
    query = "DELETE FROM admin_requests WHERE id = %s"
    result = await db.execute(query, request_id)
    return result.rowcount > 0


async def cleanup_old_requests(days: int = 15) -> int:
    """Очистка старых заявок"""
    query = """
    DELETE FROM admin_requests 
    WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY) 
    AND status != 'pending'
    """
    result = await db.execute(query, days)
    return result.rowcount


async def get_request_stats() -> dict:
    """Получение статистики по заявкам"""
    query = """
    SELECT 
        status,
        COUNT(*) as count
    FROM admin_requests 
    GROUP BY status
    """
    
    results = await db.fetch_all(query)
    stats = {}
    
    for row in results:
        stats[row["status"]] = row["count"]
    
    return stats


async def get_requests_by_admin(admin_id: int, limit: int = 20) -> list:
    """Получение заявок созданных администратором"""
    query = """
    SELECT * FROM admin_requests 
    WHERE admin_id = %s
    ORDER BY created_at DESC
    LIMIT %s
    """
    
    results = await db.fetch_all(query, admin_id, limit)
    
    for result in results:
        if result.get("additional_info"):
            try:
                result["additional_info"] = json.loads(result["additional_info"])
            except:
                result["additional_info"] = {}
    
    return results


# ======================
# ФУНКЦИИ ДЛЯ СТАТИСТИКИ ИСПОЛЬЗОВАНИЯ
# ======================

async def get_admin_usage_stats(admin_id: int) -> dict:
    """Получение статистики использования команд администратором"""
    query = """
    SELECT stat_type, SUM(stat_value) as total
    FROM admin_usage_stats 
    WHERE admin_id = %s 
    AND period_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    GROUP BY stat_type
    """
    
    results = await db.fetch_all(query, admin_id)
    stats = {}
    
    for row in results:
        stats[row["stat_type"]] = row["total"]
    
    return stats


async def update_admin_usage_stats(admin_id: int, stat_type: str, value: int = 1) -> bool:
    """Обновление статистики использования команд"""
    today = datetime.now().date()
    
    query = """
    INSERT INTO admin_usage_stats (admin_id, stat_type, stat_value, period_date)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
    stat_value = stat_value + VALUES(stat_value),
    updated_at = NOW()
    """
    
    await db.execute(query, admin_id, stat_type, value, today)
    return True


# ======================
# ФУНКЦИИ ДЛЯ СТАТИСТИКИ РАССЫЛОК
# ======================

async def get_broadcast_usage(admin_id: int) -> dict:
    """Получение статистики рассылок"""
    query = "SELECT * FROM admin_broadcast_stats WHERE admin_id = %s"
    result = await db.fetch_one(query, admin_id)
    
    if not result:
        # Создаем запись если нет
        await reset_broadcast_usage(admin_id)
        return {
            "usage_count": 0,
            "last_used": datetime.now(),
            "reset_time": datetime.now() + timedelta(days=1)
        }
    
    # Проверяем нужно ли сбросить счетчик (прошло 24 часа)
    reset_time = result["reset_time"]
    if isinstance(reset_time, str):
        reset_time = datetime.fromisoformat(reset_time.replace('Z', '+00:00'))
    
    if datetime.now() > reset_time:
        await reset_broadcast_usage(admin_id)
        return {
            "usage_count": 0,
            "last_used": datetime.now(),
            "reset_time": datetime.now() + timedelta(days=1)
        }
    
    return result


async def increment_broadcast_usage(admin_id: int) -> bool:
    """Увеличение счетчика рассылок"""
    query = """
    INSERT INTO admin_broadcast_stats (admin_id, usage_count, last_used)
    VALUES (%s, 1, NOW())
    ON DUPLICATE KEY UPDATE 
    usage_count = usage_count + 1,
    last_used = NOW()
    """
    
    await db.execute(query, admin_id)
    return True


async def reset_broadcast_usage(admin_id: int) -> bool:
    """Сброс счетчика рассылок"""
    next_reset = datetime.now() + timedelta(days=1)
    
    query = """
    INSERT INTO admin_broadcast_stats (admin_id, usage_count, reset_time)
    VALUES (%s, 0, %s)
    ON DUPLICATE KEY UPDATE 
    usage_count = 0,
    reset_time = %s,
    updated_at = NOW()
    """
    
    await db.execute(query, admin_id, next_reset, next_reset)
    return True


async def check_broadcast_limit(admin_id: int) -> tuple:
    """Проверка лимита рассылок"""
    stats = await get_broadcast_usage(admin_id)
    
    if stats["usage_count"] >= 5:
        return False, stats
    
    return True, stats


# ======================
# ФУНКЦИИ ДЛЯ СТАТИСТИКИ ПРОМОКОДОВ МОДЕРАТОРОВ
# ======================

async def get_moderator_promo_stats(admin_id: int) -> dict:
    """Получение статистики промокодов модератора"""
    query = "SELECT * FROM moderator_promo_stats WHERE admin_id = %s"
    result = await db.fetch_one(query, admin_id)
    
    if not result:
        return {
            "coins_used": 0,
            "magnesia_used": 0,
            "power_used": 0,
            "total_created": 0,
            "last_created": None
        }
    
    return result


async def update_moderator_promo_stats(admin_id: int, reward_type: str, amount: int) -> bool:
    """Обновление статистики промокодов"""
    # Сначала получаем текущую статистику
    current_stats = await get_moderator_promo_stats(admin_id)
    
    # Обновляем соответствующие поля
    if reward_type == "монеты":
        coins_used = current_stats["coins_used"] + amount
        magnesia_used = current_stats["magnesia_used"]
        power_used = current_stats["power_used"]
    elif reward_type == "магнезия":
        coins_used = current_stats["coins_used"]
        magnesia_used = current_stats["magnesia_used"] + amount
        power_used = current_stats["power_used"]
    elif reward_type == "сила":
        coins_used = current_stats["coins_used"]
        magnesia_used = current_stats["magnesia_used"]
        power_used = current_stats["power_used"] + amount
    else:
        coins_used = current_stats["coins_used"]
        magnesia_used = current_stats["magnesia_used"]
        power_used = current_stats["power_used"]
    
    total_created = current_stats["total_created"] + 1
    
    query = """
    INSERT INTO moderator_promo_stats 
    (admin_id, coins_used, magnesia_used, power_used, total_created, last_created)
    VALUES (%s, %s, %s, %s, %s, NOW())
    ON DUPLICATE KEY UPDATE 
    coins_used = VALUES(coins_used),
    magnesia_used = VALUES(magnesia_used),
    power_used = VALUES(power_used),
    total_created = VALUES(total_created),
    last_created = NOW(),
    updated_at = NOW()
    """
    
    await db.execute(query, admin_id, coins_used, magnesia_used, power_used, total_created)
    return True


async def get_promo_usage_stats(admin_id: int) -> dict:
    """Получение статистики использования промокодов администратором"""
    query = """
    SELECT 
        SUM(CASE WHEN reward_type = 'монеты' THEN reward_amount ELSE 0 END) as total_coins,
        SUM(CASE WHEN reward_type = 'магнезия' THEN reward_amount ELSE 0 END) as total_magnesia,
        SUM(CASE WHEN reward_type = 'сила' THEN reward_amount ELSE 0 END) as total_power,
        COUNT(*) as total_created
    FROM promo_codes 
    WHERE created_by = %s
    """
    
    result = await db.fetch_one(query, admin_id)
    
    return {
        "total_coins": result["total_coins"] or 0,
        "total_magnesia": result["total_magnesia"] or 0,
        "total_power": result["total_power"] or 0,
        "total_created": result["total_created"] or 0
    }


async def update_promo_usage_stats(admin_id: int, reward_type: str, amount: int) -> bool:
    """Обновление статистики использования промокодов"""
    # Эта функция вызывает update_moderator_promo_stats
    return await update_moderator_promo_stats(admin_id, reward_type, amount)


# ======================
# ФУНКЦИИ ДЛЯ РАБОТЫ С АДМИНИСТРАТОРАМИ
# ======================

async def get_admin_level(user_id: int) -> int:
    """Получение уровня администратора"""
    player = await get_player(user_id)
    if player:
        return player.get("admin_level", 0)
    return 0


async def make_admin(user_id: int, admin_id: int, level: int) -> int:
    """Назначение администратора"""
    query = """
    UPDATE players 
    SET admin_level = %s, admin_since = NOW()
    WHERE user_id = %s
    """
    
    await db.execute(query, level, user_id)
    
    # Логируем действие
    admin = await get_player(admin_id)
    target = await get_player(user_id)
    
    if admin and target:
        await add_admin_log(
            admin_id=admin_id,
            admin_name=admin.get("admin_nickname", admin["username"]),
            admin_level="Создатель" if admin.get("admin_level") == 1 else "Старший администратор",
            action_type="make_admin",
            details=f"Назначил {target['username']} на уровень {level}",
            log_type="senior_admin"
        )
    
    return user_id


async def remove_admin(user_id: int, admin_id: int) -> bool:
    """Снятие администратора"""
    query = """
    UPDATE players 
    SET admin_level = 0, admin_since = NULL, admin_nickname = NULL
    WHERE user_id = %s AND admin_level > 0
    """
    
    result = await db.execute(query, user_id)
    
    if result.rowcount > 0:
        # Логируем действие
        admin = await get_player(admin_id)
        target = await get_player(user_id)
        
        if admin and target:
            await add_admin_log(
                admin_id=admin_id,
                admin_name=admin.get("admin_nickname", admin["username"]),
                admin_level="Создатель" if admin.get("admin_level") == 1 else "Старший администратор",
                action_type="remove_admin",
                details=f"Снял с должности {target['username']}",
                log_type="senior_admin"
            )
        
        return True
    
    return False
