"""Default achievement catalog — one declaration per rule.

A rule's flavour text and its engine definition used to live 900 lines apart:
a hand-written metadata table (auto-generated from the pre-engine achievement
consts) plus a separate builder that looked the slug back up. Every rule is now
one ``RuleDef``, so adding or reading one is a single place.

Hero K/D awards stay generated: one per hero in ``overwatch.hero``, so a hero
synced from OW gets its achievement without an edit here. ``HERO_KD_FLAVOUR``
only carries the joke names for the heroes that had one.

Pure data + pure builders: no ``AsyncSession``/``await``/``asyncio`` anywhere in
this module. The DB-touching seed lives in
``src/services/achievement/engine/seeder.py``, which imports
``_all_default_rules`` from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.models.achievements.achievement import (
    AchievementCategory,
    AchievementGrain,
    AchievementRule,
    AchievementScope,
)
from shared.models.catalog.hero import Hero

__all__ = (
    "RULES",
    "RuleDef",
    "get_default_rule_slugs",
)


@dataclass(frozen=True, slots=True)
class RuleDef:
    """One seeded achievement: what it is called and how it is earned."""

    slug: str
    name: str
    description_ru: str
    description_en: str
    category: AchievementCategory
    scope: AchievementScope
    grain: AchievementGrain
    condition_tree: dict
    enabled: bool = True
    #: Rules whose meaning only holds from some tournament onward.
    min_tournament_id: int | None = None


@dataclass(frozen=True, slots=True)
class HeroKdFlavour:
    slug: str
    name: str
    description_ru: str
    description_en: str


HERO_KD_FLAVOUR: tuple[HeroKdFlavour, ...] = (
    HeroKdFlavour(
        "dva", "Nerf this!", "Иметь лучшее K/D на Диве за турнир", "Have the best K/D as D.Va during the tournament"
    ),
    HeroKdFlavour(
        "doomfist",
        "ANDTHEYSAY",
        "Иметь лучшее K/D на Думфисте за турнир",
        "Have the best K/D as Doomfist during the tournament",
    ),
    HeroKdFlavour(
        "lucio",
        "A C C E L E R A N D O",
        "Иметь лучшее K/D на Люсио за турнир",
        "Have the best K/D as Lúcio during the tournament",
    ),
    HeroKdFlavour(
        "tracer",
        "Déjà vu",
        "Иметь лучшее K/D на Трейсер за турнир",
        "Have the best K/D as Tracer during the tournament",
    ),
    HeroKdFlavour(
        "soldier-76",
        'That’s "SIR" to you',
        "Иметь лучшее K/D на Солдате за турнир",
        "Have the best K/D as Soldier: 76 during the tournament",
    ),
    HeroKdFlavour(
        "genji", "Mada Mada", "Иметь лучшее K/D на Генжи за турнир", "Have the best K/D as Genji during the tournament"
    ),
    HeroKdFlavour(
        "winston",
        "W I N T O N",
        "Иметь лучшее K/D на Винтоне за турнир",
        "Have the best K/D as Winston during the tournament",
    ),
    HeroKdFlavour(
        "hanzo",
        "Simple geometry",
        "Иметь лучшее K/D на Ханзо за турнир",
        "Have the best K/D as Hanzo during the tournament",
    ),
    HeroKdFlavour(
        "mercy",
        "Heroes never die",
        "Иметь лучшее K/D на Мерси за турнир",
        "Have the best K/D as Mercy during the tournament",
    ),
    HeroKdFlavour(
        "ana", "Everyone dies", "Иметь лучшее K/D на Ане за турнир", "Have the best K/D as Ana during the tournament"
    ),
    HeroKdFlavour(
        "sojourn",
        "THIS ENDS NOW",
        "Иметь лучшее K/D на Соджорн за турнир",
        "Have the best K/D as Sojourn during the tournament",
    ),
    HeroKdFlavour(
        "kiriko", "Кокоё", "Иметь лучшее K/D на Кирико за турнир", "Have the best K/D as Kiriko during the tournament"
    ),
    HeroKdFlavour(
        "reaper",
        "DIE DIE DIE",
        "Иметь лучшее K/D на Рипере за турнир",
        "Have the best K/D as Reaper during the tournament",
    ),
    HeroKdFlavour(
        "orisa",
        "Боевой конь",
        "Иметь лучшее K/D на Орисе за турнир",
        "Have the best K/D as Orisa during the tournament",
    ),
    HeroKdFlavour(
        "zarya",
        "Огонь по готовности!",
        "Иметь лучшее K/D на Заре за турнир",
        "Have the best K/D as Zarya during the tournament",
    ),
    HeroKdFlavour(
        "pharah",
        "Курарефан1",
        "Иметь лучшее K/D на Фарре за турнир",
        "Have the best K/D as Pharah during the tournament",
    ),
    HeroKdFlavour(
        "bastion",
        "За победу мать продам",
        "Иметь лучшее K/D на Бастионе за турнир",
        "Have the best K/D as Bastion during the tournament",
    ),
    HeroKdFlavour(
        "junkrat",
        "Специалист по взрывам",
        "Иметь лучшее K/D на Джанкрете за турнир",
        "Have the best K/D as Junkrat during the tournament",
    ),
    HeroKdFlavour(
        "widowmaker",
        "Hey bro, nice ass",
        "Иметь лучшее K/D на Видоу за турнир",
        "Have the best K/D as Widowmaker during the tournament",
    ),
    HeroKdFlavour(
        "baptiste",
        "Maximum efficiency",
        "Иметь лучшее K/D на Баптисте за турнир",
        "Have the best K/D as Baptiste during the tournament",
    ),
    HeroKdFlavour(
        "ashe", "BOOOOOOB!!!", "Иметь лучшее K/D на Аше за турнир", "Have the best K/D as Ashe during the tournament"
    ),
    HeroKdFlavour(
        "cassidy",
        "Собака сутулая",
        "Иметь лучшее K/D на МакКри за турнир",
        "Have the best K/D as Cassidy during the tournament",
    ),
    HeroKdFlavour(
        "ramattra",
        "SUFFER AS I HAD!",
        "Иметь лучшее K/D на Рамматре за турнир",
        "Have the best K/D as Ramattra during the tournament",
    ),
    HeroKdFlavour(
        "lifeweaver",
        "цветочек))",
        "Иметь лучшее K/D на ЛайфВивере за турнир",
        "Have the best K/D as Lifeweaver during the tournament",
    ),
    HeroKdFlavour(
        "illari",
        "Солнце взошло",
        "Иметь лучшее K/D на Иллари за турнир",
        "Have the best K/D as Illari during the tournament",
    ),
    HeroKdFlavour(
        "sigma", "Get rocked", "Иметь лучшее K/D на Сигме за турнир", "Have the best K/D as Sigma during the tournament"
    ),
    HeroKdFlavour(
        "wrecking-ball",
        "Шароеб",
        "Иметь лучшее K/D на Хомяке за турнир",
        "Have the best K/D as Wrecking Ball during the tournament",
    ),
    HeroKdFlavour(
        "mei", "A-MEI-ZING", "Иметь лучшее K/D на Мей за турнир", "Have the best K/D as Mei during the tournament"
    ),
    HeroKdFlavour(
        "symmetra",
        "Назад в будущее",
        "Иметь лучшее K/D на Симметре за турнир",
        "Have the best K/D as Symmetra during the tournament",
    ),
    HeroKdFlavour(
        "zenyatta",
        "Experience my ass",
        "Иметь лучшее K/D на Дзене за турнир",
        "Have the best K/D as Zenyatta during the tournament",
    ),
    HeroKdFlavour(
        "torbjorn",
        "Cummaster",
        "Иметь лучшее K/D на Торбе за турнир",
        "Have the best K/D as Torbjörn during the tournament",
    ),
    HeroKdFlavour(
        "junker-queen",
        "Женщина мечты",
        "Иметь лучшее K/D на Квине за турнир",
        "Have the best K/D as Junker Queen during the tournament",
    ),
    HeroKdFlavour(
        "echo",
        "Лучшая муха помойки",
        "Иметь лучшее K/D на Эхо за турнир",
        "Have the best K/D as Echo during the tournament",
    ),
    HeroKdFlavour(
        "reinhardt",
        "ПИВО!",
        "Иметь лучшее K/D на Рейне за турнир",
        "Have the best K/D as Reinhardt during the tournament",
    ),
    HeroKdFlavour(
        "moira",
        "Пыль в дымоход",
        "Иметь лучшее K/D на Мойре за турнир",
        "Have the best K/D as Moira during the tournament",
    ),
    HeroKdFlavour(
        "sombra",
        "Кошкодевочка",
        "Иметь лучшее K/D на Сомбре за турнир",
        "Have the best K/D as Sombra during the tournament",
    ),
    HeroKdFlavour(
        "roadhog",
        "👍 👍 👍",
        "Иметь лучшее K/D на Хоге за турнир",
        "Have the best K/D as Roadhog during the tournament",
    ),
    HeroKdFlavour(
        "brigitte",
        "АЛЛАХ ТИЛЬМЕ",
        "Иметь лучшее K/D на Бриге за турнир",
        "Have the best K/D as Brigitte during the tournament",
    ),
    HeroKdFlavour(
        "mauga",
        "СЕ СЕ КИ КИ",
        "Иметь лучшее K/D на Мауге за турнир",
        "Have the best K/D as Mauga during the tournament",
    ),
    HeroKdFlavour(
        "venture",
        "Профессиональный крот",
        "Иметь лучшее K/D на Вентуре за турнир",
        "Have the best K/D as Venture during the tournament",
    ),
    HeroKdFlavour(
        "juno", "Я могу и так", "Иметь лучшее K/D на Юне за турнир", "Have the best K/D as Juno during the tournament"
    ),
    HeroKdFlavour(
        "hazard",
        "Я и есть опасность",
        "Иметь лучшее K/D на Азарте за турнир",
        "Have the best K/D as Hazard during the tournament",
    ),
    HeroKdFlavour(
        "freja",
        "Bounty Hunter",
        "Иметь лучшее K/D на Фрейе за турнир",
        "Have the best K/D as Freja during the tournament",
    ),
    HeroKdFlavour(
        "wuyang", "Водник", "Иметь лучшее K/D на У Ян за турнир", "Have the best K/D as Wuyang during the tournament"
    ),
    HeroKdFlavour(
        "vendetta",
        "Инкредибили",
        "Иметь лучшее K/D на Вендетте за турнир",
        "Have the best K/D as Vendetta during the tournament",
    ),
    HeroKdFlavour(
        "emre", "Найду и выебу", "Иметь лучшее K/D на Эмре за турнир", "Have the best K/D as Emre during the tournament"
    ),
    HeroKdFlavour(
        "mizuki",
        "Ну это шляпа",
        "Иметь лучшее K/D на Мидзуки за турнир",
        "Have the best K/D as Mizuki during the tournament",
    ),
    HeroKdFlavour(
        "anran", "С дымком", "Иметь лучшее K/D на Анране за турнир", "Have the best K/D as Anran during the tournament"
    ),
    HeroKdFlavour(
        "domina",
        "Hot Mommy",
        "Иметь лучшее K/D на Домине за турнир",
        "Have the best K/D as Domina during the tournament",
    ),
    HeroKdFlavour(
        "jetpack-cat",
        "Пушистый Гандон",
        "Иметь лучшее K/D на Реактивной Кисе за турнир",
        "Have the best K/D as Jetpack Cat during the tournament",
    ),
)

_HERO_KD_BY_SLUG = {flavour.slug: flavour for flavour in HERO_KD_FLAVOUR}

# Heroes whose achievement is not "best K/D" — they have rules of their own below.
_HERO_NON_KD_SLUGS = frozenset({"freak", "mystery-heroes", "swiss-knife"})

# Fallback flavour text for heroes synced from OW that have no joke name here.
_GENERIC_HERO_NAME = "{name}"
_GENERIC_HERO_DESC_RU = "Иметь лучшее K/D на {name} за турнир"
_GENERIC_HERO_DESC_EN = "Have the best K/D as {name} during the tournament"


def _hero_kd_condition_tree(slug: str) -> dict:
    return {
        "type": "hero_kd_best",
        "params": {"hero_slug": slug, "min_time": 600, "min_matches": 3},
    }


RULES: tuple[RuleDef, ...] = (
    RuleDef(
        slug="balanced",
        name="Набалансил",
        description_ru="Сыграть матч с близостью 0%",
        description_en="Play a match with a close 0%",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 0}},
    ),
    RuleDef(
        slug="hard_game",
        name="Я сосал меня е&%ли",
        description_ru="Сыграть матч с близостью 100%",
        description_en="Play a match with a close 100%",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 1}},
    ),
    RuleDef(
        slug="7_years_in_azkaban",
        name="7 лет в Азкабане",
        description_ru="Сыграть матч длительностью 25+ минут",
        description_en="Play a match lasting 25+ minutes",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": ">=", "value": 1500}},
    ),
    RuleDef(
        slug="fast",
        name="Скорострел",
        description_ru="Сыграть матч длительностью максимум 5 мин",
        description_en="Play a match lasting a maximum of 5 minutes",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": "<=", "value": 300}},
    ),
    RuleDef(
        slug="friendly",
        name="Френдли",
        description_ru="Сыграть карту с 0 убийствами.",
        description_en="Play a map with 0 kills.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": "==", "value": 0}},
    ),
    RuleDef(
        slug="boris_dick",
        name="Борис Хрен Попадешь",
        description_ru="Выиграть карту ни умерев ни разу.",
        description_en="Win a card without dying once.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={
            "AND": [
                {"type": "stat_threshold", "params": {"stat": "Deaths", "op": "==", "value": 0}},
                {"type": "match_win"},
            ]
        },
    ),
    RuleDef(
        slug="john_wick",
        name="Джон Уик",
        description_ru="Сделать более 60 элимов за карту",
        description_en="Make over 60 eliminations per map",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": ">=", "value": 60}},
    ),
    RuleDef(
        slug="just_dont_fuck_around",
        name="Главное не хукнись",
        description_ru="Умереть за карту 20+ раз",
        description_en="Die for a map 20+ times",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "Deaths", "op": ">=", "value": 20}},
    ),
    RuleDef(
        slug="the-shift-factory-is-done",
        name="Смена на заводе отработана",
        description_ru="Нахилять более 30000 ед. хила за карту",
        description_en="Heal for more than 30,000 hit points per map",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "HealingDealt", "op": ">=", "value": 30000}},
    ),
    RuleDef(
        slug="shooting_and_screaming",
        name="РАБОТАЕМ ЕКАТЕРИНА!",
        description_ru="Нанести более 35000 ед. урона за карту",
        description_en="Deal more than 35000 damage per map",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "HeroDamageDealt", "op": ">=", "value": 35000}},
    ),
    RuleDef(
        slug="fiasko",
        name="Это фиаско братан",
        description_ru="Упасть за карту от бупа 3+ раза за карту",
        description_en="Fall for a map from a boop 3+ times per map",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "EnvironmentalDeaths", "op": ">=", "value": 3}},
    ),
    RuleDef(
        slug="boop_master",
        name="Чувак это яма",
        description_ru="Бупнуть за карту противника 3+ раза за карту",
        description_en="Boop the opponent 3+ times per map",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "EnvironmentalKills", "op": ">=", "value": 3}},
    ),
    RuleDef(
        slug="bullet-is-not-stupid",
        name="Пуля не дура",
        description_ru="Убить 10+ человек за карту хедшотом",
        description_en="Kill 10+ people per map with headshots",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={
            "type": "stat_threshold",
            "params": {"stat": "ScopedCriticalHitKills", "op": ">=", "value": 10},
        },
    ),
    RuleDef(
        slug="honor-and-glory",
        name="ЗА ЧЕСТЬ И СЛАВУ",
        description_ru="Выиграть турнир.",
        description_en="Win the tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "standing_position", "params": {"op": "==", "value": 1}},
    ),
    RuleDef(
        slug="versatile-player",
        name="Универсальный игрок",
        description_ru="Отыграть 3 турнира на трёх разных ролях.",
        description_en="Play 3 tournaments in three different roles.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "distinct_count",
            "params": {"field": "role", "op": ">=", "value": 3, "scope": "global"},
        },
    ),
    RuleDef(
        slug="captain-jack-sparrow",
        name="Капитан Джек Воробей",
        description_ru="Стать капитаном в своей команде.",
        description_en="Become a captain in your team.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "is_captain"},
    ),
    RuleDef(
        slug="worst-player-winrate",
        name="Джентльмен неудачи",
        description_ru="Войти в топ20 игроков по винрейту (снизу).",
        description_en="Enter the top 20 players by winrate (from the bottom).",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "global_winrate", "params": {"order": "asc", "limit": 20}},
    ),
    RuleDef(
        slug="best-player-winrate",
        name="Все просто, я лучший!",
        description_ru="Войти в топ20 игроков по винрейту.",
        description_en="Enter the top 20 players by winrate.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "global_winrate", "params": {"order": "desc", "limit": 20}},
    ),
    RuleDef(
        slug="space-created",
        name="Спейс создан",
        description_ru="Умереть 1000+ раз за историю логов",
        description_en="Die 1000+ times in the history of logs",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "global_stat_sum", "params": {"stat": "Deaths", "op": ">=", "value": 1000}},
    ),
    RuleDef(
        slug="fucking-casino-mouth",
        name="ё#%ный рот этого казино",
        description_ru="Сыграть 20 турниров",
        description_en="Play 20 tournaments",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 20}},
    ),
    RuleDef(
        slug="its-genetics",
        name="Это генетика",
        description_ru="Отыграть все турниры 1 героем",
        description_en="Play all tournaments with 1 hero",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "AND": [
                {
                    "type": "distinct_count",
                    "params": {"field": "hero", "op": "==", "value": 1, "scope": "global", "min_playtime": 60},
                },
                {"type": "distinct_count", "params": {"field": "match", "op": ">", "value": 5, "scope": "global"}},
            ]
        },
    ),
    RuleDef(
        slug="two-wins-players",
        name="Это не удача, это скилл!",
        description_ru="Выиграть турнир 2 раза.",
        description_en="Win the tournament 2 times.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 2},
        },
    ),
    RuleDef(
        slug="three-wins-players",
        name="ТАГАНРООООООГ",
        description_ru="Выиграть турнир 3 раза.",
        description_en="Win the tournament 3 times.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 3},
        },
    ),
    RuleDef(
        slug="sisyphus-and-stone",
        name="Сизиф и камень",
        description_ru="Занять второе место более двух раз.",
        description_en="Take second place more than two times.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 2, "count_by": "tournament", "op": ">=", "value": 3},
        },
    ),
    RuleDef(
        slug="dahao",
        name="ЛУПИ ИХ ДАХАО💪🏻😈🤙🏻 МЕСИ ИХ ДАХАО💪🏻😈🤙🏻",
        description_ru="Выиграть турнир на двух разных ролях.",
        description_en="Win a tournament in two different roles.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 2},
        },
    ),
    RuleDef(
        slug="pathological-sucker",
        name="Патологический лох",
        description_ru="Занять второе место на всех ролях.",
        description_en="Take second place in all roles.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 2, "count_by": "role", "op": ">=", "value": 3},
        },
    ),
    RuleDef(
        slug="lord-of-all-the-elements",
        name="Властелин всех стихий",
        description_ru="Выиграть турнир на трех разных ролях.",
        description_en="Win a tournament in three different roles.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "standing_count",
            "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 3},
        },
    ),
    RuleDef(
        slug="consistent-winner",
        name="Стабильный победитель",
        description_ru="Занять место в топ20 по выигранным картам.",
        description_en="Take a place in the top 20 by won maps.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "global_winrate", "params": {"metric": "won_maps", "order": "desc", "limit": 20}},
    ),
    RuleDef(
        slug="just-shooting",
        name="Мы просто стреляли пули",
        description_ru="Выиграть турнир с винрейтом 90%+.",
        description_en="Win a tournament with a winrate of 90%+.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "AND": [
                {"type": "standing_position", "params": {"op": "==", "value": 1}},
                {"type": "tournament_winrate", "params": {"op": ">=", "value": 0.89}},
            ]
        },
    ),
    RuleDef(
        slug="ill-definitely-survive",
        name="Я обязательно выживу",
        description_ru="Занять топ 1 по минимальному кол-ву смертей в логах турика.",
        description_en="Take top 1 by the minimum number of deaths in the logs of the tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "log_stat_rank", "params": {"stat": "Deaths", "order": "asc", "limit": 1}},
    ),
    RuleDef(
        slug="killer-machine",
        name="Машина убийца",
        description_ru="Занять топ 1 по максимальному кол-ву убийств в логах турика.",
        description_en="Take top 1 by the maximum number of kills in the logs of the tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "log_stat_rank", "params": {"stat": "Eliminations", "order": "desc", "limit": 1}},
    ),
    RuleDef(
        slug="just-shoot-in-the-head",
        name="Просто стреляй в голову",
        description_ru="Занять топ 1 по кол-ву хедшотов в логах турика.",
        description_en="Take top 1 by the number of headshots in the logs of the tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "CriticalHitAccuracy", "order": "desc", "limit": 1},
        },
    ),
    RuleDef(
        slug="poop_forever",
        name="Срать вечно",
        description_ru="Нанести наибольшее количество урона/мин за турнир",
        description_en="Deal the most damage/min per tournament",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "log_stat_rank", "params": {"stat": "HeroDamageDealt", "order": "desc", "limit": 1}},
    ),
    RuleDef(
        slug="one-shot-one-kill",
        name="Один выстрел, один труп",
        description_ru="Стать топ 1 по крит. меткости в прицеле на турнире",
        description_en="Become the top 1 by crit accuracy in the sight during the tournament",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "ScopedCriticalHitAccuracy", "order": "desc", "limit": 1},
        },
    ),
    RuleDef(
        slug="dirty-smurf",
        name="Грязный смурф",
        description_ru="Стать чемпионом в свой первый турнир.",
        description_en="Become a champion in your first tournament.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "AND": [
                {"type": "is_newcomer"},
                {"type": "standing_position", "params": {"op": "==", "value": 1}},
                {"type": "tournament_type", "params": {"is_league": False}},
            ]
        },
    ),
    RuleDef(
        slug="revenge-is-sweet",
        name="Переигран и уничтожен",
        description_ru="Победить соперника, который ранее вас выиграл.",
        description_en="Defeat an opponent who previously beat you.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "encounter_revenge"},
    ),
    RuleDef(
        slug="reverse-sweep-champion",
        name="Reverse Sweep Champion",
        description_ru="Выиграть турнир, упадя в нижнюю сетку.",
        description_en="Win a tournament by falling into the lower bracket.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "AND": [
                {"type": "standing_position", "params": {"op": "==", "value": 1}},
                {"type": "bracket_path", "params": {"played_lower_bracket": True}},
                {"type": "tournament_format", "params": {"format": "double_elim"}},
            ]
        },
    ),
    RuleDef(
        slug="win-2-plus-consecutive",
        name="Мне просто повезло",
        description_ru="Выиграть 2+ турнира подряд.",
        description_en="Win 2+ tournaments in a row.",
        category=AchievementCategory.standing,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "consecutive", "params": {"metric": "win", "min_streak": 2}},
    ),
    RuleDef(
        # Replaces the retired ``were-not-suckers``, which hard-coded a 2-3/3-2
        # scoreline and therefore awarded nothing in a series that was not best
        # of five. The series grain states the actual fact: lost the final by one
        # map, whatever the format.
        slug="heartbreaker",
        name="Да не лохи мы…",
        description_ru="Проиграть финал турнира с разницей в одну карту.",
        description_en="Lose the tournament final by a single map.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_encounter,
        condition_tree={
            "type": "encounter_result",
            "params": {"outcome": "loss", "margin": 1, "round_type": "final"},
        },
    ),
    RuleDef(
        slug="i-killed-i-stole",
        name="Я УБИВАЛ Я ВОРОВАЛ",
        description_ru="Добраться до финала, пройдя по всей нижней сетке.",
        description_en="Get to the final by going through the entire lower bracket.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "AND": [
                {"type": "standing_position", "params": {"op": "<=", "value": 2}},
                {"type": "bracket_path", "params": {"played_lower_bracket": True}},
            ]
        },
    ),
    RuleDef(
        slug="im-screwed-run",
        name="Я конченный, бегите",
        description_ru="Отыграть весь турик не сменив персонажа.",
        description_en="Play the whole tournament without changing the character.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "AND": [
                {
                    "type": "distinct_count",
                    "params": {"field": "hero", "op": "==", "value": 1, "scope": "tournament", "min_playtime": 60},
                },
                {"type": "distinct_count", "params": {"field": "match", "op": ">", "value": 5, "scope": "tournament"}},
            ]
        },
    ),
    RuleDef(
        slug="lfs-4500",
        name="LFS 20 EST 4.5k+",
        description_ru="Попасться с одним и тем же игроком 3+ раза.",
        description_en="Get caught with the same player 3+ times.",
        category=AchievementCategory.team,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "teammate_recurrence", "params": {"op": ">=", "value": 3}},
    ),
    RuleDef(
        slug="we-work-with-what-we-have",
        name="Работаем с тем, что есть",
        description_ru="Заролиться с тиммейтом OTP в команду.",
        description_en="Roll with a OTP teammate into a team.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 1}},
    ),
    RuleDef(
        slug="were-so-fucked",
        name="Какая же нам пи№#а",
        description_ru="Заролиться в команду с 3+ OTP тиммейтами.",
        description_en="Roll into a team with 3+ OTP teammates.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 3}},
    ),
    RuleDef(
        slug="freak",
        name="Фрик",
        description_ru="Сыграть на персонаже с пикрейтом менее 0.1% в течение турнира.",
        description_en="Play a character with a pickrate of less than 0.1% during the tournament.",
        category=AchievementCategory.hero,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "hero_pickrate", "params": {"op": "<", "value": 0.001}},
    ),
    RuleDef(
        slug="mystery-heroes",
        name="Мистери хироус",
        description_ru="Отыграть турнир минимум 7 героями.",
        description_en="Play the tournament with at least 7 heroes.",
        category=AchievementCategory.hero,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "distinct_count",
            "params": {"field": "hero", "op": ">=", "value": 7, "scope": "tournament", "min_playtime": 60},
        },
    ),
    RuleDef(
        slug="swiss-knife",
        name="Человек Швейцарский нож",
        description_ru="За всю историю логов сыграть минимум на 20 разных героях.",
        description_en="Play at least 20 different heroes in the history of logs.",
        category=AchievementCategory.hero,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "distinct_count",
            "params": {"field": "hero", "op": ">=", "value": 20, "scope": "global", "min_playtime": 60},
        },
    ),
    # ── Series (encounter grain) ──────────────────────────────────────────────
    RuleDef(
        slug="clean-sweep",
        name="Всухую",
        description_ru="Выиграть серию, не отдав ни одной карты.",
        description_en="Win a series without dropping a single map.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_encounter,
        condition_tree={"type": "encounter_result", "params": {"outcome": "win", "opponent_score": 0}},
    ),
    RuleDef(
        slug="reverse-sweep",
        name="Обратный свип",
        description_ru="Выиграть серию, уступая по картам 0-2.",
        description_en="Win a series after going two maps down.",
        category=AchievementCategory.standing,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_encounter,
        condition_tree={"type": "encounter_comeback", "params": {"min_deficit": 2}},
    ),
    # ── Derived log stats the parser computes but no rule used ────────────────
    RuleDef(
        slug="map-mvp",
        name="MVP карты",
        description_ru="Стать самым полезным игроком карты по импакту.",
        description_en="Finish a map as its highest-impact player.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "stat_threshold", "params": {"stat": "ImpactRank", "op": "==", "value": 1}},
    ),
    RuleDef(
        slug="impact-machine",
        name="Машина импакта",
        description_ru="Набрать больше всех импакта за турнир.",
        description_en="Earn the most impact points of anyone in a tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "ImpactPoints", "order": "desc", "limit": 1},
        },
    ),
    RuleDef(
        slug="above-my-division",
        name="Выше своего дива",
        description_ru="Сильнее всех на турнире превзойти ожидания своего дивизиона.",
        description_en="Out-perform your own division rating more than anyone in the tournament.",
        category=AchievementCategory.division,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "OverperformanceScore", "order": "desc", "limit": 1},
        },
    ),
    RuleDef(
        slug="first-blood",
        name="Первая кровь",
        description_ru="Сделать больше всех первых убийств за турнир.",
        description_en="Land the most first picks of anyone in a tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "FirstPicks", "order": "desc", "limit": 1},
        },
    ),
    RuleDef(
        slug="ult-machine",
        name="Ультует",
        description_ru="Набрать больше всех убийств ультимейтом за турнир.",
        description_en="Get the most ultimate kills of anyone in a tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "log_stat_rank",
            "params": {"stat": "UltimateKills", "order": "desc", "limit": 1},
        },
    ),
    # ── Kill feed and match events ────────────────────────────────────────────
    RuleDef(
        slug="team-wipe",
        name="Вайп",
        description_ru="Убить четверых противников в одном файте.",
        description_en="Kill four enemies inside a single fight.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={"type": "fight_multikill", "params": {"min_kills": 4, "op": ">=", "value": 1}},
    ),
    RuleDef(
        slug="nemesis",
        name="Личный клиент",
        description_ru="Набрать против одного игрока 20 убийств и перевес в 10.",
        description_en="Take twenty kills off one rival with a ten-kill margin.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "duel_dominance",
            "params": {"scope": "global", "min_kills": 20, "min_diff": 10},
        },
    ),
    RuleDef(
        slug="swap-machine",
        name="Никак не определится",
        description_ru="Сменить героя семь раз за одну карту.",
        description_en="Swap hero seven times on a single map.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={
            "type": "match_event_count",
            "params": {"event": "HeroSwap", "op": ">=", "value": 7},
        },
    ),
    RuleDef(
        slug="angel-of-mercy",
        name="Ангел-хранитель",
        description_ru="Воскресить пятерых союзников за одну карту.",
        description_en="Resurrect five team-mates on a single map.",
        category=AchievementCategory.match,
        scope=AchievementScope.match,
        grain=AchievementGrain.user_match,
        condition_tree={
            "type": "match_event_count",
            "params": {"event": "MercyRez", "op": ">=", "value": 5},
        },
    ),
    # ── Maps and gamemodes ────────────────────────────────────────────────────
    RuleDef(
        slug="world-tour",
        name="Кругосветка",
        description_ru="Сыграть на 20 разных картах.",
        description_en="Play on twenty different maps.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "map_coverage",
            "params": {"field": "map", "outcome": "played", "op": ">=", "value": 20, "scope": "global"},
        },
    ),
    RuleDef(
        slug="mode-master",
        name="Универсал режимов",
        description_ru="Победить на картах четырёх разных режимов.",
        description_en="Win on maps from four different gamemodes.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "map_coverage",
            "params": {"field": "gamemode", "outcome": "won", "op": ">=", "value": 4, "scope": "global"},
        },
    ),
    # ── Registration and draft ────────────────────────────────────────────────
    RuleDef(
        slug="early-bird",
        name="Ранняя пташка",
        description_ru="Зарегистрироваться в первый час после открытия регистрации.",
        description_en="Sign up within an hour of registration opening.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "registration_timing",
            "params": {"event": "signup", "op": "<=", "value": 60},
        },
    ),
    RuleDef(
        slug="first-overall-pick",
        name="Первый пик",
        description_ru="Уйти первым пиком на драфте.",
        description_en="Go first overall in a live draft.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "draft_pick", "params": {"role": "picked", "op": "==", "value": 1}},
    ),
    RuleDef(
        slug="draft-captain",
        name="Капитан драфта",
        description_ru="Провести команду через живой драфт в роли капитана.",
        description_en="Captain a team through a live draft.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "draft_pick", "params": {"role": "captain"}},
    ),
    RuleDef(
        slug="bench-hero",
        name="С лавки",
        description_ru="Заявиться на турнир запасным.",
        description_en="Enter a tournament as a substitute.",
        category=AchievementCategory.team,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={"type": "registration_flag", "params": {"flag": "substitute"}},
    ),
    # ── Reporting and log uploads ─────────────────────────────────────────────
    RuleDef(
        slug="by-the-book",
        name="По регламенту",
        description_ru="Отчитаться за пять серий за один турнир.",
        description_en="File the result of five series in one tournament.",
        category=AchievementCategory.overall,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree={
            "type": "captain_report_activity",
            "params": {"metric": "series_reported", "op": ">=", "value": 5},
        },
    ),
    RuleDef(
        slug="log-keeper",
        name="Хранитель логов",
        description_ru="Загрузить 25 логов матчей.",
        description_en="Upload twenty-five match logs.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={
            "type": "log_upload_count",
            "params": {"scope": "global", "status": "done", "op": ">=", "value": 25},
        },
    ),
    # ── Overwatch rank history ────────────────────────────────────────────────
    RuleDef(
        slug="top-of-the-ladder",
        name="Грандмастер",
        description_ru="Достичь грандмастера в соревновательном режиме.",
        description_en="Reach Grandmaster in competitive play.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "rank_peak", "params": {"min_division": "grandmaster"}},
    ),
    RuleDef(
        slug="climber",
        name="Альпинист",
        description_ru="Подняться на два дивизиона за один сезон.",
        description_en="Climb two divisions within a single season.",
        category=AchievementCategory.overall,
        scope=AchievementScope.glob,
        grain=AchievementGrain.user,
        condition_tree={"type": "rank_climb", "params": {"op": ">=", "value": 2}},
    ),
)


def _rule_from_def(workspace_id: int, definition: RuleDef) -> AchievementRule:
    return AchievementRule(
        workspace_id=workspace_id,
        slug=definition.slug,
        name=definition.name,
        description_ru=definition.description_ru,
        description_en=definition.description_en,
        category=definition.category,
        scope=definition.scope,
        grain=definition.grain,
        condition_tree=definition.condition_tree,
        depends_on=[],
        enabled=definition.enabled,
        min_tournament_id=definition.min_tournament_id,
    )


def _hero_kd_rule(workspace_id: int, slug: str, hero: Hero | None = None) -> AchievementRule:
    flavour = _HERO_KD_BY_SLUG.get(slug)
    display_name = hero.name if hero is not None else slug
    return AchievementRule(
        workspace_id=workspace_id,
        slug=slug,
        name=flavour.name if flavour else _GENERIC_HERO_NAME.format(name=display_name),
        description_ru=flavour.description_ru if flavour else _GENERIC_HERO_DESC_RU.format(name=display_name),
        description_en=flavour.description_en if flavour else _GENERIC_HERO_DESC_EN.format(name=display_name),
        category=AchievementCategory.hero,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree=_hero_kd_condition_tree(slug),
        depends_on=[],
        enabled=True,
        hero_id=hero.id if hero is not None else None,
        image_url=hero.image_path if hero is not None else None,
    )


def _hero_kd_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    """Hero K/D rules.

    With ``heroes`` (DB-backed seeding) one rule is generated per hero in
    ``overwatch.hero``, so newly synced heroes automatically get an achievement.
    Known slugs keep their flavour text; the rest get a generated one. Flavoured
    heroes missing from the DB still get a rule, so the catalog stays complete.

    With ``heroes=None`` (sync callers / tests) only the flavoured slugs are used,
    preserving DB-free behaviour.
    """
    rules: list[AchievementRule] = []
    seen: set[str] = set()

    for hero in heroes or []:
        if hero.slug in _HERO_NON_KD_SLUGS or hero.slug in seen:
            continue
        rules.append(_hero_kd_rule(workspace_id, hero.slug, hero))
        seen.add(hero.slug)

    for flavour in HERO_KD_FLAVOUR:
        if flavour.slug in seen:
            continue
        rules.append(_hero_kd_rule(workspace_id, flavour.slug))

    return rules


def _all_default_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    rules = [_rule_from_def(workspace_id, definition) for definition in RULES]
    rules.extend(_hero_kd_rules(workspace_id, heroes))

    seen_slugs: set[str] = set()
    duplicates = [rule.slug for rule in rules if rule.slug in seen_slugs or seen_slugs.add(rule.slug)]
    if duplicates:
        raise ValueError(f"Duplicate slugs in default engine catalog: {duplicates}")

    return rules


def get_default_rule_slugs() -> list[str]:
    return sorted(rule.slug for rule in _all_default_rules(0))
