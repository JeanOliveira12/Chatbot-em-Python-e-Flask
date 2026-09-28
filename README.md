# Chatbot de Atendimento com IA

Chatbot de atendimento para um parque de diversões (empresa fictícia), feito em **Python + Flask** com a **API da Anthropic (Claude)**.

O projeto mostra os blocos que um chatbot profissional precisa:

- **Chat com IA** que conversa de forma natural
- **Base de conhecimento (RAG):** o bot responde com base nos documentos da empresa, sem inventar
- **Contexto:** lembra do que foi dito na conversa
- **Histórico** de todas as conversas salvo em banco (SQLite)
- **Transferência para atendente humano** quando o cliente pede, em reclamações ou quando o bot não sabe
- **Painel administrativo** para ver conversas, responder como atendente e editar a base de conhecimento
- **Arquitetura em camadas**, pronta para novos canais (WhatsApp, CRM etc.)

## Como rodar

```bash
# 1. Crie e ative um ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure
cp .env.example .env      # no Windows: copy .env.example .env
# edite o .env e coloque sua ANTHROPIC_API_KEY e uma senha para o painel

# 4. Rode
python app.py
```

- Chat: http://localhost:5000
- Painel: http://localhost:5000/admin (usuário `admin`, senha do `.env`)

**Sem chave de API**, o projeto roda em **modo demonstração**: responde com o trecho da base encontrado, sem IA. Dá para testar todo o resto (histórico, transferência, painel) sem gastar nada.

## Arquitetura

```
Navegador (chat)  ──►  app.py  ──►  processar_mensagem()
                                        │
                        ┌───────────────┼────────────────┐
                        ▼               ▼                ▼
                      db.py          bot.py           (futuro)
                    (SQLite)           │           webhook WhatsApp
                                       ▼
                                    rag.py ──► conhecimento/*.md
                                       │
                                       ▼
                                 API Anthropic
```

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Rotas HTTP: página do chat, API JSON, painel admin |
| `bot.py` | Monta o prompt, chama a IA, interpreta a resposta (texto ou transferência) |
| `rag.py` | Busca os trechos relevantes da base de conhecimento |
| `db.py` | Conversas e mensagens no SQLite |
| `conhecimento/` | Documentos da empresa em Markdown (uma seção `##` por assunto) |

**Por que em camadas:** o `bot.py` não sabe nada de HTTP, e o `app.py` não sabe nada de IA. Para adicionar o WhatsApp, basta criar uma rota de webhook que chama a mesma `processar_mensagem()`. Para trocar a IA (OpenAI, por exemplo), só o `bot.py` muda.

## Decisões técnicas

- **Transferência via "tool use":** em vez de pedir para a IA escrever uma palavra-chave no texto, declaramos uma ferramenta `transferir_para_humano`. A IA devolve uma chamada estruturada, que o código trata com segurança. O mesmo mecanismo serve para integrar sistemas externos (consultar pedido, reservar festa), bastando declarar novas ferramentas.
- **RAG simples com TF-IDF:** sem dependências extras, bom para bases pequenas. Evolução natural: busca por embeddings (pgvector, Chroma), mantendo a mesma interface `buscar(pergunta)`.
- **Histórico limitado:** só as últimas 20 mensagens vão para a IA, para controlar custo.
- **Falha na IA não derruba o atendimento:** se a API der erro, a conversa é transferida para um humano.

## Próximos passos (evolução)

- [ ] Busca por embeddings na base de conhecimento
- [ ] Webhook do WhatsApp (API oficial do WhatsApp Business)
- [ ] Ferramentas de integração: consultar ingresso, pré-reservar festa
- [ ] Respostas em streaming (texto aparecendo aos poucos)
- [ ] Login de atendentes com usuário próprio
- [ ] PostgreSQL e deploy com Docker
