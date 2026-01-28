from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


DIR = Path(__file__).absolute().parent.parent.parent
BOT_DIR = Path(__file__).absolute().parent.parent


class EnvBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class BotSettings(EnvBaseSettings):
    BOT_TOKEN: str


class DBSettings(EnvBaseSettings):
    # Left for future compatibility with postgresql
    # DB_HOST: str = "postgres"
    # DB_PORT: int = 5432
    # DB_USER: str = "postgres"
    # DB_PASS: str | None = None
    # DB_NAME: str = "postgres"

    @property
    def database_path(self) -> str: 
        return "/home/timur/Documents/Languages/Python/Freelance/tutikovstanislav1/GymLegend/gym_legend.db"


class GameSettings(EnvBaseSettings):
    # ==============================
    # КОНСТАНТЫ ГАНТЕЛЕЙ (20 УРОВНЕЙ)
    # ==============================

    DUMBBELL_LEVELS: dict = {
        1: {"name": "Гантеля 1кг", "price": 0, "weight": "1кг", "income_per_use": 1, "power_per_use": 1, "display_gap": True},
        2: {"name": "Гантеля 2кг", "price": 10, "weight": "2кг", "income_per_use": 2, "power_per_use": 2, "display_gap": True},
        3: {"name": "Гантеля 3кг", "price": 25, "weight": "3кг", "income_per_use": 3, "power_per_use": 3, "display_gap": True},
        4: {"name": "Гантеля 4кг", "price": 50, "weight": "4кг", "income_per_use": 4, "power_per_use": 4, "display_gap": True},
        5: {"name": "Гантеля 5кг", "price": 100, "weight": "5кг", "income_per_use": 5, "power_per_use": 5, "display_gap": True},
        6: {"name": "Гантеля 6кг", "price": 150, "weight": "6кг", "income_per_use": 6, "power_per_use": 6, "display_gap": True},
        7: {"name": "Гантеля 7кг", "price": 175, "weight": "7кг", "income_per_use": 7, "power_per_use": 7, "display_gap": True},
        8: {"name": "Гантеля 8кг", "price": 200, "weight": "8кг", "income_per_use": 8, "power_per_use": 8, "display_gap": True},
        9: {"name": "Гантеля 9кг", "price": 215, "weight": "9кг", "income_per_use": 9, "power_per_use": 9, "display_gap": True},
        10: {"name": "Гантеля 10кг", "price": 250, "weight": "10кг", "income_per_use": 10, "power_per_use": 10, "display_gap": True},
        11: {"name": "Гантеля 11кг", "price": 300, "weight": "11кг", "income_per_use": 11, "power_per_use": 11, "display_gap": True},
        12: {"name": "Гантеля 12.5кг", "price": 350, "weight": "12.5кг", "income_per_use": 15, "power_per_use": 12, "display_gap": True},
        13: {"name": "Гантеля 15кг", "price": 400, "weight": "15кг", "income_per_use": 20, "power_per_use": 15, "display_gap": True},
        14: {"name": "Гантеля 17.5кг", "price": 475, "weight": "17.5кг", "income_per_use": 25, "power_per_use": 17, "display_gap": True},
        15: {"name": "Гантеля 20кг", "price": 550, "weight": "20кг", "income_per_use": 30, "power_per_use": 20, "display_gap": True},
        16: {"name": "Гантеля 22.5кг", "price": 650, "weight": "22.5кг", "income_per_use": 35, "power_per_use": 22, "display_gap": True},
        17: {"name": "Гантеля 25кг", "price": 750, "weight": "25кг", "income_per_use": 40, "power_per_use": 25, "display_gap": True},
        18: {"name": "Гантеля 27.5кг", "price": 850, "weight": "27.5кг", "income_per_use": 45, "power_per_use": 27, "display_gap": True},
        19: {"name": "Гантеля 30кг", "price": 1000, "weight": "30кг", "income_per_use": 50, "power_per_use": 30, "display_gap": True},
        20: {"name": "Гантеля 35кг", "price": 1100, "weight": "35кг", "income_per_use": 55, "power_per_use": 35, "display_gap": True}
    }

    DUMBBELL_COOLDOWN: int = 60
    
    # Разделитель между гантелями при выводе
    DUMBBELL_DISPLAY_SEPARATOR: str = "\n\n"

    # ==============================
    # БИЗНЕС КОНСТАНТЫ
    # ==============================

    BUSINESSES: dict = {
        1: {
            "name": "Fitness зал",
            "base_price": 150,
            "base_income": 5,
            "upgrade_price": 50,
            "income_increase": 5,
            "currency": "монет",
            "upgrade_currency": "монет",
            "upgrades": {
                1: {"name": "Улучшить освещение", "emoji": "🏢"},
                2: {"name": "Улучшить интерьер", "emoji": "🎨"},
                3: {"name": "Улучшить тренажёры", "emoji": "🏋️‍♂️"},
                4: {"name": "Улучшить грифы", "emoji": "⚙️"},
                5: {"name": "Улучшить персонал", "emoji": "👥"}
            }
        },
        2: {
            "name": "🏰 Элитный fitness клуб",
            "base_price": 35000,
            "base_income": 100,
            "upgrade_price": 500,
            "income_increase": 50,
            "currency": "монет",
            "upgrade_currency": "монет",
            "upgrades": {
                1: {"name": "Улучшить системы климат-контроля", "emoji": "🏢"},
                2: {"name": "Улучшить VIP зоны отдыха", "emoji": "🎨"},
                3: {"name": "Улучшить элитные тренажёры", "emoji": "🏋️‍♂️"},
                4: {"name": "Улучшить профессиональные штанги", "emoji": "⚙️"},
                5: {"name": "Улучшить тренерский состав", "emoji": "👥"}
            }
        },
        3: {
            "name": "👑 Сеть элитных fitness клубов",
            "base_price": 55000,
            "base_income": 500,
            "upgrade_price": 400,
            "income_increase": 50,
            "currency": "банок магнезии",
            "upgrade_currency": "банок магнезии",
            "upgrades": {
                1: {"name": "Улучшить международное управление", "emoji": "🏢"},
                2: {"name": "Улучшить архитектуру клубов", "emoji": "🎨"},
                3: {"name": "Улучшить эксклюзивное оборудование", "emoji": "🏋️‍♂️"},
                4: {"name": "Улучшить систему аналитики", "emoji": "⚙️"},
                5: {"name": "Улучшить менеджмент сети", "emoji": "👥"}
            }
        }
    }

    # ==============================
    # КОНСТАНТЫ КЛАНОВ
    # ==============================

    CLAN_CREATE_COST: int = 1000
    CLAN_UPGRADE_BASE_COST: int = 500

    # ==============================
    # АДМИН КОНСТАНТЫ
    # ==============================

    ADMIN_USERS: list[int] = [1, 322615766, 768764050]


class Settings(BotSettings, DBSettings, GameSettings):
    DEBUG: bool = False


settings = Settings()
