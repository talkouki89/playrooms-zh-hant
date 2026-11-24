"""Playrooms zh-Hant patch library.

Unity 6000.6.3 / IL2CPP build of "Playrooms" (Two Pixels UG).

What it does, using only files the user already owns:

1. Text      - rewrites the English Unity Localization string tables with the
               Traditional Chinese translations shipped in translations/zh-Hant.
2. Locale    - renames the English Locale asset's display name to 繁體中文.
3. Fonts     - converts every TextMeshPro font asset used by the UI to
               `AtlasPopulationMode.DynamicOS` (Microsoft JhengHei), clears the
               baked Latin-only glyph table and grows the atlas to 2048x2048, so
               CJK glyphs are rasterised from the OS font at runtime.
4. Catalog   - Addressables validates the CRC of every bundle; the catalog entry
               of each modified bundle gets its CRC field zeroed (check disabled).

Every operation starts from a pristine copy kept in the backup folder, so the
tool can be re-run safely.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys

import UnityPy

# ---------------------------------------------------------------- constants ---

#: OS font family used to rasterise glyphs at runtime (installed on Windows 10/11)
FONT_FAMILY = "Microsoft JhengHei"

#: Side of the dynamic font atlas (glyphs are packed by TMP at runtime)
ATLAS_SIZE = 2048

#: Files that the patch rewrites inside the game installation.
MAIN_ASSETS = ["sharedassets0.assets", "sharedassets1.assets", "sharedassets2.assets"]
BUNDLES = [
    "60b09001b44efefa3164a8f50f577bba.bundle",
    "display_assets_all_9500504c06bb0e4669450fcae95a60e7.bundle",
    "effects_assets_all_048c40810eba486e61acc0ed86d140ee.bundle",
]
STRING_BUNDLE = "localization-string-tables-english(en)_assets_all.bundle"
LOCALE_BUNDLE = "localization-locales_assets_all.bundle"
CATALOG = "catalog.bin"

#: Files that are backed up before patching / restored afterwards.
PATCHED_FILES = MAIN_ASSETS + BUNDLES + [STRING_BUNDLE, LOCALE_BUNDLE, CATALOG]

#: TextMeshPro font assets inside the main asset files, keyed by their path id.
#: These ids are specific to the build the patch was made for; when they do not
#: match, the tool falls back to a full scan of every MonoBehaviour.
FONT_PIDS = {
    "sharedassets0.assets": [148],                 # VT323 SDF
    "sharedassets1.assets": [4068],                # RobotoCondensed-Regular SDF
    "sharedassets2.assets": [3635, 3637],          # RobotoCondensed-Bold SDF, Anton SDF
}

#: Table name -> file name (without the locale suffix) for the shipped tables.
TABLE_ORDER = ["General", "Items", "Skills", "Balli", "Mails", "Popups"]


class PatchError(RuntimeError):
    pass


# ------------------------------------------------------------------- helpers ---

def aa_dir(game_dir: str) -> str:
    return os.path.join(game_dir, "Playrooms_Data", "StreamingAssets", "aa", "StandaloneWindows64")


def data_dir(game_dir: str) -> str:
    return os.path.join(game_dir, "Playrooms_Data")


def catalog_path(game_dir: str) -> str:
    return os.path.join(game_dir, "Playrooms_Data", "StreamingAssets", "aa", CATALOG)


def read_tsv(path: str) -> dict[str, str]:
    table: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            if not line.strip():
                continue
            key, _, value = line.partition("\t")
            table[key.strip()] = value.rstrip("\r")
    return table


def load_translations(repo_dir: str) -> dict[str, dict[str, str]]:
    """table name (General_en, ...) -> {entry id: text}"""
    out: dict[str, dict[str, str]] = {}
    zh_dir = os.path.join(repo_dir, "translations", "zh-Hant")
    for table in TABLE_ORDER:
        for candidate in (f"{table}_en.tsv", f"{table}.tsv"):
            path = os.path.join(zh_dir, candidate)
            if os.path.exists(path):
                out[f"{table}_en"] = read_tsv(path)
                break
        else:
            raise PatchError(f"missing translation file for table {table} in {zh_dir}")
    return out


def load_font_nodes(repo_dir: str, game_dir: str) -> "UnityPy.classes.TypeTreeNode":
    """Type tree of TMP_FontAsset, borrowed from a bundle (main files ship none)."""
    for bundle in BUNDLES:
        path = os.path.join(aa_dir(game_dir), bundle)
        if not os.path.exists(path):
            continue
        env = UnityPy.load(path)
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if "m_AtlasPopulationMode" in tree:
                return obj.serialized_type.nodes
    raise PatchError("could not locate a TextMeshPro font asset to borrow a type tree from")


# -------------------------------------------------------------------- backup ---

def backup_dir(repo_dir: str, game_dir: str) -> str:
    tag = os.path.basename(os.path.normpath(game_dir))
    return os.path.join(repo_dir, ".backup", tag)


def ensure_backup(repo_dir: str, game_dir: str, *, force: bool = False) -> str:
    """Copy the untouched game files into the backup folder (once)."""
    dst = backup_dir(repo_dir, game_dir)
    os.makedirs(dst, exist_ok=True)
    copied = 0
    for name in PATCHED_FILES:
        target = os.path.join(dst, name)
        if os.path.exists(target) and not force:
            continue
        src = (os.path.join(data_dir(game_dir), name)
               if name in MAIN_ASSETS
               else os.path.join(aa_dir(game_dir), name)
               if name != CATALOG
               else catalog_path(game_dir))
        if not os.path.exists(src):
            raise PatchError(f"game file not found: {src}")
        shutil.copy2(src, target)
        copied += 1
    return dst


def restore_from_backup(repo_dir: str, game_dir: str) -> int:
    src_dir = backup_dir(repo_dir, game_dir)
    if not os.path.isdir(src_dir):
        raise PatchError(f"no backup available at {src_dir}")
    n = 0
    for name in PATCHED_FILES:
        src = os.path.join(src_dir, name)
        if not os.path.exists(src):
            continue
        dst = (os.path.join(data_dir(game_dir), name)
               if name in MAIN_ASSETS
               else os.path.join(aa_dir(game_dir), name)
               if name != CATALOG
               else catalog_path(game_dir))
        shutil.copy2(src, dst)
        n += 1
    return n


# --------------------------------------------------------------------- patch ---

def patch_font_asset(tree: dict) -> dict:
    bold = "Bold" in (tree.get("m_Name") or "")
    tree["m_AtlasPopulationMode"] = 2                                   # DynamicOS
    if "InternalDynamicOS" in tree:
        tree["InternalDynamicOS"] = True
    tree["m_IsMultiAtlasTexturesEnabled"] = True
    face = tree["m_FaceInfo"]
    face["m_FamilyName"] = FONT_FAMILY
    face["m_StyleName"] = "Bold" if bold else "Regular"
    tree["m_SourceFontFile"] = {"m_FileID": 0, "m_PathID": 0}
    tree["m_SourceFontFilePath"] = ""
    tree["m_SourceFontFileGUID"] = ""
    if isinstance(tree.get("m_CreationSettings"), dict):
        tree["m_CreationSettings"]["sourceFontFileName"] = ""
        tree["m_CreationSettings"]["sourceFontFileGUID"] = ""
    # drop the baked Latin-only glyphs: everything is rasterised at runtime
    tree["m_GlyphTable"] = []
    tree["m_CharacterTable"] = []
    tree["m_UsedGlyphRects"] = []
    tree["m_FreeGlyphRects"] = [{
        "m_X": 0, "m_Y": 0, "m_Width": ATLAS_SIZE, "m_Height": ATLAS_SIZE,
    }]
    tree["m_AtlasWidth"] = ATLAS_SIZE
    tree["m_AtlasHeight"] = ATLAS_SIZE
    tree["m_AtlasTextureIndex"] = 0
    return tree


def patch_atlas_textures(env, tree: dict) -> None:
    """Blank, readable ATLAS_SIZE² atlas + matching material UV scale."""
    textures = {o.path_id: o for o in env.objects if o.type.name == "Texture2D"}
    for ref in tree.get("m_AtlasTextures", []):
        tid = ref["m_PathID"]
        if ref["m_FileID"] != 0 or tid not in textures:
            continue
        tex = textures[tid]
        t = tex.read_typetree()
        key = "image data" if "image data" in t else "m_ImageData"
        t["m_Width"] = ATLAS_SIZE
        t["m_Height"] = ATLAS_SIZE
        t["m_CompleteImageSize"] = ATLAS_SIZE * ATLAS_SIZE
        t[key] = bytes(ATLAS_SIZE * ATLAS_SIZE)
        t["m_IsReadable"] = True
        t["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        tex.save_typetree(t)
        for obj in env.objects:
            if obj.type.name != "Material":
                continue
            mat = obj.read_typetree()
            props = mat.get("m_SavedProperties", {})
            uses = any(n == "_MainTex" and v["m_Texture"]["m_PathID"] == tid
                       for n, v in props.get("m_TexEnvs", []))
            if not uses:
                continue
            props["m_Floats"] = [
                (k, float(ATLAS_SIZE) if k in ("_TextureWidth", "_TextureHeight") else v)
                for k, v in props.get("m_Floats", [])
            ]
            mat["m_SavedProperties"] = props
            obj.save_typetree(mat)


def patch_fonts_in_file(path: str, *, is_bundle: bool, nodes, pids=None, log=print) -> list[str]:
    env = UnityPy.load(path)
    done: list[str] = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        if pids is not None and obj.path_id not in pids:
            continue
        try:
            tree = obj.read_typetree(nodes=nodes)
        except Exception:
            continue
        if "m_AtlasPopulationMode" not in tree:
            continue
        patch_font_asset(tree)
        obj.save_typetree(tree, nodes=nodes)
        patch_atlas_textures(env, tree)
        done.append(tree["m_Name"])
    if not done:
        return done
    data = env.file.save(packer="lz4") if is_bundle else env.file.save()
    with open(path, "wb") as fh:
        fh.write(data)
    return done


def patch_string_tables(game_dir: str, translations, log=print) -> int:
    src = os.path.join(aa_dir(game_dir), STRING_BUNDLE)
    env = UnityPy.load(src)
    total = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if "m_TableData" not in tree:
            continue
        table = translations.get(tree.get("m_Name"))
        if not table:
            continue
        for entry in tree["m_TableData"]:
            text = table.get(str(entry["m_Id"]))
            if text is None:
                continue
            entry["m_Localized"] = text.replace("\\n", "\n")
            total += 1
        obj.save_typetree(tree)
    with open(src, "wb") as fh:
        fh.write(env.file.save(packer="lz4"))
    return total


def rename_locale(game_dir: str, name: str = "繁體中文") -> bool:
    path = os.path.join(aa_dir(game_dir), LOCALE_BUNDLE)
    env = UnityPy.load(path)
    hit = False
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Identifier", {}).get("m_Code") != "en":
            continue
        tree["m_LocaleName"] = name
        tree["m_Name"] = "Chinese (Traditional) (en)"
        obj.save_typetree(tree)
        hit = True
    if hit:
        with open(path, "wb") as fh:
            fh.write(env.file.save(packer="lz4"))
    return hit


def _catalog_records(cat: bytes):
    """AssetBundleRequestOptions records: [hash][hashStr][crc][size]...[self][name]"""
    out = []
    for off in range(0, len(cat) - 60, 4):
        if struct.unpack_from("<I", cat, off + 24)[0] != off:
            continue
        crc, size = struct.unpack_from("<II", cat, off + 8)
        name_off = struct.unpack_from("<I", cat, off + 28)[0]
        if not 0 < name_off < len(cat):
            continue
        raw = cat[name_off:name_off + 200].split(b"\x00")[0].decode("utf-8", "replace")
        out.append({"crc_off": off + 8, "crc": crc, "size": size, "name": raw})
    return out


def disable_crc_checks(game_dir: str, backup_dir_path: str, names, log=print):
    """Zero the catalog CRC of every modified bundle (0 disables validation)."""
    path = catalog_path(game_dir)
    cat = bytearray(open(path, "rb").read())
    records = _catalog_records(bytes(cat))
    result = {}
    for name in names:
        pristine = os.path.join(backup_dir_path, name)
        if not os.path.exists(pristine):
            result[name] = "skipped (no pristine copy)"
            continue
        size = os.path.getsize(pristine)
        needle = struct.pack("<I", size)
        hits = [i for i in range(0, len(cat) - 3) if cat[i:i + 4] == needle]
        if len(hits) == 1:                                # crc sits right before the size
            struct.pack_into("<I", cat, hits[0] - 4, 0)
            result[name] = "ok"
            continue
        for rec in records:                               # structural fallback
            if rec["size"] == size or name.startswith(rec["name"]):
                struct.pack_into("<I", cat, rec["crc_off"], 0)
                result[name] = "ok (record)"
                break
        else:
            # no CRC is validated for this bundle in the shipped catalog
            result[name] = "skip"
    with open(path, "wb") as fh:
        fh.write(bytes(cat))
    return result


# ----------------------------------------------------------------------- api ---

def apply(repo_dir: str, game_dir: str, *, log=print) -> dict:
    """Patch a (pristine or already patched) installation."""
    if not os.path.isdir(game_dir):
        raise PatchError(f"game folder not found: {game_dir}")

    bak = ensure_backup(repo_dir, game_dir)
    log(f"備份：{bak}")
    # always start from pristine bytes so re-running is deterministic
    restore_from_backup(repo_dir, game_dir)

    translations = load_translations(repo_dir)
    nodes = load_font_nodes(repo_dir, game_dir)

    stats = {"strings": 0, "fonts": {}, "locale": False, "crc": {}}
    stats["strings"] = patch_string_tables(game_dir, translations, log=log)
    stats["locale"] = rename_locale(game_dir)

    for name, pids in FONT_PIDS.items():
        path = os.path.join(data_dir(game_dir), name)
        if not os.path.exists(path):
            continue
        done = patch_fonts_in_file(path, is_bundle=False, nodes=nodes, pids=set(pids), log=log)
        stats["fonts"][name] = done
    for name in BUNDLES:
        path = os.path.join(aa_dir(game_dir), name)
        if not os.path.exists(path):
            continue
        stats["fonts"][name] = patch_fonts_in_file(path, is_bundle=True, nodes=nodes, log=log)

    bundles = [n for n in BUNDLES if os.path.exists(os.path.join(aa_dir(game_dir), n))]
    stats["crc"] = disable_crc_checks(game_dir, bak, bundles + [STRING_BUNDLE, LOCALE_BUNDLE], log=log)
    return stats


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Playrooms 繁體中文漢化套用工具")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--game-dir", required=False, help="Playrooms 安裝資料夾")
    ap.add_argument("--restore", action="store_true", help="還原成英文原版")
    args = ap.parse_args(argv)

    repo_dir = os.path.abspath(args.repo)
    game_dir = args.game_dir or os.environ.get("PLAYROOMS_DIR") or detect_game_dir()
    if not game_dir:
        print("找不到遊戲資料夾，請用 --game-dir 指定（例如 \"D:\\SteamLibrary\\steamapps\\common\\Playrooms\"）")
        return 2

    if args.restore:
        n = restore_from_backup(repo_dir, game_dir)
        print(f"已還原 {n} 個檔案 → {game_dir}")
        return 0

    stats = apply(repo_dir, game_dir)
    print(f"翻譯字串：{stats['strings']} 條")
    print(f"語系名稱：{'已改為繁體中文' if stats['locale'] else '未變更（找不到 en locale）'}")
    for name, fonts in stats["fonts"].items():
        if fonts:
            print(f"字型 {name}: {', '.join(fonts)}")
    bad = {k: v for k, v in stats["crc"].items() if v not in ("ok", "ok (record)", "skip")}
    print(f"CRC 處理：{len(stats['crc']) - len(bad)} 個成功" + (f"，失敗 {bad}" if bad else ""))
    print("完成，啟動遊戲即為繁體中文。")
    return 0


def detect_game_dir() -> str | None:
    """Best-effort detection of a Steam installation of the game."""
    candidates = []
    env = os.environ.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)"
    steam = os.path.join(env, "Steam", "steamapps", "common", "Playrooms")
    candidates.append(steam)
    for drive in "CDEFGH":
        candidates.append(f"{drive}:\\SteamLibrary\\steamapps\\common\\Playrooms")
        candidates.append(f"{drive}:\\Steam\\steamapps\\common\\Playrooms")
    for path in candidates:
        if os.path.isfile(os.path.join(path, "Playrooms.exe")):
            return path
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
