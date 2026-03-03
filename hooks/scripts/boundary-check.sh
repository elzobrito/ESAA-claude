#!/bin/bash
# ESAA Boundary Check Hook (PreToolUse)
# Intercepta modificações de arquivos antes que elas ocorram.

TARGET_PATH="$1"

if [ -z "$TARGET_PATH" ]; then
  echo "[ESAA PROTECT] Caminho do arquivo não fornecido pela ferramenta."
  exit 1
fi

# Utilizamos Python para ler o state atual e os contratos com segurança
python3 -c '
import sys, json, yaml
from pathlib import Path

target_path = sys.argv[1]

# 1. Carregar estado do projeto
try:
    with open(".roadmap/roadmap.json", "r", encoding="utf-8") as f:
        roadmap = json.load(f)
except FileNotFoundError:
    # Se o roadmap não existe, assumimos que estamos em initialization
    sys.exit(0)

# 2. Encontrar a tarefa ativa (in_progress)
active_task = None
for task in roadmap.get("tasks", []):
    if task.get("status") == "in_progress":
        active_task = task
        break

if not active_task:
    print(f"[ESAA PROTECT] Operação negada. Nenhuma tarefa em status in_progress para autorizar escrita em: {target_path}")
    sys.exit(1)

# 3. Lógica de HOTFIX (Extrema Restrição)
if active_task.get("is_hotfix"):
    scope_patch = active_task.get("scope_patch", [])
    is_allowed = any(target_path.startswith(prefix) for prefix in scope_patch)
    if not is_allowed:
        print(f"[ESAA PROTECT] BOUNDARY VIOLATION (HOTFIX). Caminho {target_path} fora do scope_patch restrito: {scope_patch}")
        sys.exit(1)
    sys.exit(0)

# 4. Lógica Core (Por task_kind via AGENT_CONTRACT.yaml)
task_kind = active_task.get("task_kind")
try:
    with open(".roadmap/AGENT_CONTRACT.yaml", "r", encoding="utf-8") as f:
        contract = yaml.safe_load(f)
        write_boundaries = contract.get("boundaries", {}).get("by_task_kind", {}).get(task_kind, {}).get("write", [])
except Exception as e:
    print(f"[ESAA PROTECT] Erro ao ler AGENT_CONTRACT.yaml: {e}")
    sys.exit(1)

# Aplica regras hardcoded inegociáveis do sistema
if target_path.startswith(".roadmap/"):
    print(f"[ESAA PROTECT] BOUNDARY VIOLATION. Escrita direta na pasta .roadmap/ é PROIBIDA para agentes.")
    sys.exit(1)

# Verifica prefix_match nas permissões do contrato
is_allowed = any(target_path.startswith(prefix.replace("/**", "/").replace("/*", "/")) for prefix in write_boundaries)

if not is_allowed:
    print(f"[ESAA PROTECT] BOUNDARY VIOLATION. task_kind={task_kind} não tem permissão para escrever em {target_path}. Permissões: {write_boundaries}")
    sys.exit(1)

# Se chegou aqui, está autorizado
sys.exit(0)
' "$TARGET_PATH"

# Captura o código de saída do script Python
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  # O exit code diferente de 0 sinaliza ao Claude Code que a Tool falhou
  exit $EXIT_CODE
fi