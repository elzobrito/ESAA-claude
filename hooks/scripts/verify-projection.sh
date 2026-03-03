#!/bin/bash
# ESAA Verify Projection Hook (PostToolUse)
# Executa a verificação determinística do estado após escritas no repositório.

echo "[ESAA PROTECT] A iniciar auditoria de integridade pós-escrita..."

# Invoque o módulo CLI do esaa-core em modo estrito
python3 -m esaa verify --strict

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "[ESAA PROTECT] ✅ Verificação concluída: Integridade do repositório e do read-model confirmada."
  exit 0
else
  echo "[ESAA PROTECT] ❌ FALHA DE INTEGRIDADE DETETADA."
  echo "[ESAA PROTECT] O estado do repositório divergiu do log imutável de eventos (activity.jsonl)."
  echo "[ESAA PROTECT] A ação foi bloqueada. Reverta as alterações locais não rastreadas ou utilize o protocolo de Hotfix."
  
  # Um exit code não-zero sinaliza ao agente de IA que a operação resultou numa falha crítica de sistema
  exit $EXIT_CODE
fi