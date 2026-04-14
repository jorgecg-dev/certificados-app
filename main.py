import os
import subprocess
import qrcode

archivo = "alumnos.txt"
alumnos = []

# =========================
# VALIDAR DNI
# =========================
def validar_dni(dni):
    return dni.isdigit() and len(dni) == 8

# =========================
# GENERAR QR
# =========================
def generar_qr(dni):
    ruta = f"qr/{dni}.png"
    url = f"http://tusistema.com/verificar/{dni}"

    img = qrcode.make(url)
    img.save(ruta)

    print("QR generado en:", ruta)

# =========================
# ABRIR PDF
# =========================
def abrir_pdf(ruta):
    if os.path.exists(ruta):
        try:
            os.startfile(ruta)
        except:
            subprocess.run(["xdg-open", ruta])
    else:
        print("Archivo no encontrado")

# =========================
# GUARDAR DATOS
# =========================
def guardar():
    with open(archivo, "w") as f:
        for alumno in alumnos:
            programas = []
            for p in alumno["programas"]:
                programas.append(f"{p['nombre']};{p['pdf']}")
            linea = "|".join(programas)
            f.write(f"{alumno['nombre']},{alumno['dni']},{linea}\n")

# =========================
# CARGAR DATOS
# =========================
if os.path.exists(archivo):
    with open(archivo, "r") as f:
        for linea in f:
            linea = linea.strip()
            if linea == "":
                continue

            partes = linea.split(",")

            nombre = partes[0]
            dni = partes[1]
            programas = []

            if len(partes) == 3:
                lista = partes[2].split("|")

                for p in lista:
                    datos = p.split(";")
                    if len(datos) == 2:
                        programas.append({
                            "nombre": datos[0],
                            "pdf": datos[1]
                        })

            alumnos.append({
                "nombre": nombre,
                "dni": dni,
                "programas": programas
            })

# =========================
# MENÚ
# =========================
print("===== SISTEMA =====")
print("1. Registrar alumno")
print("2. Ver perfil del alumno")

opcion = input("Seleccione opción: ")

# =========================
# REGISTRAR ALUMNO
# =========================
if opcion == "1":
    nombre = input("Nombre: ")
    dni = input("DNI: ")

    if not validar_dni(dni):
        print("DNI inválido")

    else:
        existe = False

        for alumno in alumnos:
            if alumno["dni"] == dni:
                existe = True
                print("Alumno ya existe, se agregará programa")
                break

        if not existe:
            alumnos.append({
                "nombre": nombre,
                "dni": dni,
                "programas": []
            })

            generar_qr(dni)

        # AGREGAR PROGRAMA
        for alumno in alumnos:
            if alumno["dni"] == dni:

                programa = input("Programa: ")
                pdf = input("Ruta del PDF: ")

                alumno["programas"].append({
                    "nombre": programa,
                    "pdf": pdf
                })

                guardar()
                print("Programa registrado correctamente")
                break

# =========================
# VER PERFIL
# =========================
elif opcion == "2":
    dni = input("Ingrese DNI: ")

    if not validar_dni(dni):
        print("DNI inválido")

    else:
        for alumno in alumnos:
            if alumno["dni"] == dni:

                print("\n===== PERFIL =====")
                print("Nombre:", alumno["nombre"])
                print("DNI:", alumno["dni"])

                print("\nProgramas:")
                for i, p in enumerate(alumno["programas"]):
                    print(f"{i+1}. {p['nombre']}  → Descargar PDF")

                ver = input("\n¿Ver detalle de programa? (s/n): ")

                if ver.lower() == "s":
                    num = int(input("Seleccione número: ")) - 1

                    programa = alumno["programas"][num]

                    print("\n--- DETALLE ---")
                    print("Programa:", programa["nombre"])
                    print("Archivo:", programa["pdf"])

                    abrir = input("¿Abrir PDF? (s/n): ")
                    if abrir.lower() == "s":
                        abrir_pdf(programa["pdf"])

                break
        else:
            print("Alumno no encontrado")

else:
    print("Opción inválida")