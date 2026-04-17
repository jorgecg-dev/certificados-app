from flask import Flask, request, render_template, session, redirect, send_file, send_from_directory, jsonify
import psycopg2
import os
import urllib.parse as urlparse
import qrcode
import zipfile
import locale
import pandas as pd
from reportlab.pdfgen import canvas
from functools import wraps
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import uuid
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ruta_fuente = os.path.join(BASE_DIR, "DejaVuSans-Bold.ttf")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

def ensure_dirs():
    os.makedirs(os.path.join(BASE_DIR, "qr"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "certificados"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "temp"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "salida"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "fotos"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "static", "pdfs"), exist_ok=True)


ensure_dirs()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin"):
            return redirect("/")
        return f(*args, **kwargs)
    return decorated_function


def get_connection():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise Exception("DATABASE_URL no está configurado")

    return psycopg2.connect(database_url, sslmode="require")


def ejecutar_query(query, params=None, fetch=False):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(query, params or ())

        data = cur.fetchall() if fetch else None
        conn.commit()
        return data

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


def quitar_tildes(texto):
    if not texto:
        return texto

    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U"
    }

    return "".join(reemplazos.get(c, c) for c in texto)


def limpiar_texto(texto):
    if texto is None:
        return ""
    return quitar_tildes(str(texto)).upper().strip()


def numero_a_letras(n):
    numeros = {
        0: "CERO", 1: "UNO", 2: "DOS", 3: "TRES", 4: "CUATRO",
        5: "CINCO", 6: "SEIS", 7: "SIETE", 8: "OCHO", 9: "NUEVE",
        10: "DIEZ", 11: "ONCE", 12: "DOCE", 13: "TRECE",
        14: "CATORCE", 15: "QUINCE", 16: "DIECISEIS",
        17: "DIECISIETE", 18: "DIECIOCHO", 19: "DIECINUEVE",
        20: "VEINTE"
    }
    return numeros.get(n, str(n))


try:
    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
except Exception:
    pass

def generar_certificado(nombre, dni_qr, output_path):
    ruta_base = os.path.join(BASE_DIR, "certificado_base.jpg")
    base = Image.open(ruta_base)
    draw = ImageDraw.Draw(base)

    font_fecha = ImageFont.truetype(ruta_fuente, 30)

    max_width = base.width - 200
    font_size = 60

    while True:
        font_nombre = ImageFont.truetype(ruta_fuente, font_size)
        bbox = draw.textbbox((0, 0), nombre, font=font_nombre)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width or font_size <= 20:
            break

        font_size -= 2

    x_nombre = (base.width - text_width) / 2
    y_nombre = 400

    draw.text((x_nombre, y_nombre), nombre, fill="black", font=font_nombre)
    draw.text((x_nombre + 1, y_nombre), nombre, fill="black", font=font_nombre)
    draw.text((x_nombre, y_nombre + 1), nombre, fill="black", font=font_nombre)

    fecha = datetime.now().strftime("%d de %B del %Y")
    texto_fecha = f"Piura, {fecha}"

    bbox_fecha = draw.textbbox((0, 0), texto_fecha, font=font_fecha)
    w_fecha = bbox_fecha[2] - bbox_fecha[0]

    x_fecha = base.width - w_fecha - 60
    y_fecha = 650

    draw.text((x_fecha, y_fecha), texto_fecha, fill="black", font=font_fecha)

    if PUBLIC_BASE_URL:
        url_qr = f"{PUBLIC_BASE_URL}/verificar/{dni_qr}"
    else:
        url_qr = f"http://127.0.0.1:5000/verificar/{dni_qr}"

    qr = qrcode.make(url_qr).convert("RGB")
    qr = qr.resize((140, 140))
    base.paste(qr, (30, base.height - 170))

    os.makedirs(os.path.join(BASE_DIR, "certificados"), exist_ok=True)

    rgb = base.convert("RGB")
    rgb.save(output_path, "PDF")

def generar_certificados_grupo(nombre_evento, promocion, sede):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.nombre, a.dni
        FROM alumnos a
        JOIN programas p ON a.dni = p.dni
        WHERE p.nombre = %s
        AND p.promocion = %s
        AND p.sede = %s
    """, (nombre_evento, promocion, sede))

    datos = cur.fetchall()

    for nombre, dni in datos:

        # =========================
        # GENERAR NOMBRE ARCHIVO
        # =========================
        nombre_archivo = nombre.replace(" ", "_")
        output = f"certificados/{nombre_archivo}.pdf"

        # =========================
        # GENERAR CERTIFICADO
        # =========================
        generar_certificado(nombre, dni, output)

        # =========================
        # GUARDAR PDF EN BD
        # =========================
        cur.execute("""
            UPDATE programas
            SET pdf = %s
            WHERE dni = %s
            AND nombre = %s
            AND promocion = %s
            AND sede = %s
        """, (output, dni, nombre_evento, promocion, sede))

    conn.commit()
    cur.close()
    conn.close()

# ================================
# PÁGINA PRINCIPAL
# ================================

@app.route("/")
def inicio():
    return render_template("inicio.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "").strip()

        # 🔒 validar campos vacíos
        if not usuario or not password:
            return "Complete todos los campos"

        # 🔒 credenciales (por ahora simples, luego mejoramos)
        if usuario == "admin" and password == "1234":
            session["admin"] = True
            return redirect("/dashboard")
        else:
            return "Credenciales incorrectas"

    return render_template("login.html")


@app.route("/buscar", methods=["GET", "POST"])
def buscar():
    if request.method == "POST":

        dni = request.form.get("dni", "").strip()

        # 🔒 validar DNI
        if not dni.isdigit() or len(dni) not in [8, 9]:
            return "DNI inválido"

        return redirect(f"/verificar/{dni}")

    return render_template("buscar.html")

# ================================
# REGISTRAR ALUMNO
# ================================
@app.route("/registrar", methods=["GET", "POST"])
@login_required
def registrar():
    if not session.get("admin"):
        return "<h3>Acceso restringido</h3>"

    if request.method == "POST":
        conn = None
        cur = None

        try:
            nombre = limpiar_texto(request.form.get("nombre"))
            dni = request.form.get("dni", "").strip()
            tipo = limpiar_texto(request.form.get("tipo"))
            programa = limpiar_texto(request.form.get("programa"))
            promocion = limpiar_texto(request.form.get("promocion"))
            sede = limpiar_texto(request.form.get("sede"))
            modalidad = limpiar_texto(request.form.get("modalidad"))
            duracion = limpiar_texto(request.form.get("duracion"))
            fecha_inicio = request.form.get("fecha_inicio", "").strip() or None
            fecha_fin = request.form.get("fecha_fin", "").strip() or None
            horas = limpiar_texto(request.form.get("horas"))
            archivo = request.files.get("pdf")

            if not nombre or not programa or not tipo or not promocion or not sede:
                return jsonify({"error": "Campos obligatorios incompletos"}), 400

            if not dni.isdigit() or len(dni) not in [8, 9]:
                return jsonify({"error": "DNI inválido (debe tener 8 o 9 dígitos)"}), 400

            qr_filename = dni

            ruta_pdf_bd = ""

            if archivo and archivo.filename:
                if not archivo.filename.lower().endswith(".pdf"):
                    return jsonify({"error": "Solo se permiten archivos PDF"}), 400

                filename = f"{uuid.uuid4().hex}.pdf"
                ruta_pdf_fisica = os.path.join(BASE_DIR, "certificados", filename)
                archivo.save(ruta_pdf_fisica)
                ruta_pdf_bd = f"certificados/{filename}"

            conn = get_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT 1
                FROM programas
                WHERE dni = %s
                  AND tipo = %s
                  AND nombre = %s
                  AND promocion = %s
                  AND sede = %s
            """, (dni, tipo, programa, promocion, sede))

            duplicado = cur.fetchone()

            if duplicado:
                return jsonify({"error": "Ese alumno ya está registrado en ese programa"}), 400

            cur.execute("""
                INSERT INTO alumnos (dni, nombre)
                VALUES (%s, %s)
                ON CONFLICT (dni) DO UPDATE
                SET nombre = EXCLUDED.nombre
            """, (dni, nombre))

            cur.execute("""
                INSERT INTO programas (
                    dni, tipo, nombre, promocion, sede,
                    modalidad, duracion, fecha_inicio,
                    fecha_fin, horas, pdf, qr
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                dni, tipo, programa, promocion, sede,
                modalidad, duracion, fecha_inicio,
                fecha_fin, horas, ruta_pdf_bd, qr_filename
            ))

            conn.commit()
            return jsonify({"mensaje": "Alumno registrado correctamente"})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({"error": str(e)}), 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    eventos_db = ejecutar_query(
        "SELECT nombre FROM eventos ORDER BY nombre",
        fetch=True
    )

    eventos = [{"nombre": e[0]} for e in eventos_db]
    return render_template("registrar.html", eventos=eventos)

# ================================
# PERFIL BONITO
# ================================
@app.route("/verificar/<dni>")
def verificar(dni):

    # 🔒 validar DNI
    if not dni.isdigit() or len(dni) not in [8, 9]:
        return "<h3>DNI inválido</h3>"

    conn = get_connection()
    cur = conn.cursor()

    # Obtener alumno
    cur.execute("SELECT nombre, dni FROM alumnos WHERE dni = %s", (dni,))
    alumno_db = cur.fetchone()

    if not alumno_db:
        cur.close()
        conn.close()
        return "<h3>Alumno no encontrado</h3>"

    nombre, dni = alumno_db

    # Obtener programas
    cur.execute("""
        SELECT tipo, nombre, promocion, sede, modalidad,
               duracion, fecha_inicio, fecha_fin, horas, pdf, qr
        FROM programas
        WHERE dni = %s
        ORDER BY fecha_inicio DESC
    """, (dni,))

    programas_db = cur.fetchall()

    programas = []

    for p in programas_db:
        programas.append({
            "tipo": p[0],
            "nombre": p[1],
            "promocion": p[2],
            "sede": p[3],
            "modalidad": p[4],
            "duracion": p[5],
            "fecha_inicio": p[6],
            "fecha_fin": p[7],
            "horas": p[8],
            "pdf": p[9] or "",
            "qr": p[10] or ""
        })

    cur.close()
    conn.close()

    alumno = {
        "nombre": nombre,
        "dni": dni,
        "programas": programas
    }

    return render_template("perfil.html", alumno=alumno, admin=session.get("admin"))

@app.route('/certificados/<path:filename>')
@login_required
def descargar_pdf(filename):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT 1 FROM programas WHERE pdf = %s",
            (f"certificados/{filename}",)
        )
        existe = cur.fetchone()

        if not existe:
            return "Archivo no autorizado"

        return send_from_directory(os.path.join(BASE_DIR, 'certificados'), filename)

    finally:
        cur.close()
        conn.close()

@app.route('/eliminar_programa/<dni>/<nombre>/<promocion>/<sede>')
@login_required
def eliminar_programa(dni, nombre, promocion, sede):

    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1 FROM programas
        WHERE dni = %s
        AND nombre = %s
        AND promocion = %s
        AND sede = %s
    """, (dni, nombre, promocion, sede))

    if not cur.fetchone():
        cur.close()
        conn.close()
        return "Programa no existe"

    # eliminar programa específico
    cur.execute("""
        DELETE FROM programas
        WHERE dni = %s
        AND nombre = %s
        AND promocion = %s
        AND sede = %s
    """, (dni, nombre, promocion, sede))

    # verificar si el alumno se quedó sin programas
    cur.execute("""
        SELECT COUNT(*) FROM programas WHERE dni = %s
    """, (dni,))

    cantidad = cur.fetchone()[0]

    if cantidad == 0:
        # eliminar alumno también
        cur.execute("DELETE FROM alumnos WHERE dni = %s", (dni,))

    conn.commit()
    cur.close()
    conn.close()

    next_page = request.args.get("next", "grupos")

    if next_page == "perfil":
        return redirect(f"/verificar/{dni}")

    return redirect("/grupos")

@app.route("/editar_programa/<dni>/<int:index>", methods=["GET", "POST"])
@login_required
def editar_programa(dni, index):

    if not session.get("admin"):
        return "<h3>Acceso restringido</h3>"

    conn = get_connection()
    cur = conn.cursor()

    if request.method == "POST":

        nombre = limpiar_texto(request.form["nombre"])
        promocion = limpiar_texto(request.form["promocion"])
        sede = limpiar_texto(request.form["sede"])
        duracion = limpiar_texto(request.form["duracion"])
        fecha_fin = request.form["fecha_fin"]
        horas = limpiar_texto(request.form["horas"])

        # ⚠️ AQUÍ NECESITAMOS LOS DATOS ORIGINALES
        nombre_original = request.form["nombre_original"]
        promocion_original = request.form["promocion_original"]
        sede_original = request.form["sede_original"]

        cur.execute("""
            UPDATE programas
            SET nombre=%s,
                promocion=%s,
                sede=%s,
                duracion=%s,
                fecha_fin=%s,
                horas=%s
            WHERE dni=%s
            AND nombre=%s
            AND promocion=%s
            AND sede=%s                   
        """, (
            nombre, promocion, sede,
            duracion, fecha_fin, horas,
            dni, nombre_original, promocion_original, sede_original
        ))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(f"/verificar/{dni}")

    # 🔍 OBTENER PROGRAMA (solo para mostrar)
    cur.execute("""
        SELECT nombre, promocion, sede, duracion, fecha_inicio, fecha_fin, horas
        FROM programas
        WHERE dni = %s
        ORDER BY nombre
        OFFSET %s LIMIT 1
    """, (dni,index))

    programa = cur.fetchone()

    cur.close()
    conn.close()

    if not programa:
        return "Programa no encontrado"

    return f"""
    <h2>Editar Programa</h2>

    <form method="post">
        <input type="hidden" name="nombre_original" value="{programa[0]}">
        <input type="hidden" name="promocion_original" value="{programa[1]}">
        <input type="hidden" name="sede_original" value="{programa[2]}">

        Nombre: <input name="nombre" value="{programa[0]}"><br><br>
        Promoción: <input name="promocion" value="{programa[1]}"><br><br>
        Sede: <input name="sede" value="{programa[2]}"><br><br>
        Duración: <input name="duracion" value="{programa[3]}"><br><br>
        Inicio: <input name="fecha_inicio" value="{programa[4]}"><br><br>
        Fin: <input name="fecha_fin" value="{programa[5]}"><br><br>
        Horas: <input name="horas" value="{programa[6]}"><br><br>

        <button type="submit">Guardar cambios</button>
    </form>

    <br><br>
    <a href="/verificar/{dni}">← Volver</a>
    """

@app.route("/editar_programa_ajax", methods=["POST"])
@login_required
def editar_programa_ajax():
    if not session.get("admin"):
        return jsonify({"error": "no autorizado"})

    dni = request.form.get("dni")

    nombre = limpiar_texto(request.form.get("nombre"))
    promocion = limpiar_texto(request.form.get("promocion"))
    sede = limpiar_texto(request.form.get("sede"))
    duracion = limpiar_texto(request.form.get("duracion"))
    fecha_inicio = request.form.get("fecha_inicio")
    fecha_fin = request.form.get("fecha_fin")
    horas = limpiar_texto(request.form.get("horas"))

    if not dni or not dni.isdigit():
        return jsonify({"error": "DNI inválido"})

    # ⚠️ datos originales (clave para ubicar registro)
    nombre_original = request.form.get("nombre_original")
    promocion_original = request.form.get("promocion_original")
    sede_original = request.form.get("sede_original")

    if not nombre_original or not promocion_original or not sede_original:
        return jsonify({"error": "DNI originales incompletos"})

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE programas
            SET nombre=%s,
                promocion=%s,
                sede=%s,
                duracion=%s,
                fecha_inicio=%s,
                fecha_fin=%s,
                horas=%s
            WHERE dni=%s
            AND nombre=%s
            AND promocion=%s
            AND sede=%s
        """, (
            nombre,
            promocion,
            sede,
            duracion,
            fecha_inicio,
            fecha_fin,
            horas,
            dni,
            nombre_original,
            promocion_original,
            sede_original
        ))

        if cur.rowcount == 0:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({"error": "No se encontró el registro para actualizar"})

        conn.commit()

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)})

    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/eliminar/<dni>")
@login_required
def eliminar(dni):
    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM alumnos WHERE dni = %s", (dni,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return "Alumno no existe"

    try:
        # eliminar programas del alumno
        cur.execute("""
            DELETE FROM programas WHERE dni = %s
        """, (dni,))

        # eliminar alumno
        cur.execute("""
            DELETE FROM alumnos WHERE dni = %s
        """, (dni,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return f"Error: {str(e)}"

    cur.close()
    conn.close()

    return redirect("/dashboard")

@app.route("/editar/<dni>", methods=["GET", "POST"])
@login_required
def editar(dni):
    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    if request.method == "POST":
        nuevo_nombre = limpiar_texto (request.form["nombre"])
        nuevo_dni = request.form["dni"]

        # 🔒 validar DNI
        if not nuevo_dni.isdigit() or len(nuevo_dni) not in [8, 9]:
            return "DNI inválido"
        
        # 🔍 verificar si ya existe otro alumno con ese DNI
        cur.execute("SELECT 1 FROM alumnos WHERE dni = %s AND dni != %s", (nuevo_dni, dni))
        if cur.fetchone():
            return "Ese DNI ya está registrado"

        try:
            # 🔥 actualizar alumno
            cur.execute("""
                UPDATE alumnos
                SET nombre = %s,
                    dni = %s
                WHERE dni = %s
            """, (nuevo_nombre, nuevo_dni, dni))

            # 🔥 actualizar programas (clave para no romper relación)
            cur.execute("""
                UPDATE programas
                SET dni = %s
                WHERE dni = %s
            """, (nuevo_dni, dni))

            conn.commit()

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return f"Error: {str(e)}"

        cur.close()
        conn.close()

        return redirect(f"/verificar/{nuevo_dni}")

    # 🔍 obtener alumno (igual que antes pero desde BD)
    cur.execute("""
        SELECT nombre, dni FROM alumnos WHERE dni = %s
    """, (dni,))

    alumno = cur.fetchone()

    cur.close()
    conn.close()

    if alumno:
        return f"""
        <h2>Editar Alumno</h2>
        <form method="post">
            Nombre: <input type="text" name="nombre" value="{alumno[0]}"><br><br>
            DNI: <input type="text" name="dni" value="{alumno[1]}"><br><br>
            <button type="submit">Guardar cambios</button>
        </form>
        """

    return "Alumno no encontrado"

@app.route("/reemplazar_pdf/<dni>/<nombre>/<promocion>/<sede>", methods=["POST"])
@login_required
def reemplazar_pdf(dni, nombre, promocion, sede):

    if not session.get("admin"):
        return "Acceso restringido"

    archivo = request.files.get("pdf")

    if not archivo or archivo.filename == "":
        return "No se envió archivo"

    # 🔒 VALIDAR QUE SEA PDF
    if not archivo.filename.lower().endswith(".pdf"):
        return "Solo se permiten archivos PDF"
    
    from werkzeug.utils import secure_filename

    import uuid

    filename = secure_filename(archivo.filename)

    # 🔥 nombre único (evita duplicados)
    nombre_unico = f"{dni}_{uuid.uuid4().hex}.pdf"

    ruta = os.path.join("certificados", nombre_unico)

    archivo.save(ruta)

    conn = get_connection()
    cur = conn.cursor()

    # 🔍 OBTENER PDF ANTERIOR
    cur.execute("""
        SELECT pdf FROM programas
        WHERE dni = %s
        AND nombre = %s
        AND promocion = %s
        AND sede = %s
    """, (dni, nombre, promocion, sede))

    resultado = cur.fetchone()

    if resultado:
        pdf_anterior = resultado[0]

        # 🔥 eliminar PDF anterior si existe (MISMA LÓGICA QUE TENÍAS)
        if pdf_anterior and os.path.exists(pdf_anterior):
            os.remove(pdf_anterior)

    # 🔥 guardar nuevo PDF en BD
    cur.execute("""
        UPDATE programas
        SET pdf = %s
        WHERE dni = %s
        AND nombre = %s
        AND promocion = %s
        AND sede = %s
    """, (ruta, dni, nombre, promocion, sede))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(f"/verificar/{dni}")

@app.route("/logout")
@login_required
def logout():
    session.pop("admin", None)
    return redirect("/")

from flask import jsonify
@app.route("/crear_evento", methods=["GET", "POST"])
@login_required
def crear_evento():
    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    if request.method == "POST":
        nombre = limpiar_texto(request.form["nombre"])

        try:
            cur.execute("""
                INSERT INTO eventos (nombre)
                VALUES (%s)
                ON CONFLICT (nombre) DO NOTHING
            """, (nombre,))

            conn.commit()

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return f"Error: {str(e)}"

        cur.close()
        conn.close()

        from flask import jsonify
        return jsonify({"mensaje": "Evento registrado correctamente"})

    # 🔍 obtener eventos
    cur.execute("SELECT nombre FROM eventos ORDER BY nombre")
    eventos_db = cur.fetchall()

    cur.close()
    conn.close()

    eventos = [{"nombre": e[0]} for e in eventos_db]

    return render_template("crear_evento.html", eventos=eventos)

@app.route("/eliminar_evento/<nombre>")
@login_required
def eliminar_evento(nombre):

    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM eventos WHERE nombre = %s
    """, (nombre,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/crear_evento")

@app.route("/grupos")
@login_required
def ver_grupos():

    if not session.get("admin"):
        return "Acceso restringido"

    conn = get_connection()
    cur = conn.cursor()

    # Filtros
    nombre_buscar = request.args.get("nombre", "").lower()
    promocion_buscar = request.args.get("promocion", "").lower()
    sede_buscar = request.args.get("sede", "").lower()

    # Consulta base
    cur.execute("""
        SELECT a.nombre, a.dni,
               p.nombre, p.promocion, p.sede
        FROM alumnos a
        JOIN programas p ON a.dni = p.dni
    """)

    datos = cur.fetchall()

    grupos = {}

    for row in datos:
        nombre_alumno = row[0]
        dni = row[1]
        nombre_evento = row[2]
        promocion = row[3]
        sede = row[4]

        # FILTROS
        if nombre_buscar and nombre_buscar not in nombre_evento.lower():
            continue

        if promocion_buscar and promocion_buscar not in promocion.lower():
            continue

        if sede_buscar and sede_buscar not in sede.lower():
            continue

        clave = f"{nombre_evento}|{promocion}|{sede}"

        if clave not in grupos:
            grupos[clave] = {
                "nombre": nombre_evento,
                "promocion": promocion,
                "sede": sede,
                "alumnos": []
            }

        grupos[clave]["alumnos"].append({
            "nombre": nombre_alumno,
            "dni": dni
        })

    cur.close()
    conn.close()

    return render_template(
        "grupos.html",
        grupos=list(grupos.values()),
        nombre_buscar=nombre_buscar,
        promocion_buscar=promocion_buscar,
        sede_buscar=sede_buscar
    )

@app.route("/carga_masiva", methods=["GET", "POST"])
@login_required
def carga_masiva():

    if not session.get("admin"):
        return "Acceso restringido"

    if request.method == "POST":
        archivo = request.files["archivo"]

        if archivo:
            df = pd.read_excel(archivo)

            # LIMPIAR ENCABEZADOS
            df.columns = df.columns.str.strip().str.upper()

            conn = get_connection()
            cur = conn.cursor()

            for _, row in df.iterrows():
                try:
                    dni = str(int(row["DNI"]))
                    nombre = limpiar_texto(row["NOMBRE"])

                    qr_filename = dni

                    # ======================
                    # TIPO EVENTO
                    # ======================
                    tipo_evento = str(row["TIPO_EVENTO"]).strip().upper()

                    if "PROG" in tipo_evento:
                        tipo_evento = "PROGRAMA"
                    elif "CUR" in tipo_evento:
                        tipo_evento = "CURSO"
                    elif "DIP" in tipo_evento:
                        tipo_evento = "DIPLOMADO"
                    elif "TALL" in tipo_evento:
                        tipo_evento = "TALLER"

                    nombre_evento = str(row["NOMBRE_EVENTO"]).upper()
                    promocion = str(row["PROMOCION"]).upper()
                    sede = str(row["SEDE"]).upper()
                    modalidad = str(row["MODALIDAD"]).upper()
                    duracion = str(row["DURACION"]).upper()
                    fecha_inicio = str(row["FECHA_INICIO"])
                    fecha_fin = str(row["FECHA_FIN"])
                    horas = str(row["HORAS"]).upper()

                    # ======================
                    # INSERTAR ALUMNO
                    # ======================
                    cur.execute("""
                        INSERT INTO alumnos (dni, nombre)
                        VALUES (%s, %s)
                        ON CONFLICT (dni) DO NOTHING
                    """, (dni, nombre))

                    # ======================
                    # VALIDAR DUPLICADO
                    # ======================
                    cur.execute("""
                        SELECT 1 FROM programas
                        WHERE dni=%s AND nombre=%s AND promocion=%s AND sede=%s AND tipo=%s
                    """, (dni, nombre_evento, promocion, sede, tipo_evento))

                    if cur.fetchone():
                        continue

                    # ======================
                    # INSERTAR PROGRAMA
                    # ======================
                    cur.execute("""
                        INSERT INTO programas (
                            dni, tipo, nombre, promocion, sede,
                            modalidad, duracion, fecha_inicio,
                            fecha_fin, horas, pdf, qr
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        dni, tipo_evento, nombre_evento, promocion, sede,
                        modalidad, duracion, fecha_inicio,
                        fecha_fin, horas, "", qr_filename
                    ))

                except Exception as e:
                    print("Error en fila:", e)

            conn.commit()
            cur.close()
            conn.close()

            from flask import jsonify
            return jsonify({"mensaje": "Excel cargado correctamente"})

    return render_template("masivo.html")

@app.route("/descargar_qr_grupo/<nombre>/<promocion>/<sede>")
@login_required
def descargar_qr_masivo(nombre, promocion, sede):

    if not session.get("admin"):
        return "Acceso restringido"

    from io import BytesIO

    # 🔥 CONEXIÓN A POSTGRESQL
    conn = get_connection()
    cur = conn.cursor()

    # 🔍 TRAER DATOS COMO TU JSON (nombre + qr)
    cur.execute("""
        SELECT a.nombre, p.qr
        FROM alumnos a
        JOIN programas p ON a.dni = p.dni
        WHERE p.nombre = %s
        AND p.promocion = %s
        AND p.sede = %s
    """, (nombre.upper(), promocion.upper(), sede.upper()))

    datos = cur.fetchall()

    cur.close()
    conn.close()

    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zipf:

        for nombre_alumno, qr_filename in datos:

            if qr_filename:

                ruta_qr = os.path.join("qr", qr_filename)

                if os.path.exists(ruta_qr):

                    # 🔥 MISMO COMPORTAMIENTO QUE TU CÓDIGO
                    nombre_archivo = f'{nombre_alumno}.png'

                    zipf.write(ruta_qr, nombre_archivo)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=f"{nombre}{promocion}{sede}.zip",
        mimetype="application/zip"
    )

@app.route("/generar_certificados", methods=["GET", "POST"])
@login_required
def generar_certificados():
    if not session.get("admin"):
        return redirect("/login")

    if request.method == "POST":
        evento = request.form["evento"]
        promocion = request.form["promocion"]
        sede = request.form["sede"]
        archivo = request.files.get("modelo")

        if archivo and archivo.filename != "":
            archivo.save(os.path.join(BASE_DIR, "certificado_base.jpg"))

        generar_certificados_grupo(evento, promocion, sede)

        from flask import jsonify
        return jsonify({"mensaje": "Certificados generados correctamente"})

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT nombre FROM eventos ORDER BY nombre")
    eventos_db = cur.fetchall()

    cur.close()
    conn.close()

    eventos = [{"nombre": e[0]} for e in eventos_db]

    return render_template("certificados.html", eventos=eventos)

@app.route("/subir_modelo", methods=["POST"])
@login_required
def subir_modelo():
    if not session.get("admin"):
        return "Acceso restringido"

    archivo = request.files["modelo"]

    if archivo:
        archivo.save(os.path.join(BASE_DIR, "certificado_base.jpg"))

    return redirect("/generar_certificados")

@app.route("/dashboard")
@login_required
def dashboard():
    if not session.get("admin"):
        return redirect("/login")
    return render_template("dashboard.html", usuario="Admin")

@app.route("/editar_alumno_ajax", methods=["POST"])
@login_required
def editar_alumno_ajax():
    if not session.get("admin"):
        return jsonify({"error": "no autorizado"})

    dni_original = request.form["dni_original"]
    nuevo_dni = request.form["dni"]
    nuevo_nombre = limpiar_texto(request.form["nombre"])

    conn = get_connection()
    cur = conn.cursor()

    try:
        # actualizar alumno
        cur.execute("""
            UPDATE alumnos
            SET dni = %s,
                nombre = %s
            WHERE dni = %s
        """, (nuevo_dni, nuevo_nombre, dni_original))

        # actualizar programas (IMPORTANTE)
        cur.execute("""
            UPDATE programas
            SET dni = %s
            WHERE dni = %s
        """, (nuevo_dni, dni_original))

        conn.commit()

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)})

    cur.close()
    conn.close()

    return jsonify({"ok": True})

@app.route("/certificados_doble", methods=["GET", "POST"])
@login_required
def certificados_doble():
    if not session.get("admin"):
        return "<h3>Acceso restringido</h3>"

    if request.method == "POST":

        frontal = request.files["frontal"]
        trasero = request.files["trasero"]
        excel = request.files["excel"]

        # 📸 GUARDAR FOTOS SUBIDAS (OPCIONAL)
        if 'fotos[]' in request.files:
            fotos = request.files.getlist('fotos[]')

            for foto in fotos:
                if foto.filename != "":
                    ruta = os.path.join("fotos", foto.filename)
                    foto.save(ruta)

        # CREAR CARPETAS SI NO EXISTEN
        os.makedirs("temp", exist_ok=True)
        os.makedirs("salida", exist_ok=True)
        os.makedirs("fotos", exist_ok=True)

        # GUARDAR ARCHIVOS
        ruta_frontal = os.path.join("temp", frontal.filename)
        ruta_trasero = os.path.join("temp", trasero.filename)
        ruta_excel = os.path.join("temp", excel.filename)

        frontal.save(ruta_frontal)
        trasero.save(ruta_trasero)
        excel.save(ruta_excel)

        # LEER EXCEL
        df = pd.read_excel(ruta_excel)

        alumnos = []

        for _, fila in df.iterrows():
            alumno = {
                "dni": str(fila["dni"]),
                "nombre": fila["nombre"],
                "modulos": []
            }

            i = 1
            while True:
                col_modulo = f"modulo_{i}"
                col_nota = f"nota_{i}"
                col_horas = f"horas_{i}"

                if col_modulo in df.columns:
                    modulo = fila.get(col_modulo)
                    nota = fila.get(col_nota)
                    horas = fila.get(col_horas)

                    if pd.notna(modulo):
                        alumno["modulos"].append({
                            "nombre": modulo,
                            "nota": nota,
                            "horas": horas
                        })

                    i += 1
                else:
                    break

            alumnos.append(alumno)

        for a in alumnos:

            # ABRIR IMAGEN BASE
            img = Image.open(ruta_frontal).convert("RGB")
            draw = ImageDraw.Draw(img)

            # ===== IMAGEN TRASERA =====
            img_back = Image.open(ruta_trasero).convert("RGB")
            draw_back = ImageDraw.Draw(img_back)

            # ===== GENERAR QR AUTOMÁTICO =====
            try:
                if PUBLIC_BASE_URL:
                    url = f"{PUBLIC_BASE_URL}/verificar/{a['dni']}"
                else:
                    url = f"http://127.0.0.1:5000/verificar/{a['dni']}"

                qr = qrcode.make(url)
                qr = qr.convert("RGB")

                # tamaño
                qr = qr.resize((100, 100))

                # posición (SE MANTIENE)
                qr_x = 610
                qr_y = 570

                img_back.paste(qr, (qr_x, qr_y))

            except:
                pass

            # ===== TABLA DE MÓDULOS =====
            modulos = a["modulos"]

            # ===== CALCULAR PROMEDIO Y HORAS =====
            notas = []
            horas_lista = []

            for m in modulos:
                if m["nota"] is not None and pd.notna(m["nota"]):
                    notas.append(float(m["nota"]))
                if m["horas"] is not None and pd.notna(m["horas"]):
                    horas_lista.append(float(m["horas"]))

            promedio = round(sum(notas) / len(notas)) if len(notas) > 0 else 0
            total_horas = int(sum(horas_lista)) if len(horas_lista) > 0 else 0
            promedio_texto = numero_a_letras(promedio)

            # TAMAÑO DE IMAGEN
            ancho_img_back, alto_img_back = img_back.size

            # ESPACIOS
            margin_x = 40
            margin_top = 80
            margin_bottom = 180

            # ÁREA DISPONIBLE
            area_ancho = ancho_img_back - (margin_x * 2)
            area_alto = alto_img_back - margin_top - margin_bottom

            # COLUMNAS
            col_modulo_w = int(area_ancho * 0.6)
            col_nota_w = int(area_ancho * 0.2)
            col_horas_w = int(area_ancho * 0.2)

            # ALTURA DINÁMICA
            total_filas = len(modulos) + 1
            alto_fila = int(area_alto / total_filas) if total_filas > 0 else 40

            # POSICIÓN INICIAL
            x_inicio = margin_x
            y_inicio = margin_top

            # FUENTE TABLA
            try:
                font_tabla = ImageFont.truetype(ruta_fuente, 22)
            except:
                font_tabla = ImageFont.load_default()

            # ===== ENCABEZADO =====
            headers = ["MÓDULO", "NOTA", "HORAS"]

            for i, text in enumerate(headers):
                if i == 0:
                    ancho_col = col_modulo_w
                    x = x_inicio
                elif i == 1:
                    ancho_col = col_nota_w
                    x = x_inicio + col_modulo_w
                else:
                    ancho_col = col_horas_w
                    x = x_inicio + col_modulo_w + col_nota_w

                bbox = draw_back.textbbox((0, 0), text, font=font_tabla)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                tx = x + (ancho_col - text_w) / 2
                ty = y_inicio + (alto_fila - text_h) / 2

                draw_back.text((tx, ty), text, fill="black", font=font_tabla)

                draw_back.rectangle(
                    [x, y_inicio, x + ancho_col, y_inicio + alto_fila],
                    outline="black",
                    width=2
                )

            # ===== FILAS =====
            y = y_inicio + alto_fila

            for m in modulos:
                datos = [
                    str(m["nombre"]),
                    str(m["nota"]),
                    str(m["horas"])
                ]

                for i, text in enumerate(datos):
                    if i == 0:
                        ancho_col = col_modulo_w
                        x = x_inicio
                    elif i == 1:
                        ancho_col = col_nota_w
                        x = x_inicio + col_modulo_w
                    else:
                        ancho_col = col_horas_w
                        x = x_inicio + col_modulo_w + col_nota_w

                    bbox = draw_back.textbbox((0, 0), text, font=font_tabla)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]

                    tx = x + (ancho_col - text_w) / 2
                    ty = y + (alto_fila - text_h) / 2

                    draw_back.text((tx, ty), text, fill="black", font=font_tabla)

                    draw_back.rectangle(
                        [x, y, x + ancho_col, y + alto_fila],
                        outline="black",
                        width=1
                    )

                y += alto_fila

            # ===== TEXTO FINAL =====
            try:
                font_estilo = ImageFont.truetype(ruta_fuente, 28)
            except:
                font_estilo = font_tabla

            try:
                font_normal = ImageFont.truetype(ruta_fuente, 24)
            except:
                font_normal = font_tabla

            try:
                font_estilo_small = ImageFont.truetype(ruta_fuente, 20)
            except:
                font_estilo_small = font_estilo

            x_label = x_inicio
            x_dospuntos = x_label + 200
            x_valor = x_dospuntos + 20

            y_label = y + 40

            draw_back.text((x_label, y_label), "PROMEDIO FINAL", fill="black", font=font_estilo_small)
            draw_back.text((x_dospuntos, y_label), ":", fill="black", font=font_estilo_small)
            draw_back.text((x_valor, y_label), f"{promedio} ({promedio_texto})", fill="black", font=font_estilo_small)

            draw_back.text((x_label, y_label + 40), "TOTAL HORAS", fill="black", font=font_estilo_small)
            draw_back.text((x_dospuntos, y_label + 40), ":", fill="black", font=font_estilo_small)
            draw_back.text((x_valor, y_label + 40), f"{total_horas} HORAS ACADÉMICAS", fill="black", font=font_estilo_small)

            # ===== FOTO DEL ALUMNO =====
            try:
                ruta_foto = f"fotos/{a['dni']}.jpeg"

                # TAMAÑO
                ancho_foto = 120
                alto_foto = 150

                # POSICIÓN (SE MANTIENE)
                pos_x = 40
                pos_y = 550

                if os.path.exists(ruta_foto):
                    foto = Image.open(ruta_foto).convert("RGB")
                    foto = foto.resize((ancho_foto, alto_foto))
                    img.paste(foto, (pos_x, pos_y))
                else:
                    draw.rectangle(
                        [pos_x, pos_y, pos_x + ancho_foto, pos_y + alto_foto],
                        outline=(0, 0, 0),
                        width=2
                    )
            except:
                pass

            # ===== TEXTO NOMBRE FRONTAL =====
            nombre = str(a["nombre"])

            # TAMAÑO DE LA IMAGEN
            ancho_img, alto_img = img.size

            # TAMAÑO INICIAL
            tamano_max = 65
            tamano_min = 40
            tamano_fuente = tamano_max

            # FUENTE
            try:
                font = ImageFont.truetype(ruta_fuente, tamano_fuente)
            except:
                font = ImageFont.load_default()

            # AJUSTE CONTROLADO
            while True:
                bbox = draw.textbbox((0, 0), nombre, font=font)
                ancho_texto = bbox[2] - bbox[0]

                if ancho_texto <= ancho_img * 0.75:
                    break

                tamano_fuente -= 2

                if tamano_fuente <= tamano_min:
                    tamano_fuente = tamano_min
                    try:
                        font = ImageFont.truetype(ruta_fuente, tamano_fuente)
                    except:
                        font = ImageFont.load_default()
                    bbox = draw.textbbox((0, 0), nombre, font=font)
                    ancho_texto = bbox[2] - bbox[0]
                    break

                try:
                    font = ImageFont.truetype(ruta_fuente, tamano_fuente)
                except:
                    font = ImageFont.load_default()

            # CENTRAR
            x = (ancho_img - ancho_texto) / 2

            # POSICIÓN VERTICAL (SE MANTIENE)
            y = 265

            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    draw.text((x + dx, y + dy), nombre, fill=(20, 20, 20), font=font)

            # GUARDAR JPGS
            ruta_salida = f"salida/{a['dni']}_frontal.jpg"
            img.save(ruta_salida)

            ruta_salida_back = f"salida/{a['dni']}_trasero.jpg"
            img_back.save(ruta_salida_back)

        # PDF FRONTALES
        img_temp = Image.open(ruta_frontal)
        ancho, alto = img_temp.size
        pdf_frontal = canvas.Canvas("salida/frontales.pdf", pagesize=(ancho, alto))

        for a in alumnos:
            ruta = f"salida/{a['dni']}_frontal.jpg"
            pdf_frontal.drawImage(ruta, 0, 0, width=ancho, height=alto)
            pdf_frontal.showPage()

        pdf_frontal.save()

        # PDF TRASEROS
        img_temp = Image.open(ruta_trasero)
        ancho, alto = img_temp.size
        pdf_trasero = canvas.Canvas("salida/traseros.pdf", pagesize=(ancho, alto))

        for a in alumnos:
            ruta = f"salida/{a['dni']}_trasero.jpg"
            pdf_trasero.drawImage(ruta, 0, 0, width=ancho, height=alto)
            pdf_trasero.showPage()

        pdf_trasero.save()

        # LIMPIAR JPGS TEMPORALES
        for a in alumnos:
            ruta_f = f"salida/{a['dni']}_frontal.jpg"
            ruta_b = f"salida/{a['dni']}_trasero.jpg"

            if os.path.exists(ruta_f):
                os.remove(ruta_f)

            if os.path.exists(ruta_b):
                os.remove(ruta_b)

        return """
        <h3>✅ Certificados generados</h3>
        <p>📁 Revisa la carpeta /salida</p>

        <a href="/salida/frontales.pdf" target="_blank">📄 Descargar PDF Frontales</a><br><br>
        <a href="/salida/traseros.pdf" target="_blank">📄 Descargar PDF Traseros</a><br><br>

        <a href="/certificados_doble">⬅ Volver</a>
        """

    return render_template("certificados_doble.html")

@app.route('/salida/<path:filename>')
@login_required
def descargar_archivo(filename):
    return send_from_directory('salida', filename)
try:
    conn = get_connection()
    print("Conectado a PostgreSQL")
    conn.close()
except Exception as e: 
    print("Error de conexión:", e)

@app.route("/subir_pdf/<dni>/<int:index>", methods=["POST"])
@login_required
def subir_pdf(dni, index):

    if not session.get("admin"):
        return "No autorizado"

    archivo = request.files.get("pdf")

    if not archivo:
        return "No se envió archivo"

    carpeta = "static/pdfs"
    os.makedirs(carpeta, exist_ok=True)

    nombre_archivo = f"{dni}_{index}.pdf"
    ruta = os.path.join(carpeta, nombre_archivo)

    archivo.save(ruta)

    conn = get_connection()
    cur = conn.cursor()

    # 🔥 obtenemos el programa correcto
    cur.execute("""
        SELECT nombre, promocion, sede
        FROM programas
        WHERE dni = %s
        ORDER BY nombre
    """, (dni,))

    programas = cur.fetchall()

    if index >= len(programas):
        return "Índice inválido"

    prog = programas[index]

    # 🔥 actualizamos solo ese programa
    cur.execute("""
        UPDATE programas
        SET pdf = %s
        WHERE dni = %s
        AND nombre = %s
        AND promocion = %s
        AND sede = %s
    """, (ruta, dni, prog[0], prog[1], prog[2]))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(f"/verificar/{dni}")

@app.route("/qr_dinamico/<dni>")
def qr_dinamico(dni):
    if not dni.isdigit() or len(dni) not in [8, 9]:
        return "DNI inválido", 400

    if PUBLIC_BASE_URL:
        url = f"{PUBLIC_BASE_URL}/verificar/{dni}"
    else:
        url = request.host_url.rstrip("/") + f"/verificar/{dni}"

    img = qrcode.make(url)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")

# ================================
# EJECUTAR
# ================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)