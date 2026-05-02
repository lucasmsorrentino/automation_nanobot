# Checklist de revisão — Intents Tier 0 autorados em 2026-04-27

> **34 intents novos** adicionados em [`workspace/PROCEDURES.md`](workspace/PROCEDURES.md), seções §12–§16,
> como parte da Frente 1 do plano em [`PLANO_EXPANSAO_TIER0_E_ROLE.md`](PLANO_EXPANSAO_TIER0_E_ROLE.md).
> (Originalmente 31; `enc_reserva_sala`, `info_certificado_conclusao` e `info_diploma_digital_acesso` adicionados depois a pedido do coordenador.)
>
> **Como usar este checklist**: clique no link `PROCEDURES.md:linha` para abrir o intent. Para cada um,
> verificar `keywords` (gatilhos), `template` (corpo do email), e — quando houver — `despacho_template`
> (peça SEI). Trocar `[ ]` por `[x]` quando aprovar; anotar correções inline na seção "Correções
> propostas" ao final do arquivo. Atualizar `last_update: "2026-04-27"` para a data da revisão se
> editar conteúdo (a engine usa esse campo para staleness check vs o RAG).
>
> Pontos a checar em cada intent:
> 1. **Keywords cobrem como o aluno realmente fala?** (ex.: gírias, abreviações, erros comuns)
> 2. **Template está com o tom certo da Coordenação DG?** (formal, mas próximo)
> 3. **Cita o setor correto?** (não "procure a Coordenação" — somos nós)
> 4. **Procedimento descrito está atualizado?** (links, telefones, fluxos SEI/SIGA)
> 5. **`required_fields` faz sentido?** (sem campos faltando = email pode ser respondido sem dados extras do aluno)
> 6. **`sources` apontam para a norma certa?**
> 7. **Para intents com `sei_action`/`despacho_template`**: o despacho está canônico e respeita os 3 métodos do `SEIWriter` (`create_process`, `attach_document`, `save_despacho_draft`)?

---

## §12. Informações e Documentos (12 intents)

ROI máximo — categoria "Informações e Documentos" tem 132 emails/mês e zero cobertura Tier 0 hoje.

- [X] [`info_declaracao_matricula`](workspace/PROCEDURES.md#L1227) — passo a passo SIGA para tirar declaração de matrícula
- [X] [`info_declaracao_vinculo`](workspace/PROCEDURES.md#L1261) — declaração de vínculo via SIGA
- [ ] [`info_declaracao_provavel_formando`](workspace/PROCEDURES.md#L1305) — **REVISADO 2026-04-27 (correção do coordenador)**: removido prazo fictício de 3 dias; dividido em Caso A (aluno ativo → self-service SIGA: Documentos → Gerar) e Caso B (já colou / perdeu acesso → secretaria gera via SIGA-Secretaria → Discente → Consultar → aba Documentos → anexa ao rascunho). Instrução de Caso B fica visível ao revisor humano até o `siga_action` ser wirado
- [ ] [`info_atestado_frequencia`](workspace/PROCEDURES.md#L1367) — frequência é com docente; orienta atestado/regime domiciliar
- [ ] [`info_historico_escolar`](workspace/PROCEDURES.md#L1411) — **REVISADO 2026-04-27 (4 cenários, refinado 2x)**: (1) ativo/trancado/mobilidade → self-service via Portal de Sistemas → SIGA → Documentos → Gerar; (2) egresso ≥2023 com diploma digital → resposta enxuta "está no mesmo lugar do diploma digital"; (3) egresso/evadido ≥2021 → Coordenação OU PROGRAD (Coord gera via SIGA-Secretaria, anexa ao rascunho); (4) egresso/evadido <2021 (ou formado <2005, com diploma) → exclusivamente atendimento@ufpr.br. Detalhes do diploma digital concentrados em `info_diploma_digital_acesso`
- [ ] [`info_certificado_conclusao`](workspace/PROCEDURES.md#L1528) — **REVISADO 2026-04-27**: Caso 1 enxuto — "certificado de conclusão **descontinuado** desde diploma digital". Caso 2 redireciona pra Provável Formando. Caso 3 = ação Coordenação via SIGA-Secretaria. Caso 4 = só PROGRAD. Detalhes do diploma digital concentrados em `info_diploma_digital_acesso`
- [ ] [`info_diploma_digital_acesso`](workspace/PROCEDURES.md#L1627) — **NOVO 2026-04-27 (a pedido)**: intent dedicado para "como acessar diploma digital", "perfil egresso", "baixar diploma", "XML do diploma", "validar diploma". Passo a passo SIGA → perfil Discente Egresso → Diploma → Visualizar → 4 arquivos. Único intent que carrega URLs do Tutorial PROGRAP/UDIP no corpo do email
- [ ] [`info_2via_diploma`](workspace/PROCEDURES.md#L1699) — encaminha para PROGRAP / Seção de Diplomas
- [ ] [`info_horario_atendimento_secretaria`](workspace/PROCEDURES.md#L1735) — horário, endereço, telefone, email
- [ ] [`info_endereco_coordenacao`](workspace/PROCEDURES.md#L1764) — só endereço/contato
- [ ] [`enc_ementa_ficha_disciplina`](workspace/PROCEDURES.md#L1800) — **REVISADO 2026-04-27 (a pedido)**: substitui `info_ementa_disciplina`. Aponta primeiro pra https://sacod.ufpr.br/coordesign/grade-curricular-grafico/ (referência), explica que responsabilidade é dos Departamentos (DDESIGN principal; Artes/Antropologia em outros casos). Keywords expandidas. Template traz **instrução para o revisor adicionar CC manual** ao DDESIGN
- [ ] [`info_quem_e_coordenadora`](workspace/PROCEDURES.md#L1873) — Stephania (coord), Carolina (vice), Lucas (secretário)

## §13. Encaminhamentos a outros setores (8 intents)

- [ ] [`enc_bolsas_assistencia_estudantil`](workspace/PROCEDURES.md#L1913) — PRAE (permanência, moradia, alimentação, creche)
- [ ] [`enc_intercambio`](workspace/PROCEDURES.md#L1948) — AUI (Erasmus+, BRAFITEC, Santander, AUGM)
- [ ] [`enc_iniciacao_cientifica`](workspace/PROCEDURES.md#L1986) — PRPPG (PIBIC/PIBITI/IC voluntária) + AFC
- [ ] [`enc_monitoria`](workspace/PROCEDURES.md#L2026) — edital semestral PROGRAP/Departamento + AFC
- [ ] [`enc_biblioteca_quitacao`](workspace/PROCEDURES.md#L2062) — SIBI; certidão negativa para colação
- [ ] [`enc_carteirinha_estudante_ru`](workspace/PROCEDURES.md#L2096) — PRAE (cadastro RU + carteirinha)
- [ ] [`enc_reserva_sala`](workspace/PROCEDURES.md#L2129) — **NOVO 2026-04-27 (a pedido)**: reservas de salas/auditórios/laboratórios são do DDESIGN (`design@ufpr.br`); template traz **instrução para o revisor adicionar CC manual** ao DDESIGN
- [ ] [`enc_atendimento_psicologico_naa`](workspace/PROCEDURES.md#L2184) — NAA/PRAE; CVV 188; oferece conversa com Coord

## §14. Estágio Obrigatório — expansão (5 intents)

Hoje só temos `estagio_obrig_matricula`. Aqui adicionamos os fluxos SEI completos. **3 destes têm `despacho_template`** — revisar com cuidado o despacho.

- [ ] [`estagio_obrig_tce_inicial`](workspace/PROCEDURES.md#L2236) — TCE inicial obrig + cria processo SEI + **despacho** (SEI tipo "Estágio Obrigatório")
- [ ] [`estagio_obrig_relatorio_parcial`](workspace/PROCEDURES.md#L2312) — relatório a cada 6 meses + anexa SEI + **despacho**
- [ ] [`estagio_obrig_defesa_avaliacao`](workspace/PROCEDURES.md#L2356) — regras de banca/defesa, sem ação SEI
- [ ] [`estagio_obrig_lancamento_nota`](workspace/PROCEDURES.md#L2391) — orienta espera de 15 dias; pede dados se persistir
- [ ] [`estagio_obrig_ic_substituicao_fluxo`](workspace/PROCEDURES.md#L2427) — IC no lugar do estágio + cria processo SEI para COE + **despacho**

## §15. Matrículas — expansão (4 intents)

- [ ] [`matricula_disciplina_isolada`](workspace/PROCEDURES.md#L2498) — edital PROGRAP de aluno especial / Res 37/97-CEPE
- [ ] [`matricula_ajuste_periodo`](workspace/PROCEDURES.md#L2536) — ajuste pelo SIGA na 1ª semana; depois requerimento ao Colegiado
- [ ] [`matricula_mobilidade_estrangeiro`](workspace/PROCEDURES.md#L2578) — incoming via AUI; análise de disciplinas pela Coord
- [ ] [`matricula_provar`](workspace/PROCEDURES.md#L2618) — Res 91/14-CEPE; reabilitação para ex-estudantes

## §16. Acadêmicos gerais (5 intents)

- [ ] [`tcc_regras_gerais`](workspace/PROCEDURES.md#L2668) — TCC1+TCC2; orientador; banca; nota mínima 50
- [ ] [`afc_atividades_validas`](workspace/PROCEDURES.md#L2716) — Res 70/04-CEPE + tabela em sacod.ufpr.br
- [ ] [`mudanca_curriculo_2016_para_2020`](workspace/PROCEDURES.md#L2764) — análise pelo Colegiado caso a caso
- [ ] [`calendario_academico`](workspace/PROCEDURES.md#L2811) — link prograp.ufpr.br
- [ ] [`enade`](workspace/PROCEDURES.md#L2846) — SINAES; obrigatório para diploma; checagem no SIGA

---

## Pontos de atenção identificados durante a autoria (vale revisar com prioridade)

1. ~~**`info_declaracao_provavel_formando`**: não sei se "até 3 dias úteis" é o prazo certo para a Coordenação preparar — confirmar com Lucas.~~ ✅ **Resolvido 2026-04-27**: prazo removido. Aluno ativo emite sozinho no SIGA (Documentos → Gerar). Caso B (já colou / sem acesso) é gerado pela Secretaria; procedimento manual documentado no template + task aberta para wirar `siga_action: fetch_declaracao_provavel_formando` na engine (ver TASKS).
2. **`info_atestado_frequencia`**: a redação cita "5 dias úteis após a falta" como prazo padrão de plano de ensino — pode variar por docente; talvez removê-lo.
3. **`info_2via_diploma`**: a taxa de GRU está mencionada genericamente ("valor publicado em edital") — confirmar se PROGRAP ainda cobra (algumas IES isentaram pós-2020).
4. **`info_quem_e_coordenadora`**: trio Stephania/Carolina/Lucas. Conferir se vice ainda é Carolina Calomeno.
5. **`enc_bolsas_assistencia_estudantil`**: telefone PRAE `(41) 3360-5180` — confirmar se ainda é esse.
6. **`enc_iniciacao_cientifica`**: cita janela "maio-julho" para edital PIBIC anual — confirmar se ainda é assim em 2026.
7. **`enc_monitoria`**: assume que PROGRAP publica o edital (era PROGRAD) — confirmar fonte oficial.
8. **`estagio_obrig_tce_inicial`**: o intent assume `sei_process_type: "Graduação/Ensino Técnico: Estágio Obrigatório"` — conferir nome exato do tipo no SEI.
9. **`estagio_obrig_ic_substituicao_fluxo`**: o despacho menciona "submeter à COE" — confirmar se a COE realmente recebe esse pedido (ou se é o Colegiado).
10. **`matricula_provar`**: cita Resolução 91/14-CEPE — confirmar número/ano (pode ter sido alterada).
11. ~~**`afc_atividades_validas`**: link http://sacod.ufpr.br/coordesign/atividades-formativas-complementares-dg/ — verificar se ainda funciona.~~ ✅ **Confirmado pelo coordenador em 2026-04-27**: `https://sacod.ufpr.br/coordesign/atividades-formativas-complementares-dg/` está correto. Nada a mudar no intent.
12. **`enade`**: instrução pra aluno checar via SIGA → Aluno → "Regularidade ENADE" — conferir se o menu se chama assim hoje.

---

## Correções propostas durante a revisão

> Use este espaço para anotar correções/edições. Quando a revisão fechar, posso aplicar as
> mudanças em batch e atualizar `last_update` dos intents tocados.

### `<intent_name>`
<!-- Cole aqui o que mudar; ex: trocar X por Y. -->

---

## Status

- [ ] Revisão concluída por: ___________________ em ____/____/____
- [ ] Correções aplicadas em PROCEDURES.md
- [ ] Tags `[A REVISAR — 2026-04-27]` removidas das seções §12–§16 após revisão
- [ ] Bench A/B pós-revisão validando cobertura via logs de runs agendados (procedures_data/ JSONL): meta `tier0_hits/total ≥ 0.85`
