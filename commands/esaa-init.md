---
name: esaa-init
description: Inicializa um novo projeto ESAA. Cria o diretorio .roadmap/ com contratos, schemas, event store inicial e projecoes vazias.
---

# Inicializando um novo projeto ESAA

Voce foi acionado para criar um novo projeto ESAA do zero.

**Protocolo de Execucao:**
1. Pergunte ao usuario (se ainda nao informado):
   - `project_name`: nome do projeto
   - `audit_scope`: escopo da auditoria (opcional)
   - `roadmap_dir`: diretorio do roadmap (padrao: `.roadmap`)
2. Utilize a ferramenta MCP `esaa_init` para criar o scaffolding do projeto com os parametros fornecidos.
3. Se o diretorio ja existir, pergunte ao usuario se deseja sobrescrever (`force=true`).
4. Apos a criacao, exiba:
   - Lista de arquivos criados
   - Status da verificacao inicial (hash SHA-256)
   - Proximos passos recomendados (adicionar tarefas ao roadmap)
5. Sugira ao usuario que adicione tarefas ao roadmap e execute `/esaa-run` para iniciar o ciclo de orquestracao.
