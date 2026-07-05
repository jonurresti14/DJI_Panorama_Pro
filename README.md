# DJI Panorama Pro 🚁📸

A professional, automatic, and **completely portable** tool for stitching spherical panoramas (360x180°) from photographs taken by DJI drones. It is specially designed and calibrated for the DJI Mini 4K but is fully compatible with most models.

![App Screenshot](https://i.imgur.com/example.png) *(You can add a screenshot here later)*

## ✨ Key Features

* **Zero Configuration:** No need to install Python, libraries, or use the command line. Just run the `.exe` file!
* **EXIF-Based Mathematical Engine:** Unlike other software that fails with empty skies or water, this program extracts the exact gimbal rotation metadata (`GimbalYawDegree`, `Pitch`, `Roll`) injected by the drone into the `.JPG` files to mathematically project the perfect sphere.
* **Multi-Band Blending:** Uses a professional Laplacian pyramid blending algorithm and Voronoi diagrams. "Winner takes all" pixel selection completely eliminates ghosting and smooths out exposure differences between the sky and the ground.
* **Precise FOV Calibration:** Dynamic Field of View adjustment (FOV 80.0°) calculated to account for the internal lens distortion correction applied by DJI drones. Say goodbye to landscape elements cut in half!
* **Integrated 360° Viewer:** Includes a web server and the **Pannellum** library so you can view and interactively navigate your panoramas in your own browser right after they are generated.
* **Automatic Sky Scaling:** Smart filling of the black holes at the zenith (since drones cannot look 90° straight up) by stretching the natural gradient of the sky.
* **Multilingual Interface:** The UI is available in English, Spanish, French, German, and Italian.

## 🚀 How to Use

Being a standalone application, using it is extremely simple:

1. **Download** the `DJI_WebApp.exe` file from this repository.
2. **Double-click** it. A black console window will appear (do not close it, it's the background server).
3. Your default web browser will automatically open to `http://127.0.0.1:5000`.
4. Click on **"Select DCIM Folder"** and locate the directory where your drone photos are (for example `E:\DJI Mini 4K\DCIM\PANORAMA\100_0205`). The program will automatically group and stitch the images.
5. Enjoy the interactive 360 viewer and click the **Download** button to save your final panorama in high resolution.

> **Note:** The first time you open it, it may take a few extra seconds, as the executable file decompresses into a temporary folder.

## 🛠 Development Environment (For Programmers)

If you want to modify the code or don't want to use the precompiled `.exe` version:

1. Clone the repository:
   ```bash
   git clone https://github.com/jonurresti14/DJI_Panorama_Pro.git
   ```
2. Install Python (3.x) dependencies:
   ```bash
   pip install opencv-python numpy flask
   ```
3. Run the server manually:
   ```bash
   python DJI_WebApp.py
   ```
   Or use the included `START_WEBAPP.bat`.

## 🏗 How it was compiled

The project was compiled using `PyInstaller` to bundle all computer vision packages (OpenCV) and the web framework (Flask) into a single file:
```bash
pyinstaller --onefile DJI_WebApp.py
```

## 📜 License

Provided "as is" for the drone pilot community. Feel free to modify or improve it!
