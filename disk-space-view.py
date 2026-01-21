#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script: disk_usage_monitor.py
Versión: 0.4.0 - Barras de longitud variable proporcional
Propósito: Mostrar barras cuya longitud visual sea proporcional al tamaño real

Característica principal:
  - La barra del disco más grande ocupa casi todo el ancho disponible
  - El resto de barras son proporcionalmente más cortas
  - No hay relleno forzado → la longitud real representa el tamaño relativo
"""

import psutil
import time
import os
from pathlib import Path


def human_size(size_bytes):
    for unit in ['B','KiB','MiB','GiB','TiB','PiB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:5.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:5.1f}EiB"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def is_system_volume(mountpoint):
    system_paths = [
        '/System/Volumes/Data', '/System/Volumes/Preboot',
        '/System/Volumes/Update', '/System/Volumes/VM',
        '/System/Volumes/iSCPreboot', '/private/var/vm',
    ]
    return any(mountpoint.startswith(p) for p in system_paths)


def get_volume_name(mountpoint):
    if mountpoint == '/':
        return 'root'
    return Path(mountpoint.rstrip('/')).name


def get_physical_disks_info():
    disks = []
    for part in psutil.disk_partitions(all=False):
        mount = part.mountpoint
        if is_system_volume(mount):
            continue
        if part.fstype in ('devfs', 'autofs', 'tmpfs', 'devtmpfs') or 'loop' in (part.device or ''):
            continue
        try:
            usage = psutil.disk_usage(mount)
            if usage.total < 100 * 1024 * 1024:  # < 100 MiB
                continue
            disks.append({
                'mountpoint': mount,
                'vol_name': get_volume_name(mount),
                'total': usage.total,
                'used': usage.used,
                'free': usage.free,
                'percent': usage.percent
            })
        except:
            continue
    return disks


def main():
    MAX_BAR_WIDTH = 60      # ← máximo para el disco más grande
    PREFIX_WIDTH = 10
    SIZE_WIDTH = 28
    MOUNT_WIDTH = 50

    while True:
        clear_screen()

        disks = get_physical_disks_info()
        if not disks:
            print("No discos físicos encontrados.\n")
            time.sleep(900)
            continue

        disks.sort(key=lambda d: (-d['total'], d['mountpoint'].lower()))

        # El disco más grande será la referencia al 100% del ancho
        max_disk_size = max(d['total'] for d in disks) if disks else 1

        print(" MONITOR DE DISCOS - tamaño proporcional ".center(140))
        print(time.strftime('%Y-%m-%d %H:%M:%S').center(140))
        print()

        header = f"{'Volumen':^{PREFIX_WIDTH}}  {'Barra':<{MAX_BAR_WIDTH}}  {'Libre/Total':^{SIZE_WIDTH}}  {'Mountpoint'}"
        print(header)
        print("─" * (PREFIX_WIDTH + MAX_BAR_WIDTH + SIZE_WIDTH + MOUNT_WIDTH + 8))

        for disk in disks:
            prefix = (disk['vol_name'][:7] + " "*7)[:7]

            # Proporción respecto al disco más grande
            proportion = disk['total'] / max_disk_size if max_disk_size > 0 else 0
            bar_length = max(1, round(MAX_BAR_WIDTH * proportion))

            # Uso dentro de esa barra
            usage_ratio = disk['used'] / disk['total'] if disk['total'] > 0 else 0
            used_chars = round(bar_length * usage_ratio)

            # Barra: █ usado + ▒ libre del disco + espacios hasta el final
            bar = "█" * used_chars + "▒" * (bar_length - used_chars) + " " * (MAX_BAR_WIDTH - bar_length)

            size_text = f"{human_size(disk['free'])} / {human_size(disk['total'])}"

            print(f"{prefix}  {bar}  {size_text:>{SIZE_WIDTH}}  {disk['mountpoint']}")

        print("─" * (PREFIX_WIDTH + MAX_BAR_WIDTH + SIZE_WIDTH + MOUNT_WIDTH + 8))

        print("\n   Actualiza cada 15 min     Ctrl+C para salir\n")
        time.sleep(900)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        print("\nMonitor detenido.\n")
    except Exception as e:
        print(f"\nError: {e}")