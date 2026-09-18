"""Canonical achievement rule catalog + default-rule builders.

Merges the former ``engine/catalog.py`` (static legacy catalog metadata) with
``engine/seeder.py``'s pure rule-builder functions, moved here verbatim: zero
``AsyncSession``/``await``/``asyncio`` anywhere in this module. Only the
DB-touching ``seed_workspace``/``hard_reset_workspace`` stayed behind in
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
    "CANONICAL_ACHIEVEMENT_CATALOG",
    "CanonicalRuleMeta",
    "get_canonical_rule_catalog",
    "get_default_rule_slugs",
)

# Auto-generated from legacy achievement consts during engine migration.
# Source removed from runtime; seeder consumes this catalog as canonical metadata.
CANONICAL_ACHIEVEMENT_CATALOG: tuple[dict[str, str], ...] = (
    {
        "category": "hero",
        "slug": "dva",
        "name": "Nerf this!",
        "description_ru": "Иметь лучшее K/D на Диве за турнир",
        "description_en": "Have the best K/D as D.Va during the tournament",
    },
    {
        "category": "hero",
        "slug": "doomfist",
        "name": "ANDTHEYSAY",
        "description_ru": "Иметь лучшее K/D на Думфисте за турнир",
        "description_en": "Have the best K/D as Doomfist during the tournament",
    },
    {
        "category": "hero",
        "slug": "lucio",
        "name": "A C C E L E R A N D O",
        "description_ru": "Иметь лучшее K/D на Люсио за турнир",
        "description_en": "Have the best K/D as Lúcio during the tournament",
    },
    {
        "category": "hero",
        "slug": "tracer",
        "name": "Déjà vu",
        "description_ru": "Иметь лучшее K/D на Трейсер за турнир",
        "description_en": "Have the best K/D as Tracer during the tournament",
    },
    {
        "category": "hero",
        "slug": "soldier-76",
        "name": 'That’s "SIR" to you',
        "description_ru": "Иметь лучшее K/D на Солдате за турнир",
        "description_en": "Have the best K/D as Soldier: 76 during the tournament",
    },
    {
        "category": "hero",
        "slug": "genji",
        "name": "Mada Mada",
        "description_ru": "Иметь лучшее K/D на Генжи за турнир",
        "description_en": "Have the best K/D as Genji during the tournament",
    },
    {
        "category": "hero",
        "slug": "winston",
        "name": "W I N T O N",
        "description_ru": "Иметь лучшее K/D на Винтоне за турнир",
        "description_en": "Have the best K/D as Winston during the tournament",
    },
    {
        "category": "hero",
        "slug": "hanzo",
        "name": "Simple geometry",
        "description_ru": "Иметь лучшее K/D на Ханзо за турнир",
        "description_en": "Have the best K/D as Hanzo during the tournament",
    },
    {
        "category": "hero",
        "slug": "mercy",
        "name": "Heroes never die",
        "description_ru": "Иметь лучшее K/D на Мерси за турнир",
        "description_en": "Have the best K/D as Mercy during the tournament",
    },
    {
        "category": "hero",
        "slug": "ana",
        "name": "Everyone dies",
        "description_ru": "Иметь лучшее K/D на Ане за турнир",
        "description_en": "Have the best K/D as Ana during the tournament",
    },
    {
        "category": "hero",
        "slug": "sojourn",
        "name": "THIS ENDS NOW",
        "description_ru": "Иметь лучшее K/D на Соджорн за турнир",
        "description_en": "Have the best K/D as Sojourn during the tournament",
    },
    {
        "category": "hero",
        "slug": "kiriko",
        "name": "Кокоё",
        "description_ru": "Иметь лучшее K/D на Кирико за турнир",
        "description_en": "Have the best K/D as Kiriko during the tournament",
    },
    {
        "category": "hero",
        "slug": "reaper",
        "name": "DIE DIE DIE",
        "description_ru": "Иметь лучшее K/D на Рипере за турнир",
        "description_en": "Have the best K/D as Reaper during the tournament",
    },
    {
        "category": "hero",
        "slug": "orisa",
        "name": "Боевой конь",
        "description_ru": "Иметь лучшее K/D на Орисе за турнир",
        "description_en": "Have the best K/D as Orisa during the tournament",
    },
    {
        "category": "hero",
        "slug": "zarya",
        "name": "Огонь по готовности!",
        "description_ru": "Иметь лучшее K/D на Заре за турнир",
        "description_en": "Have the best K/D as Zarya during the tournament",
    },
    {
        "category": "hero",
        "slug": "pharah",
        "name": "Курарефан1",
        "description_ru": "Иметь лучшее K/D на Фарре за турнир",
        "description_en": "Have the best K/D as Pharah during the tournament",
    },
    {
        "category": "hero",
        "slug": "bastion",
        "name": "За победу мать продам",
        "description_ru": "Иметь лучшее K/D на Бастионе за турнир",
        "description_en": "Have the best K/D as Bastion during the tournament",
    },
    {
        "category": "hero",
        "slug": "junkrat",
        "name": "Специалист по взрывам",
        "description_ru": "Иметь лучшее K/D на Джанкрете за турнир",
        "description_en": "Have the best K/D as Junkrat during the tournament",
    },
    {
        "category": "hero",
        "slug": "widowmaker",
        "name": "Hey bro, nice ass",
        "description_ru": "Иметь лучшее K/D на Видоу за турнир",
        "description_en": "Have the best K/D as Widowmaker during the tournament",
    },
    {
        "category": "hero",
        "slug": "baptiste",
        "name": "Maximum efficiency",
        "description_ru": "Иметь лучшее K/D на Баптисте за турнир",
        "description_en": "Have the best K/D as Baptiste during the tournament",
    },
    {
        "category": "hero",
        "slug": "ashe",
        "name": "BOOOOOOB!!!",
        "description_ru": "Иметь лучшее K/D на Аше за турнир",
        "description_en": "Have the best K/D as Ashe during the tournament",
    },
    {
        "category": "hero",
        "slug": "cassidy",
        "name": "Собака сутулая",
        "description_ru": "Иметь лучшее K/D на МакКри за турнир",
        "description_en": "Have the best K/D as Cassidy during the tournament",
    },
    {
        "category": "hero",
        "slug": "ramattra",
        "name": "SUFFER AS I HAD!",
        "description_ru": "Иметь лучшее K/D на Рамматре за турнир",
        "description_en": "Have the best K/D as Ramattra during the tournament",
    },
    {
        "category": "hero",
        "slug": "lifeweaver",
        "name": "цветочек))",
        "description_ru": "Иметь лучшее K/D на ЛайфВивере за турнир",
        "description_en": "Have the best K/D as Lifeweaver during the tournament",
    },
    {
        "category": "hero",
        "slug": "illari",
        "name": "Солнце взошло",
        "description_ru": "Иметь лучшее K/D на Иллари за турнир",
        "description_en": "Have the best K/D as Illari during the tournament",
    },
    {
        "category": "hero",
        "slug": "sigma",
        "name": "Get rocked",
        "description_ru": "Иметь лучшее K/D на Сигме за турнир",
        "description_en": "Have the best K/D as Sigma during the tournament",
    },
    {
        "category": "hero",
        "slug": "wrecking-ball",
        "name": "Шароеб",
        "description_ru": "Иметь лучшее K/D на Хомяке за турнир",
        "description_en": "Have the best K/D as Wrecking Ball during the tournament",
    },
    {
        "category": "hero",
        "slug": "mei",
        "name": "A-MEI-ZING",
        "description_ru": "Иметь лучшее K/D на Мей за турнир",
        "description_en": "Have the best K/D as Mei during the tournament",
    },
    {
        "category": "hero",
        "slug": "symmetra",
        "name": "Назад в будущее",
        "description_ru": "Иметь лучшее K/D на Симметре за турнир",
        "description_en": "Have the best K/D as Symmetra during the tournament",
    },
    {
        "category": "hero",
        "slug": "zenyatta",
        "name": "Experience my ass",
        "description_ru": "Иметь лучшее K/D на Дзене за турнир",
        "description_en": "Have the best K/D as Zenyatta during the tournament",
    },
    {
        "category": "hero",
        "slug": "torbjorn",
        "name": "Cummaster",
        "description_ru": "Иметь лучшее K/D на Торбе за турнир",
        "description_en": "Have the best K/D as Torbjörn during the tournament",
    },
    {
        "category": "hero",
        "slug": "junker-queen",
        "name": "Женщина мечты",
        "description_ru": "Иметь лучшее K/D на Квине за турнир",
        "description_en": "Have the best K/D as Junker Queen during the tournament",
    },
    {
        "category": "hero",
        "slug": "echo",
        "name": "Лучшая муха помойки",
        "description_ru": "Иметь лучшее K/D на Эхо за турнир",
        "description_en": "Have the best K/D as Echo during the tournament",
    },
    {
        "category": "hero",
        "slug": "reinhardt",
        "name": "ПИВО!",
        "description_ru": "Иметь лучшее K/D на Рейне за турнир",
        "description_en": "Have the best K/D as Reinhardt during the tournament",
    },
    {
        "category": "hero",
        "slug": "moira",
        "name": "Пыль в дымоход",
        "description_ru": "Иметь лучшее K/D на Мойре за турнир",
        "description_en": "Have the best K/D as Moira during the tournament",
    },
    {
        "category": "hero",
        "slug": "sombra",
        "name": "Кошкодевочка",
        "description_ru": "Иметь лучшее K/D на Сомбре за турнир",
        "description_en": "Have the best K/D as Sombra during the tournament",
    },
    {
        "category": "hero",
        "slug": "roadhog",
        "name": "👍 👍 👍",
        "description_ru": "Иметь лучшее K/D на Хоге за турнир",
        "description_en": "Have the best K/D as Roadhog during the tournament",
    },
    {
        "category": "hero",
        "slug": "brigitte",
        "name": "АЛЛАХ ТИЛЬМЕ",
        "description_ru": "Иметь лучшее K/D на Бриге за турнир",
        "description_en": "Have the best K/D as Brigitte during the tournament",
    },
    {
        "category": "hero",
        "slug": "mauga",
        "name": "СЕ СЕ КИ КИ",
        "description_ru": "Иметь лучшее K/D на Мауге за турнир",
        "description_en": "Have the best K/D as Mauga during the tournament",
    },
    {
        "category": "hero",
        "slug": "venture",
        "name": "Профессиональный крот",
        "description_ru": "Иметь лучшее K/D на Вентуре за турнир",
        "description_en": "Have the best K/D as Venture during the tournament",
    },
    {
        "category": "hero",
        "slug": "juno",
        "name": "Я могу и так",
        "description_ru": "Иметь лучшее K/D на Юне за турнир",
        "description_en": "Have the best K/D as Juno during the tournament",
    },
    {
        "category": "hero",
        "slug": "hazard",
        "name": "Я и есть опасность",
        "description_ru": "Иметь лучшее K/D на Азарте за турнир",
        "description_en": "Have the best K/D as Hazard during the tournament",
    },
    {
        "category": "hero",
        "slug": "freak",
        "name": "Фрик",
        "description_ru": "Сыграть на персонаже с пикрейтом менее 0.1% в течение турнира.",
        "description_en": "Play a character with a pickrate of less than 0.1% during the tournament.",
    },
    {
        "category": "hero",
        "slug": "mystery-heroes",
        "name": "Мистери хироус",
        "description_ru": "Отыграть турнир минимум 7 героями.",
        "description_en": "Play the tournament with at least 7 heroes.",
    },
    {
        "category": "hero",
        "slug": "swiss-knife",
        "name": "Человек Швейцарский нож",
        "description_ru": "За всю историю логов сыграть минимум на 20 разных героях.",
        "description_en": "Play at least 20 different heroes in the history of logs.",
    },
    {
        "category": "hero",
        "slug": "freja",
        "name": "Bounty Hunter",
        "description_ru": "Иметь лучшее K/D на Фрейе за турнир",
        "description_en": "Have the best K/D as Freja during the tournament",
    },
    {
        "category": "hero",
        "slug": "wuyang",
        "name": "Водник",
        "description_ru": "Иметь лучшее K/D на У Ян за турнир",
        "description_en": "Have the best K/D as Wuyang during the tournament",
    },
    {
        "category": "hero",
        "slug": "vendetta",
        "name": "Инкредибили",
        "description_ru": "Иметь лучшее K/D на Вендетте за турнир",
        "description_en": "Have the best K/D as Vendetta during the tournament",
    },
    {
        "category": "hero",
        "slug": "emre",
        "name": "Найду и выебу",
        "description_ru": "Иметь лучшее K/D на Эмре за турнир",
        "description_en": "Have the best K/D as Emre during the tournament",
    },
    {
        "category": "hero",
        "slug": "mizuki",
        "name": "Ну это шляпа",
        "description_ru": "Иметь лучшее K/D на Мидзуки за турнир",
        "description_en": "Have the best K/D as Mizuki during the tournament",
    },
    {
        "category": "hero",
        "slug": "anran",
        "name": "С дымком",
        "description_ru": "Иметь лучшее K/D на Анране за турнир",
        "description_en": "Have the best K/D as Anran during the tournament",
    },
    {
        "category": "hero",
        "slug": "domina",
        "name": "Hot Mommy",
        "description_ru": "Иметь лучшее K/D на Домине за турнир",
        "description_en": "Have the best K/D as Domina during the tournament",
    },
    {
        "category": "hero",
        "slug": "jetpack-cat",
        "name": "Пушистый Гандон",
        "description_ru": "Иметь лучшее K/D на Реактивной Кисе за турнир",
        "description_en": "Have the best K/D as Jetpack Cat during the tournament",
    },
    {
        "category": "overall",
        "slug": "welcome",
        "name": "Добро пожаловать в клуб",
        "description_ru": "Принять участие в турнире любым способом.",
        "description_en": "Take part in the tournament in any way.",
    },
    {
        "category": "overall",
        "slug": "honor-and-glory",
        "name": "ЗА ЧЕСТЬ И СЛАВУ",
        "description_ru": "Выиграть турнир.",
        "description_en": "Win the tournament.",
    },
    {
        "category": "overall",
        "slug": "versatile-player",
        "name": "Универсальный игрок",
        "description_ru": "Отыграть 3 турнира на трёх разных ролях.",
        "description_en": "Play 3 tournaments in three different roles.",
    },
    {
        "category": "overall",
        "slug": "two-wins-players",
        "name": "Это не удача, это скилл!",
        "description_ru": "Выиграть турнир 2 раза.",
        "description_en": "Win the tournament 2 times.",
    },
    {
        "category": "overall",
        "slug": "three-wins-players",
        "name": "ТАГАНРООООООГ",
        "description_ru": "Выиграть турнир 3 раза.",
        "description_en": "Win the tournament 3 times.",
    },
    {
        "category": "overall",
        "slug": "sisyphus-and-stone",
        "name": "Сизиф и камень",
        "description_ru": "Занять второе место более двух раз.",
        "description_en": "Take second place more than two times.",
    },
    {
        "category": "overall",
        "slug": "old",
        "name": "Олд",
        "description_ru": "Сыграть турнир в OW1.",
        "description_en": "Play a tournament in OW1.",
    },
    {
        "category": "overall",
        "slug": "young-blood",
        "name": "Молодая кровь",
        "description_ru": "Сыграть турнир в OW2.",
        "description_en": "Play a tournament in OW2.",
    },
    {
        "category": "overall",
        "slug": "dahao",
        "name": "ЛУПИ ИХ ДАХАО💪🏻😈🤙🏻 МЕСИ ИХ ДАХАО💪🏻😈🤙🏻",
        "description_ru": "Выиграть турнир на двух разных ролях.",
        "description_en": "Win a tournament in two different roles.",
    },
    {
        "category": "overall",
        "slug": "pathological-sucker",
        "name": "Патологический лох",
        "description_ru": "Занять второе место на всех ролях.",
        "description_en": "Take second place in all roles.",
    },
    {
        "category": "overall",
        "slug": "lord-of-all-the-elements",
        "name": "Властелин всех стихий",
        "description_ru": "Выиграть турнир на трех разных ролях.",
        "description_en": "Win a tournament in three different roles.",
    },
    {
        "category": "overall",
        "slug": "backyard-cyber-athlete",
        "name": "Дворовой киберспортсмен",
        "description_ru": "Играл OWAL.",
        "description_en": "Played OWAL.",
    },
    {
        "category": "overall",
        "slug": "well-deserved-anomaly",
        "name": "Заслужанная аномалия",
        "description_ru": "Победитель OWAL.",
        "description_en": "Winner of OWAL.",
    },
    {
        "category": "overall",
        "slug": "its-genetics",
        "name": "Это генетика",
        "description_ru": "Отыграть все турниры 1 героем",
        "description_en": "Play all tournaments with 1 hero",
    },
    {
        "category": "overall",
        "slug": "captain-jack-sparrow",
        "name": "Капитан Джек Воробей",
        "description_ru": "Стать капитаном в своей команде.",
        "description_en": "Become a captain in your team.",
    },
    {
        "category": "overall",
        "slug": "worst-player-winrate",
        "name": "Джентльмен неудачи",
        "description_ru": "Войти в топ20 игроков по винрейту (снизу).",
        "description_en": "Enter the top 20 players by winrate (from the bottom).",
    },
    {
        "category": "overall",
        "slug": "best-player-winrate",
        "name": "Все просто, я лучший!",
        "description_ru": "Войти в топ20 игроков по винрейту.",
        "description_en": "Enter the top 20 players by winrate.",
    },
    {
        "category": "overall",
        "slug": "consistent-winner",
        "name": "Стабильный победитель",
        "description_ru": "Занять место в топ20 по выигранным картам.",
        "description_en": "Take a place in the top 20 by won maps.",
    },
    {
        "category": "overall",
        "slug": "just-shooting",
        "name": "Мы просто стреляли пули",
        "description_ru": "Выиграть турнир с винрейтом 90%+.",
        "description_en": "Win a tournament with a winrate of 90%+.",
    },
    {
        "category": "overall",
        "slug": "ill-definitely-survive",
        "name": "Я обязательно выживу",
        "description_ru": "Занять топ 1 по минимальному кол-ву смертей в логах турика.",
        "description_en": "Take top 1 by the minimum number of deaths in the logs of the tournament.",
    },
    {
        "category": "overall",
        "slug": "killer-machine",
        "name": "Машина убийца",
        "description_ru": "Занять топ 1 по максимальному кол-ву убийств в логах турика.",
        "description_en": "Take top 1 by the maximum number of kills in the logs of the tournament.",
    },
    {
        "category": "overall",
        "slug": "just-shoot-in-the-head",
        "name": "Просто стреляй в голову",
        "description_ru": "Занять топ 1 по кол-ву хедшотов в логах турика.",
        "description_en": "Take top 1 by the number of headshots in the logs of the tournament.",
    },
    {
        "category": "overall",
        "slug": "poop_forever",
        "name": "Срать вечно",
        "description_ru": "Нанести наибольшее количество урона/мин за турнир",
        "description_en": "Deal the most damage/min per tournament",
    },
    {
        "category": "overall",
        "slug": "one-shot-one-kill",
        "name": "Один выстрел, один труп",
        "description_ru": "Стать топ 1 по крит. меткости в прицеле на турнире",
        "description_en": "Become the top 1 by crit accuracy in the sight during the tournament",
    },
    {
        "category": "overall",
        "slug": "space-created",
        "name": "Спейс создан",
        "description_ru": "Умереть 1000+ раз за историю логов",
        "description_en": "Die 1000+ times in the history of logs",
    },
    {
        "category": "overall",
        "slug": "fucking-casino-mouth",
        "name": "ё#%ный рот этого казино",
        "description_ru": "Сыграть 20 турниров",
        "description_en": "Play 20 tournaments",
    },
    {
        "category": "overall",
        "slug": "regular-boar",
        "name": "Завсегдатай кабанения",
        "description_ru": "Сыграть 30 турниров",
        "description_en": "Play 30 tournaments",
    },
    {
        "category": "division",
        "slug": "my-strength-is-growing",
        "name": "Моя сила растёт",
        "description_ru": "Получить плюс див после турнира.",
        "description_en": "Get a plus div after the tournament.",
    },
    {
        "category": "division",
        "slug": "not-good-enough",
        "name": "Недостаточно хорош",
        "description_ru": "Получить минус див после турнира.",
        "description_en": "Get a minus div after the tournament.",
    },
    {
        "category": "division",
        "slug": "i-need-more-power",
        "name": "Мне нужно больше силы",
        "description_ru": "Получить 3 див или выше.",
        "description_en": "Get 3 div or higher.",
    },
    {
        "category": "division",
        "slug": "my-drill-will-pierce-the-sky",
        "name": "Мой бур пронзит небеса",
        "description_ru": "Поднял за время турниров 10+ дивизионов.",
        "description_en": "Raised 10+ divisions during the tournaments.",
    },
    {
        "category": "division",
        "slug": "balance-from-anak",
        "name": "Баланс от Анака",
        "description_ru": "Получил +4 или больше дивов за турнир.",
        "description_en": "Got +4 or more divs for the tournament.",
    },
    {
        "category": "division",
        "slug": "critical-failure",
        "name": "Критический провал",
        "description_ru": "Получил -4 или больше дивов за турнир.",
        "description_en": "Got -4 or more divs for the tournament.",
    },
    {
        "category": "division",
        "slug": "im-fine-with-that",
        "name": "Да мне и так нормально...",
        "description_ru": "Иметь один и тот же дивизион в течении 7+ турниров.",
        "description_en": "Have the same division for 7+ tournaments.",
    },
    {
        "category": "team",
        "slug": "damage-above-5-division",
        "name": "Киберкотлета с пюрешкой",
        "description_ru": "Попасть в команду к капитану дд 5 дива и выше.",
        "description_en": "Get into a team with a captain damage 5 div and above.",
    },
    {
        "category": "team",
        "slug": "tank-above-5-division",
        "name": "Беру весь огонь на себя",
        "description_ru": "Попасть в команду к капитану танку 5 дива и выше.",
        "description_en": "Get into a team with a captain tank 5 div and above.",
    },
    {
        "category": "team",
        "slug": "support-above-5-division",
        "name": "Умрёшь только когда я скажу",
        "description_ru": "Попасть в команду к капитану саппорту 5 дива и выше.",
        "description_en": "Get into a team with a captain support 5 div and above.",
    },
    {
        "category": "team",
        "slug": "lfs-4500",
        "name": "LFS 20 EST 4.5k+",
        "description_ru": "Попасться с одним и тем же игроком 3+ раза.",
        "description_en": "Get caught with the same player 3+ times.",
    },
    {
        "category": "team",
        "slug": "im-screwed-run",
        "name": "Я конченный, бегите",
        "description_ru": "Отыграть весь турик не сменив персонажа.",
        "description_en": "Play the whole tournament without changing the character.",
    },
    {
        "category": "team",
        "slug": "we-work-with-what-we-have",
        "name": "Работаем с тем, что есть",
        "description_ru": "Заролиться с тиммейтом OTP в команду.",
        "description_en": "Roll with a OTP teammate into a team.",
    },
    {
        "category": "team",
        "slug": "were-so-fucked",
        "name": "Какая же нам пи№#а",
        "description_ru": "Заролиться в команду с 3+ OTP тиммейтами.",
        "description_en": "Roll into a team with 3+ OTP teammates.",
    },
    {
        "category": "standing",
        "slug": "beginners-are-lucky",
        "name": "Новичкам везёт",
        "description_ru": "Пройти во второй день с новичком в команде.",
        "description_en": "Pass to the second day with a newcomer in the team.",
    },
    {
        "category": "standing",
        "slug": "were-not-suckers",
        "name": "Да не лохи мы…",
        "description_ru": "Отдать финал турнира 2-3.",
        "description_en": "Give the final of the tournament 2-3.",
    },
    {
        "category": "standing",
        "slug": "reverse-sweep-champion",
        "name": "Reverse Sweep Champion",
        "description_ru": "Выиграть турнир, упадя в нижнюю сетку.",
        "description_en": "Win a tournament by falling into the lower bracket.",
    },
    {
        "category": "standing",
        "slug": "to-the-bottom",
        "name": "На дно!!!",
        "description_ru": "Отлететь в первый день со счётом 0-10 заняв последнее место в своей группе.",
        "description_en": "Take off on the first day with a score of 0-10, taking the last place in your group.",
    },
    {
        "category": "standing",
        "slug": "samurai-has-no-purpose",
        "name": "Самураю нет цели...",
        "description_ru": "Не выйти во второй день ни разу.",
        "description_en": "Not to go out on the second day even once.",
    },
    {
        "category": "standing",
        "slug": "the-best-among-the-best",
        "name": "Мы лучшие среди лучших",
        "description_ru": "Стать топ 1 своей группы в первый день со счётом 10-0.",
        "description_en": "Become the top 1 of your group on the first day with a score of 10-0.",
    },
    {
        "category": "standing",
        "slug": "revenge-is-sweet",
        "name": "Переигран и уничтожен",
        "description_ru": "Победить соперника, который ранее вас выиграл.",
        "description_en": "Defeat an opponent who previously beat you.",
    },
    {
        "category": "standing",
        "slug": "dirty-smurf",
        "name": "Грязный смурф",
        "description_ru": "Стать чемпионом в свой первый турнир.",
        "description_en": "Become a champion in your first tournament.",
    },
    {
        "category": "standing",
        "slug": "anchor-in-my-throat",
        "name": "Якорь мне в глотку",
        "description_ru": "Выиграть турик, имея в команде тиммейта 20 дива.",
        "description_en": "Win the tournament with a teammate 20 div.",
    },
    {
        "category": "standing",
        "slug": "win-2-plus-consecutive",
        "name": "Мне просто повезло",
        "description_ru": "Выиграть 2+ турнира подряд.",
        "description_en": "Win 2+ tournaments in a row.",
    },
    {
        "category": "standing",
        "slug": "five-second-day-streak",
        "name": "Да нормальный у меня див!",
        "description_ru": "Выйти во второй день 5 турниров подряд",
        "description_en": "Go out on the second day 5 tournaments in a row",
    },
    {
        "category": "standing",
        "slug": "i-killed-i-stole",
        "name": "Я УБИВАЛ Я ВОРОВАЛ",
        "description_ru": "Добраться до финала, пройдя по всей нижней сетке.",
        "description_en": "Get to the final by going through the entire lower bracket.",
    },
    {
        "category": "standing",
        "slug": "well-balanced",
        "name": "Забаланшенные",
        "description_ru": "Сыграть все матчи в группе в ничью.",
        "description_en": "Play all matches in the group in a draw.",
    },
    {
        "category": "match",
        "slug": "friendly",
        "name": "Френдли",
        "description_ru": "Сыграть карту с 0 убийствами.",
        "description_en": "Play a map with 0 kills.",
    },
    {
        "category": "match",
        "slug": "boris_dick",
        "name": "Борис Хрен Попадешь",
        "description_ru": "Выиграть карту ни умерев ни разу.",
        "description_en": "Win a card without dying once.",
    },
    {
        "category": "match",
        "slug": "just_dont_fuck_around",
        "name": "Главное не хукнись",
        "description_ru": "Умереть за карту 20+ раз",
        "description_en": "Die for a map 20+ times",
    },
    {
        "category": "match",
        "slug": "john_wick",
        "name": "Джон Уик",
        "description_ru": "Сделать более 60 элимов за карту",
        "description_en": "Make over 60 eliminations per map",
    },
    {
        "category": "match",
        "slug": "the-shift-factory-is-done",
        "name": "Смена на заводе отработана",
        "description_ru": "Нахилять более 30000 ед. хила за карту",
        "description_en": "Heal for more than 30,000 hit points per map",
    },
    {
        "category": "match",
        "slug": "shooting_and_screaming",
        "name": "РАБОТАЕМ ЕКАТЕРИНА!",
        "description_ru": "Нанести более 35000 ед. урона за карту",
        "description_en": "Deal more than 35000 damage per map",
    },
    {
        "category": "match",
        "slug": "fiasko",
        "name": "Это фиаско братан",
        "description_ru": "Упасть за карту от бупа 3+ раза за карту",
        "description_en": "Fall for a map from a boop 3+ times per map",
    },
    {
        "category": "match",
        "slug": "boop_master",
        "name": "Чувак это яма",
        "description_ru": "Бупнуть за карту противника 3+ раза за карту",
        "description_en": "Boop the opponent 3+ times per map",
    },
    {
        "category": "match",
        "slug": "bullet-is-not-stupid",
        "name": "Пуля не дура",
        "description_ru": "Убить 10+ человек за карту хедшотом",
        "description_en": "Kill 10+ people per map with headshots",
    },
    {
        "category": "match",
        "slug": "balanced",
        "name": "Набалансил",
        "description_ru": "Сыграть матч с близостью 0%",
        "description_en": "Play a match with a close 0%",
    },
    {
        "category": "match",
        "slug": "hard_game",
        "name": "Я сосал меня е&%ли",
        "description_ru": "Сыграть матч с близостью 100%",
        "description_en": "Play a match with a close 100%",
    },
    {
        "category": "match",
        "slug": "7_years_in_azkaban",
        "name": "7 лет в Азкабане",
        "description_ru": "Сыграть матч длительностью 25+ минут",
        "description_en": "Play a match lasting 25+ minutes",
    },
    {
        "category": "match",
        "slug": "fast",
        "name": "Скорострел",
        "description_ru": "Сыграть матч длительностью максимум 5 мин",
        "description_en": "Play a match lasting a maximum of 5 minutes",
    },
)


# Fallback flavour text for heroes synced from OW that are not in the legacy catalog.
_GENERIC_HERO_NAME = "{name}"
_GENERIC_HERO_DESC_RU = "Иметь лучшее K/D на {name} за турнир"
_GENERIC_HERO_DESC_EN = "Have the best K/D as {name} during the tournament"


@dataclass(frozen=True, slots=True)
class CanonicalRuleMeta:
    slug: str
    name: str
    description_ru: str
    description_en: str
    category: AchievementCategory


def _build_canonical_rule_catalog() -> list[CanonicalRuleMeta]:
    category_map = {
        "hero": AchievementCategory.hero,
        "overall": AchievementCategory.overall,
        "division": AchievementCategory.division,
        "team": AchievementCategory.team,
        "standing": AchievementCategory.standing,
        "match": AchievementCategory.match,
    }

    catalog: list[CanonicalRuleMeta] = []
    seen_slugs: set[str] = set()
    for item in CANONICAL_ACHIEVEMENT_CATALOG:
        slug = item["slug"]
        if slug in seen_slugs:
            raise ValueError(f"Duplicate achievement slug in canonical catalog: {slug}")
        seen_slugs.add(slug)
        catalog.append(
            CanonicalRuleMeta(
                slug=slug,
                name=item["name"],
                description_ru=item["description_ru"],
                description_en=item["description_en"],
                category=category_map[item["category"]],
            )
        )
    return catalog


_CANONICAL_RULES = _build_canonical_rule_catalog()
_CANONICAL_RULES_BY_SLUG = {rule.slug: rule for rule in _CANONICAL_RULES}

_PLACEHOLDER_DEFAULTS_BY_CATEGORY = {
    AchievementCategory.overall: (AchievementScope.glob, AchievementGrain.user),
    AchievementCategory.hero: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.division: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.team: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.standing: (AchievementScope.tournament, AchievementGrain.user_tournament),
    AchievementCategory.match: (AchievementScope.match, AchievementGrain.user_match),
}

_HERO_NON_KD_SLUGS = {"freak", "mystery-heroes", "swiss-knife"}
_HERO_KD_SLUGS = [
    meta.slug
    for meta in _CANONICAL_RULES
    if meta.category == AchievementCategory.hero and meta.slug not in _HERO_NON_KD_SLUGS
]
# ponytail: one global denylist, per-workspace default packs if a second tenant needs a different seed.
_DEFAULT_EXCLUDED_SLUGS = frozenset(
    {
        "anchor-in-my-throat",
        "backyard-cyber-athlete",
        "balance-from-anak",
        "beginners-are-lucky",
        "critical-failure",
        "damage-above-5-division",
        "five-second-day-streak",
        "i-need-more-power",
        "im-fine-with-that",
        "my-drill-will-pierce-the-sky",
        "my-strength-is-growing",
        "not-good-enough",
        "old",
        "regular-boar",
        "samurai-has-no-purpose",
        "support-above-5-division",
        "tank-above-5-division",
        "the-best-among-the-best",
        "to-the-bottom",
        "welcome",
        "well-balanced",
        "well-deserved-anomaly",
        "young-blood",
    }
)


def _catalog_rule(
    workspace_id: int,
    slug: str,
    *,
    scope: AchievementScope,
    grain: AchievementGrain,
    condition_tree: dict,
    depends_on: list[str] | None = None,
    enabled: bool = True,
    min_tournament_id: int | None = None,
    hero_id: int | None = None,
    image_url: str | None = None,
) -> AchievementRule:
    meta = _CANONICAL_RULES_BY_SLUG[slug]
    return AchievementRule(
        workspace_id=workspace_id,
        slug=meta.slug,
        name=meta.name,
        description_ru=meta.description_ru,
        description_en=meta.description_en,
        category=meta.category,
        scope=scope,
        grain=grain,
        condition_tree=condition_tree,
        depends_on=depends_on or [],
        enabled=enabled,
        min_tournament_id=min_tournament_id,
        hero_id=hero_id,
        image_url=image_url,
    )


def _placeholder_rule(workspace_id: int, slug: str) -> AchievementRule:
    meta = _CANONICAL_RULES_BY_SLUG[slug]
    scope, grain = _PLACEHOLDER_DEFAULTS_BY_CATEGORY[meta.category]
    return _catalog_rule(
        workspace_id,
        slug,
        scope=scope,
        grain=grain,
        condition_tree={},
        depends_on=[],
        enabled=False,
    )


def _hero_kd_condition_tree(slug: str) -> dict:
    return {
        "type": "hero_kd_best",
        "params": {"hero_slug": slug, "min_time": 600, "min_matches": 3},
    }


def _hero_kd_rule_from_db(workspace_id: int, hero: Hero) -> AchievementRule:
    """Build a hero K/D rule for a DB hero, using legacy flavour text when known."""
    meta = _CANONICAL_RULES_BY_SLUG.get(hero.slug)
    name = meta.name if meta else _GENERIC_HERO_NAME.format(name=hero.name)
    description_ru = meta.description_ru if meta else _GENERIC_HERO_DESC_RU.format(name=hero.name)
    description_en = meta.description_en if meta else _GENERIC_HERO_DESC_EN.format(name=hero.name)
    return AchievementRule(
        workspace_id=workspace_id,
        slug=hero.slug,
        name=name,
        description_ru=description_ru,
        description_en=description_en,
        category=AchievementCategory.hero,
        scope=AchievementScope.tournament,
        grain=AchievementGrain.user_tournament,
        condition_tree=_hero_kd_condition_tree(hero.slug),
        depends_on=["matches.statistics"],
        enabled=True,
        hero_id=hero.id,
        image_url=hero.image_path,
    )


def _hero_kd_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    """Hero K/D rules.

    When ``heroes`` is provided (during DB-backed seeding), one rule is generated
    per hero in ``overwatch.hero`` — so newly synced heroes automatically get an
    achievement. Catalog flavour text is used when the slug is known, otherwise a
    generic name/description is generated. Catalog heroes missing from the DB still
    get a (catalog-based) rule, so the canonical catalog stays fully covered.

    When ``heroes`` is None (sync callers / tests), only the catalog hero slugs are
    used — preserving backward-compatible, DB-free behaviour.
    """
    rules: list[AchievementRule] = []
    seen: set[str] = set()

    if heroes is not None:
        for hero in heroes:
            if hero.slug in _HERO_NON_KD_SLUGS or hero.slug in seen:
                continue
            rules.append(_hero_kd_rule_from_db(workspace_id, hero))
            seen.add(hero.slug)

    for slug in _HERO_KD_SLUGS:
        if slug in seen:
            continue
        rules.append(
            _catalog_rule(
                workspace_id,
                slug,
                scope=AchievementScope.tournament,
                grain=AchievementGrain.user_tournament,
                condition_tree=_hero_kd_condition_tree(slug),
                depends_on=["matches.statistics"],
            )
        )

    return rules


def _match_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "balanced",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 0}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "hard_game",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "closeness", "op": "==", "value": 1}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "7_years_in_azkaban",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": ">=", "value": 1500}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "fast",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "match_criteria", "params": {"field": "match_time", "op": "<=", "value": 300}},
            depends_on=["matches.match"],
        ),
        _catalog_rule(
            workspace_id,
            "friendly",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": "==", "value": 0}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "boris_dick",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "AND": [
                    {"type": "stat_threshold", "params": {"stat": "Deaths", "op": "==", "value": 0}},
                    {"type": "match_win"},
                ]
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "john_wick",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Eliminations", "op": ">=", "value": 60}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "just_dont_fuck_around",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "Deaths", "op": ">=", "value": 20}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "the-shift-factory-is-done",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={"type": "stat_threshold", "params": {"stat": "HealingDealt", "op": ">=", "value": 30000}},
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "shooting_and_screaming",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "HeroDamageDealt", "op": ">=", "value": 35000},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "fiasko",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "EnvironmentalDeaths", "op": ">=", "value": 3},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "boop_master",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "EnvironmentalKills", "op": ">=", "value": 3},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "bullet-is-not-stupid",
            scope=AchievementScope.match,
            grain=AchievementGrain.user_match,
            condition_tree={
                "type": "stat_threshold",
                "params": {"stat": "ScopedCriticalHitKills", "op": ">=", "value": 10},
            },
            depends_on=["matches.match", "matches.statistics"],
        ),
    ]


def _overall_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "welcome",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 1}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "honor-and-glory",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "standing_position", "params": {"op": "==", "value": 1}},
            depends_on=["tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "versatile-player",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "distinct_count",
                "params": {"field": "role", "op": ">=", "value": 3, "scope": "global"},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "captain-jack-sparrow",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "is_captain"},
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "worst-player-winrate",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_winrate", "params": {"order": "asc", "limit": 20}},
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "best-player-winrate",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_winrate", "params": {"order": "desc", "limit": 20}},
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "space-created",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "global_stat_sum", "params": {"stat": "Deaths", "op": ">=", "value": 1000}},
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "fucking-casino-mouth",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 20}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "regular-boar",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "tournament_count", "params": {"op": ">=", "value": 30}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "old",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": False, "start_before": "2022-10-04"},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "young-blood",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": False, "start_after": "2022-10-04"},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "backyard-cyber-athlete",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "tournament_count",
                "params": {"op": ">=", "value": 1, "is_league": True},
            },
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "well-deserved-anomaly",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "tournament_type", "params": {"is_league": True}},
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "its-genetics",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "AND": [
                    {
                        "type": "distinct_count",
                        "params": {"field": "hero", "op": "==", "value": 1, "scope": "global", "min_playtime": 60},
                    },
                    {
                        "type": "distinct_count",
                        "params": {"field": "match", "op": ">", "value": 5, "scope": "global"},
                    },
                ]
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "two-wins-players",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 2},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "three-wins-players",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "tournament", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "sisyphus-and-stone",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 2, "count_by": "tournament", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "dahao",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 2},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "pathological-sucker",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 2, "count_by": "role", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "lord-of-all-the-elements",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "standing_count",
                "params": {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 3},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "consistent-winner",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "global_winrate",
                "params": {"metric": "won_maps", "order": "desc", "limit": 20},
            },
            depends_on=["tournament.player", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "just-shooting",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "tournament_winrate", "params": {"op": ">=", "value": 0.89}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing", "tournament.encounter"],
        ),
        _catalog_rule(
            workspace_id,
            "ill-definitely-survive",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "Deaths", "order": "asc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "killer-machine",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "Eliminations", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "just-shoot-in-the-head",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "CriticalHitAccuracy", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "poop_forever",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "HeroDamageDealt", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "one-shot-one-kill",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "log_stat_rank",
                "params": {"stat": "ScopedCriticalHitAccuracy", "order": "desc", "limit": 1},
            },
            depends_on=["matches.statistics"],
        ),
    ]


def _division_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "my-strength-is-growing",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "up", "min_shift": 1}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "not-good-enough",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "down", "min_shift": 1}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "i-need-more-power",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_level", "params": {"op": "<=", "value": 3}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "balance-from-anak",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "up", "min_shift": 4}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "critical-failure",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "div_change", "params": {"direction": "down", "min_shift": 4}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "im-fine-with-that",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "stable_streak", "params": {"fields": ["role", "division"], "min_streak": 7}},
            depends_on=["tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "my-drill-will-pierce-the-sky",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "div_span", "params": {"op": ">=", "value": 10}},
            depends_on=["analytics.player_shift", "tournament.player"],
        ),
    ]


def _standing_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "dirty-smurf",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "is_newcomer"},
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "tournament_type", "params": {"is_league": False}},
                ]
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "revenge-is-sweet",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "encounter_revenge"},
            depends_on=["tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "reverse-sweep-champion",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {"type": "bracket_path", "params": {"played_lower_bracket": True}},
                    {"type": "tournament_format", "params": {"format": "double_elim"}},
                ]
            },
            depends_on=["tournament.encounter", "tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "win-2-plus-consecutive",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "consecutive", "params": {"metric": "win", "min_streak": 2}},
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "beginners-are-lucky",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "reached_playoffs", "params": {"scope": "tournament"}},
                    {
                        "type": "team_players_match",
                        "params": {"mode": "any", "condition": {"type": "is_newcomer"}},
                    },
                ]
            },
            depends_on=["tournament.player", "tournament.standing", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "were-not-suckers",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "encounter_score",
                "params": {"scores": [[2, 3], [3, 2]], "round_type": "final", "side": "loser"},
            },
            depends_on=["tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "to-the-bottom",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {
                        "type": "standing_record",
                        "params": {"field": "wins", "op": "==", "value": 0, "groups_only": True},
                    },
                    {
                        "type": "standing_record",
                        "params": {"field": "draws", "op": "==", "value": 0, "groups_only": True},
                    },
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "samurai-has-no-purpose",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "reached_playoffs",
                "params": {"scope": "global", "op": "==", "value": 0},
            },
            depends_on=["tournament.player", "tournament.standing"],
        ),
        _catalog_rule(
            workspace_id,
            "the-best-among-the-best",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {
                        "type": "standing_record",
                        "params": {"field": "wins", "op": ">=", "value": 5, "groups_only": True},
                    },
                    {
                        "type": "standing_record",
                        "params": {"field": "losses", "op": "==", "value": 0, "groups_only": True},
                    },
                    {
                        "type": "standing_record",
                        "params": {"field": "draws", "op": "==", "value": 0, "groups_only": True},
                    },
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "i-killed-i-stole",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "<=", "value": 2}},
                    {"type": "bracket_path", "params": {"played_lower_bracket": True}},
                ]
            },
            depends_on=["tournament.standing", "tournament.encounter", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "well-balanced",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {
                        "type": "standing_record",
                        "params": {"field": "draws", "op": "==", "value": 5, "groups_only": True},
                    },
                    {
                        "type": "standing_record",
                        "params": {"field": "wins", "op": "==", "value": 0, "groups_only": True},
                    },
                    {
                        "type": "standing_record",
                        "params": {"field": "losses", "op": "==", "value": 0, "groups_only": True},
                    },
                ]
            },
            depends_on=["tournament.standing", "tournament.player"],
        ),
        _catalog_rule(
            workspace_id,
            "anchor-in-my-throat",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {"type": "standing_position", "params": {"op": "==", "value": 1}},
                    {
                        "type": "team_players_match",
                        "params": {
                            "mode": "any",
                            "condition": {"type": "player_div", "params": {"op": ">=", "value": 20}},
                        },
                    },
                ]
            },
            depends_on=["analytics.player_shift", "tournament.player", "tournament.standing", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "five-second-day-streak",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "consecutive", "params": {"metric": "playoffs", "min_streak": 5}},
            depends_on=["tournament.player", "tournament.standing"],
        ),
    ]


def _team_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "damage-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Damage"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.player_shift", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "tank-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Tank"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.player_shift", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "support-above-5-division",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "captain_property",
                "params": {
                    "condition": {
                        "AND": [
                            {"type": "player_role", "params": {"role": "Support"}},
                            {"type": "player_div", "params": {"op": "<=", "value": 5}},
                        ]
                    }
                },
            },
            depends_on=["analytics.player_shift", "tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "im-screwed-run",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "AND": [
                    {
                        "type": "distinct_count",
                        "params": {"field": "hero", "op": "==", "value": 1, "scope": "tournament", "min_playtime": 60},
                    },
                    {
                        "type": "distinct_count",
                        "params": {"field": "match", "op": ">", "value": 5, "scope": "tournament"},
                    },
                ]
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "lfs-4500",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={"type": "teammate_recurrence", "params": {"op": ">=", "value": 3}},
            depends_on=["tournament.player", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "we-work-with-what-we-have",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 1}},
            depends_on=["matches.statistics", "tournament.team"],
        ),
        _catalog_rule(
            workspace_id,
            "were-so-fucked",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "team_otp_count", "params": {"op": ">=", "value": 3}},
            depends_on=["matches.statistics", "tournament.team"],
        ),
    ]


def _hero_misc_rules(workspace_id: int) -> list[AchievementRule]:
    return [
        _catalog_rule(
            workspace_id,
            "freak",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={"type": "hero_pickrate", "params": {"op": "<", "value": 0.001}},
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "mystery-heroes",
            scope=AchievementScope.tournament,
            grain=AchievementGrain.user_tournament,
            condition_tree={
                "type": "distinct_count",
                "params": {"field": "hero", "op": ">=", "value": 7, "scope": "tournament", "min_playtime": 60},
            },
            depends_on=["matches.statistics"],
        ),
        _catalog_rule(
            workspace_id,
            "swiss-knife",
            scope=AchievementScope.glob,
            grain=AchievementGrain.user,
            condition_tree={
                "type": "distinct_count",
                "params": {"field": "hero", "op": ">=", "value": 20, "scope": "global", "min_playtime": 60},
            },
            depends_on=["matches.statistics"],
        ),
    ]


def _implemented_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    return [
        rule
        for rule in (
            *_match_rules(workspace_id),
            *_overall_rules(workspace_id),
            *_division_rules(workspace_id),
            *_standing_rules(workspace_id),
            *_team_rules(workspace_id),
            *_hero_misc_rules(workspace_id),
            *_hero_kd_rules(workspace_id, heroes),
        )
        if rule.slug not in _DEFAULT_EXCLUDED_SLUGS
    ]


def _placeholder_rules(
    workspace_id: int,
    implemented_slugs: set[str],
) -> list[AchievementRule]:
    return [
        _placeholder_rule(workspace_id, meta.slug)
        for meta in _CANONICAL_RULES
        if meta.slug not in implemented_slugs and meta.slug not in _DEFAULT_EXCLUDED_SLUGS
    ]


def _all_default_rules(
    workspace_id: int,
    heroes: list[Hero] | None = None,
) -> list[AchievementRule]:
    implemented_rules = _implemented_rules(workspace_id, heroes)
    implemented_slugs = {rule.slug for rule in implemented_rules}
    placeholder_rules = _placeholder_rules(workspace_id, implemented_slugs)
    all_rules = [*implemented_rules, *placeholder_rules]

    seen_slugs: set[str] = set()
    duplicates = [rule.slug for rule in all_rules if rule.slug in seen_slugs or seen_slugs.add(rule.slug)]
    if duplicates:
        raise ValueError(f"Duplicate slugs in default engine catalog: {duplicates}")

    return all_rules


def get_default_rule_slugs() -> list[str]:
    return sorted(rule.slug for rule in _all_default_rules(0))


def get_canonical_rule_catalog() -> list[CanonicalRuleMeta]:
    return list(_CANONICAL_RULES)
