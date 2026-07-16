import os
from openai import OpenAI

archivo = False

for file in os.listdir("/home/marlon/Documents/FIS/.github/"):
    if '.txt' in file:
        archivo =  True

print('Existe el archivo:', archivo, '+30pts')

# rubrica para llm
fichero = open("/home/marlon/Documents/FIS/.github/rubrica_prueba.md", "r")

# poema a comparar
fichero2 = open("/home/marlon/Documents/FIS/.github/flor.txt", "r")
    
# Inicializar el cliente OpenAI apuntando a DeepSeek
client = OpenAI(api_key=os.environ.get('DEEPSEEK_API_KEY'),
                base_url="https://api.deepseek.com")

# Definir los mensajes de la conversación
messages = [
    {"role": "system", "content": fichero.read()},
    {"role": "user", "content": "El poema a evaluar es el siguiente:\n" + fichero2.read()}
]

# Realizar la solicitud de chat completion
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=messages,
    stream=False  # Solicitar respuesta completa (no en streaming)
)

# Extraer y mostrar la respuesta del asistente
print(response.choices[0].message.content)

