# Загрузка проекта на GitHub

Репозиторий уже инициализирован и сделан первый коммит. Осталось привязать удалённый репозиторий и отправить код.

## Шаги

### 1. Создайте репозиторий на GitHub

- Зайдите на [github.com](https://github.com) → **New repository**.
- Имя, например: `augsburg-liquid-bot`.
- **Не** добавляйте README, .gitignore или лицензию — они уже есть в проекте.
- Нажмите **Create repository**.

### 2. Привяжите репозиторий и выполните push

В терминале из папки проекта выполните (подставьте свой логин и имя репо):

```bash
cd "/Users/x/Desktop/tg bot"

git remote add origin https://github.com/ВАШ_ЛОГИН/augsburg-liquid-bot.git
git branch -M main
git push -u origin main
```

Если используете SSH:

```bash
git remote add origin git@github.com:ВАШ_ЛОГИН/augsburg-liquid-bot.git
git push -u origin main
```

При запросе авторизации введите логин/пароль или используйте [Personal Access Token](https://github.com/settings/tokens) (при 2FA пароль не подойдёт — нужен токен).

### 3. Дальше

- В Railway: **New Project** → **Deploy from GitHub repo** → выберите этот репозиторий.
- Настройте переменные и Volume по [RAILWAY.md](RAILWAY.md).
