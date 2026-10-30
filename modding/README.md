# NoomiClone — визуальный моддинг APK

Инструмент и заметки по замене **графики** в `NoomiClone.apk` (Unity **6000.3.9f1**,
IL2CPP, пакет `com.JamesWest.NoomiClone`, версия 2.4.3.1) — без Unity Editor и без
исходников проекта.

> **Готовый файл уже собран:** `NoomiClone-modded.apk` лежит в корне репозитория
> (рядом с `archive (8).zip`). В нём три замены из `examples/`.
> Что именно поменялось — видно на картинке `modding/previews/before-after.png`.

```
NoomiClone-modded.apk        # собранный APK (38 МБ, с заменами из examples/)

modding/
├── noomi_visual.py          # сам инструмент (list / extract / apply / icon)
├── noomi-textures.json      # инвентаризация всех 123 текстур внутри APK
├── examples/                # набор замен, который вшит в собранный APK
│   ├── Sunny Days - Seamless.png   # небо -> закат
│   ├── Floor Cement.png            # цементный пол -> песчаник
│   └── NoomiCoin.png               # монетка -> аметист
├── previews/
│   └── before-after.png     # сравнение «до / после»
└── README.md
```

Пересобрать такой же файл с нуля:

```bash
unzip "archive (8).zip"                      # достаёт NoomiClone.apk
pip install UnityPy pillow
python modding/noomi_visual.py apply --apk NoomiClone.apk \
       --replacements modding/examples --out NoomiClone-modded.apk
```

## Установка

```bash
pip install UnityPy pillow        # numpy нужен только если правите картинки скриптом
```

## Быстрый старт

```bash
# 1) что вообще есть внутри
python noomi_visual.py list --apk NoomiClone.apk
python noomi_visual.py list --apk NoomiClone.apk --search coin   # поиск по имени

# 2) выгрузить все текстуры в PNG (106 файлов, ~2 сек)
python noomi_visual.py extract --apk NoomiClone.apk --out png/

# 3) нарисовать свои версии и собрать APK
#    имя PNG в папке должно совпадать с именем текстуры ("Floor Cement.png")
python noomi_visual.py apply --apk NoomiClone.apk \
        --replacements examples/ --out NoomiClone-modded.apk

# 4) заменить иконку приложения (все плотности + adaptive icon)
python noomi_visual.py icon --apk NoomiClone.apk \
        --icon my_icon.png --out NoomiClone-icon.apk
```

`apply` сам подгоняет размер картинки под оригинальную текстуру (`--no-resize`,
чтобы отключить) и пересжимает её в тот же формат (ETC1/ETC2/ASTC/RGBA32…),
поэтому ничего не «плывёт» по памяти и не ломает атласы.

## Что уже проверено на этом APK

* `list` — 123 текстуры, 191 файл ассетов, ~1.7 с.
* `extract` — 106 PNG (шрифтовые SDF-атласы намеренно пропускаются).
* `apply` — на примерах из `examples/`: изменились ровно **3** элемента zip из 965,
  `resources.arsc` и все остальные файлы побайтово те же, zip валиден,
  пиксели после пересборки перечитаны и совпадают с нарисованными.
* `icon` — заменяются 24 PNG (6 плотностей × app_icon / app_icon_round /
  ic_launcher_foreground / ic_launcher_background).

## Самые полезные текстуры

| Имя в APK | Что это | Размер |
|---|---|---|
| `Sunny Days - Seamless` | фон-небо (облака + трава) | 512×256 |
| `Floor Cement` | текстура пола/земли | 512×512 |
| `Brushed Metal 3` | металл перекладин | 512×256 |
| `Fruit Jelly (B&W)` | шумовая текстура объектов | 512×512 |
| `NoomiCoin` | иконка монеты | 33×33 |
| `Gradient Diagonal (Color)` | градиент слайдеров (16×16) | 16×16 |
| `Default Sprites` | эмодзи-спрайты + лого Unity | 512×512 |
| `sc`, `ru`, `en`… (в `sharedassets1.assets`) | флаги языков | 160×107 |
| `icon_close`, `icon_menu`, `icon_arrow` | иконки UI | 128×128 |
| `Lock`, `GooglePay`, `ApplePay`, скины соцсетей | магазин/шаринг | до 1024 |

**Скины Noomi (цвета тела, земли, объектов, шапки/кепки/кеды) в текстурах
отсутствуют** — они задаются цветом материала в сценах или кодом, а сами
префабы лежат в Addressables-бандлах (`assets/aa/Android/*.bundle`), которые
в этой сборке не отдаются как обычные ассеты. Если понадобится — это отдельная
задача (распаковка бандлов + правка `Material.m_Colors`).

## Ограничения (важно)

1. **Подпись.** Zip-структуру инструмент сохраняет, но подпись APK становится
   недействительной. Перед установкой подпишите заново:
   `apksigner sign --ks my.keystore NoomiClone-modded.apk` или uber-apk-signer.
2. **Нет нативной части.** В этом APK отсутствует `lib/` — `libil2cpp.so` и
   `libunity.so` вынесены в ABI-сплит (`split_config.arm64_v8a.apk`,
   в манифесте видно `base__abi`). Пересобранный base-APK сам по себе не
   запустится: нужен тот же сплит, а ставить — комплектом:
   `adb install-multiple base.apk split_config.arm64_v8a.apk`.
3. **PairIP.** В APK встроена защита PairIP (лицензионная проверка / Play
   Integrity). Переподписанный мод может отказаться запускаться — это не
   следствие правок графики.
4. **Что менять нельзя.** Логика (физика, твист, цены, начисление монет,
   разблокировка) — нативный IL2CPP-код, `global-metadata.dat` зашифрован.
   Серверные вещи (коды карт Map Maker, облачный сейв, IAP) — на сервере.
5. Игра — коммерческий проект JamesWest. Правки «для себя» ок; публиковать
   моды с их ассетами/вырезанной рекламой — нет.

## Что дальше можно добавить в инструмент

* рекурсивная замена по маске (`--map old.png=new.png`);
* батч-перекраска (hue/saturation) прямо в скрипте без Photoshop;
* распаковка Addressables-бандлов (`assets/aa/Android/*`) для скинов и префабов;
* автоподпись через `apksigner`, если он есть в системе.
