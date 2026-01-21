#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          COMENTARIOS PARA HUMANOS                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

Script: disk_usage_monitor_pro.py
Versión: 0.6.5-pro
Fecha: enero 2026
Propósito: Monitor continuo de discos físicos con barras proporcionales, 
           top directorios cacheados y colores según % ocupación

Novedades en v0.6.5 (manual con diagnostico IA)
* Correccion de obtencion de espacio libre y usado en MACOS lo que causaba discrepancias en root.

Novedades en v0.6.4 (manual)
* El %ocupado se rellena con espacios no con ceros
* Se guardan en cache ficheros disco_ocupado_<volumen>.txt con el % en formato int

Novedades en v0.6.3-pro-paginado-niveles-fixsum:
• Thread background cada 5 min que corrige tamaños inconsistentes en caché:
  - Si padre < suma hijos → actualiza cache JSON y .mosFolderSize del padre
  - En visualización: muestra '+' delante del tamaño si se corrigió
• No modifica la lógica de refresco cada 3h ni el cálculo original

Novedades en v0.6.2-pro-paginado-niveles:
• Jerarquía paginada: muestra UN disco a la vez
• Teclas + / - para cambiar niveles mostrados (1 a 3) — solo afecta visualización
• clear_screen() en cada cambio de página / nivel
• Controles: n siguiente, p anterior, q salir, r refrescar, + / - niveles

Novedades en v0.6.1-pro-paginado:
• La sección "Jerarquía de carpetas" ahora muestra UN disco a la vez (paginado)
• Navegación interactiva: n → siguiente, p → anterior, q → salir paginado, r → refrescar

Novedades en v0.6.0-pro:
• Muestra jerarquía de 3 niveles: top 5 carpetas de nivel 1, 2 y 3
• Mejor presentación con indentación visual
• Cálculo recursivo optimizado con caché

Características principales:
• Discos físicos reales (excluye volúmenes auxiliares macOS)
• Barras proporcionales al disco más grande
• Orden visual: MAYOR → menor tamaño
• Colores neón en TODAS las líneas según % ocupación
• Caches en subcarpeta "disk-data-cache" (creada automáticamente)
• Cálculo con `du` vía subprocess (muy rápido)
• Mientras se actualiza caché → se muestra información anterior
• Actualización pantalla: cada 7 minutos
• Caches se refrescan cada 3h o si no existen (en background)

────────────────────────────────────────────────────────────────────────────────
"""

import psutil
import time
import os
import subprocess
from pathlib import Path
import threading
import datetime
import traceback
import sys
import json
import hashlib
import select

# ─── Configuración de logging ────────────────────────────────────────────────
class LogManager:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.log_file = self.cache_dir / "disk_monitor.log"
        self.max_log_size = 1 * 1024 * 1024 * 1024  # 1GB
        
    def _check_and_rotate_log(self):
        """Verifica si el log supera 1GB y lo borra si es necesario"""
        try:
            if self.log_file.exists() and self.log_file.stat().st_size > self.max_log_size:
                log_msg = f"Log file exceeds 1GB, removing: {self.log_file}"
                self._write_log_entry("INFO", log_msg)
                self.log_file.unlink()
                return True
        except Exception as e:
            print(f"Error checking/rotating log file: {type(e).__name__} - {str(e)}")
        return False
    
    def _write_log_entry(self, level, message):
        """Escribe una entrada en el log"""
        try:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] {level}: {message}\n"
            
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"CRITICAL: Failed to write to log file: {e}", file=sys.stderr)
    
    def log_error(self, error_msg, exc_info=None):
        """Registra un error en el archivo log"""
        try:
            self._check_and_rotate_log()
            
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] ERROR: {error_msg}\n"
            
            if exc_info:
                if isinstance(exc_info, Exception):
                    log_entry += f"Exception: {type(exc_info).__name__}: {str(exc_info)}\n"
                    log_entry += "Traceback:\n"
                    log_entry += ''.join(traceback.format_tb(exc_info.__traceback__))
                elif isinstance(exc_info, tuple) and len(exc_info) == 3:
                    log_entry += "Traceback:\n"
                    log_entry += ''.join(traceback.format_exception(*exc_info))
                else:
                    log_entry += f"Exception info: {exc_info}\n"
            
            log_entry += "-" * 80 + "\n"
            
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
                
        except Exception as e:
            print(f"CRITICAL: Failed to write to log file: {e}", file=sys.stderr)
            print(f"Original error: {error_msg}", file=sys.stderr)
    
    def log_info(self, info_msg):
        """Registra información en el archivo log"""
        self._write_log_entry("INFO", info_msg)
    
    def log_debug(self, debug_msg):
        """Registra mensaje de depuración en el archivo log"""
        self._write_log_entry("DEBUG", debug_msg)

# ─── Inicializar logging ─────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "disk-data-cache"
log_manager = LogManager(CACHE_DIR)

# ─── Configuración del caché por carpeta ────────────────────────────────────
CACHE_FILE_NAME = ".mosFolderSize"
FOLDER_CACHE_VALIDITY_HOURS = 12
FOLDER_CACHE_VALIDITY_SECONDS = FOLDER_CACHE_VALIDITY_HOURS * 3600

# ─── Configuración del caché de disco ───────────────────────────────────────
DISK_CACHE_VALIDITY_HOURS = 3
DISK_CACHE_VALIDITY_SECONDS = DISK_CACHE_VALIDITY_HOURS * 3600

# ─── Colores ANSI neón ─────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"

GREEN_NEON  = "\033[38;5;46m"
YELLOW_NEON = "\033[38;5;226m"
ORANGE_NEON = "\033[38;5;208m"
RED_NEON    = "\033[38;5;196m"

CYAN_NEON   = "\033[38;5;51m"
MAGENTA_NEON = "\033[38;5;201m"
BLUE_NEON   = "\033[38;5;33m"


def get_color_by_usage(percent):
    if percent < 50:
        return GREEN_NEON
    elif percent < 80:
        return YELLOW_NEON
    elif percent < 90:
        return ORANGE_NEON
    else:
        return RED_NEON


def color_line(text, color):
    return f"{color}{BOLD}{text}{RESET}"


def human_size(size_bytes):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:5.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:5.1f}EiB"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def fast_get_dir_sizes(dirs_list):
    if not dirs_list:
        return []
    try:
        result = subprocess.run(
            ['du', '-s', '--block-size=1'] + dirs_list,
            capture_output=True, text=True, timeout=1800, check=True
        )
        lines = result.stdout.strip().split('\n')
        sizes = []
        for line in lines:
            if '\t' in line:
                size_str, path = line.rsplit('\t', 1)
                try:
                    sizes.append((path.strip(), int(size_str)))
                except ValueError:
                    continue
        return sizes
    except subprocess.TimeoutExpired as e:
        error_msg = f"Timeout en 'du' para dirs: {dirs_list[:5]}... (más de 30 min)"
        log_manager.log_error(error_msg, e)
        return []
    except Exception as e:
        error_msg = f"Error en subprocess 'du' para {dirs_list[:3] if dirs_list else 'lista vacía'}..."
        log_manager.log_error(error_msg, e)
        return []


def calculate_folder_signature(folder_path):
    try:
        stat = os.stat(folder_path)
        signature_data = f"{folder_path}:{stat.st_dev}:{stat.st_ino}"
        return hashlib.md5(signature_data.encode('utf-8')).hexdigest()[:8]
    except Exception:
        return "00000000"


def read_cached_folder_size(folder_path):
    cache_file = Path(folder_path) / CACHE_FILE_NAME
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not all(key in data for key in ['timestamp', 'size', 'signature']):
            log_manager.log_error(f"Archivo de caché corrupto en {folder_path}")
            return None
        
        current_time = time.time()
        if current_time - data['timestamp'] > FOLDER_CACHE_VALIDITY_SECONDS:
            return None
        
        expected_signature = calculate_folder_signature(folder_path)
        if data['signature'] != expected_signature:
            log_manager.log_error(f"Firma de caché inválida en {folder_path}")
            return None
        
        return data['size']
    
    except json.JSONDecodeError as e:
        log_manager.log_error(f"Error decodificando caché en {folder_path}", e)
        return None
    except Exception as e:
        log_manager.log_error(f"Error leyendo caché en {folder_path}", e)
        return None


def write_cached_folder_size(folder_path, size):
    cache_file = Path(folder_path) / CACHE_FILE_NAME
    
    try:
        data = {
            'timestamp': time.time(),
            'size': size,
            'signature': calculate_folder_signature(folder_path),
            'version': '1.0',
            'generated_by': 'disk_usage_monitor_pro'
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        try:
            if os.name == 'nt':
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(cache_file), 2)
            else:
                import stat
                current_mode = cache_file.stat().st_mode
                cache_file.chmod(current_mode & ~stat.S_IWOTH)
        except Exception:
            pass
        
        return True
    except Exception as e:
        log_manager.log_error(f"Error escribiendo caché en {folder_path}", e)
        return False


def calculate_folder_size_with_cache(folder_path, verbose=False):
    cached_size = read_cached_folder_size(folder_path)
    if cached_size is not None:
        return cached_size
    
    total_size = 0
    files_processed = 0
    start_time = time.time()
    
    try:
        for root, dirs, files in os.walk(folder_path):
            for dir_name in dirs[:]:
                subdir_path = os.path.join(root, dir_name)
                subdir_cached_size = read_cached_folder_size(subdir_path)
                if subdir_cached_size is not None:
                    total_size += subdir_cached_size
                    dirs.remove(dir_name)
            
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    total_size += os.path.getsize(file_path)
                    files_processed += 1
                except (OSError, PermissionError):
                    pass
            
            if time.time() - start_time > 300:
                break
        
        if total_size > 0:
            write_cached_folder_size(folder_path, total_size)
        
        return total_size
    
    except Exception as e:
        log_manager.log_error(f"Error calculando tamaño de {folder_path}", e)
        return 0


def get_top_subdirs(directory, top_n=5):
    try:
        subdirs = [e.path for e in os.scandir(directory) if e.is_dir()]
        if not subdirs:
            return []
        
        sizes = []
        for subdir in subdirs:
            size = calculate_folder_size_with_cache(subdir, verbose=False)
            sizes.append((subdir, size))
        
        sizes.sort(key=lambda x: x[1], reverse=True)
        return sizes[:top_n]
    
    except Exception as e:
        log_manager.log_error(f"Error obteniendo subdirectorios de {directory}", e)
        return []


def get_hierarchical_sizes(directory, levels=3, top_n=5):
    result = {
        'path': directory,
        'size': calculate_folder_size_with_cache(directory, verbose=False),
        'level_1': []
    }
    
    if levels >= 1:
        top_level_1 = get_top_subdirs(directory, top_n)
        for path1, size1 in top_level_1:
            level_1_item = {
                'path': path1,
                'size': size1,
                'level_2': []
            }
            
            if levels >= 2:
                top_level_2 = get_top_subdirs(path1, top_n)
                for path2, size2 in top_level_2:
                    level_2_item = {
                        'path': path2,
                        'size': size2,
                        'level_3': []
                    }
                    
                    if levels >= 3:
                        top_level_3 = get_top_subdirs(path2, top_n)
                        level_2_item['level_3'] = [
                            {'path': path3, 'size': size3}
                            for path3, size3 in top_level_3
                        ]
                    
                    level_1_item['level_2'].append(level_2_item)
            
            result['level_1'].append(level_1_item)
    
    return result


def slow_get_hierarchical_sizes(disk_mount, top_n=5):
    log_manager.log_info(f"Iniciando cálculo jerárquico para {disk_mount}")
    
    try:
        return get_hierarchical_sizes(disk_mount, levels=3, top_n=top_n)
    except Exception as e:
        log_manager.log_error(f"Error en cálculo jerárquico para {disk_mount}", e)
        return None


def update_cache_thread(disk_mount, top_n=5, start_time=None):
    if start_time is None:
        start_time = time.time()

    safe_name = disk_mount.replace('/', '_').replace(':', '_').replace('\\', '_')
    cache_file = CACHE_DIR / f"cache_{safe_name}.json"  

    try:
        subdirs = [e.path for e in os.scandir(disk_mount) if e.is_dir()]
        if not subdirs:
            log_manager.log_info(f"No subdirectorios encontrados en {disk_mount}")
            return

        top_level_1 = fast_get_dir_sizes(subdirs)
        
        if top_level_1:
            top_level_1.sort(key=lambda x: x[1], reverse=True)
            top_level_1 = top_level_1[:top_n]
            
            hierarchical_data = {
                'disk_mount': disk_mount,
                'timestamp': time.time(),
                'level_1': []
            }
            
            for path1, size1 in top_level_1:
                level_1_item = {
                    'path': path1,
                    'size': size1,
                    'level_2': []
                }
                
                subdirs_level2 = [e.path for e in os.scandir(path1) if e.is_dir()]
                if subdirs_level2:
                    top_level_2 = fast_get_dir_sizes(subdirs_level2)
                    if not top_level_2:
                        top_level_2 = get_top_subdirs(path1, top_n)
                    
                    top_level_2.sort(key=lambda x: x[1], reverse=True)
                    top_level_2 = top_level_2[:top_n]
                    
                    for path2, size2 in top_level_2:
                        level_2_item = {
                            'path': path2,
                            'size': size2,
                            'level_3': []
                        }
                        
                        subdirs_level3 = [e.path for e in os.scandir(path2) if e.is_dir()]
                        if subdirs_level3:
                            top_level_3 = fast_get_dir_sizes(subdirs_level3)
                            if not top_level_3:
                                top_level_3 = get_top_subdirs(path2, top_n)
                            
                            top_level_3.sort(key=lambda x: x[1], reverse=True)
                            top_level_3 = top_level_3[:top_n]
                            
                            level_2_item['level_3'] = [
                                {'path': path3, 'size': size3}
                                for path3, size3 in top_level_3
                            ]
                        
                        level_1_item['level_2'].append(level_2_item)
                
                hierarchical_data['level_1'].append(level_1_item)
        
        else:
            log_manager.log_info(f"Fallback a método jerárquico completo para {disk_mount}")
            hierarchical_data = slow_get_hierarchical_sizes(disk_mount, top_n)
            if hierarchical_data:
                hierarchical_data['timestamp'] = time.time()
                hierarchical_data['disk_mount'] = disk_mount

        if hierarchical_data:
            hierarchical_data['percent'] = psutil.disk_usage(disk_mount).percent

        if hierarchical_data and hierarchical_data.get('level_1'):
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(hierarchical_data, f, indent=2, ensure_ascii=False)
            
            log_manager.log_info(f"Caché jerárquica actualizada para {disk_mount}: {len(hierarchical_data['level_1'])} carpetas nivel 1")
        else:
            log_manager.log_error(f"No se pudieron obtener datos jerárquicos para {disk_mount}")

    except Exception as e:
        error_msg = f"Error general en update_cache_thread para {disk_mount}"
        log_manager.log_error(error_msg, e)


def background_cache_fix():
    """Thread background: cada 5 minutos revisa y corrige inconsistencias en todas las cachés JSON"""
    while True:
        time.sleep(300)  # 5 minutos
        
        try:
            # Buscar todos los ficheros cache_*.json en CACHE_DIR
            for cache_path in CACHE_DIR.glob("cache_*.json"):
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    level1_list = data.get('level_1', [])
                    modified = False
                    
                    for level1 in level1_list:
                        sum_level2 = sum(item['size'] for item in level1.get('level_2', []))
                        if sum_level2 > level1['size']:
                            old_size = level1['size']
                            level1['size'] = sum_level2
                            modified = True
                            log_manager.log_info(
                                f"Corregido nivel 1 {level1['path']}: {human_size(old_size)} → {human_size(sum_level2)} (+{human_size(sum_level2 - old_size)})"
                            )
                            # También actualizamos el .mosFolderSize del directorio real
                            write_cached_folder_size(level1['path'], sum_level2)
                        
                        for level2 in level1.get('level_2', []):
                            sum_level3 = sum(item['size'] for item in level2.get('level_3', []))
                            if sum_level3 > level2['size']:
                                old_size = level2['size']
                                level2['size'] = sum_level3
                                modified = True
                                log_manager.log_info(
                                    f"Corregido nivel 2 {level2['path']}: {human_size(old_size)} → {human_size(sum_level3)} (+{human_size(sum_level3 - old_size)})"
                                )
                                write_cached_folder_size(level2['path'], sum_level3)
                    
                    if modified:
                        with open(cache_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        log_manager.log_info(f"Caché {cache_path.name} corregida y guardada")
                
                except Exception as e:
                    log_manager.log_error(f"Error procesando caché {cache_path}", e)
                    continue
        
        except Exception as e:
            log_manager.log_error("Error general en background_cache_fix", e)


def load_cache(disk_mount):
    safe_name = disk_mount.replace('/', '_').replace(':', '_').replace('\\', '_')
    cache_file = CACHE_DIR / f"cache_{safe_name}.json"

    if not cache_file.exists():
        return None, None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        timestamp = data.get('timestamp')
        hierarchical_data = data.get('level_1')
        
        if not timestamp or not hierarchical_data:
            return None, None

        return hierarchical_data, timestamp

    except Exception as e:
        log_manager.log_error(f"Error cargando caché de {disk_mount}", e)
        return None, None


def is_cache_outdated(timestamp, max_age_seconds=DISK_CACHE_VALIDITY_SECONDS):
    return timestamp is None or (time.time() - timestamp) > max_age_seconds


def is_system_volume(mountpoint):
    paths = [
        '/System/Volumes/Data', '/System/Volumes/Preboot',
        '/System/Volumes/Update', '/System/Volumes/VM',
        '/System/Volumes/iSCPreboot', '/private/var/vm',
    ]
    return any(mountpoint.startswith(p) for p in paths)


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
            if usage.total < 100 * 1024**2:
                continue
            
            # Corrección manual para inconsistencias en macOS (especialmente root)
            corrected_used = usage.total - usage.free  # Calcula used como total - free
            corrected_percent = 100.0 * corrected_used / usage.total if usage.total > 0 else 0.0
            
            disks.append({
                'mountpoint': mount,
                'vol_name': get_volume_name(mount),
                'total': usage.total,
                'used': corrected_used,     # Usa el corregido
                'free': usage.free,
                'percent': corrected_percent  # Usa el corregido
            })
        except Exception as e:
            log_manager.log_error(f"Error obteniendo uso de disco para {mount}", e)
            continue
    return disks

def display_hierarchical_data(hierarchical_data, disk_color, max_levels=3):
    """Muestra datos jerárquicos con indentación visual, filtrando por max_levels"""
    if not hierarchical_data:
        print(f"      {disk_color}(No datos disponibles){RESET}")
        return
    
    for i, level1 in enumerate(hierarchical_data, 1):
        name1 = Path(level1['path']).name
        size1 = level1['size']
        sum_level2 = sum(l2['size'] for l2 in level1.get('level_2', []))
        corrected1 = sum_level2 > size1
        if corrected1:
            size1 = sum_level2
        
        size1_str = human_size(size1)
        if corrected1:
            size1_str = '+' + size1_str
        
        print(f"      {disk_color}┌─ {name1:<30} {size1_str:>10}{RESET}")
        
        if max_levels < 2:
            continue
        
        level2_data = level1.get('level_2', [])
        for j, level2 in enumerate(level2_data, 1):
            name2 = Path(level2['path']).name
            size2 = level2['size']
            sum_level3 = sum(l3['size'] for l3 in level2.get('level_3', []))
            corrected2 = sum_level3 > size2
            if corrected2:
                size2 = sum_level3
            
            size2_str = human_size(size2)
            if corrected2:
                size2_str = '+' + size2_str
            
            is_last_level2 = j == len(level2_data)
            
            if is_last_level2:
                print(f"      {disk_color}│  └─ {CYAN_NEON}{name2:<28} {size2_str:>10}{RESET}")
            else:
                print(f"      {disk_color}│  ├─ {CYAN_NEON}{name2:<28} {size2_str:>10}{RESET}")
            
            if max_levels < 3:
                continue
            
            level3_data = level2.get('level_3', [])
            for k, level3 in enumerate(level3_data, 1):
                name3 = Path(level3['path']).name
                size3_str = human_size(level3['size'])
                
                is_last_level3 = k == len(level3_data)
                is_last_parent = is_last_level2
                
                if is_last_parent:
                    if is_last_level3:
                        print(f"      {disk_color}      └─ {MAGENTA_NEON}{name3:<26} {size3_str:>10}{RESET}")
                    else:
                        print(f"      {disk_color}      ├─ {MAGENTA_NEON}{name3:<26} {size3_str:>10}{RESET}")
                else:
                    if is_last_level3:
                        print(f"      {disk_color}│     └─ {MAGENTA_NEON}{name3:<26} {size3_str:>10}{RESET}")
                    else:
                        print(f"      {disk_color}│     ├─ {MAGENTA_NEON}{name3:<26} {size3_str:>10}{RESET}")
        
        if i < len(hierarchical_data):
            print(f"      {disk_color}│{RESET}")


def update_disk_usage_txt(mountpoint, percent):
    """Genera el archivo .txt con el porcentaje entero en la carpeta de caché"""
    try:
        # Definir el nombre según tu regla: root para / o sustituir / por _
        if mountpoint == '/':
            filename = "usage_root.txt"
        else:
            # Esto convierte /Volumes/Datos en _Volumes_Datos
            safe_name = mountpoint.replace('/', '_')
            filename = f"usage_{safe_name}.txt"
        
        target_path = CACHE_DIR / filename
        with open(target_path, 'w', encoding='utf-8') as f:
            # Escribimos el entero redondeado
            f.write(str(int(round(percent))))
    except Exception as e:
        log_manager.log_error(f"Error escribiendo ocupación TXT para {mountpoint}", e)

def main():
    MAX_BAR_WIDTH = 60
    PREFIX_W = 10
    PERC_W = 6
    SIZE_COL_W = 32
    MOUNT_W = 48
    TOP_N = 5
    INTERVALO_PANTALLA = 60 * 7          # 7 minutos
    
    active_threads = {}  # {mountpoint: (thread, start_time)}
    
    log_manager.log_info("=" * 80)
    log_manager.log_info("Iniciando Disk Usage Monitor Pro v0.6.5-pro-paginado-niveles-fixsum")
    log_manager.log_info(f"Caché disco: {DISK_CACHE_VALIDITY_HOURS}h validez")
    log_manager.log_info(f"Caché carpeta: {FOLDER_CACHE_VALIDITY_HOURS}h validez")
    log_manager.log_info("Background fix de sumas cada 5 min activado")
    
    print(f"Sistema de caché por carpeta activado (validez: {FOLDER_CACHE_VALIDITY_HOURS}h)")
    print(f"Caché disco se refresca cada: {DISK_CACHE_VALIDITY_HOURS}h")
    print(f"Mostrando top {TOP_N} carpetas por nivel (ajustable con + / -)")
    print("Background: corrección de sumas inconsistentes cada 5 minutos")
    time.sleep(3)

    # Lanzar thread de corrección de sumas en background
    threading.Thread(target=background_cache_fix, daemon=True).start()

    prefs_file = CACHE_DIR / "user_prefs.json"

    def load_prefs():
        if prefs_file.exists():
            try:
                with open(prefs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('current_levels', 1), data.get('last_mount', None)
            except Exception as e:
                log_manager.log_error(f"Error cargando prefs", e)
        return 1, None

    def save_prefs(levels, mount):
        data = {'current_levels': levels, 'last_mount': mount}
        try:
            with open(prefs_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_manager.log_error(f"Error guardando prefs", e)

    while True:
        try:
            clear_screen()

            disks = get_physical_disks_info()
            if not disks:
                print("No discos físicos encontrados.\n")
                time.sleep(INTERVALO_PANTALLA)
                continue

            for d in disks:
                update_disk_usage_txt(d['mountpoint'], d['percent'])

            disks_visual = sorted(disks, key=lambda d: (-d['total'], d['mountpoint'].lower()))

            max_disk_size = max(d['total'] for d in disks) if disks else 1
            total_capacity = sum(d['total'] for d in disks)
            total_used = sum(d['used'] for d in disks)
            total_free = sum(d['free'] for d in disks)

            print(" MONITOR DE DISCOS PRO - JERARQUÍA 3 NIVELES ".center(140))
            print(f"Versión 0.6.3-pro | Top {TOP_N} por nivel | Caché: {DISK_CACHE_VALIDITY_HOURS}h".center(140))
            print(time.strftime('%Y-%m-%d %H:%M:%S').center(140))
            print()

            header = f"{'Volumen':^{PREFIX_W}}  {'Barra':^{MAX_BAR_WIDTH}}  {'%Occ':^{PERC_W}}  {'Libre / Total':^{SIZE_COL_W}}  {'Mountpoint':<{MOUNT_W}}"
            print(BOLD + header + RESET)
            print("─" * len(header))

            for disk in disks_visual:
                color = get_color_by_usage(disk['percent'])

                prefix = (disk['vol_name'][:7] + " "*7)[:7]
                proportion = disk['total'] / max_disk_size
                bar_length = max(1, round(MAX_BAR_WIDTH * proportion))
                usage_ratio = disk['used'] / disk['total'] if disk['total'] > 0 else 0
                used_chars = round(bar_length * usage_ratio)

                bar = "█" * used_chars + "▒" * (bar_length - used_chars) + " " * (MAX_BAR_WIDTH - bar_length)
                perc_str = f"{int(round(disk['percent'])):3d}%"
                size_text = f"{human_size(disk['free']):>11} / {human_size(disk['total']):<11}"

                line = f"{prefix}  {bar}  {perc_str:^{PERC_W}}  {size_text}  {disk['mountpoint']:<{MOUNT_W}}"
                print(color_line(line, color))

            print("─" * len(header))

            total_percent = (total_used / total_capacity * 100) if total_capacity > 0 else 0
            total_color = get_color_by_usage(total_percent)
            total_perc_str = f"{int(round(total_percent)):3d}%"
            total_text = f"{human_size(total_free):>11} / {human_size(total_capacity):<11}"
            total_line = f"{'TOTAL':^{PREFIX_W}}  {' '*MAX_BAR_WIDTH}  {total_perc_str:^{PERC_W}}  {total_text}  (suma discos visibles)"
            print(color_line(total_line, total_color))

            # ──────────────────────────────────────────────────────────────
            print(f"\n  Jerarquía de carpetas (top {TOP_N} por nivel):")
            print("  ──────────────────────────────────────────────────────────────")

            # Limpieza de threads terminados
            to_remove = []
            for mount, (thread, _) in active_threads.items():
                if not thread.is_alive():
                    to_remove.append(mount)
                    log_manager.log_info(f"Thread completado para {mount}")
            for m in to_remove:
                del active_threads[m]

            caches = []
            for disk in disks:
                mount = disk['mountpoint']
                hierarchical_data, ts = load_cache(mount)
                if ts is not None:
                    caches.append((disk, hierarchical_data, ts))

                if (ts is None or is_cache_outdated(ts, DISK_CACHE_VALIDITY_SECONDS)) and mount not in active_threads:
                    start_time = time.time()
                    t = threading.Thread(
                        target=update_cache_thread,
                        args=(mount, TOP_N),
                        kwargs={"start_time": start_time},
                        daemon=True
                    )
                    t.start()
                    active_threads[mount] = (t, start_time)
                    log_manager.log_info(f"Iniciando thread de actualización jerárquica para {mount}")

            if not caches:
                print("  No hay datos jerárquicos cacheados todavía.\n")
                print("  Esperando primera actualización de caché...")
                time.sleep(INTERVALO_PANTALLA)
                continue

            caches.sort(key=lambda x: x[2], reverse=True)

            current_levels, last_mount = load_prefs()
            current_page = 0
            if last_mount:
                for i, (disk, _, _) in enumerate(caches):
                    if disk['mountpoint'] == last_mount:
                        current_page = i
                        break

            total_pages = len(caches)

            while True:
                clear_screen()

                print(" MONITOR DE DISCOS PRO - JERARQUÍA 3 NIVELES ".center(140))
                print(f"Versión 0.6.3-pro | Top {TOP_N} por nivel | Niveles: {current_levels} | Caché: {DISK_CACHE_VALIDITY_HOURS}h".center(140))
                print(time.strftime('%Y-%m-%d %H:%M:%S').center(140))
                print()

                print(BOLD + header + RESET)
                print("─" * len(header))

                for disk in disks_visual:
                    color = get_color_by_usage(disk['percent'])
                    prefix = (disk['vol_name'][:7] + " "*7)[:7]
                    proportion = disk['total'] / max_disk_size
                    bar_length = max(1, round(MAX_BAR_WIDTH * proportion))
                    usage_ratio = disk['used'] / disk['total'] if disk['total'] > 0 else 0
                    used_chars = round(bar_length * usage_ratio)

                    bar = "█" * used_chars + "▒" * (bar_length - used_chars) + " " * (MAX_BAR_WIDTH - bar_length)
                    perc_str = f"{int(round(disk['percent'])):3d}%"
                    size_text = f"{human_size(disk['free']):>11} / {human_size(disk['total']):<11}"

                    line = f"{prefix}  {bar}  {perc_str:^{PERC_W}}  {size_text}  {disk['mountpoint']:<{MOUNT_W}}"
                    print(color_line(line, color))

                print("─" * len(header))

                print(color_line(total_line, total_color))

                print(f"\n  Jerarquía de carpetas (top {TOP_N} por nivel) - {current_page+1}/{total_pages}   [niveles: {current_levels}]")
                print("  ──────────────────────────────────────────────────────────────")

                disk, hierarchical_data, ts = caches[current_page]
                color = get_color_by_usage(disk['percent'])
                mount = disk['mountpoint']

                title_line = f"  {mount}  ({human_size(disk['total'])} total)"
                print(color_line(title_line, color))

                last_update = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                update_line = f"    Última actualización: {last_update}"
                print(color_line(update_line, color))

                if mount in active_threads:
                    print(color_line("    Calculando jerarquía de carpetas...", color))
                print(f"    {CYAN_NEON}■ Nivel 1{RESET} │ {MAGENTA_NEON}■ Nivel 2{RESET} │ {BLUE_NEON}■ Nivel 3{RESET}")
                print()

                display_hierarchical_data(hierarchical_data, color, max_levels=current_levels)
                
                print()
                print("  Controles:")
                print("    n / flecha derecha → siguiente disco")
                print("    p / flecha izquierda → disco anterior")
                print("    +                  → mostrar más niveles (máx 3)")
                print("    -                  → mostrar menos niveles (mín 1)")
                print("    r                  → forzar refresco de caché de este disco")
                print("    q / ESC            → volver al modo automático")
                print()

                i, o, e = select.select([sys.stdin], [], [], INTERVALO_PANTALLA)

                if i:
                    try:
                        key = sys.stdin.read(1)
                        key_lower = key.lower()

                        if key_lower in ('q', '\x1b'):
                            save_prefs(current_levels, caches[current_page][0]['mountpoint'])
                            print("\n  Saliendo del modo paginado...")
                            break

                        elif key_lower in ('n', '\x1b[C'):
                            current_page = (current_page + 1) % total_pages
                            save_prefs(current_levels, caches[current_page][0]['mountpoint'])

                        elif key_lower in ('p', '\x1b[D'):
                            current_page = (current_page - 1) % total_pages
                            save_prefs(current_levels, caches[current_page][0]['mountpoint'])

                        elif key == '+':
                            if current_levels < 3:
                                current_levels += 1
                                save_prefs(current_levels, caches[current_page][0]['mountpoint'])

                        elif key == '-':
                            if current_levels > 1:
                                current_levels -= 1
                                save_prefs(current_levels, caches[current_page][0]['mountpoint'])

                        elif key_lower == 'r':
                            safe_name = mount.replace('/', '_').replace(':', '_').replace('\\', '_')
                            cache_file = CACHE_DIR / f"cache_{safe_name}.json"
                            if cache_file.exists():
                                cache_file.unlink()
                                print(f"  Caché eliminada para {mount}")
                            if mount not in active_threads:
                                t = threading.Thread(
                                    target=update_cache_thread,
                                    args=(mount, TOP_N),
                                    daemon=True
                                )
                                t.start()
                                active_threads[mount] = (t, time.time())
                            print(f"  Refrescando caché de {mount}...")

                    except:
                        pass
                else:
                    save_prefs(current_levels, caches[current_page][0]['mountpoint'])
                    print("\n  Timeout → volviendo a modo automático")
                    break

            time.sleep(2)

        except KeyboardInterrupt:
            clear_screen()
            log_manager.log_info("Monitor detenido por el usuario")
            print("\nMonitor detenido.\n")
            break
        except Exception as e:
            error_msg = "Error inesperado en el loop principal"
            log_manager.log_error(error_msg, e)
            
            print(f"\n¡Error detectado! Los detalles se han guardado en el log.")
            print(f"Reiniciando el monitor en 30 segundos...")
            time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        print("\nMonitor detenido.\n")
    except Exception as e:
        error_msg = "Error crítico al iniciar el monitor"
        log_manager.log_error(error_msg, e)
        print(f"\nError crítico: {type(e).__name__} - {str(e)}")
        print(f"Revise el archivo de log en: {CACHE_DIR / 'disk_monitor.log'}")