# 🚀 Деплой на продакшн сервер

## 🖥 Требования к серверу

### Минимальные:
- **OS:** Ubuntu 20.04+ / Debian 11+ / CentOS 8+
- **RAM:** 512 MB
- **CPU:** 1 core
- **HDD:** 5 GB
- **Python:** 3.8+

### Рекомендуемые:
- **OS:** Ubuntu 22.04 LTS
- **RAM:** 1 GB
- **CPU:** 2 cores
- **HDD:** 10 GB
- **Python:** 3.10+

---

## 📦 Установка на Ubuntu/Debian

### 1. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Установка Python и зависимостей

```bash
sudo apt install python3 python3-pip python3-venv git -y
```

### 3. Создание пользователя для бота

```bash
sudo adduser botuser
sudo usermod -aG sudo botuser
su - botuser
```

### 4. Клонирование проекта

```bash
cd ~
mkdir augsburg-liquid
cd augsburg-liquid

# Скопируйте все файлы проекта сюда
```

### 5. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Настройка переменных окружения

```bash
nano .env
```

Убедитесь, что все токены правильно заполнены:
```
USER_BOT_TOKEN=ваш_токен
ADMIN_BOT_TOKEN=ваш_токен
ADMIN_CHAT_ID=ваш_id
DATABASE_PATH=augsburg_liquid.db
```

### 7. Инициализация базы данных

```bash
python utils.py init
python utils.py sample  # Опционально: добавить примеры
```

---

## 🔧 Настройка Systemd сервисов

### 1. User Bot Service

Создайте файл:
```bash
sudo nano /etc/systemd/system/augsburg-user-bot.service
```

Содержимое:
```ini
[Unit]
Description=Augsburg Liquid User Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/augsburg-liquid
Environment="PATH=/home/botuser/augsburg-liquid/venv/bin"
ExecStart=/home/botuser/augsburg-liquid/venv/bin/python user_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 2. Admin Bot Service

Создайте файл:
```bash
sudo nano /etc/systemd/system/augsburg-admin-bot.service
```

Содержимое:
```ini
[Unit]
Description=Augsburg Liquid Admin Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/augsburg-liquid
Environment="PATH=/home/botuser/augsburg-liquid/venv/bin"
ExecStart=/home/botuser/augsburg-liquid/venv/bin/python admin_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 3. Активация сервисов

```bash
# Перезагрузка конфигурации systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable augsburg-user-bot
sudo systemctl enable augsburg-admin-bot

# Запуск сервисов
sudo systemctl start augsburg-user-bot
sudo systemctl start augsburg-admin-bot

# Проверка статуса
sudo systemctl status augsburg-user-bot
sudo systemctl status augsburg-admin-bot
```

---

## 📊 Мониторинг и логи

### Просмотр логов

**User Bot:**
```bash
sudo journalctl -u augsburg-user-bot -f
```

**Admin Bot:**
```bash
sudo journalctl -u augsburg-admin-bot -f
```

### Проверка статуса

```bash
sudo systemctl status augsburg-user-bot
sudo systemctl status augsburg-admin-bot
```

### Перезапуск сервисов

```bash
sudo systemctl restart augsburg-user-bot
sudo systemctl restart augsburg-admin-bot
```

### Остановка сервисов

```bash
sudo systemctl stop augsburg-user-bot
sudo systemctl stop augsburg-admin-bot
```

---

## 🔄 Обновление бота

### 1. Остановка сервисов

```bash
sudo systemctl stop augsburg-user-bot
sudo systemctl stop augsburg-admin-bot
```

### 2. Резервное копирование БД

```bash
cd ~/augsburg-liquid
cp augsburg_liquid.db augsburg_liquid.db.backup-$(date +%Y%m%d)
```

### 3. Обновление кода

```bash
# Скопируйте новые файлы
# Или используйте git pull, если проект в репозитории
```

### 4. Обновление зависимостей

```bash
source venv/bin/activate
pip install -r requirements.txt --upgrade
```

### 5. Запуск сервисов

```bash
sudo systemctl start augsburg-user-bot
sudo systemctl start augsburg-admin-bot
```

### 6. Проверка

```bash
sudo systemctl status augsburg-user-bot
sudo systemctl status augsburg-admin-bot
```

---

## 💾 Резервное копирование

### Создание backup скрипта

```bash
nano ~/backup-bot.sh
```

Содержимое:
```bash
#!/bin/bash

BACKUP_DIR="/home/botuser/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup базы данных
cp /home/botuser/augsburg-liquid/augsburg_liquid.db \
   $BACKUP_DIR/db_$DATE.db

# Backup .env (опционально)
cp /home/botuser/augsburg-liquid/.env \
   $BACKUP_DIR/env_$DATE.bak

echo "Backup completed: $DATE"

# Удаление старых backup (старше 30 дней)
find $BACKUP_DIR -type f -mtime +30 -delete
```

Сделайте скрипт исполняемым:
```bash
chmod +x ~/backup-bot.sh
```

### Автоматический backup (cron)

```bash
crontab -e
```

Добавьте строку (backup каждый день в 3:00 AM):
```
0 3 * * * /home/botuser/backup-bot.sh
```

---

## 🔒 Безопасность

### 1. Файрвол (UFW)

```bash
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
```

### 2. Права доступа к файлам

```bash
cd ~/augsburg-liquid
chmod 600 .env
chmod 600 augsburg_liquid.db
```

### 3. Fail2Ban (опционально)

```bash
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

---

## 🌐 Использование PostgreSQL (опционально)

### 1. Установка PostgreSQL

```bash
sudo apt install postgresql postgresql-contrib -y
```

### 2. Создание базы данных

```bash
sudo -u postgres psql

CREATE DATABASE augsburg_liquid;
CREATE USER botuser WITH PASSWORD 'ваш_пароль';
GRANT ALL PRIVILEGES ON DATABASE augsburg_liquid TO botuser;
\q
```

### 3. Установка драйвера

```bash
source venv/bin/activate
pip install asyncpg
```

### 4. Обновление .env

```
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://botuser:ваш_пароль@localhost/augsburg_liquid
```

### 5. Модификация database.py

Нужно будет адаптировать код для работы с PostgreSQL через asyncpg.

---

## 📈 Мониторинг производительности

### 1. Установка htop

```bash
sudo apt install htop -y
htop
```

### 2. Мониторинг процессов Python

```bash
ps aux | grep python
```

### 3. Использование диска

```bash
df -h
du -sh ~/augsburg-liquid/*
```

---

## 🚨 Troubleshooting

### Боты не запускаются

**Проверьте логи:**
```bash
sudo journalctl -u augsburg-user-bot -n 50
sudo journalctl -u augsburg-admin-bot -n 50
```

**Проверьте токены:**
```bash
cat .env
```

### База данных заблокирована

```bash
# Проверьте, нет ли других процессов
lsof augsburg_liquid.db

# Если есть - убейте их
kill -9 PID
```

### Недостаточно памяти

```bash
# Добавьте swap
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## ✅ Чеклист деплоя

- [ ] Сервер настроен и обновлен
- [ ] Python 3.8+ установлен
- [ ] Проект скопирован на сервер
- [ ] Виртуальное окружение создано
- [ ] Зависимости установлены
- [ ] .env настроен с правильными токенами
- [ ] База данных инициализирована
- [ ] Systemd сервисы созданы и запущены
- [ ] Логи проверены, ошибок нет
- [ ] Боты отвечают в Telegram
- [ ] Резервное копирование настроено
- [ ] Безопасность настроена

---

**Ваши боты готовы к работе 24/7!** 🎉
