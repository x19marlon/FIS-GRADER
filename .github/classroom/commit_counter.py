import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def ejecutar_git(repository: Path, arguments: list[str]) -> str:
    """Ejecuta un comando de Git dentro del repositorio indicado."""

    command = ["git", "-C", str(repository), *arguments]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Error ejecutando:\n{' '.join(command)}\n\n"
            f"Salida de Git:\n{result.stderr.strip()}"
        )

    return result.stdout.strip()


def obtener_ramas_remotas(repository: Path) -> list[str]:
    """Obtiene todas las ramas remotas disponibles."""

    output = ejecutar_git(
        repository,
        [
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/remotes/origin",
        ],
    )

    branches: list[str] = []

    for branch in output.splitlines():
        branch = branch.strip()

        if not branch:
            continue

        if branch == "origin/HEAD":
            continue

        if branch.endswith("/HEAD"):
            continue

        branches.append(branch)

    return sorted(set(branches))


def obtener_commits_periodo(
    repository: Path,
    days: int,
) -> list[str]:
    """Obtiene los commits de todas las ramas durante el periodo indicado."""

    output = ejecutar_git(
        repository,
        [
            "rev-list",
            "--all",
            f"--since={days} days ago",
        ],
    )

    if not output:
        return []

    # Eliminar duplicados por si un commit pertenece a varias ramas.
    return list(dict.fromkeys(output.splitlines()))


def obtener_datos_commit(
    repository: Path,
    commit_hash: str,
) -> dict[str, str]:
    """Obtiene los metadatos principales de un commit."""

    separator = "\x1f"

    output = ejecutar_git(
        repository,
        [
            "show",
            "-s",
            f"--format=%H{separator}%h{separator}%an{separator}%ae"
            f"{separator}%aI{separator}%s",
            commit_hash,
        ],
    )

    parts = output.split(separator, maxsplit=5)

    if len(parts) != 6:
        raise RuntimeError(
            f"No fue posible interpretar el commit {commit_hash}."
        )

    return {
        "hash": parts[0],
        "hash_corto": parts[1],
        "autor": parts[2],
        "correo": parts[3].lower().strip(),
        "fecha": parts[4],
        "mensaje": parts[5],
    }


def obtener_ramas_commit(
    repository: Path,
    commit_hash: str,
) -> list[str]:
    """
    Obtiene las ramas remotas que contienen el commit.

    Esto no necesariamente representa la rama donde originalmente
    se creó el commit.
    """

    output = ejecutar_git(
        repository,
        [
            "for-each-ref",
            "--contains",
            commit_hash,
            "--format=%(refname:short)",
            "refs/remotes/origin",
        ],
    )

    branches: list[str] = []

    for branch in output.splitlines():
        branch = branch.strip()

        if not branch:
            continue

        if branch == "origin/HEAD":
            continue

        if branch.endswith("/HEAD"):
            continue

        branches.append(branch)

    return sorted(set(branches))


def obtener_total_historico(repository: Path) -> int:
    """Cuenta todos los commits alcanzables desde las referencias descargadas."""

    output = ejecutar_git(
        repository,
        [
            "rev-list",
            "--all",
            "--count",
        ],
    )

    return int(output or 0)



def es_merge_commit(repository: Path, commit_hash: str) -> bool:
    """Indica si un commit tiene más de un padre."""

    output = ejecutar_git(
        repository,
        [
            "rev-list",
            "--parents",
            "-n",
            "1",
            commit_hash,
        ],
    )

    # El primer elemento es el hash del commit.
    # Si hay más de dos elementos, el commit tiene dos o más padres.
    return len(output.split()) > 2


def clasificar_mensaje_commit(message: str) -> str:
    """Clasifica el mensaje usando prefijos comunes de Conventional Commits."""

    normalized = message.strip().lower()

    prefixes = (
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "test",
        "chore",
        "build",
        "ci",
        "perf",
        "revert",
    )

    for prefix in prefixes:
        if normalized.startswith(f"{prefix}:") or normalized.startswith(
            f"{prefix}("
        ):
            return prefix

    return "otro"


def obtener_nombre_repositorio(repository: Path) -> str:
    """Obtiene el nombre del repositorio desde la URL remota o la carpeta."""

    try:
        remote_url = ejecutar_git(
            repository,
            [
                "config",
                "--get",
                "remote.origin.url",
            ],
        )
    except RuntimeError:
        remote_url = ""

    if remote_url:
        name = remote_url.rstrip("/").split("/")[-1]

        if name.endswith(".git"):
            name = name[:-4]

        if name:
            return name

    return repository.name


def generar_reportes(
    repository: Path,
    days: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Genera dos reportes complementarios:

    - autores.json: detalle de commits agrupados por correo.
    - repositorio.json: resumen estadístico del repositorio sin repetir
      la lista completa de commits.
    """

    commit_hashes = obtener_commits_periodo(repository, days)
    remote_branches = obtener_ramas_remotas(repository)

    users: dict[str, dict[str, Any]] = {}
    branch_commit_counts: defaultdict[str, int] = defaultdict(int)

    commits_by_day: Counter[str] = Counter()
    commit_types: Counter[str] = Counter()
    commits_by_author: Counter[str] = Counter()

    commit_dates: list[str] = []
    merge_commits = 0

    for commit_hash in commit_hashes:
        commit = obtener_datos_commit(repository, commit_hash)
        commit_branches = obtener_ramas_commit(repository, commit_hash)

        if not commit_branches:
            commit_branches = ["sin_rama_remota"]

        email = commit["correo"]
        author_name = commit["autor"]
        commit_date = commit["fecha"]
        commit_day = commit_date[:10]

        if email not in users:
            users[email] = {
                "correo": email,
                "nombres_utilizados": set(),
                "cantidad_commits": 0,
                "ramas": defaultdict(int),
                "commits": [],
            }

        user = users[email]

        user["nombres_utilizados"].add(author_name)
        user["cantidad_commits"] += 1

        for branch in commit_branches:
            user["ramas"][branch] += 1
            branch_commit_counts[branch] += 1

        user["commits"].append(
            {
                "hash": commit["hash"],
                "hash_corto": commit["hash_corto"],
                "fecha": commit_date,
                "mensaje": commit["mensaje"],
                "ramas": commit_branches,
            }
        )

        commits_by_day[commit_day] += 1
        commits_by_author[email] += 1
        commit_types[clasificar_mensaje_commit(commit["mensaje"])] += 1
        commit_dates.append(commit_date)

        if es_merge_commit(repository, commit_hash):
            merge_commits += 1

    users_list: list[dict[str, Any]] = []

    for user in users.values():
        users_list.append(
            {
                "correo": user["correo"],
                "nombres_utilizados": sorted(user["nombres_utilizados"]),
                "cantidad_commits": user["cantidad_commits"],
                "ramas": dict(
                    sorted(
                        user["ramas"].items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
                "commits": sorted(
                    user["commits"],
                    key=lambda commit: commit["fecha"],
                    reverse=True,
                ),
            }
        )

    users_list.sort(
        key=lambda user: (
            -user["cantidad_commits"],
            user["correo"],
        )
    )

    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    total_period_commits = len(commit_hashes)
    active_days = len(commits_by_day)
    average_per_active_day = (
        round(total_period_commits / active_days, 2)
        if active_days
        else 0.0
    )
    average_per_period_day = round(total_period_commits / days, 2)

    first_commit = min(commit_dates) if commit_dates else None
    last_commit = max(commit_dates) if commit_dates else None

    author_summary: dict[str, dict[str, Any]] = {}

    for user in users_list:
        preferred_name = (
            user["nombres_utilizados"][0]
            if user["nombres_utilizados"]
            else user["correo"]
        )

        author_summary[user["correo"]] = {
            "nombre": preferred_name,
            "cantidad_commits": user["cantidad_commits"],
            "porcentaje_participacion": (
                round(
                    user["cantidad_commits"]
                    / total_period_commits
                    * 100,
                    2,
                )
                if total_period_commits
                else 0.0
            ),
        }

    authors_report = {
        "periodo": {
            "dias": days,
            "desde": start_date.isoformat(),
            "hasta": now.isoformat(),
        },
        "cantidad_usuarios": len(users_list),
        "usuarios": users_list,
        "advertencia_ramas": (
            "Las ramas mostradas son las ramas remotas que actualmente "
            "contienen cada commit. Git no almacena la rama original "
            "en la que se creó un commit."
        ),
    }

    repository_report = {
        "repositorio": obtener_nombre_repositorio(repository),
        "periodo": {
            "dias": days,
            "desde": start_date.isoformat(),
            "hasta": now.isoformat(),
        },
        "resumen": {
            "total_commits_periodo": total_period_commits,
            "total_commits_historicos": obtener_total_historico(repository),
            "total_autores_periodo": len(users_list),
            "total_ramas_remotas": len(remote_branches),
            "dias_con_actividad": active_days,
            "dias_sin_actividad": max(days - active_days, 0),
            "promedio_commits_por_dia_activo": average_per_active_day,
            "promedio_commits_por_dia_del_periodo": average_per_period_day,
            "primer_commit_periodo": first_commit,
            "ultimo_commit_periodo": last_commit,
            "commits_merge": merge_commits,
            "commits_no_merge": total_period_commits - merge_commits,
        },
        "participacion_por_autor": dict(
            sorted(
                author_summary.items(),
                key=lambda item: (
                    -item[1]["cantidad_commits"],
                    item[0],
                ),
            )
        ),
        "actividad_por_dia": dict(
            sorted(commits_by_day.items())
        ),
        "actividad_por_rama": dict(
            sorted(
                branch_commit_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "tipos_de_commit": dict(
            sorted(
                commit_types.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "ramas_remotas_detectadas": remote_branches,
        "advertencias": [
            (
                "Un commit puede contarse dentro de varias ramas si "
                "actualmente es alcanzable desde todas ellas."
            ),
            (
                "La suma de actividad_por_rama puede superar el total de "
                "commits del periodo porque un mismo commit puede pertenecer "
                "a varias ramas."
            ),
            (
                "La clasificación de tipos de commit se basa únicamente "
                "en prefijos como feat:, fix:, docs: o refactor:."
            ),
        ],
    }

    return authors_report, repository_report


def guardar_json(path: Path, content: dict[str, Any]) -> None:
    """Guarda un diccionario en un archivo JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            content,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write("\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera reportes JSON de commits, autores y ramas "
            "de un repositorio Git."
        )
    )

    parser.add_argument(
        "--repository",
        required=True,
        help="Ruta del repositorio que será analizado.",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=65,
        help="Cantidad de días que serán analizados. Por defecto: 65.",
    )

    parser.add_argument(
        "--authors-output",
        default="autores.json",
        help="Archivo JSON de salida para el reporte por autores.",
    )

    parser.add_argument(
        "--repository-output",
        default="repositorio.json",
        help="Archivo JSON de salida para el resumen del repositorio.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    repository = Path(args.repository).resolve()
    authors_output = Path(args.authors_output).resolve()
    repository_output = Path(args.repository_output).resolve()

    if args.days <= 0:
        print(
            "Error: --days debe ser mayor que cero.",
            file=sys.stderr,
        )
        return 1

    if not repository.exists():
        print(
            f"Error: no existe la ruta {repository}.",
            file=sys.stderr,
        )
        return 1

    if not (repository / ".git").exists():
        print(
            f"Error: {repository} no parece ser un repositorio Git.",
            file=sys.stderr,
        )
        return 1

    try:
        authors_report, repository_report = generar_reportes(
            repository=repository,
            days=args.days,
        )

        guardar_json(authors_output, authors_report)
        guardar_json(repository_output, repository_report)

    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Reportes generados correctamente:")
    print(f"- Autores: {authors_output}")
    print(f"- Repositorio: {repository_output}")

    print(
        "Commits encontrados durante el periodo: "
        f"{repository_report['resumen']['total_commits_periodo']}"
    )

    print(
        "Autores encontrados durante el periodo: "
        f"{repository_report['resumen']['total_autores_periodo']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())