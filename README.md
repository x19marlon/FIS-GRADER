# FIS Grader Telegram Bot

The Telegram bot provides quick access to repository activity stored in MongoDB Atlas.

It currently supports repository summaries, commits, student activity, analysis history, and Excel report generation.

## Setup

Use Python 3.12 (the version used by GitHub Actions). Create and activate the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Debian/Ubuntu, if this fails because `ensurepip` is unavailable, install
`python3.12-venv` first (for example, `sudo apt install python3.12-venv`).

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Set the required environment variables:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export MONGODB_URI="your_mongodb_uri"
export TELEGRAM_ALLOWED_USER_IDS="your_telegram_user_id"
```

## Run the Bot

From the project root:

```bash
python src/telegram/bot.py
```

Stop it with:

```bash
Ctrl+C
```

## Telegram Commands

```text
/whoami
/groups
/summary G1
/commits G1
/commits G1 5
/history G1
/student student@email.com
/excel G1
/ask ¿Cuál es el puntaje máximo de la rúbrica?
```

### Excel Reports

The `/excel` command generates and sends an `.xlsx` report containing:

* Overview and group metrics
* Author activity
* Repository commits
* Analysis history
* Activity charts

Example:

```text
/excel G1
```

The generated file is sent directly through Telegram.

## RAG con CocoIndex

`/ask` permite consultar la rúbrica con fuentes. El pipeline lee directamente
`src/classroom/rubrica.md`: documento → CocoIndex → chunks con solapamiento →
embeddings locales → LanceDB embebido → búsqueda coseno → Ollama en GPU → Telegram.
Los comandos existentes siguen consultando MongoDB como antes.

Desde la raíz, con el entorno virtual activado, instala las dependencias:

```bash
# Los embeddings usan CPU; Ollama gestiona por separado la GPU del LLM.
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

Se utiliza la API v1 de CocoIndex y su integración `SentenceTransformerEmbedder`
con `sentence-transformers/all-MiniLM-L6-v2` (384 dimensiones, CPU). La primera
indexación descarga el modelo pequeño desde Hugging Face; después se reutiliza
su caché local. La indexación y el retrieval no necesitan credenciales ni una
API de embeddings. El modelo está orientado principalmente al inglés: conviene
evaluar la calidad en español antes de ampliar el corpus.

Validado con Python 3.12.3, CocoIndex 1.0.24, LanceDB 0.39.0 y
Sentence Transformers 6.1.0. El rango de CocoIndex excluye v2 porque esta
implementación usa la API v1 verificada.

Construye el índice y repite el mismo comando cada vez que cambies la rúbrica:

```bash
cocoindex update -f src.rag.index
```

CocoIndex divide Markdown en chunks de aproximadamente 600 bytes con
solapamiento objetivo de 100 bytes, guarda sus posiciones de caracteres e identificadores y gestiona las filas
del vector store. Su estado incremental y los embeddings se conservan en
`.rag_data/` (SQLite de CocoIndex en `cocoindex.db` y tabla LanceDB `rubric_chunks`).
No se necesita PostgreSQL ni otro servidor. Las ejecuciones sin cambios reutilizan
el trabajo anterior; los chunks retirados dejan de formar parte de la tabla.
Se usa búsqueda vectorial exacta porque la rúbrica es pequeña y no necesita un
índice aproximado entrenado. Conserva el directorio completo entre ejecuciones.

Opcionalmente, mantén la actualización activa mientras editas:

```bash
cocoindex update -f -L src.rag.index
```

Prueba el retrieval sin Telegram ni Ollama:

```bash
python -m src.rag.retrieve "¿Qué dice la rúbrica sobre la navegación entre pantallas?" --top-k 3
```

La salida JSON contiene texto, fuente, identificador, posiciones de caracteres y
`score = 1 - distancia_coseno` devuelta por LanceDB. El score no es una probabilidad
ni garantiza que el fragmento responda la pregunta. No se aplica un umbral
arbitrario: el prompt exige reconocer cuando los pasajes son insuficientes o
ajenos a la pregunta. Esta instrucción reduce, pero no elimina, las alucinaciones.

Para generar la respuesta configura Ollama siguiendo la sección siguiente.
El RAG no necesita ninguna API key:

```bash
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen3:4b
python -m src.rag.service "¿Se pueden entregar mockups de baja fidelidad?"
```

La consulta y los fragmentos se envían al servidor Ollama configurado. Con la URL
local por defecto, la generación permanece en la máquina y no usa APIs de pago.
La respuesta incluye referencias a los pasajes recuperados.

Para Telegram configura además `TELEGRAM_BOT_TOKEN`, `MONGODB_URI` y
`TELEGRAM_ALLOWED_USER_IDS` como en Setup y arranca:

```bash
python src/telegram/bot.py
```

Luego envía `/ask ¿Se pueden entregar mockups de baja fidelidad?`. `/ask` aplica
la misma lista de usuarios autorizados que los otros comandos de consulta.
El bot informa de fallos del RAG sin mostrar trazas y divide respuestas largas.
Indexar no ocurre automáticamente al arrancar el bot ni al recibir una pregunta.

`.env.example` enumera las variables sin secretos. Si prefieres un archivo
`.env`, créalo con tus valores y cárgalo en Bash antes de ejecutar los comandos:

```bash
set -a
source .env
set +a
```

El bot y las CLI de consulta no cargan `.env` automáticamente. `.env`, los índices
y los archivos de caché de Python están excluidos de Git. La rúbrica sigue versionada.

Si falta el índice o está incompleto, ejecuta de nuevo la indexación. Si el documento
está vacío, no se llama al LLM. Los errores de Ollama no afectan los comandos
de reportes. El workflow actual de GitHub Actions no ejecuta este pipeline.

Pruebas de regresión (sin servicios externos):

```bash
python -m unittest discover -s tests -v
```

La prueba de integración se habilita explícitamente; usa documentos e índices
temporales para comprobar repetición, edición y eliminación con CocoIndex real:

```bash
RUN_RAG_INTEGRATION=1 python -m unittest discover -s tests -v
```

Si el modelo ya está en caché, puedes añadir `HF_HUB_OFFLINE=1` a estos comandos
para evitar consultas a Hugging Face.

## Ollama y GPU para el RAG

Configuración verificada del host: NVIDIA GeForce RTX 4060, 8188 MiB de VRAM,
driver 595.91.07 y Ollama 0.34.2. También existe una GPU integrada AMD Raphael;
la GPU seleccionada para esta configuración es la NVIDIA, usando el backend CUDA
compatible de Ollama. No se necesitan cambios en PyTorch ni instalar ROCm para
usar esta NVIDIA. En otra máquina, verifica primero el hardware y los drivers.

Se eligió `qwen3:4b`, multilingüe y de aproximadamente 2.5 GB en su distribución
cuantizada, para dejar margen de VRAM para el contexto y el escritorio. El contexto
se limita a 4096 tokens. El nombre y la URL se configuran en `src/rag/config.py`
mediante `OLLAMA_MODEL` y `OLLAMA_BASE_URL`, leídos al iniciar el proceso.

Validación real: `ollama ps` reportó `100% GPU`, `/api/ps` devolvió
`size = size_vram = 3178149969` bytes y `nvidia-smi` mostró el proceso
`ollama/llama-server` usando 3136 MiB. El RAG respondió sobre mockups de baja
fidelidad citando la rúbrica y reconoció que no dispone de una fecha límite de
entrega. No se validó una conversación real por Telegram en esta sesión.

En Linux, instala Ollama si aún no existe:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
```

Si `nvidia-smi` falla en el host, corrige el driver NVIDIA antes de continuar.
Consulta la [compatibilidad oficial de GPU](https://docs.ollama.com/gpu).
Para AMD debe verificarse la tarjeta exacta en esa documentación y usarse su backend
soportado; la presencia de la iGPU Raphael no demuestra compatibilidad ROCm.

Comprueba el servidor; si no está activo, ejecuta `ollama serve` en otra terminal
y déjalo abierto. Si ya está gestionado por systemd, usa `sudo systemctl start ollama`
en lugar de iniciar un segundo servidor:

```bash
curl --fail http://localhost:11434/api/version
ollama list
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen3:4b
ollama pull "$OLLAMA_MODEL"
python -m src.rag.ollama
ollama ps
```

`python -m src.rag.ollama` precarga el modelo sin pregunta y consulta `/api/ps`.
Debe finalizar con `execution: GPU`; `ollama ps` debe mostrar `100% GPU` en
PROCESSOR. Si muestra `100% CPU`, no hay aceleración; un porcentaje CPU/GPU indica
descarga parcial a CPU por VRAM u otras restricciones.

Antes de generar, el código exige `size_vram >= size > 0` para el modelo configurado,
usando las métricas de `/api/ps`. Rechaza CPU, CPU+GPU y métricas desconocidas con un
error visible. Después de generar vuelve a comprobarlo. No hay fallback a DeepSeek
ni permiso implícito para continuar en CPU. La precarga puede asignarse a CPU, pero
se rechaza antes de enviarle la pregunta. Estas comprobaciones son instantáneas:
no monitorizan cada operación del servidor ni impiden que otro cliente lo recargue.
`100% GPU` describe la carga del modelo, no que todos los procesos auxiliares dejen
de usar CPU. Libera VRAM o configura un modelo menor si falla la comprobación.

Verificación adicional durante una consulta:

```bash
curl --fail http://localhost:11434/api/ps
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv
python -m src.rag.service "¿Se pueden entregar mockups de baja fidelidad?"
ollama ps
```

El modelo permanece cargado cinco minutos desde la última llamada para poder
inspeccionarlo. Para cambiarlo, exporta `OLLAMA_MODEL` con el nombre del modelo
deseado, descárgalo con `ollama pull "$OLLAMA_MODEL"` y reinicia el bot. El nuevo
modelo también debe pasar la comprobación GPU; no requiere reconstruir embeddings.
Si el servidor está en otro host, `OLLAMA_BASE_URL` debe apuntar a ese servidor;
el CLI de Ollama usa su propia variable `OLLAMA_HOST` y las inspecciones de hardware
deben realizarse allí.

DeepSeek permanece en `src/classroom/grader.py`: `create_deepseek_client()` y
`evaluate_file()` conservan su comportamiento y `DEEPSEEK_API_KEY`. El RAG dejó
de importar ese cliente. `ask_rag()` y `/ask` usan únicamente Ollama para generación.
Los embeddings locales y el pipeline CocoIndex/LanceDB permanecen independientes.

Referencias: [instalación Linux](https://docs.ollama.com/linux),
[API chat](https://docs.ollama.com/api/chat),
[modelos cargados](https://docs.ollama.com/api/ps),
[modelo Qwen3](https://ollama.com/library/qwen3:4b).

## Current Flow

```text
GitHub Repositories
        ↓
GitHub Actions
        ↓
MongoDB Atlas
        ↓
Telegram Bot
        ↓
Reports / Queries / Excel
```
