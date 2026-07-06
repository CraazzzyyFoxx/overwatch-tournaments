import json

import pandas as pd


# Преобразование строки: приведение к нижнему регистру и удаление всех пробелов
def clean_str(s):
    return str(s).replace(" ", "").strip().lower()


# URL в формате CSV для первого листа (если менять, то не весь юрл, а только уникальную часть от /d/ до /export)
# Например, если у нас ссылка такая https://docs.google.com/spreadsheets/d/1mN_mp8DUmw6SbxABCOyRpmCuo7ccWqI-u8sa_MY7FKE/edit#gid=1807279519
# мы берем только часть 1mN_mp8DUmw6SbxABCOyRpmCuo7ccWqI-u8sa_MY7FKE , которая между /d/ и /edit#gid=1807279519
# и вставляем ее в ссылку между https://docs.google.com/spreadsheets/d/ и /export?format=csv
#                             прямо вот тут   /                                            /  вот между скобок в ссылке ниже и ебашь
url = "https://docs.google.com/spreadsheets/d/1qqmMHUugph8TBoZ00Wto2q8E5fqsC_DAJIFH03JDZXA/export?format=csv"

# Чтение данных в DataFrame

df = pd.read_csv(url)

# Выбор и переименование нужных столбцов
filtered_df = df[
    [
        "Ваш Battle tag (в формате MyName#1337) Профиль обязан быть ОТКРЫТЫМ на время проведения турнира, а в друзья может добавитьcя AnakBalancer#2647 для проверки рейтингов. ЗАКРЫТЫЕ ПРОФИЛИ НЕ ПРОХОДЯТ НА ТУРНИР. Как открыть профиль на картинке ниже.",
        "Ваши battle tag СМУРФОВ. Все игроки обязаны показать ВСЕ свои другие аккаунты, если таковые имеются.",
        "Ваш ник на Твиче (Точный до буквы).",
        #   'В каком последнем турнире вы участвовали?',
        "Укажите вашу Роль в команде опираясь на ваших основных персонажах, какой набор вам лучше подходит? Если играете обоими можно выбрать пункт оба подкласса. У новичков на роли должно быть минимум 30 побед в сезоне.",
    ]
].rename(
    columns={
        "Ваш Battle tag (в формате MyName#1337) Профиль обязан быть ОТКРЫТЫМ на время проведения турнира, а в друзья может добавитьcя AnakBalancer#2647 для проверки рейтингов. ЗАКРЫТЫЕ ПРОФИЛИ НЕ ПРОХОДЯТ НА ТУРНИР. Как открыть профиль на картинке ниже.": "Battle.tag",
        "Ваши battle tag СМУРФОВ. Все игроки обязаны показать ВСЕ свои другие аккаунты, если таковые имеются.": "Smurf Battle.tag",
        "Ваш ник на Твиче (Точный до буквы).": "Twitch",
        #  'В каком последнем турнире вы участвовали?': 'Last tournament',
        "Укажите вашу Роль в команде опираясь на ваших основных персонажах, какой набор вам лучше подходит? Если играете обоими можно выбрать пункт оба подкласса. У новичков на роли должно быть минимум 30 побед в сезоне.": "Main role",
    }
)

# Чтение JSON-файла
with open("backup.json", encoding="utf-8") as f:
    json_data = json.load(f)

# Получение данных о игроках из JSON
players_data = json_data["players"]
backup_tags = [clean_str(players_data[player]["identity"]["name"]) for player in players_data]

# Сравниваем Battle.tag и Smurf battle.tag с backup_tags
google_tags = [clean_str(tag) for tag in filtered_df["Battle.tag"].tolist()]
smurf_tags = [clean_str(tag) for tag in filtered_df["Smurf Battle.tag"].tolist()]

missing_in_backup = sorted([tag for tag in google_tags if tag not in backup_tags])
missing_in_google = sorted([tag for tag in backup_tags if tag not in google_tags])

# Создаем DataFrame для вывода
result_df = pd.DataFrame(
    {
        "Missing in Backup": pd.Series(missing_in_backup),
        "Missing in Google Sheet": pd.Series(missing_in_google),
    }
)


# Добавляем новый столбец 'Main role' в filtered_df
role_mapping = {
    "Лайт хил (Мерси, Кирико)": "Support Light",
    "Проджектайл ДД (Генджи, Фара, Ханзо, Торбьерн, Джанкрет, Эхо, Мей, Рипер, Сомбра, Симметра, Трейсер)": "Dps Projectile",
    "Лайт хил (Мерси, Зен, Люсио, Брига, Мойра)": "Support Light",
    "Оба Подкласса ДД": "Dps All",
    "Хитскан ДД (Маккри, Вдова, Солдат76, Эш)": "Dps Hitscan",
    "Я флекс, могу играть абсолютно на всем": "Flex",
    "Оба Подкласса Хила": "Support All",
    "Танк": "Tank",
    "Танк.": "Tank",
    "Мейн хил (Ана, Батист, Мойра)": "Support Main",
    "Dps": "Dps All",
    "Оба Подкласса Танка.": "Tank",
    "ОффТанк (Заря, Дива, Хог, Сигма)": "Off Tank",
    "МейнТанк (Рейнхард, Винстон, Ориса, Хэммонд)": "Main Tank",
    "Лайт хил (Мерси, Зен, Люсио, Брига)": "Support Light",
    "Хитскан ДД (Кэс, Вдова, Солдат76, Эш)": "Dps Hitscan",
    "Лайт хил (Мерси, Иллари, Зен, Люсио, Брига, Мойра)": "Support Light",
    "Мейн хил (Юнона, Ана, Батист, Мойра)": "Support Main",
}

filtered_df["Main role"] = filtered_df["Main role"].map(role_mapping)

result_df = pd.DataFrame(columns=["Battle.Tag", "Main Role from Sheet", "Role from Balancer"])

json_roles = {}
for _player_id, player_data in json_data["players"].items():
    battle_tag = clean_str(player_data["identity"]["name"])
    if player_data["identity"]["isFullFlex"]:
        json_roles[battle_tag] = "Flex"
    else:
        for role_class, role_data in player_data["stats"]["classes"].items():
            if role_data["priority"] == 0 and role_data["isActive"]:
                if role_class == "tank":
                    json_roles[battle_tag] = "Tank"
                elif role_class == "support":
                    if role_data["primary"]:
                        json_roles[battle_tag] = "Support Main"
                    elif role_data["secondary"]:
                        json_roles[battle_tag] = "Support Light"
                    else:
                        json_roles[battle_tag] = "Support All"
                elif role_class == "dps":
                    if role_data["primary"]:
                        json_roles[battle_tag] = "Dps Hitscan"
                    elif role_data["secondary"]:
                        json_roles[battle_tag] = "Dps Projectile"
                    else:
                        json_roles[battle_tag] = "Dps All"

# Это будет список для хранения строк, которые мы потом добавим в result_df
rows_to_add = []

# Проверка на совпадение ролей и заполнение result_df
for _index, row in filtered_df.iterrows():
    battle_tag = row["Battle.tag"].lower()

    if battle_tag in json_roles:
        main_role_sheet = row["Main role"]
        role_balancer = json_roles[battle_tag]

        if main_role_sheet != role_balancer:
            rows_to_add.append(
                {
                    "Battle.Tag": battle_tag,
                    "Main Role from Sheet": main_role_sheet,
                    "Role from Balancer": role_balancer,
                }
            )

# Добавляем все собранные строки в result_df
result_df = pd.concat([result_df, pd.DataFrame(rows_to_add)], ignore_index=True)

result_df = result_df.sort_values(by="Battle.Tag")


# Создаем список идентификаторов для удаления
players_to_remove = []

# Находим идентификаторы ненужных игроков
for player_id, player_data in json_data["players"].items():
    battle_tag = clean_str(player_data["identity"]["name"])
    if battle_tag not in google_tags:
        players_to_remove.append(player_id)

# Удаляем ненужных игроков из копии
new_json_data = json_data.copy()
for player_id in players_to_remove:
    del new_json_data["players"][player_id]

# Сохраняем отфильтрованные данные в новый JSON-файл
with open("filtered_backup.json", "w", encoding="utf-8") as f:
    json.dump(new_json_data, f, ensure_ascii=False, indent=4)

print("Отсутствуют в лобби:")
print(pd.DataFrame(missing_in_backup))
