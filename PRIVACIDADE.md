# Política de Privacidade — Apolo AI

## Princípio fundamental

O Apolo AI foi projetado para rodar **100% localmente** no seu computador. Nenhum dado de conversa é enviado para servidores externos de IA.

## Dados coletados

| Dado | Onde fica | Propósito |
|---|---|---|
| Mensagens de conversa | SQLite local (`data/apolo.db`) | Memória persistente entre sessões |
| Código gerado | SQLite + ChromaDB local | RAG — melhora respostas futuras |
| Conteúdo web pesquisado | Supabase (se configurado) | Base de conhecimento técnico |

## O que NÃO coletamos

- Dados pessoais identificáveis
- Arquivos do sistema do usuário
- Informações de rede ou localização
- Histórico do browser

## Serviços externos

| Serviço | Dados enviados | Quando |
|---|---|---|
| **Ollama** (local) | Prompts do chat | Sempre — mas roda no seu PC |
| **DuckDuckGo** | Termos de busca | Apenas ao usar 🌐 Web |
| **Supabase** | Conteúdo web coletado | Apenas se configurado no .env |

Os prompts são processados pelo modelo Ollama rodando localmente — **nenhuma mensagem sai do computador** para processamento de IA.

## Direitos (LGPD — Lei 13.709/2018)

- **Acesso**: histórico disponível via `/api/history` e `/api/sessions`
- **Exclusão**: soft-delete via `/api/session/{id}` — dados marcados como deletados
- **Portabilidade**: dados exportáveis diretamente do arquivo `data/apolo.db`

## Credenciais

As credenciais do Supabase (`SUPABASE_URL`, `SUPABASE_KEY`) ficam apenas no arquivo `.env`, que está no `.gitignore` e nunca deve ser commitado.
