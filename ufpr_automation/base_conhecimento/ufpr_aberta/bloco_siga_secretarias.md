# BLOCO 3 — Secretarias & Coordenações (UFPR Aberta, curso "Conheça o SIGA!")

> Fonte: https://ufpraberta.ufpr.br/course/view.php?id=9 seção 3 (acessado via scraper em 2026-04-14)
> Uso: workflows SIGA para secretarias/coord + authoring de intents Tier 0 + guia de navegação para `siga/browser.py`.

## Índice
- [Matrícula e ofertas](#matrícula-e-ofertas)
  - Funcionamento da Matrícula On-line
  - Como confirmar matrícula dos calouros
  - Como emitir lista de calouros
  - Como acessar o sistema
  - Como ofertar turmas
  - Como fazer ajuste de matrícula dos alunos
- [Deferimento de solicitações](#deferimento-de-solicitações)
  - Cancelamento de matrícula em disciplinas
  - Trancamento
  - Matrícula em disciplina eletiva
- [Equivalência / Adiantamento / Aproveitamento](#equivalência--adiantamento--aproveitamento)
  - Processo de Exame de Adiantamento
  - Análise de solicitações de equivalências (coordenação)
- [Reformulação de curso / Colação / Atividades Formativas](#reformulação-de-curso--colação--atividades-formativas)
  - Reformulação de curso
  - Colação de Grau sem solenidade
  - Cadastro de Atividades Formativas
- [Análise (abandono, indicadores)](#análise-abandono-indicadores)
  - Análise de abandono
  - Análise de Indicadores Acadêmicos
- [Diploma Digital](#diploma-digital)
- [Extensão (ACE)](#extensão-ace)
- [Outros](#outros)
  - Visualização de informações no portal do SIGA
  - Comprovante de vacinação das/os discentes

---

## Matrícula e ofertas

### Funcionamento da Matrícula On-line: turmas disponíveis e prioridades
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=250
**Público:** coord (e secretaria como apoio)
**Resumo em 1 linha:** Como o SIGA processa ofertas/matrículas automáticas, quais turmas ficam disponíveis para cada aluno e qual a ordem de prioridade na fila.

**Navegação SIGA** (caminho de menus):
- Visualizar solicitações de uma turma: `Disciplinas > Turmas > Relatórios > Localizar a turma > Lupa azul > Aba "Alunos-Solicitações"`
- Conferir matriz/correspondências/plano de adaptação: `Cursos > Localize o currículo > Visualizar PPC > aba "Matriz Curricular" | "Correspondências" | "Plano de Adaptação"`

**Regras de disponibilidade** (o SIGA libera para o aluno solicitar):
1. Turmas de disciplinas com códigos da matriz curricular do aluno, ou matrizes mais recentes desde que mapeadas em Plano de Adaptação.
2. Turmas de disciplinas em que o aluno cumpriu pré-requisito.
3. Turmas correspondentes ao currículo do aluno.

**Ordem de prioridade na alocação** (SIGA ordena nesta sequência):
1. Alunos do curso
2. Alunos do turno da turma
3. Alunos para os quais a disciplina é obrigatória
4. Alunos periodizados
5. Alunos em jubilamento
6. Alunos reprovados por nota
7. Alunos atrasados

Desempate: **NSC (Número de Semestres Cursados)** e depois **IRA**. Em cursos anuais o NSC é em anos, não semestres.

**Regras/constraints:**
- Correquisito: as duas disciplinas precisam ser solicitadas simultaneamente.
- Pré-requisito não vencido: a disciplina não aparece para o aluno.
- Se o aluno já venceu toda a CH de optativas, o sistema não mostra optativas.
- Uma turma só tem vagas para calouros se estiver no 1º período da matriz curricular.
- Uma optativa só dá prioridade a periodizados se estiver em algum período da matriz.
- Disciplina atual vale para aluno de currículo antigo **apenas se houver mapeamento em Plano de Adaptação**.
- Turmas na aba "Correspondências" aparecem para alunos de outros cursos, mas **com prioridade menor**.
- Periodização: Período Atual do aluno = período da disciplina na matriz. Atualizado pelo sistema após lançamento de notas no fim do semestre.
- **Não há quebra de pré-requisito automática.**
- Calouros não fazem solicitação — são matriculados automaticamente em todas as turmas do 1º período.

**Selectors úteis para automação (siga/browser.py):**
- Menu: "Disciplinas", "Turmas", "Relatórios"
- Ícone: "lupa azul" (Localizar a turma)
- Aba: "Alunos-Solicitações"
- Menu: "Cursos"; Botão: "Visualizar PPC"
- Abas no PPC: "Matriz Curricular", "Correspondências", "Plano de Adaptação"

---

### Como confirmar a matrícula dos calouros no Siga
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=18559
**Público:** coord/secretaria
**Resumo em 1 linha:** Confirmar matrícula de calouros no período do calendário — altera situação de "Temporário - Sem direito a matrícula" para "Registro Ativo".

**Navegação SIGA:**
- `Discentes > Confirmação de Matrícula`

**Passo a passo:**
1. Acessar menu `Discentes > Confirmação de Matrícula`.
2. O sistema lista calouros do semestre atual com coluna **Ações**.
3. Para confirmar a matrícula, clicar no botão de confirmação (altera situação do discente para **Registro Ativo**).
4. Para cancelar, clicar no botão de cancelamento (cancela a matrícula e lança **Evasão - Não confirmação de vaga**, liberando a vaga para chamada complementar).

**Regras/constraints:**
- Ação **irreversível**.
- Deve ser feita **dentro do período do calendário acadêmico**, senão o discente não tem acesso ao SIGA.
- Matrículas não confirmadas geram evasão automática e liberação da vaga para próxima chamada complementar.

**Selectors úteis para automação:**
- Menu: "Discentes" > "Confirmação de Matrícula"
- Coluna: "Ações"
- Botões: "Confirmar", "Cancelar" (ícones na linha do discente)

---

### Como emitir uma lista de calouros no Siga
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=14758
**Público:** coord/secretaria
**Resumo em 1 linha:** Gerar lista de calouros ingressantes no curso via Relatório Dinâmico de Discentes (exporta CSV/Excel).

**Navegação SIGA:**
- `Relatórios > Relatório Dinâmico de Discentes`

**Passo a passo:**
1. Acessar `Relatórios > Relatório Dinâmico de Discentes`.
2. Opcional: remover colunas "Documento submetido" e "Visualizar documento" para melhorar visualização.
3. Aplicar filtro **Período ingresso** (ex: "2022/1º") para ingressantes do 1º semestre de 2022.
4. Exportar em **CSV** ou **Excel**.

**Selectors úteis para automação:**
- Menu: "Relatórios" > "Relatório Dinâmico de Discentes"
- Filtro: "Período ingresso"
- Colunas removíveis: "Documento submetido", "Visualizar documento"
- Botões de export: "CSV", "Excel"

---

### Como acessar o sistema
**Fonte:** https://ufpraberta.ufpr.br/mod/url/view.php?id=187 (link externo — redirect Moodle)
**Público:** coord/secretaria
**Resumo em 1 linha:** Link externo redirecionando para o login do SIGA (sem conteúdo próprio no Moodle).
**Observação:** atividade do tipo `url` — apenas redirect, sem passo a passo local. URL-alvo típica: `https://siga.ufpr.br/`.

---

### Como ofertar turmas
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=282
**Público:** coord
**Resumo em 1 linha:** Fluxo completo de oferta de turmas para um semestre letivo — cadastro → envio ao departamento → abertura para matrícula.

**Navegação SIGA:**
- `Disciplinas > Turmas > Ofertar Turmas`

**Passo a passo:**
1. Acessar `Disciplinas > Turmas > Ofertar Turmas`. A tela tem dois lados: **esquerdo/verde** (nova turma) e **direito/azul** (turmas criadas ainda não alocadas/abertas).
2. Preencher **Disciplina a ser ofertada** (código ou nome).
3. Selecionar **Turno**.
4. Preencher nome da turma e **vagas disponíveis** em "Informações da Turma".
5. Campo **Vagas para Calouros**: aparece **somente se a disciplina for de 1º período**.
6. Selecionar horário e dia em **Dias de Aula** (clicar no horário — fica verde).
7. Selecionar **Tipos de Aula** (Padrão, Laboratório, Campo, etc).
8. Adicionar horários extras se necessário (clicar em mais horários).
9. **EAD**: botão `<Adicionar Aula EAD>` é opcional (sem marcação na grade).
10. Para remover horário: `<Remover Dia>` (volta a cinza).
11. Clicar `<Inserir Turma na Solicitação>` — a turma migra para o lado direito com situação **Em Edição**.
12. Em "Em Edição" pode `<Editar>`, `<Informações>` ou `<Remover Oferta>`.
13. Clicar `<Enviar ao Departamento>` — situação muda para **Para alocação**.
14. Aguardar departamento alocar professor — turma retorna com situação **Ofertada**.
15. Clicar `<Abrir para matrícula dos alunos>` — só após este clique a turma aceita solicitações de matrícula.

**Regras/constraints:**
- Dentro do prazo previsto em calendário.
- Turmas com **ACE I e ACE II** (CH de extensão) **exigem** vínculo obrigatório com projeto de extensão; o coordenador do projeto confirma a aprovação. A vinculação pode ser alterada depois via `Relatórios de Turmas > aba Extensão`.
- Vagas para calouros: só em disciplinas de 1º período.

**Selectors úteis para automação:**
- Menu: "Disciplinas" > "Turmas" > "Ofertar Turmas"
- Campo: "Disciplina a ser ofertada", "Turno", "Informações da Turma", "Vagas para Calouros"
- Grade: "Dias de Aula", "Tipos de Aula"
- Botões: "Adicionar Aula EAD", "Remover Dia", "Inserir Turma na Solicitação", "Editar", "Informações", "Remover Oferta", "Enviar ao Departamento", "Abrir para matrícula dos alunos"
- Situações de turma: "Em Edição", "Para alocação", "Ofertada"
- Para edição pós-oferta: `Relatórios de Turmas` > aba "Extensão"

---

### Como fazer ajuste de matrícula dos alunos
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=292
**Público:** coord/secretaria
**Resumo em 1 linha:** Após período on-line de ajuste, a coordenação insere/retira turmas de alunos por duas vias (Gerenciar Matrículas ou Relatório da Turma).

**Navegação SIGA (opção A — por aluno):**
- `Discentes > Gerenciar Matrículas`

**Passo a passo (A):**
1. Acessar `Discentes > Gerenciar Matrículas`.
2. Pesquisar aluno por **nome** ou **GRR**.
3. Sistema exibe GRR, nome, grade horária e lista de turmas matriculadas.
4. Para adicionar: clicar `<Inserir Turma>` → digitar sigla/nome no campo Pesquisar → `<Inserir Turma>` (ou `<Inserir Turma mesmo assim>` se houver alerta de verificação).
5. Para remover: selecionar item da lista → `<Remover Matrícula>` (não deixa registro no histórico — usar quando a turma foi inserida erroneamente).

**Navegação SIGA (opção B — por turma):**
- `Disciplinas > Turmas > Relatório`

**Passo a passo (B):**
1. Acessar `Disciplinas > Turmas > Relatório`.
2. Clicar na lupa da turma desejada.
3. Abrir aba **Alunos-Matriculados**.
4. Pesquisar aluno por nome/GRR → `<Adicionar Aluno na Turma>`.
5. Para remover: botão `<Remover>` na linha do aluno.

**Regras/constraints:**
- Só dentro do prazo previsto no calendário pós-ajuste on-line.
- `<Remover Matrícula>` **não** gera histórico (diferente de cancelamento).

**Selectors úteis para automação:**
- Menu: "Discentes" > "Gerenciar Matrículas" | "Disciplinas" > "Turmas" > "Relatório"
- Campo: "Pesquisar" (aluno ou disciplina)
- Aba: "Alunos-Matriculados"
- Botões: "Inserir Turma", "Inserir Turma mesmo assim", "Remover Matrícula", "Adicionar Aluno na Turma", "Remover"

---

## Deferimento de solicitações

### Como deferir ou indeferir solicitações de cancelamento de matrícula em disciplinas
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=10417
**Público:** coord
**Resumo em 1 linha:** Analisar pedidos de cancelamento de matrícula dos discentes e, acima/abaixo da CH mínima, aplicar o procedimento adequado.

**Navegação SIGA:**
- `Discentes > Cancelamentos de Turmas`
- Cancelamento abaixo da CH mínima: `Turmas > Relatório > aba Alunos - Matriculados`

**Passo a passo (acima da CH mínima):**
1. Acessar `Discentes > Cancelamentos de Turmas`.
2. Lista todas as solicitações do curso; filtros disponíveis: **Período** e **Situação** (Solicitado, Deferido, Indeferido).
3. Na linha da solicitação clicar **Deferir** (cancela matrícula naquela turma no semestre atual) ou **Indeferir** (mantém matrícula e registra recusa).
4. Após análise, as solicitações permanecem na tela; coluna **Situação** mostra o resultado.
5. O discente consulta o resultado em `Disciplinas > Turmas Atuais` (situação: "Cancelado" ou "Cancelamento Indeferido").

**Passo a passo (abaixo da CH mínima):**
1. O discente solicita por outros canais (email, balcão da secretaria).
2. Dentro do evento de calendário SIGA **"Cancelamento de matrícula pela coordenação (Abaixo CH mínima)"**, acessar `Turmas > Relatório > aba Alunos - Matriculados`.
3. Clicar `<Cancelar>` na linha do aluno.

**Regras/constraints:**
- Cancelamento abaixo da CH mínima só pode ser feito dentro do evento específico do calendário SIGA.

**Selectors úteis para automação:**
- Menu: "Discentes" > "Cancelamentos de Turmas"
- Filtros: "Período", "Situação"
- Botões: "Deferir", "Indeferir", "Cancelar"
- Menu alt: "Turmas" > "Relatório" > aba "Alunos - Matriculados"
- Evento de calendário: "Cancelamento de matrícula pela coordenação (Abaixo CH mínima)"

---

### Como deferir ou indeferir solicitações de trancamento
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=172
**Público:** coord
**Resumo em 1 linha:** Fluxo de análise dos 3 trancamentos de curso possíveis — 1º não exige ata, 2º/3º exigem ata do colegiado em PDF.

**Navegação SIGA:**
- `Discentes > Trancamentos`

**Passo a passo:**
1. Acessar `Discentes > Trancamentos`. Lista ordenada por data decrescente; inclui solicitações, trancamentos ativos e destrancados.
2. Ver solicitação clicando no ícone da **lupa**.
3. **1º trancamento**: aluno não anexa documento/justificativa; coord analisa e clica em `<Deferir Trancamento>` ou `<Indeferir Trancamento>`. Abre janela de **observações** (não obrigatória) → `<Confirmar>`.
4. **2º trancamento**: analisar justificativa + documentos do discente. **Obrigatório anexar ata do colegiado (PDF)** tanto para Deferir quanto Indeferir. Observações opcionais → `<Confirmar>`.
5. **3º trancamento**: mesmo procedimento do 2º (ata do colegiado obrigatória).

**Regras/constraints:**
- **ATENÇÃO**: Deferir trancamento **remove** todas as solicitações pendentes de equivalências, exames e matrículas. Disciplinas com matrícula em curso são removidas do histórico. Aprovadas / equivalências lançadas / exames aprovados no período permanecem no relatório de integralização.
- 2º e 3º trancamento: **ata do colegiado em PDF é obrigatória**.

**Selectors úteis para automação:**
- Menu: "Discentes" > "Trancamentos"
- Ícone: "lupa"
- Botões: "Deferir Trancamento", "Indeferir Trancamento", "Confirmar"
- Campo: "observações" (opcional)
- Upload: campo de anexo de PDF da ata do colegiado

---

### Como analisar as solicitações de matrícula em disciplina eletiva
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=176
**Público:** coord **e** departamento (fluxo em 2 etapas)
**Resumo em 1 linha:** Eletiva passa por 2 autorizações: primeiro departamento da disciplina, depois coordenação do curso do aluno; se ambos autorizam, vai ao COPAP que matricula.

**Navegação SIGA (departamento — 1ª etapa):**
- `Discentes > Solicitações de Matrícula Eletiva`

**Navegação SIGA (coordenação — 2ª etapa):**
- `Discentes > Gerenciar Matrículas Eletivas`

**Passo a passo (departamento):**
1. Acessar `Discentes > Solicitações de Matrícula Eletiva`.
2. Visualizar solicitação (discente, turma, data/hora, **vagas restantes**).
3. Clicar `<Autorizar>` (envia à coord do curso do aluno) ou `<Não Autorizar>` (pára aqui).

**Passo a passo (coordenação):**
1. Acessar `Discentes > Gerenciar Matrículas Eletivas`.
2. Lista de solicitações já aprovadas pelo departamento.
3. Clicar `<Visualizar>` para ver disciplinas/turmas solicitadas e histórico escolar.
4. `<Cancelar>` volta à tela anterior.
5. `<Autorizar>` ou `<Não Autorizar>` por solicitação.
6. Se ambos aprovam, COPAP recebe e efetiva a matrícula.

**Regras/constraints de elegibilidade** (checadas pelo SIGA no pedido do aluno):
- Disciplina **não pode** ser do curso do aluno.
- Aluno **deve estar matriculado** em disciplina do seu curso.
- Limite: **3 eletivas por período**.
- Deve haver vagas.
- Não ultrapassar CH limite do curso (curriculares + eletivas).
- Não ultrapassar 8h diárias nem 40h semanais.
- SIGA **não** faz análise de pré-requisito em eletiva.
- **Importante**: checar vagas restantes antes de autorizar.

**Selectors úteis para automação:**
- Menu (depto): "Discentes" > "Solicitações de Matrícula Eletiva"
- Menu (coord): "Discentes" > "Gerenciar Matrículas Eletivas"
- Botões: "Autorizar", "Não Autorizar", "Visualizar", "Cancelar"

---

## Equivalência / Adiantamento / Aproveitamento

### Processo de Exame de Adiantamento
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=18811
**Público:** coord (recebe) + departamento (agenda/lança nota)
**Resumo em 1 linha:** Aluno solicita adiantamento → coord defere com ata do colegiado → depto agenda exame → depto lança nota no SIGA.

**Navegação SIGA:**
- Aluno: `Exames` (no menu lateral do aluno)
- Coord: `Exames`
- Depto: `Exames`

**Passo a passo (aluno — para referência):**
1. Menu `Exames`, selecionar **tipo do exame** e pesquisar disciplina pelo código em "Pesquisar disciplina".
2. Inserir justificativa via `<Selecionar arquivo>`.
3. Clicar `<Solicitar>` — envia para a coordenação.

**Passo a passo (coordenação):**
1. Acessar menu `Exames`.
2. Abrir solicitação; visualizar justificativa via `<Ver Justificativa>`.
3. Anexar **Ata do colegiado** via `<Selecionar arquivo>`.
4. Clicar `<DEFERIDO>` ou `<INDEFERIDO>` conforme decisão.
5. Opcional: `<Cancelar a pedido do aluno>` (**irreversível**).
6. Se deferido, o sistema notifica o departamento automaticamente.

**Passo a passo (departamento):**
1. Acessar menu `Exames`.
2. Ver `<Ver Justificativa>` e `<Ver Ata do colegiado>`.
3. Opcional: `<Cancelar a pedido do aluno>`.
4. Clicar `<Agendar>` → preencher **Local**, **Data**, **Horário** → `<Agendar>` para confirmar.
5. Após realização: clicar `<Resultado>` → preencher campo **Nota** → `<Salvar>`.
6. Histórico do aluno é atualizado com aprovação/reprovação automaticamente.

**Regras/constraints:**
- Sistema permite solicitar exame para **qualquer quantidade** de disciplinas no período, desde que o aluno **não** esteja matriculado na disciplina solicitada.
- `<Cancelar a pedido do aluno>` é **irreversível**.

**Selectors úteis para automação:**
- Menu: "Exames"
- Botões: "Selecionar arquivo", "Ver Justificativa", "Ver Ata do colegiado", "DEFERIDO", "INDEFERIDO", "Cancelar a pedido do aluno", "Agendar", "Resultado", "Salvar", "Solicitar"
- Campos: "Pesquisar disciplina", "Local", "Data", "Horário", "Nota"

---

### Análise de solicitações de equivalências (coordenação)
**Fonte:** https://ufpraberta.ufpr.br/mod/resource/view.php?id=47475
**Público:** coord
**Resumo em 1 linha:** Conteúdo em PDF — ver `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta\bloco_3_bloco_3_secretarias_e_coordenacoes_de_cursos_de_graduacao\Análise de solicitações de equivalências - Coordenação.pdf`. Resumo manual pendente.

> Notas para authoring: o PDF complementa o fluxo docente (bloco 2 `Equivalencia docente.pdf`) e o fluxo de departamento (bloco 4 `Analise de solicitaçoes de equivalencia - departamento.pdf`). A solicitação do aluno está em bloco 1 `Como solicitar equivalencia.pdf`.

---

## Reformulação de curso / Colação / Atividades Formativas

### Como fazer uma reformulação de curso
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=235
**Público:** coord (perfil **Coordenador PPC**) / comissão do projeto pedagógico
**Resumo em 1 linha:** Configurar novo currículo/reformulação pelo Checklist do PPC e submeter à análise PROGRAD/COPAC → COAFE/PROEC/CIPEAD → CEPE.

**Navegação SIGA:**
- `Cursos > [clicar lupa da proposta / Visualizar PPC]`
- Abas do PPC: **Dados Gerais**, **Comissão do Projeto Pedagógico**, **Projeto Pedagógico**, **Matriz Curricular**, **Correspondências**, **Plano de adaptação**, **Documentos**, **Pareceres**.

**Pré-requisito:** contatar **PROGRAD/COPAC** para criar o novo currículo no SIGA (COPAC habilita o currículo para a coord/comissão editar).

**Passo a passo:**
1. Perfil Coordenador PPC → `Cursos` → localizar proposta → clicar **lupa** (ou `<Visualizar PPC>` na coord).
2. Sistema exibe **Checklist** com pendências em laranja.
3. **Aba Dados Gerais**: preencher campos → `<Salvar>`.
4. **Aba Comissão do Projeto Pedagógico**: `<Adicionar novo membro da comissão +>` / `<Encerrar>`.
5. **Aba Projeto Pedagógico**: por seção, clicar `<Editar conteúdo>` → preencher → `<Salvar conteúdo>`.
6. **Aba Matriz Curricular**:
   - Inserir número mínimo de períodos → `<Salvar>`.
   - Botão `<+>` no canto superior direito de cada período para adicionar disciplinas obrigatórias (pré-req: disciplina cadastrada pelo depto e vinculada ao curso).
   - Preencher CH de optativas, atividades formativas, componentes flexíveis.
   - Tags para vincular optativas a ênfases.
   - ACE I e ACE II: escolher subconjunto de disciplinas com CH de extensão.
   - ACE III, IV e V: CH que será integralizada por creditação analisada pela coord.
   - CH de extensão **≥ 10% da CH total** da matriz.
7. **Aba Correspondências**: mapear disciplinas de outros cursos que vencem disciplinas do currículo. Anexar **ata de aprovação da outra coordenação** em "Documentos".
8. **Aba Plano de adaptação**: mapear, por disciplina do currículo atual, a disciplina do currículo anterior que a vence (regras E/OU). Vale para optativas também.
9. **Aba Documentos**: anexar atas + outros documentos da COPAC via `<Adicionar Novo Documento>` → `<Escolher arquivo>`.
10. Quando Checklist habilitar: `<Enviar Proposta para Análise da Prograd>` → `<Confirmar envio>`.
11. Acompanhar pareceres em **aba Projeto Pedagógico** (`<Visualizar>`, `<Comparar com atual>`) e **aba Pareceres**.
12. Pareceres: COAFE, PROEC, PROGRAD; se há CH EAD também CIPEAD.
13. Com todos pareceres favoráveis, PROGRAD/COPAC envia ao **CEPE** (coordenada pela PROGRAD, status alterado no SIGA).

**Regras/constraints:**
- Perfil **Coordenador PPC** obrigatório.
- Disciplina só aparece na matriz se cadastrada pelo depto e vinculada ao curso.
- CH de extensão ≥ 10% da CH total.
- Correspondências: alunos de outros cursos têm **menor prioridade** nas turmas mapeadas.

**Selectors úteis para automação:**
- Menu: "Cursos"
- Botões: "Visualizar PPC", "Salvar", "Adicionar novo membro da comissão +", "Encerrar", "Editar conteúdo", "Salvar conteúdo", "+" (add disciplina/CH), "Adicionar Novo Documento", "Escolher arquivo", "Enviar Proposta para Análise da Prograd", "Confirmar envio", "Cancelar", "Visualizar", "Comparar com atual"
- Abas: "Dados Gerais", "Comissão do Projeto Pedagógico", "Projeto Pedagógico", "Matriz Curricular", "Correspondências", "Plano de adaptação", "Documentos", "Pareceres"
- Lista de pareceres: COAFE, PROEC, PROGRAD, CIPEAD (se EAD)

---

### Como solicitar Colação de Grau sem solenidade
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=283
**Público:** coord
**Resumo em 1 linha:** Agendar colação SEM solenidade: gerar relatório de integralização → agendar → verificar Enade → enviar à COPAP → anexar ata após colação.

**Navegação SIGA:**
- `Relatórios > Integralização`
- `Colações de Grau`

**Passo a passo:**
1. **Pré-requisito**: `Relatórios > Integralização` → `<Gerar Relatório>`. Isso altera situação dos alunos de "Matriculado" para "Integralizado".
2. Acessar `Colações de Grau` → `<Solicitar Colação>`.
3. Preencher formulário (campos com "*" obrigatórios).
4. `<Selecionar Formandos>` → lista de aptos no período → clicar **Incluir** na coluna "Incluir na Colação" para cada discente → `<Salvar>` ao final.
5. Solicitação aparece na lista com situação **Agendado/Enviar a COPAP**. Clicar no número para abrir.
6. Na **aba Informações Gerais**, preencher:
   - **Local** da colação.
   - **Processo SEI** referente.
7. **Aba Discentes**: verificar regularização do **Enade**. Se irregular, clicar `<Verificar Enade>`. Se persistir irregular, contatar **UNIRAI** e repetir. Regular = sem ação.
8. Na aba Informações Gerais, 2 opções:
   - `<Cancelar Agendamento>`: inserir motivo → `<Confirmar cancelamento>`.
   - `<Enviar solicitação para a COPAP>`: irreversível quanto à edição; envia para análise da COPAP.
9. COPAP analisa: se confirma → situação **Confirmada**. Se enviar em diligência, mensagem anexada — coord edita e `<Enviar solicitação para a COPAP>` de novo.
10. Após realizada a colação, anexar **Ata de Colação** (PDF) pela aba **Documentos**: `<Escolher arquivo>` → `<Enviar>`.
11. COPAP verifica presentes e libera emissão de diplomas → situação **Liberado emissão de diplomas**.

**Regras/constraints:**
- Gerar relatório de integralização **antes** de solicitar colação (altera "Matriculado" → "Integralizado").
- Ata da colação: **PDF**, obrigatória pós-evento.
- Enade irregular impede envio — escalar UNIRAI.
- Após enviar à COPAP, não é possível alterar informações até diligência.

**Selectors úteis para automação:**
- Menu: "Relatórios" > "Integralização", "Colações de Grau"
- Botões: "Gerar Relatório", "Solicitar Colação", "Selecionar Formandos", "Incluir", "Salvar", "Verificar Enade", "Cancelar Agendamento", "Confirmar cancelamento", "Enviar solicitação para a COPAP", "Escolher arquivo", "Enviar"
- Abas: "Informações Gerais", "Discentes", "Documentos"
- Campos: "Local", "Processo SEI"
- Situações: "Agendado/Enviar a COPAP", "Confirmada", "Liberado emissão de diplomas"

---

### Como cadastrar Atividades Formativas
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=293
**Público:** coord
**Resumo em 1 linha:** Cadastrar atividades formativas de discentes do curso via aba "Atividades Formativas" na ficha do aluno; horas vão para Integralização.

**Navegação SIGA:**
- `Discentes > Consulta > [clicar nome do discente] > aba "Atividades Formativas"`

**Passo a passo:**
1. Acessar `Discentes > Consulta`.
2. Localizar discente (filtros + busca) e clicar no nome.
3. Na ficha do discente, abrir aba **Atividades Formativas**.
4. Clicar `<Cadastrar>` — cria registro em branco.
5. Clicar `<Editar>` para habilitar edição dos campos **Descrição**, **Horas**, **Número Processo SEI**.
6. Preencher e `<Salvar>`.
7. As horas aparecem na aba **Integralização** (total do discente) e detalhadas ao final da página.

**Selectors úteis para automação:**
- Menu: "Discentes" > "Consulta"
- Abas: "Atividades Formativas", "Integralização"
- Botões: "Cadastrar", "Editar", "Salvar"
- Campos: "Descrição", "Horas", "Número Processo SEI"

---

## Análise (abandono, indicadores)

### Análise de abandono
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=14652
**Público:** coord
**Resumo em 1 linha:** No período da COPAP, indicar quais discentes sem matrícula devem ter abandono lançado — COPAP confirma evasão.

**Navegação SIGA:**
- `Análise de Abandono` (menu)

**Passo a passo:**
1. Acessar menu `Análise de Abandono`. Lista de discentes sem matrícula no período vigente.
2. Por discente, consultar `<Histórico>` e `<Integralização>`.
3. Selecionar **Lançar Abandono** ou **Não Lançar Abandono**.
4. Se "Lançar Abandono": COPAP analisa e, se confirmar, cadastra evasão.
5. Se "Não Lançar Abandono": clicar `<Justificativa>` → inserir texto + anexar documentos → `<Salvar>`.

**Regras/constraints:**
- Só dentro do período definido pela COPAP.
- "Não Lançar Abandono" exige justificativa com anexos.

**Selectors úteis para automação:**
- Menu: "Análise de Abandono"
- Botões: "Histórico", "Integralização", "Lançar Abandono", "Não Lançar Abandono", "Justificativa", "Salvar"

---

### Análise de Indicadores Acadêmicos
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=912
**Público:** coord
**Resumo em 1 linha:** Dashboard de indicadores (disciplinas, ofertas, integralização) filtrados por "Ano de Ingresso" — apoia decisão de oferta e acompanhamento acadêmico.

**Navegação SIGA:**
- `Indicadores Acadêmicos` (menu)

**Estrutura (3 abas):**

**Aba DISCIPLINAS:**
- Gráfico 1: disciplinas dos currículos selecionados ordenadas por demanda (mais → menos). Barras: VERDE = periodizados; VERMELHO = desperiodizados (atrasados); AZUL = alunos do período anterior à periodização recomendada.
- Gráfico 2: demanda de optativas — barras indicam quantos alunos poderiam cursá-la (máx 500 optativas).
- Botão `<Baixar dados>` em CSV em cada gráfico.

**Aba OFERTAS:**
- Grupo "Situação dos alunos nas turmas": "Contagem de alunos por situação e período" (aprovados, cancelados, matriculados, reprovados por frequência, reprovados por nota) + versão percentual. O sistema conta matrículas (pode passar do total de alunos).
- Grupo "Alunos com dificuldades acadêmicas" (Figura 3): por período — sem matrícula / só cancelados / só reprovações / cancelados+matriculados / reprovados+matriculados. CSV inclui GRR e nome.
- Grupo "Disciplinas vencidas durante o período especial": quantitativos de alunos que venceram disciplinas em período especial estando matriculados em 2020/1.

**Aba INTEGRALIZAÇÃO:**
- Gráfico "Carga horária integralizada x período atual": dispersão alunos × CH integralizada. Linhas = relação período × CH das matrizes.
- Gráfico "Carga horária integralizada por aluno": ranking por CH; separa optativas, atividades formativas, obrigatórias. Combinado com filtro de ano de ingresso, identifica alunos com problemas de integralização.

**Regras/constraints:**
- Todo filtro parte da barra **Ano de Ingresso** (obrigatório definir o subconjunto analisado).

**Selectors úteis para automação:**
- Menu: "Indicadores Acadêmicos"
- Barra/filtro: "Ano de Ingresso"
- Abas: "Disciplinas", "Ofertas", "Integralização"
- Botão: "Baixar dados" (CSV)

---

## Diploma Digital

### Diploma Digital - Manual da Coordenação
**Fonte:** https://ufpraberta.ufpr.br/mod/resource/view.php?id=25978
**Público:** coord
**Resumo em 1 linha:** Conteúdo em PDF — ver `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta\bloco_3_bloco_3_secretarias_e_coordenacoes_de_cursos_de_graduacao\Diploma Digital - Manual da Coordenação.pdf`. Resumo manual pendente.

### Diploma Digital - Perfil Egresso
**Fonte:** https://ufpraberta.ufpr.br/mod/resource/view.php?id=25979
**Público:** coord (repassar ao egresso)
**Resumo em 1 linha:** Conteúdo em PDF — ver `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta\bloco_3_bloco_3_secretarias_e_coordenacoes_de_cursos_de_graduacao\Tutorial Diploma Digital - Perfil Egresso.pdf`. Resumo manual pendente.

---

## Extensão (ACE)

### Creditação da Extensão: Como deferir ou indeferir solicitações de ACE III, IV e V
**Fonte:** https://ufpraberta.ufpr.br/mod/resource/view.php?id=26114
**Público:** coord
**Resumo em 1 linha:** Conteúdo em PDF — ver `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta\bloco_3_bloco_3_secretarias_e_coordenacoes_de_cursos_de_graduacao\Como analisar solicitações de ACE III, IV e V.pdf`. Resumo manual pendente.

> Notas para authoring: creditação da extensão (ACE III/IV/V) é feita por creditação analisada pela coord conforme a nova reformulação de curso (ver seção "Como fazer uma reformulação de curso" — CH de extensão ≥ 10% da CH total da matriz). O aluno solicita via bloco 1 `Como solicitar ACE III, IV e V.pdf`.

---

## Outros

### Visualização de informações dos cursos de graduação no portal do Siga
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=15335
**Público:** coord/secretaria (e público externo)
**Resumo em 1 linha:** Portal público do SIGA para consultar matriz curricular, disciplinas e ementas dos cursos — sem login.

**URL do portal:** https://siga.ufpr.br/portal/

**Navegação (portal):**
- `Ensino > Graduação > Cursos` — lista currículos (filtrar por versão/grau/habilitação) → `<Visualizar>` → abas **Dados Gerais** / **Matriz Curricular**.
- `Ensino > Graduação > Disciplinas` — busca por código ou filtros.

**Conteúdo disponível:**
- Dados Gerais: Modalidade, Regime, Duração, Carga horária.
- Matriz Curricular: disciplinas por período, CH, pré-req, correquisitos.
- Clicar no código da disciplina abre ementa (se o depto preencheu).

**Selectors úteis para automação:**
- Menu: "Ensino" > "Graduação" > "Cursos" | "Disciplinas"
- Botão: "Visualizar"
- Abas: "Dados Gerais", "Matriz Curricular"
- URL base: `https://siga.ufpr.br/portal/`

---

### Como visualizar o comprovante de vacinação das/os discentes
**Fonte:** https://ufpraberta.ufpr.br/mod/page/view.php?id=12059
**Público:** coord
**Resumo em 1 linha:** Consultar/inserir/alterar comprovante de vacinação na aba "Comprovante de vacinação" da ficha do aluno; relatório via Relatório Dinâmico.

**Navegação SIGA:**
- Ficha do aluno: `Discentes > Consultar > [aluno] > aba "Comprovante de vacinação"`
- Relatório: `Relatórios > Relatório Dinâmico de Discentes`

**Passo a passo:**
1. Acessar cadastro do aluno → aba **Comprovante de vacinação**.
2. Para **ver**: `<Ver Arquivo>`.
3. Para **inserir**: selecionar tipo de documento → `<Selecionar arquivo>` → `<Salvar>`.
4. Para **alterar**: clicar no ícone **amarelo** ao lado de "Ver Arquivo" → selecionar tipo + novo arquivo → `<Salvar>`.
5. Consulta em massa:
   - `Relatórios > Relatório Dinâmico de Discentes`: colunas "Documento Submetido" e "Visualizar documento".
   - `Discentes > Consultar`: mesmas colunas.

**Selectors úteis para automação:**
- Menu: "Discentes" > "Consultar"
- Aba: "Comprovante de vacinação"
- Botões: "Ver Arquivo", "Selecionar arquivo", "Salvar"
- Ícone: "amarelo" (editar arquivo existente)
- Relatório: "Relatórios" > "Relatório Dinâmico de Discentes"
- Colunas: "Documento Submetido", "Visualizar documento"

---

## Atividades apenas em PDF (resumo manual pendente)

- **Análise de solicitações de equivalências** (Coordenação) — `Análise de solicitações de equivalências - Coordenação.pdf`
- **Creditação da Extensão: Como deferir ou indeferir solicitações de ACE III, IV e V** — `Como analisar solicitações de ACE III, IV e V.pdf`
- **Diploma Digital - Manual da Coordenação** — `Diploma Digital - Manual da Coordenação.pdf`
- **Diploma Digital - Perfil Egresso** — `Tutorial Diploma Digital - Perfil Egresso.pdf`
- **Como acessar o sistema** — atividade do tipo `url` (link externo para SIGA), sem conteúdo Moodle próprio.
