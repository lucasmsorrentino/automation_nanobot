Atue como um Arquiteto de Software de nível Sênior. Preciso que você crie um diagrama de arquitetura de sistemas (forneça o código em Mermaid.js) que represente o "Sistema de Automação Burocrática da UFPR".

A arquitetura deve ilustrar a progressão do sistema através de três marcos temporais de maturidade (Fases), detalhando o fluxo de dados, os componentes centrais e as tecnologias envolvidas. Utilize a seguinte especificação atualizada:

Contexto Geral do Sistema:

Linguagem Central: Python.

Motor Cognitivo Principal: API do Gemini 1.5 Pro (ou outra de baixo custo a principio para testes, mas importante manter facilmente cambiável).

Interface de Entrada/Saída (A Nova Abordagem): Acesso ao Microsoft 365 Outlook Web Access (OWA) da UFPR estritamente via Web Scraping e Automação de Navegador (RPA) utilizando a biblioteca Playwright. A Microsoft Graph API e o protocolo OAuth2 foram totalmente descartados devido a bloqueios de governança de TI. O sistema utilizará o Playwright para gerenciar o contexto do navegador, fazer login, extrair os e-mails lendo o DOM (Document Object Model) da página e simular cliques para despachar ações.

Componentes por Fase de Maturidade:

Marco I: O Triângulo de Ingestão Assistida (Protótipo)

Orquestrador: Framework nanobot, utilizado como um kernel minimalista focado puramente no ciclo cíclico de "Perceber-Pensar-Agir".

Memória: Aprendizado em Contexto (ICL). Normas de ofícios da UFPR injetadas diretamente no prompt principal do Gemini.

Ação: Um script em Playwright abre o Outlook Web em background (headless), varre a caixa de entrada por mensagens não lidas, envia o texto para o Gemini classificar e gerar a resposta. Em seguida, o Playwright localiza o botão "Responder" na interface, digita o texto e salva como rascunho, aguardando validação humana (Human-in-the-loop).

Marco II: Roteamento Agêntico e Estado Persistente (Intermediário)

Orquestrador: Transição da arquitetura do Nanobot para o framework LangGraph. Isso habilita a criação de workflows multi-agentes, controle de grafos de estado e tratamento nativo de exceções (ex: caso o layout do site do Outlook mude e o scraper falhe).

Memória: Implementação de Vector RAG (Geração Aumentada por Recuperação Vetorial) utilizando um banco de dados vetorial local (como LanceDB ou Chroma) para indexar e recuperar portarias e memorandos institucionais sob demanda.

Ação: Roteamento autônomo condicional. E-mails de risco baixo são respondidos e enviados automaticamente pelo robô; e-mails complexos ativam nós de recuperação de documentos (Retrieval Nodes) na base vetorial.

Marco III: Automação Governamental Total e Cognição Relacional (Avançado)

Orquestrador: LangGraph gerenciando uma frota de sub-agentes com diferentes contextos de navegador via Playwright.

Memória: Evolução para GraphRAG (Grafos de Conhecimento, ex: Neo4j) para mapear a complexa hierarquia departamental e relacional das normativas da UFPR.

Ação em Sistemas Legados (Expansão): Além de dominar o webmail, os agentes autônomos acessam ativamente e se autenticam na interface do Sistema Integrado de Gestão Acadêmica (SIGA-UFPR) e no portal web do Sistema Eletrônico de Informações (SEI). Eles usam o Playwright para protocolar processos, preencher formulários burocráticos dinâmicos e extrair números de trâmite em lote para responder ao requerente original.

Gere o código Mermaid.js formatado como um fluxograma ou diagrama de arquitetura de software contendo essas especificações, destacando a evolução tecnológica (Python, Gemini, Playwright, Nanobot, LangGraph, RAG) e como os componentes se integram em cada fase.

