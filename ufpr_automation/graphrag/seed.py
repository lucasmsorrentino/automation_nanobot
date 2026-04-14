"""Seed the Neo4j knowledge graph with UFPR institutional data.

Sources:
    - SOUL.md (hierarchy, norms, workflows, templates)
    - ClaudeCowork/BaseDeConhecimento/SEI/manual.txt
    - ClaudeCowork/BaseDeConhecimento/SIGA/manual_siga.txt
    - ClaudeCowork/BaseDeConhecimento/FichaDoCurso.txt
    - ClaudeCowork/BaseDeConhecimento/estagios/*.txt

Usage:
    python -m ufpr_automation.graphrag.seed              # full seed
    python -m ufpr_automation.graphrag.seed --clear       # clear graph first
    python -m ufpr_automation.graphrag.seed --dry-run     # print stats only
"""

from __future__ import annotations

import argparse

from ufpr_automation.graphrag.client import Neo4jClient
from ufpr_automation.graphrag.schema import apply_constraints
from ufpr_automation.utils.logging import logger

# ============================================================================
# Despacho templates (SOUL.md section 14) — seeded into Template nodes so that
# sei/client.py can fetch them at runtime via graphrag.templates.TemplateRegistry.
# ============================================================================

_DESPACHO_HEADER = """UNIVERSIDADE FEDERAL DO PARANA
COORDENACAO DO CURSO DE DESIGN GRAFICO
Rua General Carneiro, 460, 8o andar - sala 801 - Bairro Centro, Curitiba/PR, CEP 80060-150
Telefone: 41 3360-5360 - https://ufpr.br/

Despacho no [NUMERO]/[ANO]/UFPR/R/AC/CCDG

Processo no [NUMERO_PROCESSO_SEI]"""

_DESPACHO_FOOTER = """Certa de sua atencao, solicitamos sequencia nos encaminhamentos devidos.

Atenciosamente,

Stephania Padovani
Coordenadora do Curso de Design Grafico"""

_DESPACHO_TEMPLATES: dict[str, str] = {
    "tce_inicial": """Prezados,

        A Coordenacao do Curso de Design Grafico acusa o recebimento do Termo de
Compromisso de Estagio no [NUMERO_TCE] (SEI [NUMERO_SEI_TCE]) e manifesta-se favoravel
a realizacao do Estagio [Nao Obrigatorio / Obrigatorio] do estudante [NOME COMPLETO DO
ALUNO EM MAIUSCULAS], [GRR_MATRICULA], na [NOME DA CONCEDENTE EM MAIUSCULAS],
[programa: NOME DO PROGRAMA se houver], no periodo de [DD/MM/AAAA] a [DD/MM/AAAA],
com jornada de [X] horas diarias, totalizando [Y] horas semanais, sendo a jornada realizada de
forma compativel com as atividades academicas.

        Por este despacho, declaro tambem minha assinatura no referido documento, que
corresponde tanto como professora orientadora do estagio quanto como coordenadora de curso,
e informamos que ratifica-se integralmente o Termo de Compromisso de Estagio no [NUMERO_TCE],
anexo a este processo, para todos os fins legais.""",
    "aditivo": """Prezadas/os,

        A Coordenacao do Curso de Design Grafico acusa o recebimento do Relatorio Parcial de
Estagio (SEI [NUMERO_SEI_RELATORIO]), do Termo de Aditivo de Estagio Numero [NUMERO_ADITIVO]
(SEI [NUMERO_SEI_ADITIVO]), referente ao Termo de Estagio original no [NUMERO_TCE_ORIGINAL]
[da Agente de Integracao / (SEI NUMERO_SEI_TCE_ORIGINAL)], e manifesta-se favoravel a
continuacao do Estagio Nao Obrigatorio da estudante [NOME COMPLETO] - [GRR], na
[NOME DA CONCEDENTE], prorrogando a vigencia ate dia [DD/MM/AAAA], preservadas as demais
clausulas do termo original.

        Por este despacho, ainda informo que a minha assinatura nos referidos documentos,
corresponde tanto como professora orientadora do estagio, como coordenadora de curso, e
informamos que ratifica-se integralmente o Aditivo no [NUMERO_ADITIVO] do Termo de
Compromisso de Estagio no [NUMERO_TCE_ORIGINAL], anexo a este processo, para todos os
fins legais.""",
    "rescisao": """Prezados/as,

        A Coordenacao do Curso de Design Grafico acusa o recebimento do Relatorio [Final /
de Final] de Estagio (SEI [NUMERO_SEI_RELATORIO]) e do Termo de Rescisao/Conclusao
[no. NUMERO_RESCISAO] (SEI [NUMERO_SEI_RESCISAO]), referentes ao Contrato "Termo de
Compromisso de Estagio" no. [NUMERO_TCE] da Parte Concedente e/ou Agente Integradora,
do(a) estudante [NOME COMPLETO], [GRR], na [NOME DA CONCEDENTE], referente ao periodo
de [DD/MM/AAAA] ate [DD/MM/AAAA].

        Por este despacho, informo ainda, minha assinatura nos referidos documentos como
coordenadora de curso e/ou professora orientadora, e informo tambem que ratificam-se
integralmente os documentos referentes ao Termo de Compromisso de Estagio no. [NUMERO_TCE]
[e Termo de Rescisao no NUMERO_RESCISAO], anexos a este processo, para todos os fins legais.""",
}


def _compose_despacho(tipo: str) -> str:
    """Compose full despacho text by joining header + body + footer with blank lines.

    Must match exactly what sei.client.SEIClient.prepare_despacho_draft used to
    produce so that downstream placeholder substitution keeps working.
    """
    body = _DESPACHO_TEMPLATES[tipo]
    return f"{_DESPACHO_HEADER}\n\n{body}\n\n{_DESPACHO_FOOTER}"


# Mapping of existing Template nodes (by their `nome` property as seeded in
# _seed_templates) to the despacho_tipo string used by sei/models.py.
_DESPACHO_NODE_MAP: dict[str, str] = {
    "Despacho SEI: TCE Inicial": "tce_inicial",
    "Despacho SEI: Termo Aditivo com Relatório": "aditivo",
    "Despacho SEI: Rescisão/Conclusão": "rescisao",
}


# ============================================================================
# 1. ORGANIZATIONAL HIERARCHY
# ============================================================================

def _seed_orgaos(client: Neo4jClient) -> int:
    """Create organizational units and SUBORDINADO_A relationships."""
    cypher = """
    // Top-level
    MERGE (reitoria:Orgao {sigla: 'REITORIA', nome: 'Reitoria da UFPR'})

    // Pró-Reitorias
    MERGE (prograp:Orgao {sigla: 'PROGRAP', nome: 'Pró-Reitoria de Graduação e Políticas Afirmativas',
           descricao: 'Antiga PROGRAD, renomeada em 2025'})
    MERGE (prppg:Orgao {sigla: 'PRPPG', nome: 'Pró-Reitoria de Pesquisa e Pós-Graduação'})
    MERGE (proec:Orgao {sigla: 'PROEC', nome: 'Pró-Reitoria de Extensão e Cultura'})
    MERGE (pra:Orgao {sigla: 'PRA', nome: 'Pró-Reitoria de Administração'})
    MERGE (progepe:Orgao {sigla: 'PROGEPE', nome: 'Pró-Reitoria de Gestão de Pessoas',
           descricao: 'Cadastro SIAPE, folha de pagamento, estágios remunerados na UFPR'})
    MERGE (prae:Orgao {sigla: 'PRAE', nome: 'Pró-Reitoria de Assuntos Estudantis'})
    MERGE (proplan:Orgao {sigla: 'PROPLAN', nome: 'Pró-Reitoria de Planejamento, Orçamento e Finanças'})

    // PROGRAP sub-units
    MERGE (coappe:Orgao {sigla: 'COAPPE', nome: 'Coordenação de Atividades de Práticas Profissionais e Estágios',
           descricao: 'Antiga COAFE. Gerencia contratações, cadastros, seguros e trâmites legais de estágio',
           email: 'estagio@ufpr.br', telefone: '(41) 3310-2706'})
    MERGE (ue:Orgao {sigla: 'UE', nome: 'Unidade de Estágios',
           descricao: 'Execução operacional dentro da COAPPE',
           email: 'estagio@ufpr.br', telefone: '(41) 3310-2706'})

    // Setor e Departamento
    MERGE (sacod:Orgao {sigla: 'SACOD', nome: 'Setor de Artes, Comunicação e Design'})
    MERGE (ddesign:Orgao {sigla: 'DDESIGN', nome: 'Departamento de Design'})
    MERGE (ccdg:Orgao {sigla: 'CCDG', nome: 'Coordenação do Curso de Design Gráfico',
           descricao: 'Unidade SEI: UFPR/R/AC/CCDG',
           email: 'design.grafico@ufpr.br', telefone: '(41) 3360-5360',
           endereco: 'Rua General Carneiro, 460, 8º andar, sala 801, Curitiba/PR'})
    MERGE (coe:Orgao {sigla: 'COE', nome: 'Comissão Orientadora de Estágio',
           descricao: 'Comissão do curso DG: analisa documentação, define critérios, acompanha estágios'})
    MERGE (colegiado:Orgao {sigla: 'COLEGIADO_DG', nome: 'Colegiado do Curso de Design Gráfico'})

    // Conselhos superiores
    MERGE (cepe:Orgao {sigla: 'CEPE', nome: 'Conselho de Ensino, Pesquisa e Extensão'})
    MERGE (coplad:Orgao {sigla: 'COPLAD', nome: 'Conselho de Planejamento e Administração'})
    MERGE (coun:Orgao {sigla: 'COUN', nome: 'Conselho Universitário'})
    MERGE (concur:Orgao {sigla: 'CONCUR', nome: 'Conselho de Curadores'})

    // Outros
    MERGE (aui:Orgao {sigla: 'AUI', nome: 'Agência UFPR Internacional',
           descricao: 'Homologa estágios no exterior'})
    MERGE (sibi:Orgao {sigla: 'SIBI', nome: 'Sistema de Bibliotecas'})

    // Hierarchical relationships
    MERGE (prograp)-[:SUBORDINADO_A]->(reitoria)
    MERGE (prppg)-[:SUBORDINADO_A]->(reitoria)
    MERGE (proec)-[:SUBORDINADO_A]->(reitoria)
    MERGE (pra)-[:SUBORDINADO_A]->(reitoria)
    MERGE (progepe)-[:SUBORDINADO_A]->(reitoria)
    MERGE (prae)-[:SUBORDINADO_A]->(reitoria)
    MERGE (proplan)-[:SUBORDINADO_A]->(reitoria)
    MERGE (cepe)-[:SUBORDINADO_A]->(reitoria)
    MERGE (coplad)-[:SUBORDINADO_A]->(reitoria)
    MERGE (coun)-[:SUBORDINADO_A]->(reitoria)
    MERGE (concur)-[:SUBORDINADO_A]->(reitoria)

    MERGE (coappe)-[:SUBORDINADO_A]->(prograp)
    MERGE (ue)-[:SUBORDINADO_A]->(coappe)
    MERGE (aui)-[:SUBORDINADO_A]->(reitoria)
    MERGE (sibi)-[:SUBORDINADO_A]->(reitoria)

    MERGE (sacod)-[:SUBORDINADO_A]->(reitoria)
    MERGE (ddesign)-[:SUBORDINADO_A]->(sacod)
    MERGE (ccdg)-[:SUBORDINADO_A]->(ddesign)
    MERGE (coe)-[:SUBORDINADO_A]->(ccdg)
    MERGE (colegiado)-[:SUBORDINADO_A]->(ccdg)

    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    rows = client.run_query("MATCH (o:Orgao) RETURN count(o) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 2. PEOPLE
# ============================================================================

def _seed_pessoas(client: Neo4jClient) -> int:
    """Create people nodes (docentes, coordination)."""
    cypher = """
    MERGE (stepha:Pessoa {nome: 'Stephania Padovani', titulo: 'Dra.',
           cargo: 'Coordenadora do Curso de Design Gráfico'})
    MERGE (carol:Pessoa {nome: 'Carolina Calomeno Machado', titulo: 'Dra.',
           cargo: 'Vice-Coordenadora do Curso de Design Gráfico'})
    MERGE (lucas:Pessoa {nome: 'Lucas Martins Sorrentino',
           cargo: 'Secretário do Curso de Design Gráfico'})

    // Docentes
    MERGE (:Pessoa {nome: 'Daniella Rosito Michelena Munhoz', titulo: 'Dra.'})
    MERGE (:Pessoa {nome: 'Juliana Bueno', titulo: 'Dra.'})
    MERGE (:Pessoa {nome: 'Kelli Cristine A. da Silva Smythe', titulo: 'Dra.'})
    MERGE (:Pessoa {nome: 'Marcel Pereira Pauluk', titulo: 'Me.'})
    MERGE (:Pessoa {nome: 'Marcos Namba Beccari', titulo: 'Dr.'})
    MERGE (:Pessoa {nome: 'Naotake Fukushima', titulo: 'Dr.'})
    MERGE (:Pessoa {nome: 'Rafael Castro Andrade', titulo: 'Dr.'})
    MERGE (:Pessoa {nome: 'Rafael Pereira Dubiela', titulo: 'Dr.'})
    MERGE (:Pessoa {nome: 'Ivy Higino', titulo: 'Dra.'})

    // Roles
    WITH carol, stepha, lucas
    MATCH (ccdg:Orgao {sigla: 'CCDG'})
    MERGE (carol)-[:PERTENCE_A]->(ccdg)
    MERGE (stepha)-[:PERTENCE_A]->(ccdg)
    MERGE (lucas)-[:PERTENCE_A]->(ccdg)

    WITH carol, stepha, lucas
    MERGE (p_coord:Papel {nome: 'Coordenador'})
    MERGE (p_vice:Papel {nome: 'Vice-Coordenador'})
    MERGE (p_secr:Papel {nome: 'Secretário'})
    MERGE (stepha)-[:EXERCE]->(p_coord)
    MERGE (carol)-[:EXERCE]->(p_vice)
    MERGE (lucas)-[:EXERCE]->(p_secr)

    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    rows = client.run_query("MATCH (p:Pessoa) RETURN count(p) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 3. SYSTEMS
# ============================================================================

def _seed_sistemas(client: Neo4jClient) -> int:
    """Create IT system nodes."""
    cypher = """
    MERGE (sei:Sistema {nome: 'SEI', descricao: 'Sistema Eletrônico de Informações',
           url: 'https://sei.ufpr.br', unidade: 'UFPR/R/AC/CCDG'})
    MERGE (siga:Sistema {nome: 'SIGA', descricao: 'Sistema Integrado de Gestão Acadêmica',
           url: 'https://siga.ufpr.br/siga/',
           url_discentes: '/siga/discente?operacao=listar&tipodiscente=I',
           url_trancamentos: '/siga/graduacao/trancamentos.jsp',
           url_estagios: '/siga/graduacao/estagioPeriodoEspecial?op=listarEstagios',
           url_colacoes: '/siga/graduacao/colacoes?op=listar',
           url_email: '/siga/graduacao/email'})
    MERGE (owa:Sistema {nome: 'OWA', descricao: 'Outlook Web Access — Microsoft 365',
           url: 'https://outlook.cloud.microsoft/mail/'})
    MERGE (gmail:Sistema {nome: 'Gmail', descricao: 'Gmail IMAP (canal primário)',
           email: 'design.grafico.ufpr@gmail.com'})
    MERGE (soc:Sistema {nome: 'SOC', descricao: 'Resoluções dos Conselhos Superiores UFPR',
           url: 'https://soc.ufpr.br/'})
    MERGE (chamados:Sistema {nome: 'Chamados UFPR', descricao: 'Abertura de chamados de suporte',
           url: 'https://chamados.ufpr.br/'})

    // Which organs operate which systems
    WITH sei, siga, owa
    MATCH (ccdg:Orgao {sigla: 'CCDG'})
    MATCH (coappe:Orgao {sigla: 'COAPPE'})
    MATCH (prograp:Orgao {sigla: 'PROGRAP'})
    MERGE (ccdg)-[:OPERA_SISTEMA]->(sei)
    MERGE (ccdg)-[:OPERA_SISTEMA]->(siga)
    MERGE (ccdg)-[:OPERA_SISTEMA]->(owa)
    MERGE (coappe)-[:OPERA_SISTEMA]->(sei)
    MERGE (prograp)-[:OPERA_SISTEMA]->(siga)

    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    rows = client.run_query("MATCH (s:Sistema) RETURN count(s) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 4. ROLES (papéis nos fluxos)
# ============================================================================

def _seed_papeis(client: Neo4jClient) -> int:
    """Create workflow role nodes (MERGE on nome, SET description separately)."""
    papeis = [
        ("Coordenador", "Coordenador(a) do curso — aprova processos, assina despachos SEI"),
        ("Vice-Coordenador", "Vice-Coordenador(a) do curso"),
        ("Secretário", "Secretário(a) — operações diárias, triagem de emails, abertura de processos SEI"),
        ("Orientador", "Professor orientador de estágio — acompanha estagiário, assina relatórios"),
        ("Supervisor", "Supervisor na concedente — formação/experiência em Design, acompanha atividades"),
        ("Estagiário", "Discente estagiário — preenche TCE, coleta assinaturas, envia relatórios"),
        ("COE", "Comissão Orientadora de Estágio — analisa documentação, define critérios"),
        ("COAPPE", "Coordenação de Estágios (PROGRAP) — registra estágio, emite certificados"),
        ("PROGEPE", "Gestão de Pessoas — cadastro SIAPE, pagamento de estágios remunerados na UFPR"),
        ("Docente", "Professor da disciplina de estágio supervisionado (OD501/ODDA5)"),
    ]
    for nome, desc in papeis:
        client.run_write(
            "MERGE (p:Papel {nome: $nome}) SET p.descricao = $desc",
            {"nome": nome, "desc": desc},
        )
    rows = client.run_query("MATCH (p:Papel) RETURN count(p) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 5. NORMS / REGULATIONS
# ============================================================================

def _seed_normas(client: Neo4jClient) -> int:
    """Create regulatory document nodes and relationships."""
    cypher = """
    MERGE (lei:Norma {codigo: 'Lei 11.788/2008', tipo: 'Lei Federal',
           nome: 'Lei do Estágio', descricao: 'Lei federal que regulamenta os estágios no Brasil'})
    MERGE (res70:Norma {codigo: 'Resolução 70/04-CEPE', tipo: 'Resolução',
           nome: 'Atividades Formativas', descricao: 'Flexibilização curricular na UFPR'})
    MERGE (res46:Norma {codigo: 'Resolução 46/10-CEPE', tipo: 'Resolução',
           nome: 'Estágios na UFPR', descricao: 'Regulamentação geral dos estágios na UFPR, cria a COE'})
    MERGE (in01_12:Norma {codigo: 'IN 01/12-CEPE', tipo: 'Instrução Normativa',
           nome: 'Estágios não obrigatórios externos'})
    MERGE (in02_12:Norma {codigo: 'IN 02/12-CEPE', tipo: 'Instrução Normativa',
           nome: 'Estágios no exterior'})
    MERGE (in01_13:Norma {codigo: 'IN 01/13-CEPE', tipo: 'Instrução Normativa',
           nome: 'Estágios remunerados no âmbito da UFPR'})
    MERGE (reg_dg:Norma {codigo: 'Regulamento DG 2024', tipo: 'Regulamento',
           nome: 'Regulamento de Estágio do Curso de Design Gráfico',
           descricao: 'Normas específicas do curso, aprovado 23/02/2024'})
    MERGE (res92:Norma {codigo: 'Resolução 92/13-CEPE', tipo: 'Resolução',
           nome: 'Dispensa/Aproveitamento de Disciplinas',
           descricao: 'Alterada pela Res 39/18-CEPE'})
    MERGE (in01_16:Norma {codigo: 'IN 01/16-PROGRAD', tipo: 'Instrução Normativa',
           nome: 'Trancamento de Curso'})
    MERGE (cne:Norma {codigo: 'Resolução CNE/CES nº 2/2006', tipo: 'Resolução Federal',
           nome: 'Diretrizes Curriculares para Design'})

    // ALTERA relationships
    MERGE (reg_dg)-[:ALTERA]->(res46)
    MERGE (res70)-[:ALTERA {descricao: 'Alterada pela Res 21/18-CEPE'}]->(res70)

    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    rows = client.run_query("MATCH (n:Norma) RETURN count(n) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 6. DOCUMENTS
# ============================================================================

def _seed_documentos(client: Neo4jClient) -> int:
    """Create document type nodes."""
    cypher = """
    MERGE (:Documento {nome: 'TCE', nome_completo: 'Termo de Compromisso de Estágio',
           descricao: 'Principal documento — obrigatório em todos os estágios. Formalizado ANTES do início.'})
    MERGE (:Documento {nome: 'Plano de Atividades', nome_completo: 'Plano de Atividades de Estágio',
           descricao: 'Parte integrante do TCE. Elaborado com supervisor, aprovado pelo orientador.'})
    MERGE (:Documento {nome: 'Termo Aditivo',
           descricao: 'Altera condições do TCE: prazo, carga, supervisor, bolsa. Solicitar ANTES do vencimento.'})
    MERGE (:Documento {nome: 'Termo de Rescisão',
           descricao: 'Encerra o estágio antes do prazo. Obrigatório em encerramento antecipado.'})
    MERGE (:Documento {nome: 'Relatório Parcial', nome_completo: 'Relatório Parcial de Estágio',
           descricao: 'Elaborado pelo aluno a cada 6 meses.'})
    MERGE (:Documento {nome: 'Relatório Final', nome_completo: 'Relatório Final de Estágio',
           descricao: 'Elaborado ao término. Para obrigatório, inclui defesa oral.'})
    MERGE (:Documento {nome: 'Ficha de Avaliação', nome_completo: 'Ficha de Avaliação de Estágio',
           descricao: 'Preenchida pelo supervisor. Necessária para certificado (apenas não obrigatório).'})
    MERGE (:Documento {nome: 'Declaração Experiência Supervisor',
           descricao: 'Quando supervisor não tem formação compatível com Design.'})
    MERGE (:Documento {nome: 'Declaração de Parentesco',
           descricao: 'Apenas estágios remunerados na UFPR.'})
    MERGE (:Documento {nome: 'Termo Responsabilidade Financeira',
           descricao: 'Apenas estágios remunerados na UFPR (unidade orçamentária).'})
    MERGE (:Documento {nome: 'Controle Frequência e Férias',
           descricao: 'Apenas estágios remunerados na UFPR.'})
    MERGE (:Documento {nome: 'Atestado Médico',
           descricao: 'Exigido para estágios remunerados na UFPR (Art. 16 ON 07/2008-MPOG).'})
    MERGE (:Documento {nome: 'Despacho SEI',
           descricao: 'Documento gerado pela coordenação dentro do processo SEI.'})
    MERGE (:Documento {nome: 'Certificado de Estágio',
           descricao: 'Emitido pela COAPPE apenas para estágios NÃO OBRIGATÓRIOS concluídos.'})
    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    rows = client.run_query("MATCH (d:Documento) RETURN count(d) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 7. SEI PROCESS TYPES (with frequency data from manual)
# ============================================================================

def _seed_tipos_processo(client: Neo4jClient) -> int:
    """Create SEI process types with frequency counts."""
    tipos = [
        ("Graduação/Ensino Técnico: Estágios não Obrigatórios", 238),
        ("Administração Geral: Informações e Documentos", 132),
        ("Graduação: Registro de Diplomas", 62),
        ("Graduação/Ensino Técnico: Estágio Obrigatório", 60),
        ("Graduação/Ensino Técnico: Dispensa/Isenção/Aproveitamento de disciplinas", 60),
        ("Graduação: Programa de Voluntariado Acadêmico", 42),
        ("Graduação: Matrículas", 30),
        ("Graduação/Ensino Técnico: Expedição de Diploma", 23),
        ("Graduação: Solicitação de Trancamento/Destrancamento de Curso", 13),
        ("Graduação: Cancelamento por Abandono de Curso", 12),
        ("Graduação: Cancelamento de Registro Acadêmico (prazo de integralização)", 11),
        ("Graduação: Colação de Grau com Solenidade", 11),
        ("Administração Geral: Acordos. Ajustes. Contratos. Convênios", 11),
        ("Graduação/Ensino Técnico: Matrícula em curso", 10),
        ("PROGEPE: Avaliação de Estágio Probatório", 7),
        ("Graduação: PROVAR - Processo de Ocupação de Vagas Remanescentes", 7),
        ("Graduação/Ensino Técnico: Mobilidade Acadêmica Internacional", 5),
        ("Graduação: Colação de Grau sem Solenidade", 5),
        ("Graduação: Colação de Grau / Antecipação", 3),
        ("Graduação: Prorrogação de prazo para Conclusão do Curso", 2),
    ]
    for nome, freq in tipos:
        client.run_write(
            "MERGE (tp:TipoProcesso {nome: $nome}) SET tp.frequencia = $freq",
            {"nome": nome, "freq": freq},
        )

    # Link process types to SEI
    client.run_write("""
        MATCH (tp:TipoProcesso), (sei:Sistema {nome: 'SEI'})
        MERGE (tp)-[:TRAMITA_VIA]->(sei)
    """)

    # Link internship types to relevant norms
    client.run_write("""
        MATCH (tp:TipoProcesso)
        WHERE tp.nome CONTAINS 'Estágios não Obrigatórios'
        MATCH (lei:Norma {codigo: 'Lei 11.788/2008'})
        MATCH (res:Norma {codigo: 'Resolução 46/10-CEPE'})
        MATCH (in1:Norma {codigo: 'IN 01/12-CEPE'})
        MERGE (lei)-[:REGULAMENTA]->(tp)
        MERGE (res)-[:REGULAMENTA]->(tp)
        MERGE (in1)-[:REGULAMENTA]->(tp)
    """)
    client.run_write("""
        MATCH (tp:TipoProcesso)
        WHERE tp.nome CONTAINS 'Estágio Obrigatório'
        MATCH (lei:Norma {codigo: 'Lei 11.788/2008'})
        MATCH (res:Norma {codigo: 'Resolução 46/10-CEPE'})
        MERGE (lei)-[:REGULAMENTA]->(tp)
        MERGE (res)-[:REGULAMENTA]->(tp)
    """)
    client.run_write("""
        MATCH (tp:TipoProcesso)
        WHERE tp.nome CONTAINS 'Dispensa/Isenção/Aproveitamento'
        MATCH (res:Norma {codigo: 'Resolução 92/13-CEPE'})
        MERGE (res)-[:REGULAMENTA]->(tp)
    """)
    client.run_write("""
        MATCH (tp:TipoProcesso)
        WHERE tp.nome CONTAINS 'Trancamento'
        MATCH (in1:Norma {codigo: 'IN 01/16-PROGRAD'})
        MERGE (in1)-[:REGULAMENTA]->(tp)
    """)

    rows = client.run_query("MATCH (tp:TipoProcesso) RETURN count(tp) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 8. WORKFLOWS (Fluxos + Etapas)
# ============================================================================

def _seed_fluxos(client: Neo4jClient) -> int:
    """Create workflow nodes with ordered steps."""
    fluxos = {
        "TCE Não Obrigatório": {
            "descricao": "Solicitação inicial de estágio não obrigatório",
            "prazo": "10 dias úteis de antecedência antes do início",
            "etapas": [
                ("Aluno preenche e assina TCE + Plano de Atividades", "Estagiário", None),
                ("Aluno envia documentação em PDF para design.grafico@ufpr.br", "Estagiário", None),
                ("Secretaria verifica situação acadêmica no SIGA", "Secretário", "SIGA"),
                ("Secretaria analisa documentação e condições", "Secretário", None),
                ("Secretaria abre processo no SEI (tipo: Estágios não Obrigatórios)", "Secretário", "SEI"),
                ("Coordenação gera despacho e inclui no processo SEI", "Coordenador", "SEI"),
                ("Coordenação envia processo SEI para COAPPE", "Coordenador", "SEI"),
                ("COAPPE analisa e registra o estágio", "COAPPE", "SEI"),
                ("Coordenação envia documentos ao discente por email", "Secretário", "OWA"),
            ],
        },
        "TCE Obrigatório": {
            "descricao": "Solicitação inicial de estágio obrigatório",
            "prazo": "10 dias úteis de antecedência antes do início",
            "etapas": [
                ("Aluno confirma matrícula em OD501/ODDA5", "Estagiário", "SIGA"),
                ("Aluno preenche e assina TCE + Plano de Atividades", "Estagiário", None),
                ("Aluno envia documentação em PDF para design.grafico@ufpr.br", "Estagiário", None),
                ("Secretaria verifica situação acadêmica no SIGA", "Secretário", "SIGA"),
                ("Secretaria abre processo no SEI (tipo: Estágio Obrigatório)", "Secretário", "SEI"),
                ("Coordenação gera despacho para docente da disciplina", "Coordenador", "SEI"),
                ("Docente gera despacho e retorna processo", "Docente", "SEI"),
                ("Coordenação envia processo SEI para COAPPE", "Coordenador", "SEI"),
                ("COAPPE registra o estágio", "COAPPE", "SEI"),
                ("Coordenação envia documentos ao discente por email", "Secretário", "OWA"),
            ],
        },
        "Termo Aditivo": {
            "descricao": "Prorrogação ou alteração de estágio em andamento",
            "prazo": "ANTES da data de término do TCE — 10 dias úteis de antecedência",
            "regra_bloqueio": "Bloquear se pedido de aditivo for POSTERIOR à data de término do TCE",
            "etapas": [
                ("Aluno preenche Termo Aditivo com assinaturas", "Estagiário", None),
                ("Aluno apresenta Relatório Parcial do período", "Estagiário", None),
                ("Aluno envia documentos para design.grafico@ufpr.br", "Estagiário", None),
                ("Secretaria verifica relatório e documentação", "Secretário", None),
                ("Secretaria inclui documentos no processo SEI existente", "Secretário", "SEI"),
                ("Coordenação gera despacho de aditivo", "Coordenador", "SEI"),
                ("Coordenação envia processo para COAPPE", "Coordenador", "SEI"),
                ("COAPPE atualiza período e seguro", "COAPPE", "SEI"),
            ],
        },
        "Rescisão": {
            "descricao": "Encerramento antecipado de estágio",
            "etapas": [
                ("Aluno preenche Termo de Rescisão + Relatório Final", "Estagiário", None),
                ("Aluno coleta assinaturas e envia para design.grafico@ufpr.br", "Estagiário", None),
                ("Secretaria inclui documentos no processo SEI existente", "Secretário", "SEI"),
                ("Coordenação gera despacho de rescisão/conclusão", "Coordenador", "SEI"),
                ("Coordenação envia processo para COAPPE", "Coordenador", "SEI"),
                ("COAPPE homologa rescisão e atualiza cadastro", "COAPPE", "SEI"),
                ("COAPPE retira estagiário do seguro", "COAPPE", None),
                ("Coordenação encerra processo no SEI", "Coordenador", "SEI"),
            ],
        },
        "Certificação": {
            "descricao": "Emissão de certificado (apenas estágio não obrigatório)",
            "etapas": [
                ("Supervisor preenche Ficha de Avaliação", "Supervisor", None),
                ("Aluno coleta assinaturas e envia para design.grafico@ufpr.br", "Estagiário", None),
                ("Secretaria inclui no processo SEI", "Secretário", "SEI"),
                ("COE aprecia e emite parecer favorável", "COE", None),
                ("Coordenação encaminha para COAPPE via SEI", "Coordenador", "SEI"),
                ("COAPPE verifica documentação e contabiliza horas", "COAPPE", None),
                ("COAPPE emite certificado (até 5 dias úteis)", "COAPPE", None),
                ("Coordenação envia certificado ao aluno por email", "Secretário", "OWA"),
            ],
        },
        "Convalidação": {
            "descricao": "Convalidação de IC/extensão/trabalho como estágio obrigatório",
            "prazo": "Até 30 dias antes do final do semestre letivo",
            "etapas": [
                ("Aluno preenche formulário de convalidação online", "Estagiário", None),
                ("COE analisa documentação", "COE", None),
                ("COE emite parecer", "COE", None),
                ("Coordenação comunica resultado ao aluno", "Secretário", "OWA"),
            ],
        },
    }

    total_etapas = 0
    for nome_fluxo, data in fluxos.items():
        # Create Fluxo node
        client.run_write(
            "MERGE (f:Fluxo {nome: $nome}) SET f.descricao = $desc, f.prazo = $prazo",
            {"nome": nome_fluxo, "desc": data["descricao"],
             "prazo": data.get("prazo", "")},
        )
        if "regra_bloqueio" in data:
            client.run_write(
                "MATCH (f:Fluxo {nome: $nome}) SET f.regra_bloqueio = $regra",
                {"nome": nome_fluxo, "regra": data["regra_bloqueio"]},
            )

        for i, (descricao, papel_nome, sistema_nome) in enumerate(data["etapas"], 1):
            etapa_id = f"{nome_fluxo}::{i}"
            client.run_write(
                """
                MERGE (e:Etapa {id: $id})
                SET e.descricao = $desc, e.ordem = $ordem
                WITH e
                MATCH (f:Fluxo {nome: $fluxo})
                MERGE (f)-[:TEM_ETAPA {ordem: $ordem}]->(e)
                WITH e
                MATCH (p:Papel {nome: $papel})
                MERGE (e)-[:EXECUTADA_POR]->(p)
                """,
                {"id": etapa_id, "desc": descricao, "ordem": i,
                 "fluxo": nome_fluxo, "papel": papel_nome},
            )
            if sistema_nome:
                client.run_write(
                    """
                    MATCH (e:Etapa {id: $id}), (s:Sistema {nome: $sistema})
                    MERGE (e)-[:USA_SISTEMA]->(s)
                    """,
                    {"id": etapa_id, "sistema": sistema_nome},
                )
            total_etapas += 1

    rows = client.run_query("MATCH (f:Fluxo) RETURN count(f) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 9. TEMPLATES (email + despacho SEI)
# ============================================================================

def _seed_templates(client: Neo4jClient) -> int:
    """Create email and despacho template nodes."""
    templates = [
        ("Email: Como iniciar estágio não obrigatório", "email", "TCE Não Obrigatório",
         "Resposta para aluno que pergunta como começar estágio"),
        ("Email: Como iniciar estágio obrigatório", "email", "TCE Obrigatório",
         "Resposta para aluno matriculado em OD501/ODDA5"),
        ("Email: Documentação incompleta / Pendência no TCE", "email", "TCE Não Obrigatório",
         "TCE recebido com erro, faltando assinatura, dados incorretos"),
        ("Email: Estágio deferido / aprovado", "email", "TCE Não Obrigatório",
         "Após aprovação pela COAPPE, informar o aluno"),
        ("Email: Prorrogação de estágio (Termo Aditivo)", "email", "Termo Aditivo",
         "Aluno quer prorrogar estágio em andamento"),
        ("Email: Encerramento antecipado (Rescisão)", "email", "Rescisão",
         "Aluno quer encerrar estágio antes do prazo"),
        ("Email: Convalidação de estágio", "email", "Convalidação",
         "Aluno pergunta sobre convalidar IC, trabalho, extensão"),
        ("Email: Empresa oferece vagas", "email", None,
         "Empresa/RH quer divulgar vagas de estágio"),
        ("Email: Aluno não cumpre requisitos", "email", None,
         "Aluno impedido por reprovação, currículo integralizado, etc."),
        ("Email: Solicitação de relatório parcial", "email", None,
         "Lembrete semestral para alunos com estágio em andamento"),
        ("Email: Certificado de estágio", "email", "Certificação",
         "Aluno pergunta como obter certificado"),
        ("Despacho SEI: TCE Inicial", "despacho_sei", "TCE Não Obrigatório",
         "Despacho para novo estágio (TCE inicial)"),
        ("Despacho SEI: Termo Aditivo com Relatório", "despacho_sei", "Termo Aditivo",
         "Despacho para prorrogação com relatório parcial"),
        ("Despacho SEI: Rescisão/Conclusão", "despacho_sei", "Rescisão",
         "Despacho para encerramento de estágio"),
        ("Email: Encaminhamento à COAPPE", "email_interno", "TCE Não Obrigatório",
         "Email interno para estagio@ufpr.br encaminhando processo SEI"),
    ]

    for nome, tipo, fluxo_nome, descricao in templates:
        params = {"nome": nome, "tipo": tipo, "desc": descricao}
        client.run_write(
            "MERGE (t:Template {nome: $nome}) SET t.tipo = $tipo, t.descricao = $desc",
            params,
        )
        if fluxo_nome:
            client.run_write(
                """
                MATCH (t:Template {nome: $nome}), (f:Fluxo {nome: $fluxo})
                MERGE (t)-[:USADO_EM]->(f)
                """,
                {"nome": nome, "fluxo": fluxo_nome},
            )

    # Attach despacho body + despacho_tipo to the three SEI despacho templates
    # so that sei.client.SEIClient.prepare_despacho_draft can fetch them via
    # graphrag.templates.TemplateRegistry at runtime.
    templates_seeded: list[str] = []
    for nome, despacho_tipo in _DESPACHO_NODE_MAP.items():
        conteudo = _compose_despacho(despacho_tipo)
        client.run_write(
            """
            MERGE (t:Template {nome: $nome})
            SET t.despacho_tipo = $despacho_tipo, t.conteudo = $conteudo
            """,
            {"nome": nome, "despacho_tipo": despacho_tipo, "conteudo": conteudo},
        )
        templates_seeded.append(despacho_tipo)

    logger.info("Seeded %d templates with conteudo", len(templates_seeded))

    rows = client.run_query("MATCH (t:Template) RETURN count(t) AS cnt")
    return rows[0]["cnt"]


# ============================================================================
# 10. COURSE + DISCIPLINES
# ============================================================================

def _seed_curso(client: Neo4jClient) -> int:
    """Create course and discipline nodes."""
    cypher = """
    MERGE (dg:Curso {nome: 'Design Gráfico', grau: 'Bacharelado',
           duracao: '4 anos (8 semestres)', turno: 'Integral', vagas: 33,
           curriculo_vigente: '2020', curriculo_anterior: '2016'})
    WITH dg
    MATCH (sacod:Orgao {sigla: 'SACOD'})
    MERGE (dg)-[:OFERECIDO_POR]->(sacod)

    MERGE (od501:Disciplina {codigo: 'OD501', nome: 'Estágio Supervisionado',
           curriculo: '2016', ch: 360})
    MERGE (odda5:Disciplina {codigo: 'ODDA5', nome: 'Estágio Supervisionado',
           curriculo: '2020', ch: 360})
    MERGE (od501)-[:PERTENCE_A]->(dg)
    MERGE (odda5)-[:PERTENCE_A]->(dg)

    RETURN count(*) AS ops
    """
    client.run_write(cypher)
    return 1


# ============================================================================
# 11. SIGA NAVIGATION MAP (abas x assuntos)
# ============================================================================

def _seed_siga_navigation(client: Neo4jClient) -> int:
    """Create SIGA navigation hints as relationship properties."""
    abas = [
        ("informacoes", "Status de matrícula", "Status atual (ativo/trancado/cancelado)"),
        ("informacoes", "Dados de contato", "E-mail pessoal e institucional"),
        ("historico", "Histórico de notas/IRA", "Desempenho por semestre, IRA geral"),
        ("integralizacao", "Situação para formatura", "CH concluída vs. exigida, status integralizado"),
        ("trancamento", "Trancamento/destrancamento", "Histórico e status da solicitação"),
        ("estagio", "Estágio", "Estágios vinculados ao discente"),
        ("exames", "Exame de aproveitamento", "Solicitações em aberto"),
        ("equivalencias", "Equivalência de disciplina", "Solicitações em aberto"),
    ]
    for aba, assunto, verificar in abas:
        client.run_write(
            """
            MATCH (siga:Sistema {nome: 'SIGA'})
            MERGE (nav:SigaAba {nome: $aba, assunto: $assunto, verificar: $verificar})
            MERGE (nav)-[:PERTENCE_A]->(siga)
            """,
            {"aba": aba, "assunto": assunto, "verificar": verificar},
        )
    return len(abas)


# ============================================================================
# MAIN SEED ORCHESTRATOR
# ============================================================================

def seed_all(client: Neo4jClient, clear: bool = False) -> dict[str, int]:
    """Run all seed functions and return counts per category.

    Args:
        client: Connected Neo4jClient instance.
        clear: If True, delete all existing nodes/relationships first.

    Returns:
        Dict mapping category name to node count.
    """
    if clear:
        client.clear_graph()

    logger.info("GraphRAG seed: aplicando constraints...")
    apply_constraints(client)

    stats = {}
    seed_fns = [
        ("Órgãos", _seed_orgaos),
        ("Pessoas", _seed_pessoas),
        ("Sistemas", _seed_sistemas),
        ("Papéis", _seed_papeis),
        ("Normas", _seed_normas),
        ("Documentos", _seed_documentos),
        ("Tipos de Processo SEI", _seed_tipos_processo),
        ("Fluxos", _seed_fluxos),
        ("Templates", _seed_templates),
        ("Curso", _seed_curso),
        ("Navegação SIGA", _seed_siga_navigation),
    ]

    for name, fn in seed_fns:
        count = fn(client)
        stats[name] = count
        logger.info("  %s: %d", name, count)

    total_nodes = client.node_count()
    total_rels = client.relationship_count()
    stats["_total_nodes"] = total_nodes
    stats["_total_relationships"] = total_rels

    logger.info("GraphRAG seed completo: %d nós, %d relações", total_nodes, total_rels)
    return stats


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Neo4j knowledge graph — UFPR")
    parser.add_argument("--clear", action="store_true", help="Clear graph before seeding")
    parser.add_argument("--dry-run", action="store_true", help="Just show connection + stats")
    args = parser.parse_args()

    client = Neo4jClient()

    if not client.health_check():
        print("ERRO: Neo4j não está acessível. Verifique se o serviço está rodando.")
        print(f"  URI: {client._uri}")
        print(f"  User: {client._username}")
        return

    if args.dry_run:
        n = client.node_count()
        r = client.relationship_count()
        print(f"Neo4j conectado: {n} nós, {r} relações")
        client.close()
        return

    stats = seed_all(client, clear=args.clear)
    print("\n=== GraphRAG Seed Results ===")
    for key, val in stats.items():
        if not key.startswith("_"):
            print(f"  {key}: {val}")
    print(f"\nTotal: {stats['_total_nodes']} nós, {stats['_total_relationships']} relações")
    client.close()


if __name__ == "__main__":
    main()
