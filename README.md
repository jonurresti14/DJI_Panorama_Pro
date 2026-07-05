# DJI Panorama Pro 🚁📸

Una herramienta profesional, automática y **completamente portátil** para coser panorámicas esféricas (360x180°) a partir de fotografías tomadas por drones DJI (especialmente diseñada y calibrada para el DJI Mini 4K, pero compatible con la mayoría de modelos).

![Captura de pantalla de la Interfaz](https://i.imgur.com/example.png) *(Puedes añadir aquí una captura más adelante)*

## ✨ Características Principales

* **Cero Configuración:** No necesitas instalar Python, ni librerías, ni usar la línea de comandos. Solo ejecuta el `.exe`.
* **Motor Matemático Basado en EXIF:** A diferencia de otros programas que se pierden con cielos vacíos o agua, este programa extrae los metadatos de giro exactos (`GimbalYawDegree`, `Pitch`, `Roll`) inyectados por el dron en el archivo `.JPG` para proyectar matemáticamente la esfera perfecta.
* **Fusión MultiBanda (MultiBandBlender):** Utiliza un algoritmo profesional de fusión de pirámides laplacianas y diagramas de Voronoi. El ganador de cada píxel se lleva todo, eliminando totalmente el "ghosting" y suavizando los cambios de exposición entre el cielo y el suelo.
* **Calibración Precisa del FOV:** Ajuste dinámico del campo de visión (FOV 80.0°) calculado para tener en cuenta la corrección interna de lente que aplican los drones DJI. ¡Adiós a los elementos del paisaje partidos a la mitad!
* **Visor 360° Integrado:** Incluye un servidor web y la librería **Pannellum** para poder visualizar y navegar interactivamente por las panorámicas en tu propio navegador justo después de que se generen.
* **Escalado Automático de Cielos:** Relleno inteligente de los huecos negros en el cénit (ya que los drones no pueden mirar 90° hacia arriba) estirando el gradiente natural del cielo.

## 🚀 Cómo Usarlo

Al ser un programa `standalone` (portable), el uso es extremadamente sencillo:

1. **Descarga** el archivo `DJI_WebApp.exe` de este repositorio.
2. **Haz doble clic** en él. Aparecerá una consola negra (no la cierres, es el servidor en segundo plano).
3. Tu navegador web predeterminado se abrirá automáticamente en `http://127.0.0.1:5000`.
4. Pulsa en **"Seleccionar Carpeta"** y busca el directorio donde están tus fotos (por ejemplo `E:\DJI Mini 4K\DCIM\PANORAMA\100_0205`). El programa agrupará y coserá las imágenes.
5. Observa el visor 360 interactivo y pulsa el **botón de Descarga** para guardar tu panorámica final en alta resolución.

> **Nota:** La primera vez que lo abras puede tardar unos segundos extra, ya que el archivo ejecutable se descomprime en una carpeta temporal.

## 🛠 Entorno de Desarrollo (Para Programadores)

Si deseas modificar el código o no quieres usar la versión precompilada en `.exe`:

1. Clona el repositorio:
   ```bash
   git clone https://github.com/jonurresti14/DJI_Panorama_Pro.git
   ```
2. Instala las dependencias en Python (3.x):
   ```bash
   pip install opencv-python numpy flask
   ```
3. Ejecuta el servidor manualmente:
   ```bash
   python DJI_WebApp.py
   ```

## 🏗 Cómo se compiló

El proyecto fue compilado usando `PyInstaller` para incluir todos los paquetes de visión artificial (OpenCV) y el framework web (Flask) en un solo archivo:
```bash
pyinstaller --onefile DJI_WebApp.py
```

## 📜 Licencia

Proporcionado "tal cual" para la comunidad de pilotos de drones. ¡Siéntete libre de modificarlo o mejorarlo!
