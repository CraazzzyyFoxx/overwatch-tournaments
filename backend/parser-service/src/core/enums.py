# Import all enums from shared library and re-export
from shared.core.enums import *

from enum import StrEnum


# Parser-specific enum
class RouteTag(StrEnum):
    """Tags used to classify API routes"""

    ENCOUNTER = " Encounter"
    TEAMS = " Teams"
    TOURNAMENT = " Tournament"
    STANDINGS = " Standings"
    GAMEMODE = " Gamemode"
    MAP = " Map"
    HERO = " Hero"
    USER = " User"
    LOGS = " Logs"
    CHALLONGE = " Challonge"
    ANALYTICS = " Analytics"
    ACHIEVEMENT = " Achievement"


game_mode_dict = {
    "Осада": "Assault",
    "Натиск": "Push",
    "Сопровождение": "Escort",
    "Точка возгорания": "Flashpoint",
    "Гибридный режим": "Hybrid",
    "Контроль": "Control",
    "Битва": "Clash",
}


map_name_dict = {
    "Blizzard World (зима)": "Blizzard World",
    "Blizzard World (winter)": "Blizzard World",
    "Hollywood (Halloween)": "Hollywood",
    "Голливуд (Хеллоуин)": "Hollywood",
    "King's Row": "King’s Row",
    "King's Row (Winter)": "King’s Row",
    "Lijiang Tower (Lunar New Year)": "Lijiang Tower",
    "Башня Лицзян (Лунный Новый год)": "Lijiang Tower",
    "Circuit royal": "Circuit Royal",
    "Айхенвальд": "Eichenwalde",
    "Антарктический полуостров": "Antarctic Peninsula",
    "Башня Лицзян": "Lijiang Tower",
    "Гавана": "Havana",
    "Голливуд": "Hollywood",
    "Джанкертаун": "Junkertown",
    "Дорадо": "Dorado",
    "Илиос": "Ilios",
    "Кингс Роу": "King’s Row",
    "Кингс Роу (зима)": "King’s Row",
    "Колизей": "Colosseo",
    "Королевская трасса": "Circuit Royal",
    "Мидтаун": "Midtown",
    "Монастырь Шамбала": "Shambali Monastery",
    "Непал": "Nepal",
    "Нумбани": "Numbani",
    "Нью-Джанк": "New Junk City",
    "Нью-Квин-стрит": "New Queen Street",
    "Оазис": "Oasis",
    "Параисо": "Paraíso",
    "Пост наблюдения: Гибралтар": "Watchpoint: Gibraltar",
    "Пусан": "Busan",
    "Риальто": "Rialto",
    "Самоа": "Samoa",
    "Сураваса": "Suravasa",
    "Шоссе 66": "Route 66",
    "Эсперанса": "Esperança",
    "Ханамура": "Hanamura",
    "Рунасапи": "Runasapi",
    "Ханаока": "Hanaoka",
    "Трон Анубиса": "Throne of Anubis",
    "Атлус": "Aatlis",
    "Айхенвальд (Хеллоуин)": "Eichenwalde",
    "Eichenwalde (Halloween)": "Eichenwalde",
}


hero_translation = {
    "Кулак Смерти": "Doomfist",
    "Лусио": "Lúcio",
    "Трейсер": "Tracer",
    "Солдат-76": "Soldier: 76",
    "Гэндзи": "Genji",
    "Ана": "Ana",
    "Ангел": "Mercy",
    "Ориса": "Orisa",
    "Заря": "Zarya",
    "Соджорн": "Sojourn",
    "Роковая Вдова": "Widowmaker",
    "Эш": "Ashe",
    "Кэссиди": "Cassidy",
    "Батист": "Baptiste",
    "Симметра": "Symmetra",
    "Мойра": "Moira",
    "Хандзо": "Hanzo",
    "Уинстон": "Winston",
    "Жнец": "Reaper",
    "Фарра": "Pharah",
    "Турбосвин": "Roadhog",
    "Бригитта": "Brigitte",
    "Ткач Жизни": "Lifeweaver",
    "Торбьорн": "Torbjörn",
    "Королева Стервятников": "Junker Queen",
    "Эхо": "Echo",
    "Иллари": "Illari",
    "Мауга": "Mauga",
    "Таран": "Wrecking Ball",
    "Раматтра": "Ramattra",
    "Мэй": "Mei",
    "Дзенъятта": "Zenyatta",
    "Райнхардт": "Reinhardt",
    "Сигма": "Sigma",
    "Крысавчик": "Junkrat",
    "Сомбра": "Sombra",
    "Авентюра": "Venture",
    "Кирико": "Kiriko",
    "Бастион": "Bastion",
    "Юнона": "Juno",
    "Азарт": "Hazard",
    "Фрейя": "Freja",
    "Freya": "Freja",
    "Вендетта": "Vendetta",
    "У Ян": "Wuyang",
    "Ань Жань": "Anran",
    "Мидзуки": "Mizuki",
    "Домина": "Domina",
    "Амре": "Emre",
    "Реактивная киса": "Jetpack Cat",
    "Эмре": "Emre",
    "Реактивная Киса": "Jetpack Cat",
    "Сьерра": "Sierra",
}


log_stats_index_map: dict[LogStatsName, int] = {
    LogStatsName.Eliminations: 4,
    LogStatsName.FinalBlows: 5,
    LogStatsName.Deaths: 6,
    LogStatsName.AllDamageDealt: 7,
    LogStatsName.BarrierDamageDealt: 8,
    LogStatsName.HeroDamageDealt: 9,
    LogStatsName.HealingDealt: 10,
    LogStatsName.HealingReceived: 11,
    LogStatsName.SelfHealing: 12,
    LogStatsName.DamageTaken: 13,
    LogStatsName.DamageBlocked: 14,
    LogStatsName.DefensiveAssists: 15,
    LogStatsName.OffensiveAssists: 16,
    LogStatsName.UltimatesEarned: 17,
    LogStatsName.UltimatesUsed: 18,
    LogStatsName.MultikillBest: 19,
    LogStatsName.Multikills: 20,
    LogStatsName.SoloKills: 21,
    LogStatsName.ObjectiveKills: 22,
    LogStatsName.EnvironmentalKills: 23,
    LogStatsName.EnvironmentalDeaths: 24,
    LogStatsName.CriticalHits: 25,
    LogStatsName.CriticalHitAccuracy: 26,
    LogStatsName.ScopedAccuracy: 27,
    LogStatsName.ScopedCriticalHitAccuracy: 28,
    LogStatsName.ScopedCriticalHitKills: 29,
    LogStatsName.ShotsFired: 30,
    LogStatsName.ShotsHit: 31,
    LogStatsName.ShotsMissed: 32,
    LogStatsName.ScopedShotsFired: 33,
    LogStatsName.ScopedShotsHit: 34,
    LogStatsName.WeaponAccuracy: 35,
    LogStatsName.HeroTimePlayed: 36,
}