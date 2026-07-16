import os
import json
import argparse
from openai import OpenAI

parser = argparse.ArgumentParser()
parser.add_argument('--repository', type=str, required=True)
parser.add_argument('--required-files', type=str, required=True)

args = parser.parse_args()

carpeta = args.repository

archivos_requeridos = args.required_files.split(',')

archivo = False

todos_existentes = all(
    os.path.isfile(os.path.join(carpeta, archivo))
    for archivo in archivos_requeridos
)

if todos_existentes:
    # Rúbrica para el LLM
    ruta_rubrica = "calificador/classroom/rubrica.md"

    with open(ruta_rubrica, "r", encoding="utf-8") as fichero:
        rubrica = fichero.read()

    for archivo in archivos_requeridos:
        with open(
            os.path.join(carpeta, archivo),
            "r",
            encoding="utf-8"
        ) as fichero2:

            # Inicializar el cliente OpenAI apuntando a DeepSeek
            client = OpenAI(
                api_key=os.environ.get('DEEPSEEK_API_KEY'),
                base_url="https://api.deepseek.com"
            )

            # Definir los mensajes de la conversación
            messages = [
                {
                    "role": "system",
                    "content": rubrica
                },
                {
                    "role": "user",
                    "content": (
                        "El archivo a evaluar es el siguiente:\n"
                        + fichero2.read()
                    )
                }
            ]

            # Realizar la solicitud de chat completion
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                stream=False
            )

            # Obtener la respuesta del LLM
            respuesta_llm = response.choices[0].message.content

            # Mostrarla en la consola
            print(respuesta_llm)

            # Crear el contenido que tendrá el JSON
            resultado = {
                "archivo_evaluado": archivo,
                "respuesta_llm": respuesta_llm
            }

            # Guardar el resultado en un archivo JSON
            with open(
                "resultado.json",
                "w",
                encoding="utf-8"
            ) as fichero_json:
                json.dump(
                    resultado,
                    fichero_json,
                    indent=4,
                    ensure_ascii=False
                )

            print("La evaluación se guardó en resultado.json")