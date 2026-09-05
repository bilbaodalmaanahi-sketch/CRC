"""
Streamlit app - Verificador de CRC para EEPROM interna
(FEE - Flash EEPROM Emulation) de ECUs BMW/Bosch MED17.x (TriCore).

Esta app es SOLO DE LECTURA/DIAGNOSTICO:
  - Verifica si los CRC almacenados en cada bloque de 0x80 bytes
    coinciden con el CRC calculado (CRC-16/XMODEM).
  - Permite comparar (diff) dos archivos .bin para ver que bytes
    cambiaron y si el CRC de esos bloques sigue siendo valido.

No incluye ninguna funcion de recalculo/escritura de CRC.
"""

import streamlit as st
import pandas as pd
import io

BLOCK_LEN = 0x80
TRAILER_OFF = 0x7E
DATA_LEN = TRAILER_OFF
SECTOR_SIZE = 0x18000


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


def find_active_sector(data: bytes) -> int:
    sector0_nonzero = any(b != 0 for b in data[0x90:SECTOR_SIZE])
    if sector0_nonzero:
        return 0x000000
    return 0x018000


def iter_blocks(data: bytes, sector_start: int):
    start = sector_start + 0x080
    end = sector_start + SECTOR_SIZE
    for bstart in range(start, end, BLOCK_LEN):
        if bstart + BLOCK_LEN > len(data):
            break
        yield bstart


def verificar_bytes(data: bytes):
    """Devuelve (sector_start, DataFrame con el detalle de cada bloque)."""
    sector_start = find_active_sector(bytearray(data))
    filas = []
    for bstart in iter_blocks(data, sector_start):
        chunk = data[bstart:bstart + DATA_LEN]
        calc = crc16_xmodem(chunk)
        stored = data[bstart + TRAILER_OFF] | (data[bstart + TRAILER_OFF + 1] << 8)
        filas.append({
            "offset": hex(bstart),
            "crc_calculado": f"{calc:04x}",
            "crc_almacenado": f"{stored:04x}",
            "coincide": calc == stored,
        })
    return sector_start, pd.DataFrame(filas)


def diff_bytes(a: bytes, b: bytes):
    """Devuelve lista de rangos contiguos distintos entre a y b."""
    n = min(len(a), len(b))
    diffs = [i for i in range(n) if a[i] != b[i]]
    if not diffs:
        return []
    ranges = []
    start = prev = diffs[0]
    for i in diffs[1:]:
        if i == prev + 1:
            prev = i
        else:
            ranges.append((start, prev))
            start = prev = i
    ranges.append((start, prev))
    return ranges


st.set_page_config(page_title="Verificador CRC EEPROM MED17.x", layout="wide")
st.title("Verificador de CRC - EEPROM MED17.x (TriCore)")
st.caption(
    "Herramienta de solo lectura para verificar integridad de volcados de "
    "EEPROM. No modifica ni recalcula checksums."
)

tab_verificar, tab_diff = st.tabs(["Verificar archivo", "Comparar 2 archivos (diff)"])

with tab_verificar:
    st.subheader("Verificar CRC de un archivo .bin")
    up = st.file_uploader("Subi tu archivo .bin", type=["bin"], key="verificar")
    if up is not None:
        data = up.read()
        st.write(f"Archivo: **{up.name}** ({len(data)} bytes)")
        sector_start, df = verificar_bytes(data)
        st.write(f"Sector activo detectado en offset: `{hex(sector_start)}`")

        total = len(df)
        ok = int(df["coincide"].sum()) if total else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("Bloques analizados", total)
        col2.metric("CRC correctos", ok)
        col3.metric("CRC incorrectos", total - ok)

        st.dataframe(df, use_container_width=True)

        fallos = df[~df["coincide"]]
        if not fallos.empty:
            st.warning(f"{len(fallos)} bloque(s) con CRC invalido.")
            st.dataframe(fallos, use_container_width=True)
        else:
            st.success("Todos los bloques tienen CRC valido.")

with tab_diff:
    st.subheader("Comparar dos archivos .bin")
    col_a, col_b = st.columns(2)
    with col_a:
        up_a = st.file_uploader("Archivo original", type=["bin"], key="diff_a")
    with col_b:
        up_b = st.file_uploader("Archivo modificado", type=["bin"], key="diff_b")

    if up_a is not None and up_b is not None:
        a = up_a.read()
        b = up_b.read()

        if len(a) != len(b):
            st.warning(
                f"Los archivos tienen tamanos distintos ({len(a)} vs {len(b)} bytes)."
            )

        ranges = diff_bytes(a, b)
        if not ranges:
            st.success("Los archivos son identicos.")
        else:
            st.write(f"Total de rangos distintos: **{len(ranges)}**")
            sector_start_a = find_active_sector(bytearray(a))

            filas = []
            for r0, r1 in ranges:
                block_start = sector_start_a + 0x080 + (
                    (r0 - sector_start_a - 0x080) // BLOCK_LEN
                ) * BLOCK_LEN
                offset_in_block = r0 - block_start

                estado_a = "N/A"
                estado_b = "N/A"
                if block_start + BLOCK_LEN <= len(a):
                    chunk_a = a[block_start:block_start + DATA_LEN]
                    calc_a = crc16_xmodem(chunk_a)
                    stored_a = a[block_start + TRAILER_OFF] | (a[block_start + TRAILER_OFF + 1] << 8)
                    estado_a = "OK" if calc_a == stored_a else "INVALIDO"
                if block_start + BLOCK_LEN <= len(b):
                    chunk_b = b[block_start:block_start + DATA_LEN]
                    calc_b = crc16_xmodem(chunk_b)
                    stored_b = b[block_start + TRAILER_OFF] | (b[block_start + TRAILER_OFF + 1] << 8)
                    estado_b = "OK" if calc_b == stored_b else "INVALIDO"

                filas.append({
                    "rango": f"{hex(r0)}-{hex(r1)}",
                    "largo": r1 - r0 + 1,
                    "bloque": hex(block_start),
                    "offset_en_bloque": hex(offset_in_block),
                    "crc_original": estado_a,
                    "crc_modificado": estado_b,
                })

            st.dataframe(pd.DataFrame(filas), use_container_width=True)

st.divider()
st.caption(
    "Esta herramienta solo lee y compara archivos; no genera ni descarga "
    "archivos modificados."
)
