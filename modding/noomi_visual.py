#!/usr/bin/env python3
"""
NoomiClone visual patcher
=========================

Меняет графику внутри APK NoomiClone (Unity 6000.3.9f1, IL2CPP) без Unity Editor:
  * текстуры из assets/bin/Data/* (скины, фоны, земля, иконки, флаги, монетка)
  * иконку приложения из res/mipmap-* (app_icon / adaptive icon)

Игровая логика (физика, цены, монеты) в нативном IL2CPP-коде и НЕ трогается.

Примеры:
    # 1. посмотреть, что вообще есть внутри
    python noomi_visual.py list --apk NoomiClone.apk

    # 2. выгрузить все текстуры в PNG (для правки в Photoshop/Krita/GIMP)
    python noomi_visual.py extract --apk NoomiClone.apk --out png/

    # 3. собрать APK с заменами: имена PNG в папке должны совпадать с именами текстур
    python noomi_visual.py apply --apk NoomiClone.apk --replacements presets/ \
                                 --out NoomiClone-modded.apk

    # 4. отдельно заменить иконку приложения
    python noomi_visual.py icon --apk NoomiClone.apk --icon my_icon.png \
                                --out NoomiClone-icon.apk

Требуется: pip install UnityPy pillow
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field

try:
    import UnityPy
except ImportError:  # pragma: no cover
    sys.exit("Нужен UnityPy: pip install UnityPy pillow")

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Нужен Pillow: pip install pillow")


# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------

# Внутри APK нас интересуют только эти области.
BLOB_PREFIXES = ("assets/bin/Data/", "assets/aa/Android/")
ICON_RE = re.compile(r"^res/mipmap-[^/]+/(app_icon|app_icon_round|"
                     r"ic_launcher_foreground|ic_launcher_background)\.png$")
SKIP_EXT = (".resource", ".json", ".config", ".txt", ".hash", ".xml", ".bin")

# Текстуры шрифтов (SDF-атласы) лежат в .resource-стриме и не декодируются
# как обычные картинки — их специально пропускаем, иначе шрифты «поедут».
FONT_TEXTURE_HINTS = (" SDF Atlas", "Font Texture")


@dataclass
class TexEntry:
    """Одна текстура внутри APK."""
    name: str
    width: int
    height: int
    fmt: str
    container: str          # путь внутри APK (zip-элемент)
    path_id: int
    index: int              # порядковый номер среди одноимённых (0,1,2...)
    streamed: bool = False  # данные в .resource

    @property
    def key(self) -> str:
        """Уникальный читаемый ключ: имя, а при дублях — имя#N."""
        return f"{self.name}#{self.index}" if self.index else self.name

    def as_dict(self) -> dict:
        return {
            "name": self.name, "key": self.key, "width": self.width,
            "height": self.height, "format": self.fmt,
            "container": self.container, "path_id": self.path_id,
            "streamed": self.streamed,
        }


@dataclass
class PatchReport:
    replaced: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    containers_written: list = field(default_factory=list)


# ----------------------------------------------------------------------------
# Работа с APK как zip
# ----------------------------------------------------------------------------

def is_blob(name: str) -> bool:
    return name.startswith(BLOB_PREFIXES) and not name.endswith(SKIP_EXT)


def read_blob(apk_path: str, member: str) -> bytes:
    with zipfile.ZipFile(apk_path) as z:
        return z.read(member)


def iter_blobs(apk_path: str):
    with zipfile.ZipFile(apk_path) as z:
        for info in z.infolist():
            if is_blob(info.filename):
                yield info.filename


def rewrite_zip(apk_path: str, out_path: str, replacements: dict[str, bytes]) -> None:
    """Копирует APK, подменяя/добавляя только указанные элементы.

    Остальные элементы переносятся как есть (с тем же именем и способом сжатия),
    поэтому resources.arsc и прочие «неприкасаемые» данные остаются валидными.
    """
    with zipfile.ZipFile(apk_path) as zin, \
            zipfile.ZipFile(out_path, "w", allowZip64=True) as zout:
        written = set()
        for info in zin.infolist():
            if info.filename in replacements:
                zout.writestr(info, replacements[info.filename],
                              compress_type=zipfile.ZIP_DEFLATED)
                written.add(info.filename)
            else:
                zout.writestr(info, zin.read(info.filename),
                              compress_type=info.compress_type)
        for name, data in replacements.items():
            if name not in written:  # новый файл, которого раньше не было
                zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


# ----------------------------------------------------------------------------
# Инвентаризация текстур
# ----------------------------------------------------------------------------

def scan_textures(apk_path: str, verbose: bool = False) -> list[TexEntry]:
    entries: list[TexEntry] = []
    seen: dict[str, int] = {}
    containers = list(iter_blobs(apk_path))
    if verbose:
        print(f"  просматриваю {len(containers)} файлов ассетов...", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        for member in containers:
            data = read_blob(apk_path, member)
            path = os.path.join(tmp, "_blob")
            with open(path, "wb") as f:
                f.write(data)
            try:
                env = UnityPy.load(path)
            except Exception:
                continue
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    tex = obj.read()
                except Exception:
                    continue
                name = getattr(tex, "m_Name", "") or ""
                if not name:
                    continue
                streamed = bool(getattr(tex, "m_StreamData", None)
                                and getattr(tex.m_StreamData, "path", ""))
                idx = seen.get(name, 0)
                seen[name] = idx + 1
                entries.append(TexEntry(
                    name=name,
                    width=int(getattr(tex, "m_Width", 0) or 0),
                    height=int(getattr(tex, "m_Height", 0) or 0),
                    fmt=_fmt_name(tex),
                    container=member,
                    path_id=obj.path_id,
                    index=idx,
                    streamed=streamed,
                ))
    return entries


def _fmt_name(tex) -> str:
    try:
        from UnityPy.enums import TextureFormat
        return TextureFormat(tex.m_TextureFormat).name
    except Exception:
        return str(getattr(tex, "m_TextureFormat", "?"))


def is_font_texture(name: str) -> bool:
    return any(h in name for h in FONT_TEXTURE_HINTS)


# ----------------------------------------------------------------------------
# Правка текстур
# ----------------------------------------------------------------------------

def _match_key(name: str, index: int) -> tuple[str, str]:
    """Возвращает (key, key) — полный ключ и короткий."""
    return (f"{name}#{index}" if index else name), name


def load_replacements(folder: str) -> dict[str, Image.Image]:
    """Читает PNG/JPEG из папки: имя файла = имя текстуры (можно с #N)."""
    out: dict[str, Image.Image] = {}
    if not os.path.isdir(folder):
        sys.exit(f"Нет такой папки: {folder}")
    for fname in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(fname)
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        out[stem] = Image.open(os.path.join(folder, fname))
    return out


def patch_apk(apk_path: str, out_path: str,
              replacements: dict[str, Image.Image],
              allow_resize: bool = True,
              verbose: bool = True) -> PatchReport:
    """Подставляет картинки в APK по именам текстур."""
    report = PatchReport()
    if not replacements:
        report.skipped.append(("—", "папка замен пустая"))
        shutil.copyfile(apk_path, out_path)
        return report

    with tempfile.TemporaryDirectory() as tmp:
        new_members: dict[str, bytes] = {}
        used: set[str] = set()

        for member in iter_blobs(apk_path):
            blob_path = os.path.join(tmp, "_blob")
            with open(blob_path, "wb") as f:
                f.write(read_blob(apk_path, member))
            env = UnityPy.load(blob_path)

            changed = False
            seen: dict[str, int] = {}
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    tex = obj.read()
                except Exception:
                    continue
                name = getattr(tex, "m_Name", "") or ""
                idx = seen.get(name, 0)
                seen[name] = idx + 1
                key, short = _match_key(name, idx)

                img = replacements.get(key) or (replacements.get(short) if name else None)
                if img is None:
                    continue
                if short in used or key in used:
                    continue
                if is_font_texture(name):
                    report.skipped.append((key, "SDF-атлас шрифта — не трогаем"))
                    continue
                w, h = int(tex.m_Width), int(tex.m_Height)
                if w <= 0 or h <= 0:
                    report.skipped.append((key, "текстура без пиксельных данных"))
                    continue

                src = img.convert("RGBA")
                if src.size != (w, h):
                    if not allow_resize:
                        report.skipped.append((key, f"нужен размер {w}x{h}, "
                                                    f"а картинка {src.size[0]}x{src.size[1]}"))
                        continue
                    src = src.resize((w, h), Image.LANCZOS)

                try:
                    tex.set_image(src, target_format=tex.m_TextureFormat)
                    tex.save()
                    changed = True
                    used.add(key)
                    used.add(short)
                    report.replaced.append((key, f"{w}x{h}", member))
                    if verbose:
                        print(f"  + {key}  {w}x{h}  -> {member}")
                except Exception as exc:
                    report.skipped.append((key, f"ошибка записи: {exc}"))

            if changed:
                out_dir = os.path.join(tmp, "out")
                os.makedirs(out_dir, exist_ok=True)
                env.save(out_path=out_dir)
                produced = os.listdir(out_dir)
                if not produced:
                    report.skipped.append((member, "UnityPy ничего не сохранил"))
                    continue
                with open(os.path.join(out_dir, produced[0]), "rb") as f:
                    new_members[member] = f.read()
                report.containers_written.append(member)

        for key in replacements:
            if key not in used:
                report.skipped.append((key, "такой текстуры в APK нет"))

        rewrite_zip(apk_path, out_path, new_members)
    return report


# ----------------------------------------------------------------------------
# Иконка приложения (res/mipmap-*)
# ----------------------------------------------------------------------------

def _round_icon(img: Image.Image, size: int) -> Image.Image:
    from PIL import ImageDraw
    big = img.convert("RGBA").resize((size * 4, size * 4), Image.LANCZOS)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big.size[0] - 1, big.size[1] - 1), fill=255)
    big.putalpha(mask)
    return big.resize((size, size), Image.LANCZOS)


def patch_icons(apk_path: str, out_path: str, icon_path: str,
                verbose: bool = True) -> PatchReport:
    """Меняет иконку приложения во всех плотностях."""
    report = PatchReport()
    src = Image.open(icon_path).convert("RGBA")
    with zipfile.ZipFile(apk_path) as z:
        members = [i.filename for i in z.infolist() if ICON_RE.match(i.filename)]
    if not members:
        report.skipped.append(("icon", "в APK нет res/mipmap-*/app_icon.png"))
        shutil.copyfile(apk_path, out_path)
        return report

    new_members: dict[str, bytes] = {}
    for member in members:
        kind = ICON_RE.match(member).group(1)
        with zipfile.ZipFile(apk_path) as z:
            size = Image.open(_biowrapper(z.read(member))).size[0]
        if kind == "app_icon":
            img = src.resize((size, size), Image.LANCZOS)
        elif kind == "app_icon_round":
            img = _round_icon(src, size)
        elif kind == "ic_launcher_foreground":
            # адаптивная иконка: картинка занимает ~62% и центр безопасной зоны
            inner = max(1, int(size * 0.62))
            small = src.resize((inner, inner), Image.LANCZOS)
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            img.paste(small, ((size - inner) // 2, (size - inner) // 2), small)
        else:  # ic_launcher_background — средний цвет картинки
            px = src.convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))
            img = Image.new("RGBA", (size, size), px + (255,))
        buf = tempfile.SpooledTemporaryFile()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        new_members[member] = buf.read()
        report.replaced.append((kind, f"{size}x{size}", member))
        if verbose:
            print(f"  + иконка {kind:<22} {size}x{size}  -> {member}")

    rewrite_zip(apk_path, out_path, new_members)
    report.containers_written.extend(new_members)
    return report


def _biowrapper(data: bytes):
    import io
    return io.BytesIO(data)


# ----------------------------------------------------------------------------
# Команды CLI
# ----------------------------------------------------------------------------

def cmd_list(args) -> None:
    entries = scan_textures(args.apk, verbose=True)
    if not entries:
        sys.exit("Текстур не найдено — это точно APK NoomiClone?")

    if args.search:
        needle = args.search.lower()
        entries = [e for e in entries if needle in e.name.lower()]

    print(f"\n{'текстура':52} {'размер':>11}  {'формат':<12} контейнер")
    print("-" * 110)
    for e in sorted(entries, key=lambda x: (-x.width * x.height, x.name)):
        size = f"{e.width}x{e.height}" if e.width else "streamed"
        flag = "  [шрифт]" if is_font_texture(e.name) else ""
        print(f"{e.key[:52]:52} {size:>11}  {e.fmt:<12} {e.container}{flag}")
    print(f"\nвсего текстур: {len(entries)}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([e.as_dict() for e in entries], f, ensure_ascii=False, indent=2)
        print(f"список сохранён: {args.json}")


def cmd_extract(args) -> None:
    os.makedirs(args.out, exist_ok=True)
    entries = scan_textures(args.apk, verbose=True)
    by_container: dict[str, list[TexEntry]] = {}
    for e in entries:
        by_container.setdefault(e.container, []).append(e)

    done = 0
    with tempfile.TemporaryDirectory() as tmp:
        for member, group in by_container.items():
            path = os.path.join(tmp, "_blob")
            with open(path, "wb") as f:
                f.write(read_blob(args.apk, member))
            env = UnityPy.load(path)
            idx_by_name: dict[str, int] = {}
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    tex = obj.read()
                except Exception:
                    continue
                name = getattr(tex, "m_Name", "") or ""
                idx = idx_by_name.get(name, 0)
                idx_by_name[name] = idx + 1
                if is_font_texture(name):
                    continue
                entry = next((g for g in group
                              if g.path_id == obj.path_id), None)
                if entry is None:
                    continue
                try:
                    img = tex.image
                except Exception as exc:
                    print(f"  ! {name}: не декодируется ({exc})", file=sys.stderr)
                    continue
                safe = re.sub(r'[\\/:*?"<>|]', "_", entry.key)
                img.save(os.path.join(args.out, f"{safe}.png"))
                done += 1
    print(f"\nвыгружено PNG: {done} -> {args.out}")


def cmd_apply(args) -> None:
    replacements = load_replacements(args.replacements)
    print(f"Замен в папке: {len(replacements)} ({args.replacements})")
    print(f"Исходный APK: {args.apk}")
    report = patch_apk(args.apk, args.out, replacements,
                       allow_resize=not args.no_resize)

    print(f"\nготово: {args.out}")
    print(f"  заменено: {len(report.replaced)}")
    print(f"  перезаписано файлов ассетов: {len(report.containers_written)}")
    if report.skipped:
        print("  пропущено:")
        for key, why in report.skipped:
            print(f"    - {key}: {why}")
    print(_signature_notice(args.apk))


def cmd_icon(args) -> None:
    report = patch_icons(args.apk, args.out, args.icon)
    print(f"\nготово: {args.out}  (иконок заменено: {len(report.replaced)})")
    print(_signature_notice(args.apk))


def _signature_notice(apk_path: str) -> str:
    has_libs = any(n.startswith("lib/") and n.endswith(".so")
                   for n in zipfile.ZipFile(apk_path).namelist())
    lines = [
        "",
        "ВАЖНО:",
        "  * zip-структура APK сохранена, но подпись APK стала недействительной —",
        "    перед установкой подпишите файл заново (apksigner / uber-apk-signer),",
        "    иначе Android его не примет.",
    ]
    if not has_libs:
        lines += [
            "  * В этом APK нет lib/*.so (нативная часть Unity лежит в отдельном",
            "    ABI-сплите split_config.arm64_v8a.apk). Такой файл сам по себе не",
            "    запустится: патчить нужно пару base.apk + ABI-сплит и ставить их",
            "    вместе (adb install-multiple).",
        ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Замена графики в APK NoomiClone (Unity IL2CPP)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="список текстур внутри APK")
    pl.add_argument("--apk", required=True)
    pl.add_argument("--search", help="фильтр по имени, например --search skin")
    pl.add_argument("--json", help="сохранить список в JSON")
    pl.set_defaults(func=cmd_list)

    pe = sub.add_parser("extract", help="выгрузить текстуры в PNG")
    pe.add_argument("--apk", required=True)
    pe.add_argument("--out", default="png")
    pe.set_defaults(func=cmd_extract)

    pa = sub.add_parser("apply", help="собрать APK с заменами картинок")
    pa.add_argument("--apk", required=True)
    pa.add_argument("--replacements", required=True,
                    help="папка с PNG; имя файла = имя текстуры")
    pa.add_argument("--out", required=True)
    pa.add_argument("--no-resize", action="store_true",
                    help="не подгонять размер картинки под текстуру")
    pa.set_defaults(func=cmd_apply)

    pi = sub.add_parser("icon", help="заменить иконку приложения")
    pi.add_argument("--apk", required=True)
    pi.add_argument("--icon", required=True)
    pi.add_argument("--out", required=True)
    pi.set_defaults(func=cmd_icon)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not os.path.isfile(args.apk):
        sys.exit(f"Файл не найден: {args.apk}")
    args.func(args)


if __name__ == "__main__":
    main()
