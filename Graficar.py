import sys
import os
import pandas as pd
import matplotlib.pyplot as plt

def parse_time_to_seconds(time_str):
    """Convierte string H:M:S.ms a segundos totales (float)"""
    try:
        # Formato esperado: 0:00:00.000
        h, m, s = time_str.split(':')
        return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception:
        return 0.0

def main():
    # 1. Verificar si se arrastró un archivo
    if len(sys.argv) < 2:
        print("❌ Error: No se ha detectado ningún archivo.")
        print("👉 Por favor, ARRASTRA tu archivo .csv encima de este script.")
        input("Presiona ENTER para salir...")
        return

    file_path = sys.argv[1]
    print(f"📂 Procesando: {os.path.basename(file_path)}...")

    try:
        # 2. Leer el CSV
        # Primero intentamos leer normal. Si la primera columna no es 'time', 
        # asumimos que la linea 1 es la ruta del archivo (como en tu ejemplo) y saltamos una fila.
        df = pd.read_csv(file_path)
        
        if 'time' not in df.columns:
            # Reintentar saltando la primera fila (skiprows=1)
            df = pd.read_csv(file_path, skiprows=1)
            
        # Limpieza de nombres de columnas (quitar espacios extra si los hay)
        df.columns = df.columns.str.strip()

        # Verificar que existen las columnas necesarias
        required_cols = ['time', 'time_benchmark', 'total_image_size', 'image_count']
        if not all(col in df.columns for col in required_cols):
            print(f"❌ El CSV no tiene las columnas esperadas: {required_cols}")
            print(f"   Columnas encontradas: {list(df.columns)}")
            input("Presiona ENTER para salir...")
            return

        # 3. Procesar datos
        # Convertir tiempo a segundos para el eje X
        df['seconds_axis'] = df['time'].apply(parse_time_to_seconds)

        # 4. Configurar el gráfico
        plt.style.use('dark_background') # Estilo oscuro, ideal para fansubbers
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        
        # Título de la ventana y del gráfico
        fig.canvas.manager.set_window_title(f'Benchmark: {os.path.basename(file_path)}')
        ax1.set_title(f'Análisis de Rendimiento - {os.path.basename(file_path)}', fontsize=14, color='white')

        # --- GRÁFICO 1: TIEMPO DE RENDERIZADO (LAG) ---
        # time_benchmark suele estar en segundos o ms. En tu ejemplo son segundos (0.002).
        # Lo pasamos a ms para leerlo mejor (x1000)
        render_ms = df['time_benchmark'] * 1000
        
        ax1.plot(df['seconds_axis'], render_ms, color='#ff4d4d', linewidth=1.5, label='Render Time (ms)')
        ax1.fill_between(df['seconds_axis'], render_ms, color='#ff4d4d', alpha=0.3)
        
        ax1.set_ylabel('Render Time (ms)', fontsize=12)
        ax1.grid(True, linestyle='--', alpha=0.3)
        ax1.legend(loc='upper left')
        
        # Línea de referencia (opcional): 1 frame a 24fps son ~41ms. 
        # Si pasa de eso, hay lag visible (drop frames).
        ax1.axhline(y=41.6, color='yellow', linestyle=':', alpha=0.7, label='Límite 24fps (~41ms)')

        # --- GRÁFICO 2: CARGA (TAMAÑO IMÁGENES Y CANTIDAD) ---
        # Eje izquierdo: Total Image Size
        color_size = '#4d94ff'
        ax2.plot(df['seconds_axis'], df['total_image_size'], color=color_size, label='Total Image Size')
        ax2.set_ylabel('Total Image Size (Bytes)', color=color_size, fontsize=12)
        ax2.tick_params(axis='y', labelcolor=color_size)
        
        # Eje derecho: Image Count
        ax3 = ax2.twinx()
        color_count = '#00ff00'
        ax3.plot(df['seconds_axis'], df['image_count'], color=color_count, linestyle='--', alpha=0.7, label='Image Count')
        ax3.set_ylabel('Image Count (Objetos)', color=color_count, fontsize=12)
        ax3.tick_params(axis='y', labelcolor=color_count)
        
        ax2.set_xlabel('Tiempo de Video (segundos)', fontsize=12)
        ax2.grid(True, linestyle='--', alpha=0.3)
        
        # Unir leyendas del gráfico 2
        lines_1, labels_1 = ax2.get_legend_handles_labels()
        lines_2, labels_2 = ax3.get_legend_handles_labels()
        ax2.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

        # Ajustar diseño
        plt.tight_layout()
        
        print("✅ Gráfico generado. Cierra la ventana del gráfico para terminar.")
        plt.show()

    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")
        import traceback
        traceback.print_exc()
        input("Presiona ENTER para cerrar...")

if __name__ == "__main__":
    main()