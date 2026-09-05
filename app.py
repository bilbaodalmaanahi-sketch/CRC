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

import streamlit as st
import io


# ============================================================
# CONFIGURACIÓN
# ============================================================

BLOCK_LEN = 0x80
TRAILER_OFF = 0x7E
DATA_LEN = TRAILER_OFF

SECTOR_SIZE = 0x18000
SECTOR_START = 0x018080


# ============================================================
# CRC16 XMODEM
# ============================================================

def crc16_xmodem(data: bytes, init: int = 0x0000, poly: int = 0x1021) -> int:
    crc = init

    for b in data:
        crc ^= (b << 8)

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


# ============================================================
# DETECTAR SECTOR ACTIVO
# ============================================================

def find_active_sector(data: bytes) -> int:

    sector0_nonzero = any(
        b != 0
        for b in data[0x90:SECTOR_SIZE]
    )

    if sector0_nonzero:
        return 0x000000

    return 0x018000


# ============================================================
# BLOQUES
# ============================================================

def iter_blocks(data: bytes, sector_start: int):

    start = sector_start + 0x080
    end = sector_start + SECTOR_SIZE

    for bstart in range(start, end, BLOCK_LEN):

        if bstart + BLOCK_LEN > len(data):
            break

        yield bstart


# ============================================================
# VERIFICAR
# ============================================================

def verificar_bytes(data):

    sector_start = find_active_sector(data)

    total = 0
    ok = 0
    fallos = []

    for bstart in iter_blocks(data, sector_start):

        chunk = data[
            bstart:bstart + DATA_LEN
        ]

        calc = crc16_xmodem(chunk)

        stored = (
            data[bstart + TRAILER_OFF]
            |
            (
                data[bstart + TRAILER_OFF + 1]
                << 8
            )
        )

        total += 1

        if calc == stored:
            ok += 1

        else:
            fallos.append({
                "offset": bstart,
                "calculado": calc,
                "almacenado": stored
            })

    return sector_start, total, ok, fallos


# ============================================================
# REPARAR
# ============================================================

def reparar_bytes(data):

    data = bytearray(data)

    sector_start = find_active_sector(data)

    corregidos = 0

    for bstart in iter_blocks(data, sector_start):

        chunk = bytes(
            data[bstart:bstart + DATA_LEN]
        )

        calc = crc16_xmodem(chunk)

        stored = (
            data[bstart + TRAILER_OFF]
            |
            (
                data[bstart + TRAILER_OFF + 1]
                << 8
            )
        )

        if calc != stored:

            data[bstart + TRAILER_OFF] = (
                calc & 0xFF
            )

            data[bstart + TRAILER_OFF + 1] = (
                (calc >> 8) & 0xFF
            )

            corregidos += 1

    return bytes(data), sector_start, corregidos


# ============================================================
# STREAMLIT
# ============================================================

st.set_page_config(
    page_title="EEPROM MED17 CRC Tool",
    page_icon="",
    layout="wide"
)

st.title("EEPROM MED17 CRC Tool")

st.write(
    "Analizador y reparador de CRC16/XMODEM para archivos BIN."
)


# ============================================================
# SUBIR BIN
# ============================================================

archivo = st.file_uploader(
    "Seleccionar archivo BIN",
    type=["bin"]
)


if archivo is not None:

    datos = archivo.getvalue()

    st.success(
        f"Archivo cargado: {archivo.name}"
    )

    st.write(
        f"Tamaño: **{len(datos):,} bytes**"
    )


    # ========================================================
    # BOTONES
    # ========================================================

    col1, col2 = st.columns(2)


    # ========================================================
    # VERIFICAR
    # ========================================================

    with col1:

        verificar = st.button(
            "VERIFICAR CRC",
            use_container_width=True
        )


    # ========================================================
    # REPARAR
    # ========================================================

    with col2:

        reparar = st.button(
            "REPARAR CRC",
            use_container_width=True
        )


    # ========================================================
    # VERIFICAR
    # ========================================================

    if verificar:

        sector, total, ok, fallos = verificar_bytes(datos)

        st.subheader("Resultado")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Tamaño",
            f"{len(datos):,} bytes"
        )

        c2.metric(
            "Sector activo",
            hex(sector)
        )

        c3.metric(
            "Bloques",
            total
        )

        c4.metric(
            "CRC correctos",
            ok
        )


        if len(fallos) == 0:

            st.success(
                "TODOS LOS CRC SON CORRECTOS"
            )

        else:

            st.error(
                f"Se encontraron {len(fallos)} CRC incorrectos."
            )

            import pandas as pd

            df = pd.DataFrame(fallos)

            df["offset"] = df["offset"].apply(
                lambda x: hex(x)
            )

            df["calculado"] = df["calculado"].apply(
                lambda x: f"{x:04X}"
            )

            df["almacenado"] = df["almacenado"].apply(
                lambda x: f"{x:04X}"
            )

            st.dataframe(
                df,
                use_container_width=True
            )


    # ========================================================
    # REPARAR
    # ========================================================

    if reparar:

        datos_reparados, sector, corregidos = (
            reparar_bytes(datos)
        )

        st.subheader("Reparación")

        st.write(
            f"Sector activo: **{hex(sector)}**"
        )

        if corregidos == 0:

            st.success(
                "No había CRC incorrectos."
            )

        else:

            st.warning(
                f"Se recalcularon {corregidos} bloques."
            )


        # ====================================================
        # BOTÓN DESCARGAR
        # ====================================================

        nombre_salida = (
            archivo.name.rsplit(".", 1)[0]
            + "_REPARADO.bin"
        )

        st.download_button(
            label="DESCARGAR BIN REPARADO",
            data=datos_reparados,
            file_name=nombre_salida,
            mime="application/octet-stream",
            use_container_width=True
        )
