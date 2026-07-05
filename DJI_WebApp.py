import os
import glob
import cv2
import numpy as np
import math
import re
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog
from flask import Flask, jsonify, request, send_file, render_template_string

app = Flask(__name__)
panoramas_data = []

# ============================================================
# ALGORITMO DE COSIDO ESFÉRICO CON DATOS EXIF DEL DRON
# ============================================================

def read_dji_exif(filepath):
    """Lee los metadatos XMP del gimbal DJI incrustados en el JPEG."""
    with open(filepath, 'rb') as f:
        data = f.read(1024 * 1024)
    text = data.decode('latin1', errors='ignore')
    def ex(tag):
        m = re.search(rf'drone-dji:{tag}="([+-]?[\d.]+)"', text)
        return float(m.group(1)) if m else 0.0
    return ex('GimbalYawDegree'), ex('GimbalPitchDegree'), ex('GimbalRollDegree')


def make_rotation_matrix(yaw_deg, pitch_deg, roll_deg):
    """Crea la matriz de rotación 3x3 a partir de los ángulos del gimbal DJI.
    
    Convenciones DJI:
    - Yaw: rotación alrededor del eje Y (vertical). Positivo = sentido horario desde arriba.
    - Pitch: rotación alrededor del eje X (lateral). Negativo = mirando hacia abajo.
    - Roll: rotación alrededor del eje Z (frontal).
    
    Sistema de coordenadas mundial: X=Este, Y=Arriba, Z=Norte.
    Sistema de cámara: X=Derecha, Y=Arriba, Z=Adelante.
    """
    y = math.radians(yaw_deg)
    p = math.radians(-pitch_deg)  # Negamos: DJI neg = abajo, rotación neg = abajo
    r = math.radians(-roll_deg)
    
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    
    # Ry (yaw alrededor de Y)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    # Rx (pitch alrededor de X)  
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=np.float64)
    # Rz (roll alrededor de Z)
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], dtype=np.float64)
    
    # Orden: primero roll, luego pitch, luego yaw
    return Ry @ Rx @ Rz


def stitch_panorama(folder_path, scale=1.0, out_w=8000, out_h=4000, diag_fov=80.0):
    """Cose las imágenes en una proyección equirectangular usando datos EXIF del dron."""
    
    files = sorted(set(
        glob.glob(os.path.join(folder_path, "*.JPG")) + 
        glob.glob(os.path.join(folder_path, "*.jpg"))
    ))
    
    # Filtrar cosidos anteriores: solo archivos que empiecen por DJI_
    files = [f for f in files if os.path.basename(f).upper().startswith('DJI_')]
    valid_files = files
    
    # Cargar todas las imágenes y sus metadatos
    image_data = []
    for f in valid_files:
        img = cv2.imread(f)
        if img is None:
            continue
        # Escalar para rendimiento (0.5 = buena calidad, rápido)
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        yaw, pitch, roll = read_dji_exif(f)
        image_data.append((img, yaw, pitch, roll, os.path.basename(f)))
    
    if not image_data:
        return None
    
    h_img, w_img = image_data[0][0].shape[:2]
    
    # Calcular distancia focal a partir del FOV diagonal (82.1° para DJI Mini 4K)
    diag_pixels = math.sqrt(w_img**2 + h_img**2)
    focal = (diag_pixels / 2.0) / math.tan(math.radians(diag_fov / 2.0))
    
    print(f"  Imagen: {w_img}x{h_img}, focal: {focal:.1f}px, FOV diag: {diag_fov}")
    
    # Arrays para calcular el diagrama de Voronoi (ganador se lo lleva todo)
    best_weight = np.zeros((out_h, out_w), dtype=np.float32)
    winner_idx = np.full((out_h, out_w), -1, dtype=np.int32)
    
    # Almacenar los datos remapeados para la segunda pasada
    remapped_data = []
    wx = np.minimum(
        np.arange(w_img, dtype=np.float32),
        np.arange(w_img - 1, -1, -1, dtype=np.float32)
    )
    wy = np.minimum(
        np.arange(h_img, dtype=np.float32),
        np.arange(h_img - 1, -1, -1, dtype=np.float32)
    )
    # Distancia mínima al borde (horizontal o vertical)
    weight_map = np.minimum(wx[np.newaxis, :], wy[:, np.newaxis])
    # Suavizar sobre el 25% del borde más pequeño (zona de fusión amplia)
    feather = min(w_img, h_img) * 0.25
    weight_map = np.clip(weight_map / max(feather, 1), 0, 1).astype(np.float32)
    
    for idx, (img, yaw, pitch, roll, name) in enumerate(image_data):
        print(f"  [{idx+1}/{len(image_data)}] {name}: yaw={yaw:+.1f} pitch={pitch:+.1f}")
        
        # Matriz de rotación de la cámara y su inversa
        R = make_rotation_matrix(yaw, pitch, roll)
        R_inv = R.T  # Inversa = traspuesta (matriz ortogonal)
        
        # Dirección frontal de la cámara en coordenadas mundo
        forward = R @ np.array([0.0, 0.0, 1.0])
        cam_lon = math.atan2(forward[0], forward[2])
        cam_lat = math.asin(np.clip(forward[1], -1, 1))
        
        # Calcular bounding box en el output equirectangular
        h_fov = 2 * math.atan(w_img / (2 * focal))
        v_fov = 2 * math.atan(h_img / (2 * focal))
        
        # Cerca de los polos (nadir/zenith), la imagen se estira
        # horizontalmente en equirectangular. Escalar el spread_x
        # inversamente con cos(latitud) para cubrir toda la anchura.
        cos_lat_factor = max(0.05, abs(math.cos(cam_lat)))
        spread_x = int(h_fov / (2 * math.pi) * out_w * 1.6 / cos_lat_factor)
        spread_x = min(spread_x, out_w)  # Máximo = anchura completa
        spread_y = int(v_fov / math.pi * out_h * 1.6)
        
        cx = int((cam_lon / (2 * math.pi) + 0.5) * out_w) % out_w
        cy = int((0.5 - cam_lat / math.pi) * out_h)
        
        # Manejar wrap-around en los bordes (±180°)
        regions = []
        x0 = cx - spread_x
        x1 = cx + spread_x
        y0 = max(0, cy - spread_y)
        y1 = min(out_h, cy + spread_y)
        
        # Si cubre toda la anchura (nadir/zenith), usar región completa
        if spread_x >= out_w // 2:
            regions.append((0, out_w, y0, y1))
        elif x0 < 0:
            regions.append((out_w + x0, out_w, y0, y1))
            regions.append((0, min(x1, out_w), y0, y1))
        elif x1 > out_w:
            regions.append((x0, out_w, y0, y1))
            regions.append((0, x1 - out_w, y0, y1))
        else:
            regions.append((x0, x1, y0, y1))
        
        for rx0, rx1, ry0, ry1 in regions:
            if rx1 <= rx0 or ry1 <= ry0:
                continue
            
            X, Y = np.meshgrid(np.arange(rx0, rx1), np.arange(ry0, ry1))
            
            # Convertir píxeles del output a longitud/latitud
            lon = (X.astype(np.float64) / out_w - 0.5) * 2 * math.pi
            lat = (0.5 - Y.astype(np.float64) / out_h) * math.pi
            
            # Convertir a vectores 3D unitarios (coordenadas mundo)
            cos_lat = np.cos(lat)
            dx = cos_lat * np.sin(lon)
            dy = np.sin(lat)
            dz = cos_lat * np.cos(lon)
            
            # Transformar a coordenadas de cámara usando R^-1
            dirs = np.stack([dx.ravel(), dy.ravel(), dz.ravel()], axis=0)
            cam_dirs = R_inv @ dirs
            
            cam_x = cam_dirs[0].reshape(X.shape)
            cam_y = cam_dirs[1].reshape(X.shape)
            cam_z = cam_dirs[2].reshape(X.shape)
            
            # Solo válido si está delante de la cámara (z > 0)
            valid = cam_z > 0.01
            
            # Proyectar al plano de imagen
            # u = f * x/z + w/2 (horizontal, misma dirección)
            # v = -f * y/z + h/2 (vertical, invertida porque Y-arriba → v-abajo)
            u = np.full_like(cam_x, -1, dtype=np.float32)
            v = np.full_like(cam_y, -1, dtype=np.float32)
            
            u[valid] = (focal * cam_x[valid] / cam_z[valid] + w_img / 2.0).astype(np.float32)
            v[valid] = (-focal * cam_y[valid] / cam_z[valid] + h_img / 2.0).astype(np.float32)
            
            # Verificar que el píxel cae dentro de la imagen
            valid = valid & (u >= 0) & (u < w_img - 1) & (v >= 0) & (v < h_img - 1)
            
            # Crear mapas de remap
            map_x = np.full(X.shape, -1.0, dtype=np.float32)
            map_y = np.full(Y.shape, -1.0, dtype=np.float32)
            map_x[valid] = u[valid]
            map_y[valid] = v[valid]
            
            # Remapear la imagen y los pesos
            mapped_rgb = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
            mapped_w = cv2.remap(weight_map, map_x, map_y, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            
            # Registrar en el mapa global de pesos (Voronoi)
            sl = (slice(ry0, ry1), slice(rx0, rx1))
            better = mapped_w > best_weight[sl]
            
            # Actualizar el ganador
            current_best = best_weight[sl]
            current_winner = winner_idx[sl]
            current_best[better] = mapped_w[better]
            current_winner[better] = idx
            best_weight[sl] = current_best
            winner_idx[sl] = current_winner
            
            # Guardar el parche para la segunda pasada
            remapped_data.append((idx, mapped_rgb, rx0, ry0, rx1, ry1))
            
    # --- SEGUNDA PASADA: Fusión con MultiBandBlender usando máscaras binarias ---
    # Esto garantiza CERO blur (porque cada píxel viene de 1 sola foto) 
    # y CERO costuras (porque el blender suaviza los colores en los bordes)
    print("  Preparando fusión de pirámides...")
    blender = cv2.detail_MultiBandBlender()
    blender.setNumBands(8)  # 8 bandas = fusión de color a gran escala
    blender.prepare((0, 0, out_w, out_h))
    
    for idx, mapped_rgb, rx0, ry0, rx1, ry1 in remapped_data:
        sl = (slice(ry0, ry1), slice(rx0, rx1))
        
        # La máscara es 255 solo si esta imagen es la ganadora absoluta
        binary_mask = (winner_idx[sl] == idx).astype(np.uint8) * 255
        
        # Suavizar ligeramente la máscara de corte para dar un pequeño
        # margen de transición de píxeles y ocultar micro-desalineaciones
        binary_mask = cv2.GaussianBlur(binary_mask, (21, 21), 0)
        
        img_int16 = mapped_rgb.astype(np.int16)
        blender.feed(img_int16, binary_mask, (rx0, ry0))
    
    # Obtener el resultado final del MultiBandBlender
    print("  Mezclando imágenes (MultiBandBlender)...")
    result, result_mask = blender.blend(None, None)
    result = np.clip(result, 0, 255).astype(np.uint8)
    
    # Post-procesado (sin blur adicional, máxima nitidez)
    
    # Rellenar el cielo faltante (cénit) estirando el último píxel válido hacia arriba
    # y el suelo (nadir) estirándolo hacia abajo para evitar el feo efecto del inpaint en áreas gigantes.
    print("  Rellenando cielo y suelo...")
    gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    valid_mask = gray >= 3
    
    y_indices = np.arange(out_h)[:, None]
    
    # Relleno del cielo
    y_valid_top = np.where(valid_mask, y_indices, out_h)
    first_y = y_valid_top.min(axis=0)
    for x in range(out_w):
        fy = first_y[x]
        if 0 < fy < out_h:
            result[:fy, x] = result[fy, x]
            
    # Relleno del suelo
    y_valid_bottom = np.where(valid_mask, y_indices, -1)
    last_y = y_valid_bottom.max(axis=0)
    for x in range(out_w):
        ly = last_y[x]
        if ly >= 0 and ly < out_h - 1:
            result[ly+1:, x] = result[ly, x]
            
    # Inpaint final muy leve solo para huecos internos pequeños o micro-imperfecciones
    gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    black_mask = (gray < 3).astype(np.uint8) * 255
    if np.sum(black_mask) > 0:
        result = cv2.inpaint(result, black_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
        
    return result


# ============================================================
# SERVIDOR WEB (Flask)
# ============================================================

def get_folder_dialog():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(title="Selecciona la carpeta DCIM del dron")
    root.destroy()
    return folder_path

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/select_folder')
def select_folder():
    folder = get_folder_dialog()
    if not folder:
        return jsonify({"error": "No folder selected"})
    
    global panoramas_data
    panoramas_data = []
    
    # 1. Buscar HTMLs en 100MEDIA para obtener fechas y links a PANORAMA
    html_files = []
    for root_dir, dirs, files in os.walk(folder):
        if '100MEDIA' in root_dir.upper():
            for f in files:
                if f.upper().endswith('.HTML'):
                    html_files.append(os.path.join(root_dir, f))
    
    for html_path in html_files:
        try:
            with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            match = re.search(r'url=\.\./PANORAMA/([^/]+)/', content)
            if match:
                folder_name = match.group(1)
                pano_dir = None
                for root_dir, dirs, files in os.walk(folder):
                    if os.path.basename(root_dir) == folder_name and 'PANORAMA' in root_dir.upper():
                        pano_dir = root_dir
                        break
                if pano_dir:
                    jpgs = [f for f in os.listdir(pano_dir) if f.upper().endswith('.JPG') and f.upper().startswith('DJI_')]
                    if len(jpgs) > 5:
                        panoramas_data.append({
                            'id': 0,
                            'name': f"Pano_{folder_name}",
                            'path': pano_dir,
                            'stitched_path': None,
                            'count': len(jpgs),
                            'date': os.path.getmtime(html_path),
                            'date_str': ''
                        })
        except Exception as e:
            print("Error:", html_path, e)
    
    # Fallback: escanear PANORAMA directamente
    if not panoramas_data:
        for root_dir, dirs, files in os.walk(folder):
            jpgs = [f for f in files if f.upper().endswith('.JPG') and f.upper().startswith('DJI_')]
            if len(jpgs) >= 10:
                panoramas_data.append({
                    'id': 0,
                    'name': 'Pano_' + os.path.basename(root_dir),
                    'path': root_dir,
                    'stitched_path': None,
                    'count': len(jpgs),
                    'date': os.path.getmtime(root_dir),
                    'date_str': ''
                })
    
    # Ordenar por fecha descendente y asignar IDs
    panoramas_data.sort(key=lambda x: x['date'], reverse=True)
    for i, p in enumerate(panoramas_data):
        p['id'] = i
        from datetime import datetime
        p['date_str'] = datetime.fromtimestamp(p['date']).strftime('%d/%m/%Y %H:%M')
    
    return jsonify({"panoramas": panoramas_data})


@app.route('/api/stitch/<int:pano_id>')
def stitch_pano(pano_id):
    if pano_id >= len(panoramas_data):
        return jsonify({"error": "ID invalido"}), 400
    
    pano = panoramas_data[pano_id]
    
    if pano['stitched_path'] and os.path.exists(pano['stitched_path']):
        return jsonify({"success": True, "url": f"/api/image/{pano_id}"})
    
    print(f"\n=== COSIENDO: {pano['name']} ({pano['count']} fotos) ===")
    result = stitch_panorama(pano['path'])
    
    if result is not None:
        desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        safe_name = pano['name'] + '_cosido.jpg'
        out_path = os.path.join(desktop, safe_name)
        success, buf = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if success:
            with open(out_path, 'wb') as f:
                f.write(buf.tobytes())
        pano['stitched_path'] = out_path
        print(f"=== LISTO: {out_path} ===")
        return jsonify({"success": True, "url": f"/api/image/{pano_id}"})
    else:
        return jsonify({"error": "No se pudieron procesar las imagenes"}), 500


@app.route('/api/image/<int:pano_id>')
def serve_image(pano_id):
    if pano_id < len(panoramas_data):
        path = panoramas_data[pano_id]['stitched_path']
        if path and os.path.exists(path):
            return send_file(path, mimetype='image/jpeg')
    return "Not found", 404

@app.route('/api/download/<int:pano_id>')
def download_image(pano_id):
    if pano_id < len(panoramas_data):
        path = panoramas_data[pano_id]['stitched_path']
        if path and os.path.exists(path):
            name = panoramas_data[pano_id]['name'] + '_esfera.jpg'
            return send_file(path, mimetype='image/jpeg', as_attachment=True, download_name=name)
    return "Not found", 404


# ============================================================
# HTML + PANNELLUM (FRONTEND)
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DJI Panorama Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css"/>
    <script src="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { display: flex; font-family: 'Inter', sans-serif; background: #0f172a; color: white; height: 100vh; overflow: hidden; }
        
        #sidebar { width: 380px; min-width: 380px; background: #0f172a; border-right: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; }
        #sidebar-header { padding: 28px; border-bottom: 1px solid rgba(255,255,255,0.08); position: relative; }
        
        .lang-picker { position: absolute; top: 28px; right: 28px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: white; padding: 4px 8px; border-radius: 6px; font-size: 0.8rem; cursor: pointer; outline: none; }
        .lang-picker option { background: #0f172a; color: white; }
        
        h1 { font-size: 1.5rem; font-weight: 700; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 12px; }
        .subtitle { color: #94a3b8; font-size: 0.82rem; line-height: 1.6; margin-bottom: 20px; }
        
        .btn { display: flex; justify-content: center; align-items: center; width: 100%; padding: 14px; background: linear-gradient(135deg, #3b82f6, #6366f1); color: white; border-radius: 12px; font-weight: 600; font-size: 0.95rem; cursor: pointer; border: none; transition: all 0.2s; box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3); }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .btn-sm { padding: 10px 18px; font-size: 0.85rem; border-radius: 10px; width: auto; }
        .btn-green { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3); }
        
        #pano-list { flex: 1; overflow-y: auto; padding: 16px; }
        #pano-list::-webkit-scrollbar { width: 5px; }
        #pano-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 10px; }
        
        .pano-item { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 16px; margin-bottom: 10px; cursor: pointer; transition: all 0.2s; }
        .pano-item:hover { background: rgba(255,255,255,0.08); transform: translateX(4px); }
        .pano-item.active { background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); }
        .pano-item.done { border-left: 3px solid #10b981; }
        .pano-name { font-weight: 600; font-size: 0.95rem; margin-bottom: 5px; }
        .pano-info { font-size: 0.78rem; color: #94a3b8; }
        .pano-info span { margin-right: 14px; }
        
        #viewer { flex: 1; position: relative; background: radial-gradient(ellipse at center, #1e293b, #0f172a); }
        #panorama { width: 100%; height: 100%; }
        
        #overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 20; pointer-events: none; }
        #loading-box { display: none; background: rgba(15, 23, 42, 0.92); backdrop-filter: blur(12px); padding: 35px 50px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); text-align: center; pointer-events: auto; box-shadow: 0 25px 50px rgba(0,0,0,0.5); }
        .spinner { width: 36px; height: 36px; border: 4px solid rgba(99,102,241,0.2); border-top-color: #6366f1; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        
        #toolbar { position: absolute; top: 16px; right: 16px; z-index: 100; display: none; }
        
        .empty-state { text-align: center; padding: 50px 20px; color: #475569; }
        .empty-state svg { margin-bottom: 16px; opacity: 0.3; }
        
        .pnlm-load-button { background: #3b82f6 !important; border-radius: 50% !important; }
        .pnlm-controls-container { top: 60px !important; }
    </style>
</head>
<body>
    <div id="sidebar">
        <div id="sidebar-header">
            <select id="lang-sel" class="lang-picker" onchange="changeLang()">
                <option value="en">EN</option>
                <option value="es">ES</option>
                <option value="fr">FR</option>
                <option value="de">DE</option>
                <option value="it">IT</option>
            </select>
            <h1>DJI Panorama Pro</h1>
            <div class="subtitle" id="t-sub">Select the drone's <b>DCIM</b> folder. Panoramas will be detected automatically and sorted by date. The algorithm stitches them using gimbal position data.</div>
            <button class="btn" id="select-btn" onclick="selectFolder()">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <span id="t-btn-txt">Select DCIM Folder</span>
            </button>
        </div>
        <div id="pano-list">
            <div class="empty-state">
                <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                <div id="t-wait">Waiting for folder...</div>
            </div>
        </div>
    </div>
    
    <div id="viewer">
        <div id="overlay">
            <div id="loading-box">
                <div class="spinner"></div>
                <div style="font-weight:600; color:#a5b4fc; font-size:1.1rem;" id="t-stitch">Stitching panorama...</div>
                <div style="font-size:0.82rem; color:#94a3b8; margin-top:8px;" id="t-stitchsub">The algorithm is aligning and blending.<br>This may take 1-2 minutes.</div>
            </div>
        </div>
        <div id="toolbar">
            <button class="btn btn-sm btn-green" onclick="downloadCurrent()">
                <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                <span id="t-down-txt">Download JPG</span>
            </button>
        </div>
        <div id="panorama"></div>
    </div>
    
    <script>
        const tDict = {
            en: { sub: "Select the drone's <b>DCIM</b> folder. Panoramas will be detected automatically and sorted by date. The algorithm stitches them using gimbal position data.", btn: "Select DCIM Folder", wait: "Waiting for folder...", err: "No panoramas found.", stitch: "Stitching panorama...", stitchsub: "The algorithm is aligning and blending.<br>This may take 1-2 minutes.", down: "Download JPG", search: "Searching...", error_conn: "Server connection error.", err_server: "Error: ", f_fotos: " photos" },
            es: { sub: "Selecciona la carpeta <b>DCIM</b> del dron. Se detectarán automáticamente todas las panorámicas, ordenadas por fecha. El algoritmo las coserá usando los datos de posición del gimbal.", btn: "Seleccionar Carpeta DCIM", wait: "Esperando carpeta...", err: "No se encontraron panorámicas.", stitch: "Cosiendo panorámica...", stitchsub: "El algoritmo está alineando y fusionando.<br>Puede tardar 1-2 minutos.", down: "Descargar JPG", search: "Buscando...", error_conn: "Error de conexión con el servidor.", err_server: "Error: ", f_fotos: " fotos" },
            fr: { sub: "Sélectionnez le dossier <b>DCIM</b> du drone. Les panoramas seront détectés et triés par date. L'algorithme les assemble à l'aide des données du cardan.", btn: "Sélectionner Dossier", wait: "En attente de dossier...", err: "Aucun panorama trouvé.", stitch: "Création du panorama...", stitchsub: "L'algorithme aligne et fusionne.<br>Cela peut prendre 1 à 2 minutes.", down: "Télécharger JPG", search: "Recherche...", error_conn: "Erreur de connexion au serveur.", err_server: "Erreur: ", f_fotos: " photos" },
            de: { sub: "Wählen Sie den <b>DCIM</b>-Ordner der Drohne. Panoramen werden automatisch erkannt. Der Algorithmus fügt sie anhand von Gimbal-Positionsdaten zusammen.", btn: "Ordner Auswählen", wait: "Warten auf Ordner...", err: "Keine Panoramen gefunden.", stitch: "Panorama wird erstellt...", stitchsub: "Algorithmus richtet aus und verschmilzt.<br>Dies kann 1-2 Minuten dauern.", down: "JPG Herunterladen", search: "Suchen...", error_conn: "Serververbindungsfehler.", err_server: "Fehler: ", f_fotos: " fotos" },
            it: { sub: "Seleziona la cartella <b>DCIM</b> del drone. I panorami verranno rilevati automaticamente. L'algoritmo li unisce usando i dati di posizione del gimbal.", btn: "Seleziona Cartella", wait: "In attesa della cartella...", err: "Nessun panorama trovato.", stitch: "Creazione panorama...", stitchsub: "L'algoritmo sta allineando e fondendo.<br>Potrebbero volerci 1-2 minuti.", down: "Scarica JPG", search: "Ricerca...", error_conn: "Errore di connessione al server.", err_server: "Errore: ", f_fotos: " foto" }
        };
        let curLang = 'en';

        function changeLang() {
            curLang = document.getElementById('lang-sel').value;
            updateUI();
        }

        function updateUI() {
            let t = tDict[curLang];
            document.getElementById('t-sub').innerHTML = t.sub;
            document.getElementById('t-btn-txt').innerText = t.btn;
            if(document.getElementById('t-wait')) document.getElementById('t-wait').innerText = t.wait;
            if(document.getElementById('t-err')) document.getElementById('t-err').innerText = t.err;
            document.getElementById('t-stitch').innerText = t.stitch;
            document.getElementById('t-stitchsub').innerHTML = t.stitchsub;
            document.getElementById('t-down-txt').innerText = t.down;
            
            // Actualizar boton si estaba buscando
            const btnTxt = document.getElementById('t-btn-txt');
            if (document.getElementById('select-btn').disabled) {
                btnTxt.innerText = t.search;
            }
        }

        let viewer = null;
        let currentId = null;
        
        async function selectFolder() {
            const btn = document.getElementById('select-btn');
            btn.disabled = true;
            document.getElementById('t-btn-txt').innerText = tDict[curLang].search;
            
            const res = await fetch('/api/select_folder');
            const data = await res.json();
            
            btn.disabled = false;
            document.getElementById('t-btn-txt').innerText = tDict[curLang].btn;
            
            if (data.error || !data.panoramas || data.panoramas.length === 0) {
                document.getElementById('pano-list').innerHTML = '<div class="empty-state"><div style="color:#ef4444" id="t-err">' + tDict[curLang].err + '</div></div>';
                return;
            }
            
            const list = document.getElementById('pano-list');
            list.innerHTML = '';
            
            data.panoramas.forEach(p => {
                const div = document.createElement('div');
                div.className = 'pano-item';
                div.id = 'pano-' + p.id;
                div.innerHTML = '<div class="pano-name">' + p.name + '</div><div class="pano-info"><span>📅 ' + p.date_str + '</span><span>📷 ' + p.count + tDict[curLang].f_fotos + '</span></div>';
                div.onclick = () => loadPano(p.id);
                list.appendChild(div);
            });
        }
        
        async function loadPano(id) {
            currentId = id;
            document.querySelectorAll('.pano-item').forEach(el => el.classList.remove('active'));
            document.getElementById('pano-' + id).classList.add('active');
            
            document.getElementById('loading-box').style.display = 'block';
            document.getElementById('toolbar').style.display = 'none';
            
            if (viewer) { viewer.destroy(); viewer = null; }
            
            try {
                const res = await fetch('/api/stitch/' + id);
                const data = await res.json();
                
                document.getElementById('loading-box').style.display = 'none';
                
                if (data.error) {
                    alert(tDict[curLang].err_server + data.error);
                    return;
                }
                
                document.getElementById('toolbar').style.display = 'block';
                document.getElementById('pano-' + id).classList.add('done');
                
                viewer = pannellum.viewer('panorama', {
                    type: 'equirectangular',
                    panorama: data.url,
                    autoLoad: true,
                    compass: true,
                    showZoomCtrl: true,
                    mouseZoom: true,
                    autoRotate: -1,
                    autoRotateInactivityDelay: 3000
                });
            } catch(e) {
                document.getElementById('loading-box').style.display = 'none';
                alert(tDict[curLang].error_conn);
            }
        }
        
        function downloadCurrent() {
            if (currentId !== null) window.location.href = '/api/download/' + currentId;
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    print("="*50)
    print("  DJI PANORAMA PRO - Servidor Web")
    print("  Abriendo navegador en http://127.0.0.1:5000")
    print("="*50)
    threading.Timer(1.2, lambda: webbrowser.open('http://127.0.0.1:5000/')).start()
    app.run(port=5000)
