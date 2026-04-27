"""DSPy Signatures for the UFPR email processing pipeline.

Signatures are declarative descriptions of LLM input/output behavior.
DSPy compilers (GEPA, MIPROv2) optimize the underlying prompts automatically.
"""

from __future__ import annotations

import dspy


class EmailClassifier(dspy.Signature):
    """Classifique um e-mail recebido na caixa de entrada da UFPR.

    Analise o e-mail e determine sua categoria, resuma o conteudo,
    indique a acao necessaria e redija uma resposta formal se aplicavel.
    Categorias validas (use exatamente uma): Estagios; Academico / Matricula;
    Academico / Equivalencia de Disciplinas; Academico / Aproveitamento de
    Disciplinas; Academico / Ajuste de Disciplinas; Diplomacao / Diploma;
    Diplomacao / Colacao de Grau; Extensao; Formativas; Requerimentos;
    Urgente; Correio Lixo; Outros.

    REGRA CRITICA — voce E a Coordenacao do Curso de Design Grafico (UFPR).
    NUNCA escreva no draft "procure a Coordenacao", "entre em contato com
    a Coordenacao", "consulte a Coordenacao" nem "consulte a Secretaria do
    Curso" — voce e o remetente do e-mail. Se faltar info, peca diretamente
    nesta resposta. Se for de outro setor, cite o setor especifico (COAPPE,
    PRAE, AUI, PROGRAP, SIBI, PROGEPE, NAA, PRPPG).
    """

    email_subject: str = dspy.InputField(desc="Assunto do e-mail")
    email_body: str = dspy.InputField(desc="Corpo completo do e-mail (ou preview)")
    email_sender: str = dspy.InputField(desc="Remetente do e-mail")
    rag_context: str = dspy.InputField(
        desc="Normas e documentos institucionais recuperados da base vetorial (pode estar vazio)"
    )

    categoria: str = dspy.OutputField(
        desc="Categoria do e-mail — uma de: Estagios, Academico / Matricula, "
        "Academico / Equivalencia de Disciplinas, Academico / Aproveitamento de Disciplinas, "
        "Academico / Ajuste de Disciplinas, Diplomacao / Diploma, "
        "Diplomacao / Colacao de Grau, Extensao, Formativas, Requerimentos, "
        "Urgente, Correio Lixo, Outros"
    )
    resumo: str = dspy.OutputField(
        desc="Breve resumo (1-2 sentencas) do conteudo e intencao principal do e-mail"
    )
    acao_necessaria: str = dspy.OutputField(
        desc="Proxima acao a ser tomada (ex: Arquivar, Redigir Resposta, "
        "Encaminhar para Secretaria, Solicitar Assinatura)"
    )
    sugestao_resposta: str = dspy.OutputField(
        desc="Resposta formal redigida em nome do setor. Vazio se nao for necessario responder"
    )
    confianca: float = dspy.OutputField(desc="Confianca na classificacao e resposta (0.0 a 1.0)")


class DraftCritic(dspy.Signature):
    """Avalie criticamente um rascunho de resposta institucional da UFPR.

    Verifique se a resposta cita a norma correta, se o tom e adequado
    para correspondencia oficial, se a classificacao esta correta,
    se a resposta atende a demanda do remetente, se ha erros factuais,
    e se a resposta NAO contem o anti-padrao "procure/entre em contato com/
    consulte a Coordenacao" ou "consulte a Secretaria do Curso". O agente
    E a Coordenacao do Curso de Design Grafico — mandar o aluno procurar a
    Coordenacao e mandar procurar a si mesmo. Se houver duvida, deve dizer
    "responda este e-mail" ou citar outro setor (COAPPE, PRAE, AUI, PROGRAP,
    SIBI, PROGEPE, NAA, PRPPG).
    """

    email_subject: str = dspy.InputField(desc="Assunto do e-mail original")
    email_body: str = dspy.InputField(desc="Corpo do e-mail original")
    draft_response: str = dspy.InputField(desc="Rascunho de resposta a ser avaliado")
    categoria: str = dspy.InputField(desc="Categoria atribuida ao e-mail")
    rag_context: str = dspy.InputField(desc="Normas recuperadas da base vetorial")

    has_issues: bool = dspy.OutputField(
        desc="True se houver problemas no rascunho, False se estiver adequado"
    )
    critique: str = dspy.OutputField(
        desc="Lista de problemas encontrados, ou 'SEM PROBLEMAS' se nao houver"
    )


class DraftRefiner(dspy.Signature):
    """Refine um rascunho de resposta institucional com base na critica recebida.

    Corrija os problemas identificados pela critica, mantendo o tom
    formal e as normas corretas da UFPR.
    """

    email_subject: str = dspy.InputField(desc="Assunto do e-mail original")
    email_body: str = dspy.InputField(desc="Corpo do e-mail original")
    original_draft: str = dspy.InputField(desc="Rascunho original com problemas")
    critique: str = dspy.InputField(desc="Critica identificando os problemas")
    rag_context: str = dspy.InputField(desc="Normas recuperadas da base vetorial")

    categoria: str = dspy.OutputField(desc="Categoria corrigida do e-mail")
    resumo: str = dspy.OutputField(desc="Resumo corrigido")
    acao_necessaria: str = dspy.OutputField(desc="Acao necessaria corrigida")
    sugestao_resposta: str = dspy.OutputField(desc="Resposta refinada e corrigida")
    confianca: float = dspy.OutputField(desc="Confianca na classificacao refinada (0.0 a 1.0)")
