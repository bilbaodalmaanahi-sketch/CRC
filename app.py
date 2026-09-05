"""
Herramienta de verificacion/recalculo de CRC para EEPROM interna
(FEE - Flash EEPROM Emulation) de ECUs BMW/Bosch MED17.x (TriCore).

Estructura detectada:
  - Archivo dividido en 2 sectores de 0x18000 bytes (wear-leveling).
  - El sector activo contiene registros de 0x80 (128) bytes:
        +0x00..+0x07  Header (ID de bloque, version, contador)
        +0x08..+0x7D  Payload / datos           (118 bytes)
        +0x7E..+0x7F  CRC-16 (little-endian) de los 126 bytes anteriores

Algoritmo de CRC: CRC-16/XMODEM
  poly=0x1021  init=0x0000  refin=False  refout=False  xorout=0x0000

Uso:
  python3 eeprom_med17_crc_tool.py verificar archivo.bin
  python3 eeprom_med17_crc_tool.py reparar archivo_in.bin archivo_out.bin
  python3 eeprom_med17_crc_tool.py diff original.bin modificado.bin
"""

import sys

BLOCK_LEN = 0x80          # 128 bytes por bloque
TRAILER_OFF = 0x7E        # offset del CRC dentro del bloque
DATA_LEN = TRAILER_OFF    # bytes cubiertos por el CRC (126)

# Rango donde viven los bloques reales (sector activo).
# Ajustar SECTOR_START/SECTOR_END si el layout de tu archivo difiere.
SECTOR_SIZE = 0x18000
SECTOR_START = 0x018080   # primer bloque de datos (despues del header de sector)


def crc16_xmodem(data: bytes, init: int = 0x0000, poly: int = 0x1021) -> int:
    """CRC-16/XMODEM: poly=0x1021, init=0x0000, sin reflexion, sin xor final."""
    crc = init
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def find_active_sector(data: bytes) -> int:
    """Determina cual de los dos sectores de 0x18000 tiene datos reales
    (el otro esta en blanco, usado para wear-leveling)."""
    sector0_nonzero = any(b != 0 for b in data[0x90:SECTOR_SIZE])
    if sector0_nonzero:
        return 0x000000
    return 0x018000


def iter_blocks(data: bytes, sector_start: int):
    """Itera todos los bloques de 0x80 bytes dentro del sector activo."""
    offset = sector_start + SECTOR_START - (sector_start)  # normaliza
    start = sector_start + (SECTOR_START - 0x018000 if sector_start == 0x018000 else SECTOR_START)
    # En la practica el offset de inicio de datos es sector_start + 0x080
    start = sector_start + 0x080
    end = sector_start + SECTOR_SIZE
    for bstart in range(start, end, BLOCK_LEN):
        if bstart + BLOCK_LEN > len(data):
            break
        yield bstart

def reparar(path_in: str, path_out: str):
    data = bytearray(open(path_in, "rb").read())
    sector_start = find_active_sector(data)

    corregidos = 0
    for bstart in iter_blocks(data, sector_start):
        chunk = bytes(data[bstart:bstart + DATA_LEN])
        calc = crc16_xmodem(chunk)
        stored = data[bstart + TRAILER_OFF] | (data[bstart + TRAILER_OFF + 1] << 8)
        if calc != stored:
            data[bstart + TRAILER_OFF] = calc & 0xFF
            data[bstart + TRAILER_OFF + 1] = (calc >> 8) & 0xFF
            corregidos += 1

    with open(path_out, "wb") as f:
        f.write(data)

    print(f"Sector activo detectado en offset: {hex(sector_start)}")
    print(f"Bloques con CRC recalculado: {corregidos}")
    print(f"Archivo guardado en: {path_out}")

