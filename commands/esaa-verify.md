---
name: esaa-verify
description: Executa a auditoria de integridade do ESAA (esaa verify). Re-projeta o log de eventos (.roadmap/activity.jsonl) e compara o hash SHA-256 para garantir que o roadmap.json não foi corrompido ou editado manualmente.
---

# Auditoria de Integridade ESAA (Verify)

Você foi acionado para garantir a segurança matemática e a integridade do estado do projeto ESAA.

**Protocolo de Execução:**
1. Atue sob as regras do Passo 7 da skill `esaa-orchestrator` (`verify_projection`).
2. Utilize a ferramenta do sistema (ex: `python -m esaa verify --strict` ou a *tool* MCP equivalente) para disparar a auditoria.
3. Leia o output retornado pela ferramenta (`verify_status`).
4. **Se o status for `ok`:** Responda com uma mensagem afirmativa e exiba o `projection_hash_sha256` e o `last_event_seq` validados.
5. **Se o status for `mismatch` ou `corrupted`:** Alerte o usuário imediatamente. Um `mismatch` significa que a projeção divergiu do log de eventos (alguém editou os read-models manualmente). Sugira as ações de recuperação (`reproject_or_halt` ou `halt_and_snapshot`).