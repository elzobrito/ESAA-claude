---
name: esaa-orchestrator
description: This skill should be used when implementing, debugging, or reasoning about the ESAA Orchestrator runtime. Provides the complete deterministic pipeline (7 steps), validation layers, event envelope format, state machine transitions, hotfix protocol, and issue escalation policy. Also activates when the user mentions "esaa orchestrator", "pipeline ESAA", "esaa run", "esaa verify", "event store", or "projeção ESAA".
esaa_version: "0.4.0"
applies_to_actor: "orchestrator"
is_single_writer: true
---

# PARCER PROFILE — orchestrator-runtime (esaa-claude v0.4.0)
# ⚠️ NOTA ARQUITETURAL: O Orchestrator é um runtime determinístico — não um LLM.
# Este profile governa sua implementação e comportamento como single-writer do event store.

## PERSONA

**Role:** Runtime Determinístico e Árbitro de Autoridade do sistema ESAA.
Única entidade que escreve no event store e aplica efeitos no repositório.
Toda ação de agente passa por você — você valida, aceita, rejeita, e persiste.

**Identity constraints:**
- Você é o único escritor do event store (`is_single_writer: true`). Nenhuma exceção.
- Você nunca emite as ações reservadas a agentes (`claim`, `complete`, `review`, `issue.report`) como se fosse um agente.
- Você nunca interpreta intenção implícita nos outputs dos agentes — você valida contra schema e contrato.
- Você rejeita antes de persistir, sempre. Fail-closed é um invariante, não uma opção.
- Você nunca regride uma tarefa de status `done`. Imutabilidade do done é absoluta.

**Authority scope:**
- CAN emit: `run.start`, `run.end`, `task.create`, `hotfix.create`, `issue.resolve`, `output.rejected`, `orchestrator.file.write`, `orchestrator.view.mutate`, `verify.start`, `verify.ok`, `verify.fail`
- CANNOT emit as orchestrator: `claim`, `complete`, `review`, `issue.report`

---

## EVENT ENVELOPE

Todo evento persistido deve ter exatamente estes campos:

```json
{
  "schema_version": "0.4.0",
  "event_id": "EV-00000001",
  "event_seq": 1,
  "ts": "2026-02-27T01:25:22Z",
  "actor": "orchestrator",
  "action": "run.start",
  "payload": {}
}
```

**Regras invariantes:**
- `event_seq` é estritamente monotônico e gap-free. Qualquer gap = corrupção → `halt`.
- `event_id` é único em todo o event store.
- `actor` = `orchestrator` para eventos do Orchestrator; `actor` = nome do agente para ações de agentes.
- Event store é append-only — jamais editar eventos existentes.

---

## STATE MACHINE

```
         claim              complete          review(approve)
[todo] ─────────► [in_progress] ─────────► [review] ─────────► [done] ✗
                       ▲                       │                   (imutável)
                       └───────────────────────┘
                          review(request_changes)
```

| De | Action | Para |
|---|---|---|
| `todo` | `claim` | `in_progress` |
| `in_progress` | `complete` | `review` |
| `review` | `review(approve)` | `done` |
| `review` | `review(request_changes)` | `in_progress` |

`done` é terminal. Qualquer ação sobre tarefa `done` → `output.rejected (immutable_done_violation)`.

---

## PIPELINE — 7 passos sequenciais determinísticos

### Passo 1: parse_event_store
- Ler `.roadmap/activity.jsonl` linha a linha.
- Validar JSON de cada evento.
- Verificar `event_seq` monotônico e gap-free.
- **On failure:** `halt` — event store corrompido.

### Passo 2: select_next_eligible_task
- Projetar estado atual a partir de events.
- Identificar tarefas `status=todo` com todos os `depends_on` em `done`.
- Se nenhuma elegível mas há pendentes: verificar deadlock → emitir `issue.report(severity=high)`.
- Se todas as tarefas `done`: emitir `run.end(success)`.

### Passo 3: dispatch_agent
- Resolver agente pelo `task_kind` via `agents_swarm.yaml`.
- Montar contexto purificado: roadmap subset + spec + lessons filtradas + issues filtradas.
- Iniciar timer TTL (PT30M).
- Invocar agente com contexto montado.
- **On TTL exceeded:** emitir `output.rejected(ATTEMPT_TIMEOUT)`, incrementar `attempt_count`.

### Passo 4: validate_agent_output — 7 camadas em ordem estrita

| Camada | Verificação | Falha → |
|---|---|---|
| 4a | Parse JSON | `output.rejected(schema_violation)` |
| 4b | Schema validation vs `agent_result.schema.json` | `output.rejected(schema_violation)` |
| 4c | `action` em `allowed_agent_actions` | `output.rejected(unknown_action)` |
| 4d | Transição de estado válida | `output.rejected(invalid_transition)` |
| 4e | Boundary check por `task_kind` | `output.rejected(boundary_violation)` |
| 4f | `task.status != done` | `output.rejected(immutable_done_violation)` |
| 4g | `verification.checks >= 1` (impl) ou `>= 2` (hotfix) | `output.rejected(verification_gate)` |

**On reject:**
1. Emitir `output.rejected` com `error_code` e payload descritivo.
2. Incrementar `attempt_count`.
3. Se `attempt_count >= 3`: emitir `issue.report(severity=high)` automaticamente.
4. Retornar ao passo 2 (não encerrar o run).

### Passo 5: append_events
Após validação bem-sucedida, persistir na ordem:
- `[5a]` Evento da action do agente (`claim`, `complete`, `review`, `issue.report`) com `actor=<agente>`.
- `[5b]` Para cada item em `file_updates`: evento `orchestrator.file.write`.
- `[5c]` Evento `orchestrator.view.mutate` para cada projeção atualizada.
- Cada evento: `event_id` único, `event_seq = last_seq + 1`, `ts = now()`.
- **On seq conflict:** `halt` — violação de single-writer.

### Passo 6: project_views
- Aplicar função pura `project(events) → (roadmap, issues, lessons)`.
- Recalcular indexes: `by_status`, `by_kind`, `by_task_kind`, `by_enforcement_applies_to`.
- Serializar JSON canônico: UTF-8, chaves ordenadas, `separators=(',', ':')`, final LF.
- Escrever `roadmap.json`, `issues.json`, `lessons.json`.

### Passo 7: verify_projection
- Emitir `verify.start`.
- Executar replay determinístico do event store completo.
- Computar SHA-256 de:
  ```json
  { "schema_version": "...", "project": {...}, "tasks": [...], "indexes": {...} }
  ```
  *(exclui `meta.run` para evitar auto-referência)*
- Comparar com `roadmap.json#meta.run.projection_hash_sha256`.
- **On match:** emitir `verify.ok`.
- **On mismatch:** emitir `verify.fail` → `reproject_or_halt`.
- **On corrupted:** emitir `verify.fail` → `halt_and_snapshot` imediato.

---

## ISSUE ESCALATION

| Severity | Ação |
|---|---|
| `low` | `log_only` — registrar no event store, não bloquear |
| `medium` | `log_and_flag` — registrar, marcar tarefa como flagged |
| `high` | `block_task` — não despachar novos agentes para esta tarefa |
| `critical` | `halt_pipeline` — emitir `run.end(failed)` e parar |

---

## HOTFIX PROTOCOL

**Trigger:** `issue.report` com `status=open` referenciando tarefa `done`.

**Flow:**
1. Criar nova tarefa `is_hotfix=true` via `hotfix.create`.
2. Definir `scope_patch` com paths afetados.
3. Definir `required_verification` com mínimo 2 checks.
4. Despachar agente com template `impl.hotfix` (skill `esaa-impl-hotfix`).
5. Após `complete`: exigir `verification.checks >= 2` + `issue_id` + `fixes`.
6. Após `approve`: emitir `issue.resolve` para fechar o issue original.

**Invariante:** A tarefa `done` original **nunca é modificada**. O hotfix cria nova tarefa derivada.

---

## VERIFY COMMAND (standalone)

`esaa verify` executa:
1. `parse_event_store` (passo 1)
2. `project(events)` determinístico
3. Compute SHA-256 do hash_input canônico
4. Comparar com `roadmap.json#meta.run.projection_hash_sha256`

**Output:** `verify_status_enum: ok | mismatch | corrupted`

---

## RESPONSE — Eventos válidos do Orchestrator

### ✅ run.start
```json
{
  "schema_version": "0.4.0",
  "event_id": "EV-00000001",
  "event_seq": 1,
  "ts": "2026-02-27T01:25:22Z",
  "actor": "orchestrator",
  "action": "run.start",
  "payload": {
    "run_id": "RUN-0001",
    "status": "initialized",
    "master_correlation_id": "CID-ESAA-INIT"
  }
}
```

### ✅ output.rejected
```json
{
  "schema_version": "0.4.0",
  "event_id": "EV-00000010",
  "event_seq": 10,
  "ts": "2026-02-27T01:30:00Z",
  "actor": "orchestrator",
  "action": "output.rejected",
  "payload": {
    "task_id": "T-1000",
    "error_code": "boundary_violation",
    "violated_path": "src/T-1000.py",
    "allowed_boundary": "docs/**",
    "attempt_count": 1
  }
}
```

### ✅ verify.ok
```json
{
  "schema_version": "0.4.0",
  "event_id": "EV-00000015",
  "event_seq": 15,
  "ts": "2026-02-27T01:35:00Z",
  "actor": "orchestrator",
  "action": "verify.ok",
  "payload": {
    "projection_hash_sha256": "7f32d838c797f55429b11483f163a1cdcf12cb75e335ebb96f0202b07dc26014",
    "last_event_seq": 14
  }
}
```

### ❌ INVÁLIDO — event_seq com gap
```json
[
  { "event_seq": 5, "action": "claim" },
  { "event_seq": 7, "action": "complete" }
]
```
**Razão:** Gap em `event_seq` (5 → 7, faltando 6) = event store corrompido → `halt`.

### ❌ INVÁLIDO — Orchestrator emitindo complete como se fosse agente
```json
{
  "actor": "orchestrator",
  "action": "complete",
  "payload": { "task_id": "T-1000" }
}
```
**Razão:** `complete` é ação reservada a agentes. O Orchestrator não pode emiti-la com `actor=orchestrator`.