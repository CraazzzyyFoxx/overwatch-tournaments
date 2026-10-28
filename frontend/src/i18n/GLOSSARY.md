# i18n Glossary — terminology authority (EN ↔ RU)

Register: **esports/community jargon** (Overwatch competitive community). Applies
to every message in `messages/en.json` and `messages/ru.json`. When a term below
appears, use exactly this translation for consistency across the app.

## Core terms

| EN | RU | Notes |
|---|---|---|
| Standings | Таблица | tournament standings; short form «Таблица» in navigation |
| Bracket | Сетка | |
| Playoff | Плей-офф | |
| Group / Groups | Группа / Группы | |
| Group stage | Групповой этап | |
| Round-robin | Круговой | |
| Swiss | Швейцарка | |
| Check-in | Чек-ин | verb: «Пройти чек-ин» |
| Withdraw | Снять заявку | |
| Roster / Rostered | Ростер / В ростере | |
| Participants | Участники | |
| Heroes | Герои | |
| Tank / Damage / Support | Танк / Дамаг / Саппорт | roles |
| Rank | Ранг | |
| SR | SR | not translated |
| Division | Дивизион | |
| Draft | Драфт | |
| Pick | Пик | verb: «пикать/выбрать» |
| Ban | Бан | |
| Encounter | Встреча | a pair of teams within a match |
| Match | Матч | |
| Map | Карта | |
| Tiebreakers | Тай-брейки | |
| Buchholz | Бухгольц | |
| Head-to-Head | Личные встречи | |
| Balancer | Балансировщик | |
| Registration | Регистрация | |
| Phase | Фаза | tournament lifecycle phase: registration, check-in, draft, live |
| Schedule | Расписание | «Расписание фаз» — public page with phase times |
| Smurf | Смурф | |
| BattleTag | BattleTag | not translated |
| Playtime | Тайм на героях | «% playtime» → «% тайма» |
| Seed / Seeding | Посев | |
| Slot | Слот | a single map of a series |
| Candidate | Кандидат | «карты-кандидаты» |
| Reserve map | Резервная карта | reserve used on a tie |
| One-trick | Вантрик | a player who lives on one hero; «Вантрики» |
| Blind ban / per-player ban | Бан вслепую / бан по игроку | first-map ban vs a ban aimed at one opponent |
| Autopick | Автопик | a draft pick the clock made |
| Form | Форма | a team's last results (W/D/L) |

## Admin console terms

| EN | RU | Notes |
|---|---|---|
| Workspace | Воркспейс | not «пространство»; masculine: «в воркспейсе», «воркспейсы» |
| Division grid | Шкала дивизионов | |
| Player identity | Игровой профиль | the player record, as opposed to the sign-in account |
| Auth account | Аккаунт входа | the account a person signs in with |
| Sessions | Сессии | |
| Team registration | Командная регистрация | |
| Tournament hub | Панель турнира | |
| Bracket layout | Схема сетки | |
| Google Sheets feed | Фид Google Sheets | masculine: «фид сохранён» |
| Parsed maps | Разобранные карты | not «распарсенные» |
| Unresolved names | Нераспознанные названия | |
| On call | На подмену | registration flag: ready to step in as a substitute |
| Best-of | Best-of | not translated |
| Stats | | the public site's `matches.stat.*` wording |
| Roles, tournament statuses | | reuse `common.roles` and `common.statusBadge` rather than new keys; plurals and the genitive (`tournamentDetail.roles`, `tournamentDetail.roleOf`) are the only role words outside them |

## Style rules

- Tone: address the user with «вы», no officialese; short and to the point (UI strings).
- Buttons are imperative («Снять заявку», «Пройти чек-ин»), headings are nouns.
- Numbers: Russian pluralization via ICU (`plural` with `one/few/many/other`).
- Never translated: `SR`, `BattleTag`, hero and map names, `Overwatch`.
- «Rotation» as a noun is not translated: in this community «ротация» already means
  map/hero rotation, so «ротация первого бана» reads as something about pool
  composition. The control is labelled «Кто банит первым», with the options «Всегда
  высший сид» / «По очереди».
- English — check for naturalness and consistency (the same thing is named the same
  way across all namespaces).
