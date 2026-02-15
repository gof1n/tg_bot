#!/usr/bin/env python3
"""
Проверка ссылки на таблицу и доступности фото.
Запуск: python3 check_table.py
Читает CSV_URL из .env, скачивает CSV, выводит колонки и пробует открыть первую ссылку на фото.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

CSV_URL = os.getenv("CSV_URL", "").strip()
if not CSV_URL:
    print("В .env не задан CSV_URL.")
    sys.exit(1)

def main():
    import pandas as pd
    import urllib.request

    print("Таблица (CSV_URL):", CSV_URL[:80] + "..." if len(CSV_URL) > 80 else CSV_URL)
    try:
        req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        print("Ошибка при открытии таблицы:", e)
        sys.exit(1)

    try:
        from io import BytesIO
        df = pd.read_csv(BytesIO(raw), header=1, encoding="utf-8")
    except Exception as e:
        print("Ошибка при разборе CSV:", e)
        sys.exit(1)

    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    print("Колонки:", list(df.columns))
    # Ищем колонку с фото
    photo_col = None
    for c in df.columns:
        n = c.strip().lower()
        if "фото" in n or "photo" in n or "image" in n or "ссылка" in n and "фото" in str(c).lower():
            if "фото" in n or "photo" in n or "image" in n:
                photo_col = c
                break
    if not photo_col:
        for c in df.columns:
            if "ссылка" in c.lower():
                photo_col = c
                break
    if not photo_col:
        print("Колонка со ссылкой на фото не найдена.")
        return
    print("Колонка для фото:", photo_col)
    urls = df[photo_col].dropna().astype(str).str.strip()
    urls = [u.strip('"\'') for u in urls if u.startswith("http")]
    if not urls:
        print("В таблице нет ссылок на фото (http...) в колонке", photo_col)
        return
    sample = urls[0]
    print("Пример ссылки на фото:", sample[:100] + "..." if len(sample) > 100 else sample)
    try:
        req = urllib.request.Request(sample, headers={"User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            code = r.getcode()
            size = len(r.read())
        print("Проверка фото: HTTP", code, "размер", size, "байт — ссылка открывается.")
    except Exception as e:
        print("Проверка фото: не удалось открыть ссылку —", e)


if __name__ == "__main__":
    main()
