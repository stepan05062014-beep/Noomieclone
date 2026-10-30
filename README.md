# Noomieclone

Мод NoomiClone (Android, Unity) — замена графики + инструменты для этого.

## Что скачивать

| Файл | Что это |
|---|---|
| **`NoomiClone-modded.apk`** | Готовый APK: закатное небо, песчаный пол, аметистовая монетка. **Подписан** (схема v2, RSA-2048/SHA-256) — Android 7+ примет установку. 38 МБ |
| `archive (8).zip` | Исходная сборка (внутри `NoomiClone.apk`), как её загрузили |
| `modding/` | Скрипты: разбор APK, выгрузка/замена текстур, замена иконки, **подпись APK на чистом Python**, сборка установочного комплекта из XAPK |

Скачать APK: откройте файл в списке выше → кнопка **Download** (или
[прямая ссылка](https://raw.githubusercontent.com/stepan05062014-beep/Noomieclone/main/NoomiClone-modded.apk)).

## Что изменено в моде

| Текстура | Было → стало |
|---|---|
| `Sunny Days - Seamless` (512×256) | голубое небо → оранжевый закат |
| `Floor Cement` (512×512) | серый цемент → тёплый песчаник |
| `NoomiCoin` (33×33) | жёлтая монетка → аметист |

Сравнение «до/после»: `modding/previews/before-after.png`.
Из 965 файлов внутри APK изменились ровно 3, `resources.arsc` побайтово тот же.

## Как установить

```bash
adb install NoomiClone-modded.apk          # если в APK есть lib/ (полный бандл)
```

⚠️ **В этой сборке нет нативной части** — `libil2cpp.so` и `libunity.so` вынесены
в отдельный ABI-сплит `split_config.arm64_v8a.apk`. Файл установится, но при
запуске упадёт, пока рядом нет сплита:

```bash
adb install-multiple NoomiClone-modded.apk split_config.arm64_v8a.apk
```

Ещё два нюанса: подпись не совпадает с оригиналом из Play (сначала удалите игру),
и внутри стоит защита PairIP, которая может блокировать переподписанные сборки.

## Есть XAPK (полный бандл)?

В этой сборке нет `lib/*.so` — их надо взять из XAPK/APKM и подписать **тем же
ключом**, что и base, иначе Android не даст установить комплект. Одна команда:

```bash
python modding/build_installable.py --xapk Game.xapk --out ready/ \
       --replacements modding/examples
# -> ready/base-signed.apk + ready/split_config.arm64_v8a-signed.apk
# -> adb install-multiple base-signed.apk split_config.arm64_v8a-signed.apk
```

Как передать большой файл в репозиторий (лимиты): веб-загрузка — 25 МБ,
`git push` — 100 МБ на файл, Release — 2 ГБ. 83-мегабайтный XAPK проходит
обычным `git push`; сжимать его дополнительно бессмысленно.

## Инструменты

```bash
pip install UnityPy pillow cryptography
python modding/noomi_visual.py list    --apk NoomiClone.apk      # 123 текстуры внутри
python modding/noomi_visual.py extract --apk NoomiClone.apk --out png/
python modding/noomi_visual.py apply   --apk NoomiClone.apk \
        --replacements modding/examples --out NoomiClone-modded.apk
python modding/noomi_visual.py icon    --apk NoomiClone.apk --icon my_icon.png --out icon.apk
python modding/noomi_visual.py verify  --apk NoomiClone-modded.apk
```

Подробности, ограничения и список всех текстур — в [`modding/README.md`](modding/README.md).
