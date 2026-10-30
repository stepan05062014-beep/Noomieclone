# NoomiClone — визуальный моддинг APK

Инструмент и заметки по замене **графики** в `NoomiClone.apk` (Unity **6000.3.9f1**,
IL2CPP, пакет `com.JamesWest.NoomiClone`, версия 2.4.3.1) — без Unity Editor и без
исходников проекта.

> **Готовый файл уже собран и ПОДПИСАН:** `NoomiClone-modded.apk` лежит в корне
> репозитория (рядом с `archive (8).zip`). В нём три замены из `examples/`,
> подпись — схема **v2** (RSA-2048/SHA-256), Android 7+ её принимает.
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
├── apksign.py               # подпись APK схемой v2 на чистом Python
├── build_installable.py     # XAPK -> подписанный base + сплиты (install-multiple)
├── keys/
│   ├── debug-key.pem        # ключ, которым подписан готовый APK
│   ├── debug-cert.pem
│   ├── debug-key.p12        # тот же ключ для MT Manager / apksigner (alias: noomi)
│   └── README.md
└── README.md
```

Пересобрать такой же файл с нуля:

```bash
unzip "archive (8).zip"                      # достаёт NoomiClone.apk
pip install UnityPy pillow cryptography

# apply сам подпишет результат -> появится NoomiClone-modded-signed.apk
python modding/noomi_visual.py apply --apk NoomiClone.apk \
       --replacements modding/examples --out NoomiClone-modded.apk

python modding/noomi_visual.py verify --apk modding/NoomiClone-modded-signed.apk
python modding/noomi_visual.py install --apk modding/NoomiClone-modded-signed.apk
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

## Если есть XAPK: как собрать запускаемый комплект

Полный бандл игры (`.xapk`/`.apkm`) — это zip с base APK + ABI-сплитами, в одном
из которых лежат `libil2cpp.so` / `libunity.so`. Ставится он только комплектом,
и **все файлы должны быть подписаны одним сертификатом** — иначе Android ответит
`INSTALL_FAILED_INVALID_APK` (split signature mismatch).

```bash
python modding/build_installable.py --xapk Game.xapk --out ready/ \
       --replacements modding/examples
```

Скрипт: распаковывает XAPK → находит base и сплиты → подставляет текстуры в base
→ подписывает **всё одним ключом** (v2) → печатает готовую команду установки.

Проверено на синтетическом XAPK (base 38 МБ + сплит 3 МБ): на выходе
`base-signed.apk` и `split_config.arm64_v8a-signed.apk` с одинаковым отпечатком
сертификата `3b3538d7…`, подпись v2 у обоих проверяется.

Если XAPK уже распакован — `--dir unpacked/`.

### Передача большого файла в репозиторий

| Способ | Лимит | Комментарий |
|---|---|---|
| Веб-интерфейс GitHub (кнопка загрузки) | **25 МБ** | сюда 83 МБ не влезет |
| `git push` (обычный git) | 100 МБ на файл (предупреждение с 50 МБ) | наш APK на 38 МБ попал именно так |
| GitHub Release (ассет) | 2 ГБ | но у агента в песочнице нет доступа к uploads/objects.github.com |

То есть XAPK на 83 МБ **можно** запушить обычным git — «сильно сжимать» ничего
не нужно (и не поможет: внутри уже сжатые apk).

### Установка без ПК (телефон)

Если комплекс собран у вас, а не у меня — вариант через MT Manager:

1. `modding/keys/debug-key.p12` — ключ, которым подписан `NoomiClone-modded.apk`
   (alias `noomi`, пароль `noomi`). Импортируйте его в MT Manager:
   *Настройки → Подпись → выбрать keystore → `debug-key.p12`*.
2. Достаньте из XAPK `split_config.arm64_v8a.apk` и подпишите его этим ключом
   (долгое нажатие → Подписать, схема v2).
3. Ставьте оба файла сразу: MT Manager → *Install multiple* (или SAI).

Подпись сплита тем же ключом, что и base, — обязательна.

## Подпись — почему она нужна и как работает

Любая правка zip-содержимого убивает исходную подпись, и Android отвечает
`Установочный пакет не подписан сертификатом` (INSTALL_PARSE_FAILED_NO_CERTIFICATES).
`apksign.py` подписывает файл **схемой APK Signature Scheme v2** на чистом Python:

* APK Signing Block (ID `0x7109871a`), алгоритм `0x0103` — RSA PKCS#1 v1.5 + SHA-256;
* content digest считается по трём секциям (данные, Central Directory, EOCD)
  блоками по 1 МиБ — точно как в спецификации;
* ключ и самоподписанный сертификат генерируются автоматически
  (`cryptography`), хранятся в `modding/keys/` и переиспользуются, чтобы
  обновления мода ставились поверх предыдущей версии;
* `verify` пересчитывает digest и проверяет подпись — ловит порчу файла.

Проверено независимо: androguard видит `is_signed_v2: True` и
`is_signed: True`; записи сертификата совпадают с нашими.

```bash
python noomi_visual.py sign   --apk in.apk --out out.apk     # подписать
python noomi_visual.py verify --apk out.apk                  # проверить
```

## Ограничения (важно)

1. **Нет нативной части.** В этом APK отсутствует `lib/` — `libil2cpp.so` и
   `libunity.so` вынесены в ABI-сплит (`split_config.arm64_v8a.apk`,
   в манифесте `requiredSplitTypes` / `base__abi`). Подписанный файл
   **установится**, но при запуске упадёт без сплита. Ставить комплектом:

   ```bash
   adb install-multiple base.apk split_config.arm64_v8a.apk
   ```
2. **Подпись не совпадает с оригиналом.** Мод нельзя поставить поверх игры из
   Play/APKPure — сначала удалите её (или подпишите мод тем же ключом, что и
   оригинал, чего у нас нет).
3. **PairIP.** В APK встроена защита PairIP (лицензионная проверка / Play
   Integrity). Переподписанный мод может отказаться запускаться — это не
   следствие правок графики.
4. **Что менять нельзя.** Логика (физика, твист, цены, начисление монет,
   разблокировка) — нативный IL2CPP-код, `global-metadata.dat` зашифрован.
   Серверные вещи (коды карт Map Maker, облачный сейв, IAP) — на сервере.
5. Подпись только v2, без v1/v3. Для `minSdk 26` этого достаточно; для
   устройств древнее Android 7 понадобился бы v1 (JAR signing).

## Что дальше можно добавить в инструмент

* рекурсивная замена по маске (`--map old.png=new.png`);
* батч-перекраска (hue/saturation) прямо в скрипте без Photoshop;
* распаковка Addressables-бандлов (`assets/aa/Android/*`) для скинов и префабов;
* v3/v4 подпись и `source stamp` (сейчас только v2);
* проверка совместимости с ABI-сплитом, когда он появится.
