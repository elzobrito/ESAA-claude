---
name: esaa-run
description: Inicia um ou mais ciclos de orquestração do ESAA. Lê o roadmap, seleciona a próxima tarefa elegível (todo -> in_progress) e despacha o agente correto.
---

# Iniciando o ciclo de execução ESAA

Você foi acionado para rodar o loop de orquestração do ESAA. Assuma imediatamente as restrições e o pipeline definidos na skill `esaa-orchestrator`.

**Protocolo de Execução:**
1. Leia o estado atual do projeto no arquivo `@.roadmap/roadmap.json`.
2. Execute o Passo 2 do Orquestrador (`select_next_eligible_task`): encontre a primeira tarefa com `status=todo` onde todas as dependências (`depends_on`) possuam `status=done`.
3. Se houver uma tarefa elegível, informe ao usuário qual tarefa foi selecionada e qual `task_kind` será acionado.
4. Carregue mentalmente a skill correspondente ao `task_kind` (`esaa-spec`, `esaa-impl`, `esaa-impl-hotfix` ou `esaa-qa`).
5. Gere a intenção/artefato e passe pelo funil de validação de 7 camadas (Passo 4 do Orquestrador).
6. Utilize a ferramenta apropriada (MCP `esaa-orchestrator-server` ou invocação Python) para registrar o evento validado e materializar a projeção.
7. Ao final, apresente um sumário curto e estruturado da ação realizada.

*Se não houver tarefas elegíveis, verifique se o projeto está concluído ou bloqueado por dependências/issues, e reporte o status atual.*