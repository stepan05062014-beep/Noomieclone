#!/usr/bin/env python3
"""
build_installable.py — собрать комплект для установки из XAPK.

XAPK/APKM — это обычный zip, внутри которого base APK и ABI/density-сплиты.
Проблема, которую решает скрипт: Android требует, чтобы base и все сплиты были
подписаны ОДНИМ сертификатом, иначе установка падает. Поэтому здесь:

  1. распаковывается XAPK и находятся base + сплиты;
  2. в base подставляются картинки (если передан --replacements);
  3. ВСЕ apk подписываются одним ключом (схема v2);
  4. выводится готовая команда установки и список файлов.

Примеры:
    python build_installable.py --xapk game.xapk --out ready/
    python build_installable.py --xapk game.xapk --out ready/ \\
           --replacements ../examples

    # если XAPK уже разархивирован в папку
    python build_installable.py --dir unpacked/ --out ready/
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import apksign
except ImportError:  # pragma: no cover
    sys.exit("Нет модуля apksign.py рядом со скриптом")

import noomi_visual as nv


SPLIT_HINTS = ("split_config", "config.arm64", "config.armeabi", "config.xxhdpi",
               "config.ru", "split_", ".config.")


def is_split(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in SPLIT_HINTS)


def pick_apks(files: list[str]) -> tuple[str, list[str]]:
    """Возвращает (base, [splits]) по именам файлов."""
    apks = [f for f in files if f.lower().endswith(".apk")]
    if not apks:
        raise SystemExit("в входных данных нет ни одного .apk")
    splits = [f for f in apks if is_split(os.path.basename(f))]
    bases = [f for f in apks if f not in splits]
    if not bases:
        raise SystemExit("не нашёл base APK — только сплиты")
    base = max(bases, key=lambda f: os.path.getsize(f))
    if len(bases) > 1:
        others = [os.path.basename(b) for b in bases if b != base]
        print(f"  ! несколько кандидатов в base, беру самый крупный; "
              f"остальные считаю сплитами: {others}")
        splits += others
    return base, splits


def unpack_input(xapk: str | None, folder: str | None, tmp: str) -> str:
    if folder:
        return folder
    work = os.path.join(tmp, "xapk")
    os.makedirs(work, exist_ok=True)
    print(f"распаковываю {xapk} ...")
    with zipfile.ZipFile(xapk) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = os.path.join(work, os.path.basename(info.filename))
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return work


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Собрать установочный комплект из XAPK")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--xapk", help="путь к .xapk/.apkm (это zip)")
    src.add_argument("--dir", help="уже распакованная папка с apk/сплитами")
    p.add_argument("--out", required=True, help="куда сложить результат")
    p.add_argument("--replacements", help="папка с PNG для замены текстур в base")
    p.add_argument("--no-resize", action="store_true")
    p.add_argument("--key", default=os.path.join(nv.KEY_DIR, "debug-key.pem"))
    p.add_argument("--cert", default=os.path.join(nv.KEY_DIR, "debug-cert.pem"))
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    key, cert, created = apksign.load_key_and_cert(
        args.key, args.cert, create_missing_to=args.key)
    if created:
        print(f"создан новый ключ: {args.key}")

    with tempfile.TemporaryDirectory() as tmp:
        work = unpack_input(args.xapk, args.dir, tmp)
        files = [os.path.join(work, f) for f in os.listdir(work)]
        base, splits = pick_apks(files)
        print(f"base: {os.path.basename(base)} "
              f"({os.path.getsize(base) / 1e6:.1f} МБ)")
        print(f"сплитов: {len(splits)}")
        for s in splits:
            print(f"   {os.path.basename(s)} ({os.path.getsize(s) / 1e6:.1f} МБ)")

        # 1) патчим текстуры в base
        patched_base = os.path.join(tmp, "base-patched.apk")
        if args.replacements:
            reps = nv.load_replacements(args.replacements)
            print(f"\nзамен текстур: {len(reps)}")
            report = nv.patch_apk(base, patched_base, reps,
                                  allow_resize=not args.no_resize, verbose=False)
            print(f"  заменено: {len(report.replaced)}")
            for k, why in report.skipped:
                print(f"  пропущено: {k} — {why}")
            if not report.replaced:
                shutil.copyfile(base, patched_base)
        else:
            shutil.copyfile(base, patched_base)

        # 2) подписываем всё одним ключом
        print("\nподписываю (v2, один ключ на base и сплиты):")
        results = []
        for src_apk, prefix in [(patched_base, "base")] + \
                               [(s, os.path.splitext(os.path.basename(s))[0])
                                for s in splits]:
            out_name = f"{prefix}-signed.apk" if prefix == "base" \
                else f"{prefix}-signed.apk"
            out_path = os.path.join(args.out, out_name)
            info = apksign.sign_apk(src_apk, out_path, key, cert)
            res = apksign.verify_apk(out_path)
            results.append(out_path)
            print(f"  + {out_name:42} {os.path.getsize(out_path) / 1e6:6.1f} МБ  "
                  f"v2 ok")

    names = " ".join(os.path.basename(r) for r in results)
    print(f"\nготово: {args.out}")
    print("  файлы:")
    for r in results:
        print(f"    {r}")
    print("\nустановка (все файлы сразу, иначе Android откажет):")
    print(f"    adb install-multiple {names}")
    print("\nбез ПК: перекинь файлы на телефон и поставь через SAI (Split APKs "
          "Installer) или MT Manager -> Install multiple")
    print("\nвсе файлы подписаны одним ключом, поэтому подпись совместима между "
          "ними, но НЕ совпадает с оригиналом из Play — старую игру удалить.")


if __name__ == "__main__":
    main()
