import streamlit as st
import sqlite3
import pandas as pd
import os
import json
import re
from docx import Document
from dotenv import load_dotenv
from google import genai

load_dotenv()

DB_NAME = "reclutamiento.db"
API_KEY = os.getenv("GEMINI_API_KEY")

if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    client = None

def conectar():
    return sqlite3.connect(DB_NAME)

def crear_tablas():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plazas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            puesto TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            requisitos TEXT NOT NULL,
            habilidades TEXT NOT NULL,
            experiencia TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candidatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            correo TEXT,
            texto_cv TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analisis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plaza_id INTEGER NOT NULL,
            candidato_id INTEGER NOT NULL,
            porcentaje INTEGER NOT NULL,
            coincidencias TEXT NOT NULL,
            faltantes TEXT NOT NULL,
            explicacion TEXT NOT NULL,
            recomendacion TEXT NOT NULL,
            preguntas TEXT NOT NULL,
            FOREIGN KEY (plaza_id) REFERENCES plazas(id),
            FOREIGN KEY (candidato_id) REFERENCES candidatos(id)
        )
    """)

    conexion.commit()
    conexion.close()

def guardar_plaza(puesto, descripcion, requisitos, habilidades, experiencia):
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("""
        INSERT INTO plazas (puesto, descripcion, requisitos, habilidades, experiencia)
        VALUES (?, ?, ?, ?, ?)
    """, (puesto, descripcion, requisitos, habilidades, experiencia))
    conexion.commit()
    conexion.close()

def guardar_candidato(nombre, correo, texto_cv):
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("""
        INSERT INTO candidatos (nombre, correo, texto_cv)
        VALUES (?, ?, ?)
    """, (nombre, correo, texto_cv))
    conexion.commit()
    conexion.close()

def obtener_plazas():
    conexion = conectar()
    df = pd.read_sql_query("SELECT * FROM plazas ORDER BY id DESC", conexion)
    conexion.close()
    return df

def obtener_candidatos():
    conexion = conectar()
    df = pd.read_sql_query("SELECT * FROM candidatos ORDER BY id DESC", conexion)
    conexion.close()
    return df

def guardar_analisis(plaza_id, candidato_id, resultado):
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("""
        DELETE FROM analisis
        WHERE plaza_id = ? AND candidato_id = ?
    """, (plaza_id, candidato_id))

    cursor.execute("""
        INSERT INTO analisis (
            plaza_id,
            candidato_id,
            porcentaje,
            coincidencias,
            faltantes,
            explicacion,
            recomendacion,
            preguntas
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        plaza_id,
        candidato_id,
        resultado["porcentaje"],
        resultado["coincidencias"],
        resultado["faltantes"],
        resultado["explicacion"],
        resultado["recomendacion"],
        resultado["preguntas"]
    ))

    conexion.commit()
    conexion.close()

def obtener_ranking(plaza_id):
    conexion = conectar()
    query = """
        SELECT 
            c.nombre AS candidato,
            c.correo AS correo,
            a.porcentaje AS compatibilidad,
            a.coincidencias,
            a.faltantes,
            a.explicacion,
            a.recomendacion,
            a.preguntas
        FROM analisis a
        INNER JOIN candidatos c ON c.id = a.candidato_id
        WHERE a.plaza_id = ?
        ORDER BY a.porcentaje DESC
    """
    df = pd.read_sql_query(query, conexion, params=(plaza_id,))
    conexion.close()
    return df

def extraer_texto_docx(archivo):
    documento = Document(archivo)
    texto = []

    for parrafo in documento.paragraphs:
        contenido = parrafo.text.strip()
        if contenido:
            texto.append(contenido)

    return "\n".join(texto)

def limpiar_json(respuesta):
    texto = respuesta.strip()
    texto = texto.replace("```json", "")
    texto = texto.replace("```", "")
    inicio = texto.find("{")
    fin = texto.rfind("}")

    if inicio != -1 and fin != -1:
        texto = texto[inicio:fin + 1]

    return json.loads(texto)

def analizar_con_gemini(plaza, candidato):
    if client is None:
        raise ValueError("No se encontró la API Key de Gemini.")

    prompt = f"""
Analiza la compatibilidad entre esta plaza laboral y este CV.

Devuelve únicamente un JSON válido con esta estructura:

{{
  "porcentaje": 0,
  "coincidencias": "texto",
  "faltantes": "texto",
  "explicacion": "texto",
  "recomendacion": "texto",
  "preguntas": "texto"
}}

Reglas:
El porcentaje debe ser un número entero entre 0 y 100.
No agregues texto antes ni después del JSON.
La explicación debe ser clara y breve.
Las preguntas deben servir para una entrevista laboral.

PLAZA:
Puesto: {plaza["puesto"]}
Descripción: {plaza["descripcion"]}
Requisitos: {plaza["requisitos"]}
Habilidades: {plaza["habilidades"]}
Experiencia: {plaza["experiencia"]}

CV:
Nombre: {candidato["nombre"]}
Correo: {candidato["correo"]}
Contenido del CV:
{candidato["texto_cv"]}
"""

    respuesta = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    resultado = limpiar_json(respuesta.text)

    return {
        "porcentaje": int(resultado.get("porcentaje", 0)),
        "coincidencias": str(resultado.get("coincidencias", "")),
        "faltantes": str(resultado.get("faltantes", "")),
        "explicacion": str(resultado.get("explicacion", "")),
        "recomendacion": str(resultado.get("recomendacion", "")),
        "preguntas": str(resultado.get("preguntas", ""))
    }

def responder_chatbot(pregunta, plaza, ranking):
    if client is None:
        raise ValueError("No se encontró la API Key de Gemini.")

    contexto = ranking.to_string(index=False)

    prompt = f"""
Responde la pregunta del usuario usando únicamente la información de la plaza y el ranking de candidatos.

PLAZA:
{plaza}

RANKING:
{contexto}

PREGUNTA:
{pregunta}

Responde en español, de forma clara y breve.
"""

    respuesta = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return respuesta.text

crear_tablas()

st.set_page_config(page_title="Sistema Inteligente de Reclutamiento", layout="wide")

st.title("Sistema Inteligente de Reclutamiento con IA")

menu = st.sidebar.radio(
    "Menú",
    [
        "Registrar plaza",
        "Cargar CV",
        "Analizar compatibilidad",
        "Ranking",
        "Chatbot"
    ]
)

if menu == "Registrar plaza":
    st.header("Registrar plaza laboral")

    puesto = st.text_input("Nombre del puesto")
    descripcion = st.text_area("Descripción de la plaza")
    requisitos = st.text_area("Requisitos")
    habilidades = st.text_area("Habilidades requeridas")
    experiencia = st.text_input("Experiencia mínima")

    if st.button("Guardar plaza"):
        if puesto and descripcion and requisitos and habilidades and experiencia:
            guardar_plaza(puesto, descripcion, requisitos, habilidades, experiencia)
            st.success("Plaza guardada correctamente.")
        else:
            st.warning("Completa todos los campos.")

    plazas = obtener_plazas()

    if not plazas.empty:
        st.subheader("Plazas registradas")
        st.dataframe(plazas)

if menu == "Cargar CV":
    st.header("Cargar CV de candidato")

    nombre = st.text_input("Nombre del candidato")
    correo = st.text_input("Correo del candidato")
    archivo = st.file_uploader("Subir CV en Word .docx", type=["docx"])
    texto_manual = st.text_area("O pegar texto del CV manualmente", height=250)

    texto_cv = ""

    if archivo is not None:
        texto_cv = extraer_texto_docx(archivo)
        st.subheader("Texto extraído del Word")
        st.text_area("Contenido extraído", texto_cv, height=250)

    if texto_manual.strip():
        texto_cv = texto_manual.strip()

    if st.button("Guardar candidato"):
        if nombre and texto_cv:
            guardar_candidato(nombre, correo, texto_cv)
            st.success("Candidato guardado correctamente.")
        else:
            st.warning("Ingresa el nombre y el contenido del CV.")

    candidatos = obtener_candidatos()

    if not candidatos.empty:
        st.subheader("Candidatos registrados")
        st.dataframe(candidatos[["id", "nombre", "correo"]])

if menu == "Analizar compatibilidad":
    st.header("Analizar compatibilidad")

    plazas = obtener_plazas()
    candidatos = obtener_candidatos()

    if plazas.empty or candidatos.empty:
        st.warning("Debes registrar al menos una plaza y un candidato.")
    else:
        plaza_opcion = st.selectbox(
            "Selecciona una plaza",
            plazas["id"].astype(str) + " - " + plazas["puesto"]
        )

        plaza_id = int(plaza_opcion.split(" - ")[0])

        if st.button("Analizar todos los candidatos para esta plaza"):
            plaza = plazas[plazas["id"] == plaza_id].iloc[0].to_dict()

            barra = st.progress(0)
            total = len(candidatos)

            for indice, candidato_fila in candidatos.iterrows():
                candidato = candidato_fila.to_dict()

                try:
                    resultado = analizar_con_gemini(plaza, candidato)
                    guardar_analisis(plaza_id, candidato["id"], resultado)
                except Exception as e:
                    st.error(f"Error con {candidato['nombre']}: {e}")

                avance = int(((indice + 1) / total) * 100)
                barra.progress(avance)

            st.success("Análisis finalizado.")

if menu == "Ranking":
    st.header("Ranking de candidatos")

    plazas = obtener_plazas()

    if plazas.empty:
        st.warning("No hay plazas registradas.")
    else:
        plaza_opcion = st.selectbox(
            "Selecciona una plaza",
            plazas["id"].astype(str) + " - " + plazas["puesto"]
        )

        plaza_id = int(plaza_opcion.split(" - ")[0])
        ranking = obtener_ranking(plaza_id)

        if ranking.empty:
            st.info("Todavía no hay análisis para esta plaza.")
        else:
            st.dataframe(ranking)

            mejor = ranking.iloc[0]

            st.subheader("Mejor candidato")
            st.metric("Candidato", mejor["candidato"])
            st.metric("Compatibilidad", f"{mejor['compatibilidad']}%")

            st.write("Coincidencias")
            st.write(mejor["coincidencias"])

            st.write("Faltantes")
            st.write(mejor["faltantes"])

            st.write("Explicación")
            st.write(mejor["explicacion"])

            st.write("Recomendación")
            st.write(mejor["recomendacion"])

            st.write("Preguntas sugeridas")
            st.write(mejor["preguntas"])

if menu == "Chatbot":
    st.header("Chatbot sobre plazas y candidatos")

    plazas = obtener_plazas()

    if plazas.empty:
        st.warning("No hay plazas registradas.")
    else:
        plaza_opcion = st.selectbox(
            "Selecciona una plaza",
            plazas["id"].astype(str) + " - " + plazas["puesto"]
        )

        plaza_id = int(plaza_opcion.split(" - ")[0])
        plaza = plazas[plazas["id"] == plaza_id].iloc[0].to_dict()
        ranking = obtener_ranking(plaza_id)

        if ranking.empty:
            st.info("Primero debes analizar candidatos para esta plaza.")
        else:
            pregunta = st.text_input("Haz una pregunta")

            if st.button("Preguntar"):
                if pregunta:
                    try:
                        respuesta = responder_chatbot(pregunta, plaza, ranking)
                        st.write(respuesta)
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("Escribe una pregunta.")