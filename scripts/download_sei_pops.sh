#!/bin/bash
set -u
DEST_G="/g/Meu Drive/ufpr_rag/docs/ainda_n_ingeridos/SEI-tutotiais"
DEST_R="/c/Users/Lucas/Documents/automation/automation_nanobot/ufpr_automation/base_conhecimento/SEI-tutotiais"
mkdir -p "$DEST_G" "$DEST_R"

URLS=(
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-1-Acessar-o-SEI.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-2-Receber-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-3-Atribuir-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-4-Inserir-Anotação.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-5-Iniciar-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-6-Excluir-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-7-Relacionar-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-8-Remover-Relacionamento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-9-Iniciar-Processo-Relacionado.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-10-Anexar-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-11-Abrir-Processo-Anexado.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-12-Sobrestar-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-13-Remover-Sobrestamento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-14-Duplicar-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-15-Enviar-processo-1.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-16-Concluir-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-17-Inserir-ponto-de-controle.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-18-Gerenciar-ponto-de-controle.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-19-Criar-documento-interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-20-Editar-documento-interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-21-Gerar-versão-do-documento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-22-Assinar-documento-interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-23-Criar-texto-padrão.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-24-Criar-consultar-alterar-e-excluir-modelo-de-documento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-25-Incluir-documento-externo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-26-Excluir-documento-do-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-27-Cancelar-documento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-28-Incluir-documento-em-múltiplos-processos.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-29-Imprimir-documento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-30-Dar-ciência.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-31-Encaminhar-documento-para-assinatura-em-outra-Unidade.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-32-Assinar-documento-encaminhado-por-outra-Unidade.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-33-Encaminhar-processo-para-consulta-de-outra-Unidade.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-34-Visualizar-minutas-e-documentos-por-meio-de-Blocos-de-Reunião.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-35-Incluir-processos-em-um-Bloco-Interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-36-Visualizar-processos-em-um-Bloco-Interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-37-Verificar-o-histórico-do-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-38-Incluir-processo-em-Acompanhamento-Especial.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-39-Alterar-grupo-em-Acompanhamento-Especial.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-40-Excluir-grupo-em-Acompanhamento-Especial.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-41-Criar-e-disponibilizar-a-Base-de-Conhecimento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-42-Alterar-a-Base-de-Conhecimento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-43-Executar-pesquisa.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-44-Reabrir-processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-45-Exportar-documentos-do-processo-em-formato-PDF.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-46-Exportar-documentos-do-processo-em-formato-ZIP.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-47-Estatística-dos-processos.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-48-Enviar-e-mail-utilizando-o-SEI.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-49-Criar-grupo-de-e-mail.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-50-Permitir-visualização-de-processo-por-usuário-externo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-51-Cadastrar-usuário-externo-para-assinatura-em-documento-interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-52-Solicitar-assinatura-de-usuário-externo-em-documento-interno.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-53-Marcadores.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-54-Bloco-de-Asssinatura.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-55-Filtro-Tipo-de-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-56-Pesquisar-no-Processo.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-57-Comparação-de-versões-do-documento.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2018/07/POP-58-Administração-de-Acervo-de-Processos-Sigilosos-da-Unidade.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2022/11/PLANO-DE-INTEGRIDADE-DA-UFPR-2022-2023.pdf"
"https://cgr.ufpr.br/portal/wp-content/uploads/2022/12/organograma_UFPR.xls"
)

ok=0; fail=0
for url in "${URLS[@]}"; do
  fname=$(basename "$url" | python -c "import sys, urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))")
  out="$DEST_G/$fname"
  if [ -s "$out" ]; then
    echo "SKIP $fname"
  else
    if curl -sSL --fail -o "$out" "$url"; then
      echo "OK   $fname"
      ok=$((ok+1))
    else
      echo "FAIL $url"
      fail=$((fail+1))
      continue
    fi
  fi
  cp -f "$out" "$DEST_R/$fname"
done
echo "---"
echo "Downloaded: $ok, Failed: $fail"
ls "$DEST_G" | wc -l
ls "$DEST_R" | wc -l
