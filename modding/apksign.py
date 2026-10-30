#!/usr/bin/env python3
"""
apksign.py — подпись APK схемой **APK Signature Scheme v2** на чистом Python.

Зачем: после любой правки APK (замена текстур, иконки, манифеста) исходная
подпись становится недействительной, а Android отказывается ставить файл с
ошибкой INSTALL_PARSE_FAILED_NO_CERTIFICATES («Установочный пакет не подписан
сертификатом»). apksigner/toolkit требуют Java — здесь нужен только Python.

Реализовано:
  * APK Signing Block (ID 0x7109871a) со схемой v2;
  * алгоритм 0x0103 — RSA PKCS#1 v1.5 + SHA-256 (понимают все Android 7+);
  * генерация самоподписанного сертификата (cryptography), если своего нет;
  * проверка результата: пересчёт digest + проверка подписи.

Не реализовано: v1 (JAR signing) и v3 — для minSdk >= 24 они не нужны.
"""
from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

MAGIC = b"APK Sig Block 42"
V2_BLOCK_ID = 0x7109871A
SIG_RSA_PKCS1_SHA256 = 0x0103
CHUNK = 1024 * 1024            # 1 MiB — размер блока для content digest
EOCD_SIG = b"PK\x05\x06"


# ---------------------------------------------------------------------------
# примитивы разметки
# ---------------------------------------------------------------------------

def _u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def _u64(b: bytes, off: int) -> int:
    return struct.unpack_from("<Q", b, off)[0]


def _lp(data: bytes) -> bytes:
    """length-prefixed (uint32) — базовый тип всех полей схемы v2."""
    return struct.pack("<I", len(data)) + data


def _u32seq(*items: int) -> bytes:
    return b"".join(struct.pack("<I", i) for i in items)


# ---------------------------------------------------------------------------
# поиск структур в zip
# ---------------------------------------------------------------------------

def find_eocd(data: bytes) -> int:
    """Смещение End of Central Directory (последние 64 КиБ файла)."""
    start = max(0, len(data) - 65557)
    idx = data.rfind(EOCD_SIG, start)
    if idx < 0:
        raise ValueError("это не zip/apk: не найден EOCD")
    return idx


@dataclass
class ZipLayout:
    eocd: int
    cd_offset: int
    cd_size: int
    block_offset: int   # где начинается существующий APK Signing Block (=cd_offset, если нет)
    block_size: int     # полный размер блока вместе с полями size и magic

    @property
    def has_block(self) -> bool:
        return self.block_size > 0


def read_layout(data: bytes) -> ZipLayout:
    eocd = find_eocd(data)
    cd_size = _u32(data, eocd + 12)
    cd_offset = _u32(data, eocd + 16)
    block_size = 0
    block_offset = cd_offset
    if cd_offset >= 24 and data[cd_offset - 16:cd_offset] == MAGIC:
        size2 = _u64(data, cd_offset - 24)
        start = cd_offset - size2 - 8
        if start >= 0 and _u64(data, start) == size2 and size2 >= 24:
            block_offset = start
            block_size = 8 + size2
    return ZipLayout(eocd=eocd, cd_offset=cd_offset, cd_size=cd_size,
                     block_offset=block_offset, block_size=block_size)


# ---------------------------------------------------------------------------
# content digest (то, что реально подписывается)
# ---------------------------------------------------------------------------

def content_digest(prefix: bytes, cd: bytes, eocd_for_digest: bytes,
                   algo=hashlib.sha256) -> bytes:
    """Digest по схеме v2: три секции, каждая рубится на блоки по 1 МиБ."""
    chunk_digests = []
    for section in (prefix, cd, eocd_for_digest):
        for i in range(0, len(section), CHUNK):
            part = section[i:i + CHUNK]
            h = algo()
            h.update(b"\x5a")
            h.update(struct.pack("<I", len(part)))
            h.update(part)
            chunk_digests.append(h.digest())
    h = algo()
    h.update(b"\x5a")
    h.update(struct.pack("<I", len(chunk_digests)))
    for d in chunk_digests:
        h.update(d)
    return h.digest()


# ---------------------------------------------------------------------------
# ключи и сертификат
# ---------------------------------------------------------------------------

def generate_key_and_cert(cn: str = "NoomiClone Mod", bits: int = 2048):
    """Новая пара ключей + самоподписанный сертификат (PEM-байты)."""
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local modding"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * 30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


def load_key_and_cert(key_path: str | None, cert_path: str | None,
                      create_missing_to: str | None = None):
    """Читает PEM-ключ и сертификат; при отсутствии — создаёт новые."""
    key = cert = None
    if key_path and os.path.isfile(key_path):
        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    if cert_path and os.path.isfile(cert_path):
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

    created = False
    if key is None or cert is None:
        key_pem, cert_pem = generate_key_and_cert()
        key = serialization.load_pem_private_key(key_pem, password=None)
        cert = x509.load_pem_x509_certificate(cert_pem)
        created = True
        if create_missing_to:
            os.makedirs(os.path.dirname(create_missing_to) or ".", exist_ok=True)
            if key_path:
                with open(key_path, "wb") as f:
                    f.write(key_pem)
                os.chmod(key_path, 0o600)
            if cert_path:
                with open(cert_path, "wb") as f:
                    f.write(cert_pem)
    return key, cert, created


# ---------------------------------------------------------------------------
# сборка блока v2
# ---------------------------------------------------------------------------

def build_v2_block(prefix: bytes, cd: bytes, eocd_for_digest: bytes,
                   key, cert) -> bytes:
    """Возвращает готовый APK Signing Block с одной подписью RSA/SHA-256."""
    digest = content_digest(prefix, cd, eocd_for_digest)

    signed_data = (
        _lp(_lp(_u32seq(SIG_RSA_PKCS1_SHA256) + _lp(digest)))   # digests
        + _lp(_lp(cert.public_bytes(serialization.Encoding.DER)))  # certificates
        + _lp(b"")                                                 # attributes
    )
    signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    pubkey = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signer = (
        _lp(signed_data)
        + _lp(_u32seq(SIG_RSA_PKCS1_SHA256) + _lp(signature))
        + _lp(pubkey)
    )
    value = _lp(_lp(signer))          # length-prefixed sequence of signers

    pair = struct.pack("<Q", 4 + len(value)) + struct.pack("<I", V2_BLOCK_ID) + value
    size = len(pair) + 8 + len(MAGIC)
    return struct.pack("<Q", size) + pair + struct.pack("<Q", size) + MAGIC


# ---------------------------------------------------------------------------
# подпись и проверка
# ---------------------------------------------------------------------------

def sign_apk(src: str, dst: str, key, cert) -> dict:
    """Подписывает APK схемой v2. Возвращает информацию о результате."""
    with open(src, "rb") as f:
        data = f.read()

    lay = read_layout(data)
    prefix = data[:lay.block_offset]          # существующая подпись отбрасывается
    cd = data[lay.cd_offset:lay.cd_offset + lay.cd_size]
    eocd = bytearray(data[lay.eocd:])

    # EOCD для расчёта digest: смещение CD заменяем на начало signing block
    eocd_for_digest = bytearray(eocd)
    struct.pack_into("<I", eocd_for_digest, 16, lay.block_offset)

    block = build_v2_block(prefix, cd, bytes(eocd_for_digest), key, cert)

    # EOCD для готового файла: CD теперь начинается после блока
    final_eocd = bytearray(eocd)
    struct.pack_into("<I", final_eocd, 16, lay.block_offset + len(block))

    with open(dst, "wb") as f:
        f.write(prefix)
        f.write(block)
        f.write(cd)
        f.write(final_eocd)

    return {
        "replaced_old_block": lay.has_block,
        "old_block_size": lay.block_size,
        "new_block_size": len(block),
        "cert_subject": cert.subject.rfc4514_string(),
        "cert_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        "size_in": len(data),
        "size_out": os.path.getsize(dst),
    }


def verify_apk(path: str) -> dict:
    """Независимая проверка: digest из блока v2 + криптоподпись."""
    with open(path, "rb") as f:
        data = f.read()
    lay = read_layout(data)
    if not lay.has_block:
        raise ValueError("APK Signing Block отсутствует — файл не подписан")

    block = data[lay.block_offset:lay.block_offset + lay.block_size]
    pairs = block[8:lay.block_size - 24]
    off = 0
    value = None
    while off < len(pairs):
        plen = _u64(pairs, off)
        pid = _u32(pairs, off + 8)
        if pid == V2_BLOCK_ID:
            value = pairs[off + 12: off + 8 + plen]
        off += 8 + plen
    if value is None:
        raise ValueError("в блоке нет схемы v2 (0x7109871a)")

    def read_lp(buf: bytes, o: int):
        n = _u32(buf, o)
        return buf[o + 4: o + 4 + n], o + 4 + n

    signers, _ = read_lp(value, 0)
    signer, _ = read_lp(signers, 0)
    signed_data, o = read_lp(signer, 0)

    sd_off = 0
    digests_seq, sd_off = read_lp(signed_data, sd_off)   # sequence of digests
    certs_raw, sd_off = read_lp(signed_data, sd_off)

    digest_item, _ = read_lp(digests_seq, 0)             # первый (он же единственный)
    alg = _u32(digest_item, 0)
    stored_digest, _ = read_lp(digest_item, 4)
    if alg != SIG_RSA_PKCS1_SHA256:
        raise ValueError(f"неожиданный алгоритм: 0x{alg:04x}")

    cert_der, _ = read_lp(certs_raw, 0)
    cert = x509.load_der_x509_certificate(cert_der)

    sigs_raw, o = read_lp(signer, o)
    pubkey_raw, _ = read_lp(signer, o)
    sig_alg = _u32(sigs_raw, 0)
    signature, _ = read_lp(sigs_raw, 4)

    pubkey = serialization.load_der_public_key(pubkey_raw)
    pubkey.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())

    # пересчёт digest по фактическому содержимому файла
    cd = data[lay.cd_offset:lay.cd_offset + lay.cd_size]
    eocd = bytearray(data[lay.eocd:])
    struct.pack_into("<I", eocd, 16, lay.block_offset)
    actual = content_digest(data[:lay.block_offset], cd, bytes(eocd))

    if actual != stored_digest:
        raise ValueError("digest не совпадает: файл изменён после подписи")

    return {
        "scheme": "v2",
        "algorithm": f"0x{sig_alg:04x} (RSA PKCS#1 v1.5 / SHA-256)",
        "cert_subject": cert.subject.rfc4514_string(),
        "cert_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        "digest_ok": True,
    }


# ---------------------------------------------------------------------------
# CLI для ручной проверки
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="Подпись/проверка APK схемой v2")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sign")
    ps.add_argument("apk")
    ps.add_argument("-o", "--out", required=True)
    ps.add_argument("--key")
    ps.add_argument("--cert")
    pv = sub.add_parser("verify")
    pv.add_argument("apk")
    args = p.parse_args()

    if args.cmd == "sign":
        k, c, created = load_key_and_cert(args.key, args.cert,
                                          create_missing_to=args.key)
        print("ключ: создан новый" if created else "ключ: использован существующий")
        print(json.dumps(sign_apk(args.apk, args.out, k, c), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(verify_apk(args.apk), indent=2, ensure_ascii=False))
