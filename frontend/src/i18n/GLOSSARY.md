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
