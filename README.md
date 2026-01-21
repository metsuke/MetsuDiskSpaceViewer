# MetsuDiskSpaceViewer

Script de apoyo en el desarrollo de **MetsuOS** para analizar y visualizar dónde se consume el espacio en disco, especialmente en volúmenes externos.

## Descripción

Esta herramienta permite escanear directorios o unidades completas para identificar rápidamente qué carpetas y archivos ocupan más espacio. Está pensada para:

- Depuración de almacenamiento durante el desarrollo de MetsuOS
- Análisis de discos externos, unidades secundarias o montajes grandes
- Usuarios que necesitan una alternativa simple y sin dependencias pesadas

## Características actuales

- Escaneo recursivo de directorios y subdirectorios
- Cálculo preciso de tamaños (archivos + carpetas) con caches para evitar relectura continua (esto puede causar discrepancias en la exactitud, pero recordemos que el objetivo es detectar rapido donde debemos actuar, no hacer una auditoria)
- Ordenación por tamaño descendente
- Salida legible en consola (con tamaños en formato humano: KB, MB, GB…)
- Dos versiones del script:
  - `disk-space-view.py` → implementación básica
  - `disk-space-view-pro.py` → versión mejorada / extendida

## Requisitos

- Python 3.8 o superior
- Módulos estándar de Python (sin dependencias externas en la versión actual)

## Instalación y uso rápido

1. Clona el repositorio:

   ```bash
   git clone https://github.com/metsuke/MetsuDiskSpaceViewer.git
   cd MetsuDiskSpaceViewer
   ```

2. Ejecuta uno de los scripts directamente:

   ```bash
   # Versión básica
   python disk-space-view.py

   # Versión mejorada
   python disk-space-view-pro.py
   ```

## Roadmap / Próximos pasos

- Quiza incluir trabajo con root, por ahora centrado en Volumenes extenos
- Comprobaciones multiplataforma, pora ahora centrado en MacOS

## Contribuir

Las contribuciones son bienvenidas, especialmente para:

- Mejorar la usabilidad de los scripts actuales

Pasos estándar:

1. Haz fork del repositorio
2. Crea una rama descriptiva (`git checkout -b mejora/progreso-bar`)
3. Commitea tus cambios
4. Abre un Pull Request

## Licencia

**GPL-3.0**  
Consulta el archivo [LICENSE](./LICENSE) para más detalles.

## Autor

**Metsuke**  
[@metsuke](https://github.com/metsuke)  

---

Herramienta creada para facilitar el desarrollo y mantenimiento de **MetsuOS**.
